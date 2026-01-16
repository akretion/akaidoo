import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set
import shlex
import subprocess
import os
from git import Repo, InvalidGitRepositoryError

import typer
from manifestoo_core.addons_set import AddonsSet
from manifestoo_core.core_addons import get_core_addons
from manifestoo_core.odoo_series import OdooSeries, detect_from_addons_set
from manifestoo.addon_sorter import AddonSorterTopological
from manifestoo.addons_path import AddonsPath as ManifestooAddonsPath
from manifestoo.addons_selection import AddonsSelection
from manifestoo.commands.list_depends import list_depends_command
from manifestoo import echo
import manifestoo.echo as manifestoo_echo_module
from manifestoo.exceptions import CycleErrorExit
from manifestoo.utils import ensure_odoo_series, print_list, comma_split

from .shrinker import shrink_python_file, shrink_manifest
from .utils import get_file_odoo_models, get_odoo_model_stats, get_model_relations, AUTO_EXPAND_THRESHOLD
from .scanner import (
    BINARY_EXTS,
    is_trivial_init_py,
    scan_directory_files,
    scan_addon_files,
)
from .tree import print_akaidoo_tree

PRUNE_MODES = ["none", "soft", "medium", "hard"]
SHRINK_MODES = ["none", "soft", "medium", "hard"]

try:
    from importlib import metadata
except ImportError:
    import importlib_metadata as metadata

try:
    import pyperclip
except ImportError:
    pyperclip = None

try:
    __version__ = metadata.version("akaidoo")
except metadata.PackageNotFoundError:
    __version__ = "0.0.0-dev"

FRAMEWORK_ADDONS = (
    "base",
    "web",
    "web_editor",
    "web_tour",
    "portal",
    "mail",
    "digest",
    "bus",
    "auth_signup",
    "base_setup",
    "http_routing",
    "utm",
    "uom",
    "product",
)

PARENT_CHILD_AUTO_EXPAND = True
BLACKLIST_AUTO_EXPAND = {"res.config.settings"}
TOKEN_FACTOR = 0.27  # empiric factor to estimate how many token


@dataclass
class AkaidooContext:
    found_files_list: List[Path]
    shrunken_files_content: Dict[Path, str]
    addon_files_map: Dict[str, List[Path]]
    pruned_addons: Dict[str, str]
    addons_set: AddonsSet
    final_odoo_series: Optional[OdooSeries]
    selected_addon_names: Set[str]
    exclude_core: bool
    exclude_framework: bool
    expand_models_set: Set[str]
    diffs: List[str]
    shrink_mode: str = "none"
    prune_mode: str = "soft"

def version_callback_for_run(value: bool):
    if value:
        m_version = "unknown"
        mc_version = "unknown"
        try:
            m_version = metadata.version("manifestoo")
        except metadata.PackageNotFoundError:
            pass
        try:
            mc_version = metadata.version("manifestoo-core")
        except metadata.PackageNotFoundError:
            pass
        typer.echo(f"akaidoo version: {__version__}")
        typer.echo(f"manifestoo version: {m_version}")
        typer.echo(f"manifestoo-core version: {mc_version}")
        raise typer.Exit()


def process_and_output_files(
    files_to_process: List[Path],
    output_file_opt: Optional[Path],
    clipboard_opt: bool,
    edit_in_editor_opt: bool,
    editor_command_str_opt: Optional[str],
    separator_char: str,
    shrunken_files_content: Dict[Path, str],
    diffs: List[str],
    introduction: str,
):
    """Helper function to handle the output of found files."""
    if not files_to_process:
        echo.info("No files matched the criteria.")
        raise typer.Exit()

    sorted_file_paths = sorted(files_to_process)

    output_actions_count = sum(
        [edit_in_editor_opt, bool(output_file_opt), clipboard_opt]
    )
    if output_actions_count > 1:
        actions = [
            name
            for flag, name in [
                (edit_in_editor_opt, "--edit"),
                (output_file_opt, "--output-file"),
                (clipboard_opt, "--clipboard"),
            ]
            if flag
        ]
        echo.error(
            f"Please choose only one primary output action from: {', '.join(actions)}."
        )
        raise typer.Exit(1)

    if edit_in_editor_opt:
        cmd_to_use = (
            editor_command_str_opt
            or os.environ.get("VISUAL")
            or os.environ.get("EDITOR")
            or "nvim"
        )
        try:
            editor_parts = shlex.split(cmd_to_use)
        except ValueError as e:
            echo.error(f"Error parsing editor command '{cmd_to_use}': {e}")
            raise typer.Exit(1)
        if not editor_parts:
            echo.error(f"Editor command '{cmd_to_use}' invalid.")
            raise typer.Exit(1)
        full_command = editor_parts + [str(p) for p in sorted_file_paths]
        echo.info(f"Executing: {' '.join(shlex.quote(str(s)) for s in full_command)}")
        try:
            process = subprocess.run(full_command, check=False)
            if process.returncode != 0:
                echo.warning(f"Editor exited with status {process.returncode}.")
        except FileNotFoundError:
            echo.error(f"Editor command not found: {shlex.quote(editor_parts[0])}")
            raise typer.Exit(1)
        except Exception as e:
            echo.error(f"Failed to execute editor: {e}")
            raise typer.Exit(1)
    elif clipboard_opt:
        if pyperclip is None:
            echo.error("Clipboard requires 'pyperclip'. Install it and try again.")
            if not output_file_opt:
                echo.warning("Fallback: File paths:")
                print_list(
                    [str(p) for p in sorted_file_paths],
                    separator_char,
                )
            raise typer.Exit(1)
        all_content_for_clipboard = []
        for fp in sorted_file_paths:
            try:
                try:
                    header_path = fp.resolve().relative_to(Path.cwd())
                except ValueError:
                    header_path = fp.resolve()
                header = (
                    f"# FILEPATH: {header_path}\n"
                )
                content = shrunken_files_content.get(
                    fp.resolve(),
                    re.sub(r"^(?:#.*\n)+", "", fp.read_text(encoding="utf-8")),
                )
                all_content_for_clipboard.append(header + content)
            except Exception as e:
                echo.warning(f"Could not read file {fp} for clipboard: {e}")
        for diff in diffs:
            all_content_for_clipboard.append(diff)

        clipboard_text = introduction + "\n\n".join(all_content_for_clipboard)
        try:
            pyperclip.copy(clipboard_text)
            print(
                f"Content of {len(sorted_file_paths)} files ({len(clipboard_text) / 1024:.2f} KB - {len(clipboard_text) * TOKEN_FACTOR / 1000.0:.0f}k TOKENS) copied to clipboard."
            )
        except Exception as e:  # Catch pyperclip specific errors
            echo.error(f"Clipboard operation failed: {e}")
            if not output_file_opt:
                echo.warning("Fallback: File paths:")
                print_list(
                    [str(p) for p in sorted_file_paths],
                    separator_char,
                )
            raise typer.Exit(1)
    elif output_file_opt:
        output_file_opt.parent.mkdir(parents=True, exist_ok=True)
        echo.info(
            f"Writing content of {len(sorted_file_paths)} files to {output_file_opt}..."
        )
        total_size = 0
        try:
            with output_file_opt.open("w", encoding="utf-8") as f:
                f.write(introduction + "\n\n")
                for fp in sorted_file_paths:
                    try:
                        try:
                            header_path = fp.resolve().relative_to(Path.cwd())
                        except ValueError:
                            header_path = fp.resolve()
                        header = f"# FILEPATH: {header_path}\n"
                        content = shrunken_files_content.get(
                            fp.resolve(),
                            re.sub(
                                r"^(?:#.*\n)+",
                                "",
                                fp.read_text(encoding="utf-8"),
                            ),
                        )
                        f.write(header + content + "\n\n")
                        total_size += len(header) + len(content) + 2
                    except Exception as e:
                        echo.warning(f"Could not read or write file {fp}: {e}")
                for diff in diffs:
                    f.write(diff)
                    total_size += len(diff)
            print(
                f"Successfully wrote {total_size / 1024:.2f} KB - {total_size * TOKEN_FACTOR / 1000.0:.0f}k TOKENS to {output_file_opt}"
            )
        except Exception as e:
            echo.error(f"Error writing to {output_file_opt}: {e}")
            raise typer.Exit(1)
    else:  # Default: print paths
        print_list([str(p.resolve()) for p in sorted_file_paths], separator_char)


def scan_extra_scripts(
    addon_name: str,
    openupgrade_path: Optional[Path],
    module_diff_path: Optional[Path],
) -> List[Path]:
    extra_files = []
    if openupgrade_path:
        ou_scripts_base_path = openupgrade_path / "openupgrade_scripts" / "scripts"
        addon_ou_script_path = ou_scripts_base_path / addon_name
        if addon_ou_script_path.is_dir():
            echo.debug(
                f"Scanning OpenUpgrade scripts in {addon_ou_script_path} "
                f"for {addon_name}..."
            )
            for ou_file in addon_ou_script_path.rglob("*"):
                if ou_file.is_file():
                    extra_files.append(ou_file.resolve())
        else:
            echo.debug(
                f"No OpenUpgrade script directory found for {addon_name} "
                f"at {addon_ou_script_path}"
            )

    if module_diff_path:
        addon_diff_path = module_diff_path / addon_name
        if addon_diff_path.is_dir():
            echo.debug(
                f"Scanning module diff scripts in {addon_diff_path} "
                f"for {addon_name}..."
            )
            for diff_file in addon_diff_path.rglob("*"):
                if diff_file.is_file():
                    extra_files.append(diff_file.resolve())
        else:
            echo.debug(
                f"No addon diff directory found for {addon_name} at {addon_diff_path}"
            )
    return extra_files


def expand_inputs(
    addon_name_input: str,
) -> tuple[Set[str], Set[Path], bool, Optional[Path]]:
    """
    Parses the input string to determine:
    1. Target addon names (explicit or discovered from paths).
    2. Implicit addons paths (directories containing the discovered addons).
    3. Whether to force directory mode (if input is a single path ending in /).
    4. The directory path for directory mode.
    """
    raw_inputs = comma_split(addon_name_input)
    selected_addon_names = set()
    implicit_addons_paths = set()

    # Check for forced directory mode (Mode 1)
    # If single input, is a directory, and ends with separator OR is not an addon
    if len(raw_inputs) == 1:
        path_str = raw_inputs[0]
        potential_path = Path(path_str)
        is_dir = potential_path.is_dir()
        ends_with_sep = path_str.endswith(os.path.sep)
        has_manifest = (potential_path / "__manifest__.py").is_file()
        
        if is_dir and (ends_with_sep or not has_manifest):
            # Special case: It's a directory scan request
            # Unless it's a container of addons and user DID NOT force slash?
            # User requirement: "akaidoo some_dir" -> concat content (recursively) if not an addon?
            # But "project mode" says: "akaidoo ./custom_addons" -> select all addons inside.
            # Conflict: ./custom_addons (container) vs ./some_dir (just files).
            # Heuristic: If it contains addons (subdirs with manifests), treat as project mode.
            # If forced with slash, treat as directory mode.
            
            if ends_with_sep:
                return set(), set(), True, potential_path
            
            # Check if container
            has_sub_addons = any((sub / "__manifest__.py").is_file() for sub in potential_path.iterdir() if sub.is_dir())
            if not has_sub_addons:
                 return set(), set(), True, potential_path

    # Project/Addon Mode (Mode 2)
    for item in raw_inputs:
        path = Path(item)
        if path.is_dir():
            # Case A: Path to an addon
            if (path / "__manifest__.py").is_file():
                # Addon found by path
                # Use directory name as addon name (standard convention)
                name = path.name
                selected_addon_names.add(name)
                implicit_addons_paths.add(path.parent.resolve())
            else:
                # Case B: Path to a container of addons
                found_any = False
                for sub in path.iterdir():
                    if sub.is_dir() and (sub / "__manifest__.py").is_file():
                        selected_addon_names.add(sub.name)
                        found_any = True
                
                if found_any:
                    implicit_addons_paths.add(path.resolve())
                else:
                    # It's a directory path but not an addon and no addons inside?
                    # Treat as simple name? Or warn?
                    # If it was part of a comma list, assume user meant it as a name if no path found.
                    # But path.is_dir() is true. So it's just a folder with no addons.
                    # Ignore or warn. Let's ignore path expansion and treat as name? 
                    # No, if it exists as a dir, it shouldn't be treated as an addon name unless it IS one.
                    # Let's assume user made a mistake or it's a weird input.
                    # For now, if we found nothing, maybe just add it as a name fallback?
                    if not found_any:
                         selected_addon_names.add(item)
        else:
            # Simple name
            selected_addon_names.add(item)

    return selected_addon_names, implicit_addons_paths, False, None


def resolve_addons_selection(
    selected_addon_names: Set[str],
    addons_set: AddonsSet,
    exclude_core: bool,
    final_odoo_series: Optional[OdooSeries],
) -> List[str]:
    selection = AddonsSelection(selected_addon_names)
    sorter = AddonSorterTopological()
    try:
        dependent_addons, missing = list_depends_command(
            selection, addons_set, True, True, sorter
        )
    except CycleErrorExit:
        raise typer.Exit(1)
    if missing:
        echo.warning(f"Missing dependencies: {', '.join(sorted(missing))}")

    dependent_addons_list = list(dependent_addons)
    echo.info(
        f"{len(dependent_addons_list)} addons in dependency tree (incl. targets).",
        bold=True,
    )
    if manifestoo_echo_module.verbosity >= 2:
        echo.info("Dependency list: ", nl=False)
        print_list(dependent_addons_list, ", ")

    if exclude_core:
        ensure_odoo_series(final_odoo_series)
        core_addons_set = get_core_addons(final_odoo_series)
        echo.info(
            f"Excluding {len(core_addons_set)} core addons for {final_odoo_series}."
        )
        intermediate_target_addons = []
        for dep_name in dependent_addons_list:
            if dep_name not in core_addons_set:
                intermediate_target_addons.append(dep_name)
            elif manifestoo_echo_module.verbosity >= 1:
                echo.info(f"Excluding core addon: {dep_name}")
        return intermediate_target_addons

    return dependent_addons_list


def resolve_addons_path(
    addons_path_str: Optional[str],
    addons_path_from_import_odoo: bool,
    addons_path_python: str,
    odoo_cfg: Optional[Path],
) -> ManifestooAddonsPath:
    m_addons_path = ManifestooAddonsPath()
    if addons_path_str:
        m_addons_path.extend_from_addons_path(addons_path_str)
    if addons_path_from_import_odoo:
        m_addons_path.extend_from_import_odoo(addons_path_python)
    if odoo_cfg:
        m_addons_path.extend_from_odoo_cfg(odoo_cfg)
    elif (
        os.environ.get("VIRTUAL_ENV")
        and os.environ["VIRTUAL_ENV"].endswith("odoo")
        and Path(os.environ["VIRTUAL_ENV"] + ".cfg").is_file()
    ):
        echo.debug(f"reading addons_path from {os.environ['VIRTUAL_ENV']}.cfg")
        m_addons_path.extend_from_odoo_cfg(os.environ["VIRTUAL_ENV"] + ".cfg")
    elif Path("/etc/odoo.cfg").is_file():
        echo.debug("reading addons_path from /etc/odoo.cfg")
        m_addons_path.extend_from_odoo_cfg("/etc/odoo.cfg")
    return m_addons_path


def resolve_akaidoo_context(
    addon_name: str,
    addons_path_str: Optional[str] = None,
    addons_path_from_import_odoo: bool = True,
    addons_path_python: str = sys.executable,
    odoo_cfg: Optional[Path] = None,
    odoo_series: Optional[OdooSeries] = None,
    openupgrade_path: Optional[Path] = None,
    module_diff_path: Optional[Path] = None,
    migration_commits: bool = False,
    include_models: bool = True,
    include_views: bool = False,
    include_wizards: bool = False,
    include_reports: bool = False,
    include_data: bool = False,
    only_models: bool = False,
    only_views: bool = False,
    exclude_core: bool = False,
    exclude_framework: bool = True,
    shrink_mode: str = "none",
    expand_models_str: Optional[str] = None,
    auto_expand: bool = True,
    focus_models_str: Optional[str] = None,
    add_expand_str: Optional[str] = None,
    rm_expand_str: Optional[str] = None,
    prune_mode: str = "soft",
) -> AkaidooContext:
    found_files_list: List[Path] = []
    addon_files_map: Dict[str, List[Path]] = {}
    shrunken_files_content: Dict[Path, str] = {}
    diffs = []
    expand_models_set = set()

    if expand_models_str:
        expand_models_set = {m.strip() for m in expand_models_str.split(",")}

    focus_models_set: set[str] = set()
    add_expand_set: set[str] = set()
    rm_expand_set: set[str] = set()

    if rm_expand_str:
        rm_expand_set = {m.strip() for m in rm_expand_str.split(",")}

    # If focus models are provided, auto-expand is disabled automatically
    if focus_models_str and auto_expand:
        auto_expand = False

    focus_modes_count = sum([bool(focus_models_str), bool(add_expand_str), auto_expand])
    if focus_modes_count > 1:
        focus_flags = [
            name
            for flag, name in [
                (focus_models_str, "--focus-models"),
                (add_expand_str, "--add-expand"),
                (auto_expand, "--auto-expand"),
            ]
            if flag
        ]
        echo.error(
            f"Only one mode can be used at a time: {', '.join(focus_flags)}. "
            "Use either --focus-models, --add-expand, or --auto-expand."
        )
        raise typer.Exit(1)

    if focus_models_str:
        focus_models_set = {m.strip() for m in focus_models_str.split(",")}
        auto_expand = False
        expand_models_set = focus_models_set.copy()
    elif add_expand_str:
        add_expand_set = {m.strip() for m in add_expand_str.split(",")}
    elif auto_expand:
        pass

    # Apply rm_expand
    if rm_expand_set:
        expand_models_set = expand_models_set - rm_expand_set
        if rm_expand_set and manifestoo_echo_module.verbosity >= 1:
            echo.info(
                f"Removed {len(rm_expand_set)} models from auto-expand set: {', '.join(sorted(rm_expand_set))}"
            )

    focus_models_set: set[str] = set()
    add_expand_set: set[str] = set()

    # If focus models are provided, auto-expand is disabled automatically
    if focus_models_str and auto_expand:
        auto_expand = False

    focus_modes_count = sum([bool(focus_models_str), bool(add_expand_str), auto_expand])
    if focus_modes_count > 1:
        focus_flags = [
            name
            for flag, name in [
                (focus_models_str, "--focus-models"),
                (add_expand_str, "--add-expand"),
                (auto_expand, "--auto-expand"),
            ]
            if flag
        ]
        echo.error(
            f"Only one mode can be used at a time: {', '.join(focus_flags)}. "
            "Use either --focus-models, --add-expand, or --auto-expand."
        )
        raise typer.Exit(1)

    if focus_models_str:
        focus_models_set = {m.strip() for m in focus_models_str.split(",")}
        auto_expand = False
        expand_models_set = focus_models_set.copy()
    elif add_expand_str:
        add_expand_set = {m.strip() for m in add_expand_str.split(",")}
    elif auto_expand:
        pass

    # Expand inputs (Project Mode / Smart Path)
    (
        selected_addon_names,
        implicit_addons_paths,
        force_directory_mode,
        directory_mode_path,
    ) = expand_inputs(addon_name)

    # Update Session Context Summary
    if Path(".akaidoo/context").is_dir():
        summary_path = Path(".akaidoo/context/summary.json")
        try:
            summary = {
                "addons": sorted(list(selected_addon_names)),
                "focus_models": sorted(list(focus_models_set))
                if focus_models_set
                else None,
            }
            summary_path.write_text(json.dumps(summary, indent=2))
        except Exception as e:
            echo.warning(f"Failed to update session summary: {e}")

    # --- Mode 1: Directory Mode ---
    if force_directory_mode and directory_mode_path:
        echo.info(
            f"Target '{directory_mode_path}' is a directory. Listing all files recursively.",
            bold=True,
        )
        if not directory_mode_path.is_absolute():
            directory_mode_path = directory_mode_path.resolve()
            echo.debug(f"Resolved relative path to: {directory_mode_path}")

        found_files_list = scan_directory_files(directory_mode_path)
        echo.info(
            f"Found {len(found_files_list)} files in directory {directory_mode_path}."
        )

        return AkaidooContext(
            found_files_list=found_files_list,
            shrunken_files_content=shrunken_files_content,
            addon_files_map={},
            pruned_addons={},
            addons_set=AddonsSet(),
            final_odoo_series=None,
            selected_addon_names=set(),
            exclude_core=exclude_core,
            exclude_framework=exclude_framework,
            expand_models_set=set(),
            diffs=[],
        )

    # --- Mode 2: Odoo Addon Mode (Project Mode) ---
    echo.info(
        f"Target(s) '{', '.join(sorted(selected_addon_names))}' treated as Odoo addon name(s).",
        bold=True,
    )

    m_addons_path = resolve_addons_path(
        addons_path_str,
        addons_path_from_import_odoo,
        addons_path_python,
        odoo_cfg,
    )

    # Add implicit paths discovered from arguments
    if implicit_addons_paths:
        m_addons_path.extend_from_addons_dirs(implicit_addons_paths)
        echo.info(
            f"Implicitly added addons paths: {', '.join(str(p) for p in implicit_addons_paths)}"
        )

    if not m_addons_path:
        echo.error(
            "Could not determine addons path for Odoo mode. "
            "Please provide one via --addons-path or --odoo-cfg, or provide a path to an addon/container."
        )
        raise typer.Exit(1)

    if m_addons_path:
        echo.info(str(m_addons_path), bold_intro="Using Addons path: ")

    addons_set = AddonsSet()
    if m_addons_path:
        addons_set.add_from_addons_dirs(m_addons_path)

    if not addons_set:
        echo.error("No addons found in the specified addons path(s) for Odoo mode.")
        raise typer.Exit(1)

    if addons_set:
        echo.info(str(addons_set), bold_intro="Found Addons set: ")

    final_odoo_series = odoo_series
    if not final_odoo_series and addons_set:
        detected_odoo_series = detect_from_addons_set(addons_set)
        if len(detected_odoo_series) == 1:
            final_odoo_series = detected_odoo_series.pop()
    if exclude_core and not final_odoo_series:
        ensure_odoo_series(final_odoo_series)

    missing_addons = selected_addon_names - set(addons_set.keys())
    if missing_addons:
        echo.error(
            f"Addon(s) '{', '.join(missing_addons)}' not found in configured Odoo addons paths. "
            f"Available: {', '.join(sorted(addons_set)) or 'None'}"
        )
        raise typer.Exit(1)

    intermediate_target_addons = resolve_addons_selection(
        selected_addon_names, addons_set, exclude_core, final_odoo_series
    )

    target_addon_names: List[str]
    if prune_mode == "hard":
        target_addon_names = [
            addon
            for addon in intermediate_target_addons
            if addon in selected_addon_names
        ]
        if target_addon_names:
            echo.info(
                f"Focusing only on the target addon(s): {', '.join(target_addon_names)}",
                bold=True,
            )
        else:
            echo.warning(
                f"Target addon(s) '{', '.join(selected_addon_names)}' excluded by other filters or dependencies. "
                "No files processed."
            )
    else:
        target_addon_names = intermediate_target_addons
    echo.info(
        f"Will scan files from {len(target_addon_names)} Odoo addons after all filters.",
        bold=True,
    )

    # Initialize relevant_models as empty set for first pass
    relevant_models: Set[str] = set()

    # Auto-expand harvesting
    if auto_expand:
        # We need to scan the TARGET addons to find which models are significantly extended
        # We use a set of names we explicitly selected OR detected as targets
        harvest_targets = selected_addon_names
        echo.debug(
            f"Auto-expand: Scanning {len(harvest_targets)} target addon(s) for models with score >= {AUTO_EXPAND_THRESHOLD}"
        )
        for addon_name_to_harvest in harvest_targets:
            addon_meta = addons_set.get(addon_name_to_harvest)
            if not addon_meta:
                continue

            addon_dir = addon_meta.path.resolve()
            models_dir = addon_dir / "models"
            if not models_dir.exists() or not models_dir.is_dir():
                echo.debug(
                    f"Auto-expand: No models directory in addon '{addon_name_to_harvest}'"
                )
                continue

            echo.debug(
                f"Auto-expand: Harvesting from addon '{addon_name_to_harvest}' models at {models_dir}"
            )
            # Scan all .py files in models directory
            for py_file in models_dir.rglob("*.py"):
                if not py_file.is_file() or "__pycache__" in py_file.parts:
                    continue
                try:
                    stats = get_odoo_model_stats(py_file.read_text(encoding="utf-8"))
                    if manifestoo_echo_module.verbosity >= 1:
                        echo.info(f"Auto-expand: Scanning {py_file.relative_to(addon_dir)}")
                    for model_name, info in stats.items():
                        score = info.get("score", 0)
                        if score >= AUTO_EXPAND_THRESHOLD:
                            if model_name not in expand_models_set:
                                if model_name in BLACKLIST_AUTO_EXPAND:
                                    if manifestoo_echo_module.verbosity >= 1:
                                        echo.info(
                                            f"Skipping model '{model_name}' - blacklisted from auto-expand"
                                        )
                                    continue
                                if manifestoo_echo_module.verbosity >= 1:
                                    echo.info(
                                        f"Auto-expanding model '{model_name}' (score: {score}, fields: {info['fields']}, methods: {info['methods']})"
                                    )
                                expand_models_set.add(model_name)
                        else:
                            if manifestoo_echo_module.verbosity >= 1:
                                echo.info(
                                    f"Skipping model '{model_name}' - score {score} below threshold {AUTO_EXPAND_THRESHOLD}"
                                )
                except Exception:
                    continue
        if manifestoo_echo_module.verbosity >= 1:
            if expand_models_set:
                echo.info(
                    f"Auto-expanded {len(expand_models_set)} models: {', '.join(sorted(expand_models_set))}"
                )
            else:
                echo.info("Auto-expand: No models met the threshold criteria.")
    elif focus_models_set:
        if manifestoo_echo_module.verbosity >= 1:
            echo.info(
                f"Focus mode: Expanding {len(focus_models_set)} specified models: {', '.join(sorted(focus_models_set))}"
            )

    if add_expand_set:
        expand_models_set.update(add_expand_set)
        if manifestoo_echo_module.verbosity >= 1:
            echo.info(
                f"Added {len(add_expand_set)} models to expand set: {', '.join(sorted(add_expand_set))}"
            )

    if PARENT_CHILD_AUTO_EXPAND and expand_models_set and prune_mode == "soft":
        enriched_additions = set()
        for m in list(expand_models_set):
            if m.endswith(".line"):
                parent = m[:-5]
                if (
                    parent
                    and parent not in expand_models_set
                    and parent not in BLACKLIST_AUTO_EXPAND
                ):
                    enriched_additions.add(parent)
            else:
                child = f"{m}.line"
                if (
                    child not in expand_models_set
                    and child not in BLACKLIST_AUTO_EXPAND
                ):
                    enriched_additions.add(child)

        if enriched_additions:
            expand_models_set.update(enriched_additions)
            if manifestoo_echo_module.verbosity >= 1:
                echo.info(
                    f"Enriched parent/child models ({len(enriched_additions)}): {', '.join(sorted(enriched_additions))}"
                )

    relevant_models = expand_models_set.copy()

    processed_addons_count = 0
    for addon_to_scan_name in target_addon_names:
        addon_meta = addons_set.get(addon_to_scan_name)
        if addon_meta:
            addon_dir = addon_meta.path.resolve()
            if addon_dir.parts[-1] not in FRAMEWORK_ADDONS:
                manifest_path = addon_dir / "__manifest__.py"
                found_files_list.append(manifest_path)

                # Shrink manifest for dependencies
                is_dependency = addon_to_scan_name not in selected_addon_names
                if is_dependency and shrink_mode != "none":
                    try:
                        content = manifest_path.read_text(encoding="utf-8")
                        shrunken = shrink_manifest(content, prune_mode=prune_mode)
                        shrunken_files_content[manifest_path.resolve()] = shrunken
                    except Exception as e:
                        echo.warning(
                            f"Failed to shrink manifest for {addon_to_scan_name}: {e}"
                        )

                if migration_commits and not str(addon_dir).endswith(
                    f"/addons/{addon_to_scan_name}"
                ):
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    manifest_dict = ast.literal_eval(content)
                    serie = manifest_dict.get("version").split(".")[0]
                    find_pr_commits_after_target(
                        diffs, addon_dir.parent, addon_to_scan_name, serie
                    )

                if (addon_dir / "readme" / "DESCRIPTION.md").is_file():
                    found_files_list.append(addon_dir / "readme" / "DESCRIPTION.md")
                elif (addon_dir / "readme" / "DESCRIPTION.rst").is_file():
                    found_files_list.append(addon_dir / "readme" / "DESCRIPTION.rst")
                if (addon_dir / "readme" / "USAGE.md").is_file():
                    found_files_list.append(addon_dir / "readme" / "USAGE.md")
                elif (addon_dir / "readme" / "USAGE.rst").is_file():
                    found_files_list.append(addon_dir / "readme" / "USAGE.rst")

            processed_addons_count += 1
            if manifestoo_echo_module.verbosity >= 3:
                echo.info(f"Scanning {addon_dir} for Odoo addon {addon_to_scan_name}...")

            addon_files = scan_addon_files(
                addon_dir=addon_dir,
                addon_name=addon_to_scan_name,
                selected_addon_names=selected_addon_names,
                include_models=include_models,
                include_views=include_views,
                include_wizards=include_wizards,
                include_reports=include_reports,
                include_data=include_data,
                only_models=only_models,
                only_views=only_views,
                exclude_framework=exclude_framework,
                framework_addons=FRAMEWORK_ADDONS,
                shrink_mode=shrink_mode,
                expand_models_set=expand_models_set,
                shrunken_files_content=shrunken_files_content,
                relevant_models=relevant_models,
                prune_mode=prune_mode,
            )
            addon_files_map[addon_to_scan_name] = addon_files
            for f in addon_files:
                if f not in found_files_list:
                    found_files_list.append(f)
        else:
            echo.warning(
                f"Odoo Addon '{addon_to_scan_name}' metadata not found, "
                "skipping its Odoo file scan."
            )

        extra_scripts = scan_extra_scripts(
            addon_to_scan_name, openupgrade_path, module_diff_path
        )
        for f in extra_scripts:
            if f not in found_files_list:
                found_files_list.append(f)

    # --- Smart Pruning ---
    pruned_addons: Dict[str, str] = {}
    if prune_mode not in ("none", "hard") and target_addon_names:
        echo.info("Analyzing models for smart pruning...", bold=True)

        all_relations: Dict[str, Set[str]] = {}
        addon_models: Dict[str, Set[str]] = {}

        # 1. Build Model Map from ALL scanned files
        for addon_name_iter, files in addon_files_map.items():
            addon_models[addon_name_iter] = set()
            for f in files:
                if f.suffix == ".py" and "__init__.py" not in f.name:
                    try:
                        # Optimization: we could use shrunken content if available and reliable,
                        # but getting relations requires field definitions which might be preserved.
                        # However, to be safe and accurate, we read the original file.
                        content = f.read_text(encoding="utf-8")
                        rels = get_model_relations(content)
                        if rels:
                            addon_models[addon_name_iter].update(rels.keys())
                            for m, r in rels.items():
                                if m not in all_relations:
                                    all_relations[m] = set()
                                all_relations[m].update(r)
                    except Exception:
                        pass

        # 2. Derive Related Models based on prune_mode
        related_models_set = set()
        if prune_mode == "soft":
            # Soft: Expand + Parent/Child + Related
            for m in expand_models_set:
                if m in all_relations:
                    related_models_set.update(all_relations[m])
            new_related = related_models_set - expand_models_set
            if new_related and manifestoo_echo_module.verbosity >= 1:
                echo.info(
                    f"Related models (not in expanded) ({len(new_related)}): {', '.join(sorted(new_related))}"
                )
        elif prune_mode == "medium":
            # Medium: Expanded only, no P/C or related
            pass

        relevant_models = expand_models_set | related_models_set

        if manifestoo_echo_module.verbosity >= 2:
            echo.info(
                f"Relevant models ({len(relevant_models)}): {', '.join(sorted(relevant_models))}"
            )

        # 3. Determine Pruned Addons
        files_to_remove = set()

        for addon in target_addon_names:
            reason = None
            if addon in FRAMEWORK_ADDONS:
                reason = "framework"
            else:
                # Check if addon contains any relevant model (defined or extended)
                if not (addon_models.get(addon, set()) & relevant_models):
                    reason = "no_relevant_models"

            if reason:
                pruned_addons[addon] = reason
                if manifestoo_echo_module.verbosity >= 1:
                    echo.info(f"Pruning addon '{addon}' ({reason})")

                # Mark files for removal (keep manifest)
                addon_files = addon_files_map.get(addon, [])
                for f in addon_files:
                    if f.name != "__manifest__.py":
                        files_to_remove.add(f)

        # Apply removal
        if files_to_remove:
            original_count = len(found_files_list)
            found_files_list = [f for f in found_files_list if f not in files_to_remove]
            echo.info(
                f"Pruned {len(pruned_addons)} addons, removed {original_count - len(found_files_list)} files."
            )

    return AkaidooContext(
        found_files_list=found_files_list,
        shrunken_files_content=shrunken_files_content,
        addon_files_map=addon_files_map,
        pruned_addons=pruned_addons,
        addons_set=addons_set,
        final_odoo_series=final_odoo_series,
        selected_addon_names=selected_addon_names,
        exclude_core=exclude_core,
        exclude_framework=exclude_framework,
        expand_models_set=expand_models_set,
        diffs=diffs,
    )


akaidoo_app = typer.Typer(help="Akaidoo: Odoo Context Dumper for AI")


@akaidoo_app.command(name="init")
def init_command():
    """Initialize Akaidoo state directory."""
    dot_akaidoo = Path(".akaidoo")
    if dot_akaidoo.exists():
        echo.info(".akaidoo/ already exists.")
    else:
        dot_akaidoo.mkdir()
        echo.info("Created .akaidoo/ directory.")

    rules_dir = dot_akaidoo / "rules"
    rules_dir.mkdir(exist_ok=True)

    guidelines_file = rules_dir / "oca_guidelines.md"
    if not guidelines_file.exists():
        guidelines_file.write_text(
            "# OCA Guidelines\n\n"
            "- Follow PEP8.\n"
            "- Use 4 spaces for indentation.\n"
            "- No tabs.\n"
            "- Use single quotes for strings unless they contain single quotes.\n"
            "- Models should have a `_description`.\n"
            "- Fields should have strings.\n"
            "- XML files should be indented with 2 spaces.\n"
            "- Use `odoo.addons.<module_name>` for imports.\n"
        )
        echo.info(f"Created {guidelines_file}")

    (dot_akaidoo / "context").mkdir(exist_ok=True)


@akaidoo_app.command(name="serve")
def serve_command(
    transport: str = typer.Option("stdio", help="Transport mechanism (stdio or sse)"),
):
    """Start the Akaidoo MCP server."""
    from .server import mcp

    echo.info(f"Starting Akaidoo MCP server using {transport}...")
    mcp.run(transport=transport)


@akaidoo_app.callback()
def global_callback(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=version_callback_for_run,
        is_eager=True,
        help="Show the version and exit.",
        show_default=False,
    ),
):
    """Akaidoo: Odoo Context Dumper for AI"""
    pass


@akaidoo_app.command(name="addon")
def akaidoo_command_entrypoint(
    addon_name: str = typer.Argument(
        ...,
        help="The name of the target Odoo addon, or a path to a directory.",
    ),
    verbose_level_count: int = typer.Option(
        0,
        "--verbose",
        "-V",
        count=True,
        help="Increase verbosity (can be used multiple times).",
        show_default=False,
    ),
    quiet_level_count: int = typer.Option(
        0,
        "--quiet",
        "-q",
        count=True,
        help="Decrease verbosity (can be used multiple times).",
        show_default=False,
    ),
    addons_path_str: Optional[str] = typer.Option(
        None,
        "--addons-path",
        help="Comma-separated list of directories to add to the addons path.",
        show_default=False,
    ),
    addons_path_from_import_odoo: bool = typer.Option(
        True,
        "--addons-path-from-import-odoo/--no-addons-path-from-import-odoo",
        help="Expand addons path by trying to `import odoo` and looking at `odoo.addons.__path__`.",
        show_default=True,
    ),
    addons_path_python: str = typer.Option(
        sys.executable,
        "--addons-path-python",
        show_default=True,
        metavar="PYTHON",
        help="The python executable for importing `odoo.addons.__path__`.",
    ),
    odoo_cfg: Optional[Path] = typer.Option(
        None,
        "-c",
        "--odoo-cfg",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        envvar="ODOO_RC",
        help="Expand addons path from Odoo configuration file.",
        show_default=False,
    ),
    odoo_series: Optional[OdooSeries] = typer.Option(
        None,
        envvar=["ODOO_VERSION", "ODOO_SERIES"],
        help="Odoo series to use, if not autodetected.",
        show_default=False,
    ),
    openupgrade_path: Optional[Path] = typer.Option(
        None,
        "--openupgrade",
        "-u",
        help="Path to the OpenUpgrade clone. If provided, includes migration scripts.",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        show_default=False,
    ),
    module_diff_path: Optional[Path] = typer.Option(
        None,
        "--module-diff",
        "-D",
        help="Path to the odoo-module-diff clone. If provided, includes pseudo version diffs",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        show_default=False,
    ),
    migration_commits: bool = typer.Option(
        False, "--migration-commits", help="Include deps migration commits"
    ),
    include_models: bool = typer.Option(
        True, "--include-models/--no-include-models", help="Include Python model files."
    ),
    include_views: bool = typer.Option(
        False, "--include-views/--no-include-views", help="Include XML view files."
    ),
    include_wizards: bool = typer.Option(
        False,
        "--include-wizards/--no-include-wizards",
        "-w",
        help="Include XML wizard files.",
    ),
    include_reports: bool = typer.Option(
        False,
        "--include-reports/--no-include-reports",
        "-r",
        help="Include XML report files (from report/ or reports/ subdir).",
    ),
    include_data: bool = typer.Option(
        False,
        "--include-data/--no-include-data",
        "-d",
        help="Include data files (from data/ subdir).",
    ),
    only_models: bool = typer.Option(
        False,
        "--only-models",
        "-m",
        help="Only list files under 'models/' directories.",
        show_default=False,
    ),
    only_views: bool = typer.Option(
        False,
        "--only-views",
        "-v",
        help="Only list files under 'views/' directories.",
        show_default=False,
    ),
    exclude_core: bool = typer.Option(
        False,
        "--exclude-core/--no-exclude-core",
        help="Exclude files from Odoo core addons.",
    ),
    exclude_framework: bool = typer.Option(
        True,
        "--exclude-framework/--no-exclude-framework",
        help=f"Exclude {FRAMEWORK_ADDONS} framework addons.",
    ),
    separator: str = typer.Option(
        "\n", "--separator", help="Separator character between filenames."
    ),
    shrink_mode: str = typer.Option(
        "soft",
        "--shrink",
        help="Shrink mode: none (no shrink), soft (deps shrunk with 'pass # shrunk', targets full), medium (relevant: soft in deps/none in targets, irrelevant: hard everywhere), hard (all methods removed).",
        case_sensitive=False,
    ),
    expand_models_str: Optional[str] = typer.Option(
        None,
        "--expand",
        "-E",
        help="Comma-separated list of Odoo models to fully expand even when shrinking.",
        show_default=False,
    ),
    rm_expand_str: Optional[str] = typer.Option(
        None,
        "--rm-expand",
        help="Remove models from auto-expand set. Comma-separated list.",
        show_default=False,
    ),
    auto_expand: bool = typer.Option(
        True,
        "--auto-expand/--no-auto-expand",
        help="Automatically expand models significantly extended in target addons (score >= 7). Score: field=1, method=3, 10 lines=2.",
    ),
    focus_models_str: Optional[str] = typer.Option(
        None,
        "--focus-models",
        "-F",
        help="Only expand specific models (overrides auto-expand). Comma-separated list.",
        show_default=False,
    ),
    add_expand_str: Optional[str] = typer.Option(
        None,
        "--add-expand",
        help="Add models to auto-expand set. Comma-separated list.",
        show_default=False,
    ),
    output_file: Optional[Path] = typer.Option(
        None,
        "--output-file",
        "-o",
        help="File path to write output to.",
        writable=True,
        file_okay=True,
        dir_okay=False,
    ),
    clipboard: bool = typer.Option(
        False,
        "--clipboard",
        "-x",
        help="Copy file contents to clipboard.",
        show_default=True,
    ),
    edit_in_editor: bool = typer.Option(
        False, "--edit", "-e", help="Open found files in an editor.", show_default=False
    ),
    editor_command_str: Optional[str] = typer.Option(
        None,
        "--editor-cmd",
        help="Editor command (e.g., 'code -r'). Defaults to $VISUAL, $EDITOR, then 'nvim'.",
    ),
    prune_mode: str = typer.Option(
        "soft",
        "--prune",
        help="Prune mode: none (keep all), soft (expanded + parent/child + related), medium (expanded only), hard (target addons only).",
        case_sensitive=False,
    ),
):
    manifestoo_echo_module.verbosity = (
        manifestoo_echo_module.verbosity + verbose_level_count - quiet_level_count
    )
    echo.debug(f"Effective verbosity: {manifestoo_echo_module.verbosity}")

    context = resolve_akaidoo_context(
        addon_name=addon_name,
        addons_path_str=addons_path_str,
        addons_path_from_import_odoo=addons_path_from_import_odoo,
        addons_path_python=addons_path_python,
        odoo_cfg=odoo_cfg,
        odoo_series=odoo_series,
        openupgrade_path=openupgrade_path,
        module_diff_path=module_diff_path,
        migration_commits=migration_commits,
        include_models=include_models,
        include_views=include_views,
        include_wizards=include_wizards,
        include_reports=include_reports,
        include_data=include_data,
        only_models=only_models,
        only_views=only_views,
        exclude_core=exclude_core,
        exclude_framework=exclude_framework,
        shrink_mode=shrink_mode,
        expand_models_str=expand_models_str,
        auto_expand=auto_expand,
        focus_models_str=focus_models_str,
        add_expand_str=add_expand_str,
        rm_expand_str=rm_expand_str,
        prune_mode=prune_mode,
    )

    cmd_call = shlex.join(sys.argv)
    introduction = f"""Role: Senior Odoo Architect enforcing OCA standards.
Context: The following is a codebase dump produced by the akaidoo CLI.
Command: {cmd_call}
Conventions:
1. Files start with `# FILEPATH: [path]`.
2. Some files were filtered out to save tokens; ask for them if you need."""
    if shrink_mode != "none":
        introduction += """
3. `# shrunk` indicates code removed to save tokens; ask for full content if a specific logic flow is unclear."""
    if shrink_mode == "hard":
        introduction += """
4. Method definitions were eventually entirely skipped to save tokens and focus on the data model only."""

    echo.info(f"Found {len(context.found_files_list)} total files.", bold=True)

    if (
        not any([clipboard, output_file, edit_in_editor])
        and context.selected_addon_names
    ):
        print_akaidoo_tree(
            context.selected_addon_names,
            context.addons_set,
            context.addon_files_map,
            context.final_odoo_series,
            context.exclude_core,
            fold_framework_addons=context.exclude_framework,
            framework_addons=FRAMEWORK_ADDONS,
            pruned_addons=context.pruned_addons,
        )
    else:
        process_and_output_files(
            context.found_files_list,
            output_file,
            clipboard,
            edit_in_editor,
            editor_command_str,
            separator,
            context.shrunken_files_content,
            context.diffs,
            introduction,
        )


def get_akaidoo_context_dump(
    context: AkaidooContext,
    introduction: str,
    focus_files: Optional[List[str]] = None,
) -> str:
    all_content = []
    all_content.append(introduction)

    sorted_files = sorted(context.found_files_list)
    if focus_files:
        filtered_files = []
        for f in sorted_files:
            f_str = str(f)
            if any(focus in f_str for focus in focus_files):
                filtered_files.append(f)
        sorted_files = filtered_files

    for fp in sorted_files:
        try:
            try:
                header_path = fp.resolve().relative_to(Path.cwd())
            except ValueError:
                header_path = fp.resolve()
            header = f"# FILEPATH: {header_path}\n"
            content = context.shrunken_files_content.get(
                fp.resolve(),
                re.sub(r"^(?:#.*\n)+", "", fp.read_text(encoding="utf-8")),
            )
            all_content.append(header + content)
        except Exception:
            continue

    for diff in context.diffs:
        all_content.append(diff)

    return "\n\n".join(all_content)


def find_pr_commits_after_target(
    diffs_list, repo_path, addon, serie, target_message=None
):
    if target_message is None:
        target_message = f" {addon}: Migration to {serie}"
    try:
        # Open the repository
        repo = Repo(repo_path)

        pr_commits = []

        # Find the target commit
        target_commit = None
        last_commits = []
        for commit in repo.iter_commits():
            last_commits.append(commit)
            if target_message in commit.message:
                target_commit = commit
                break

        if target_commit is None:
            print(f"no migration found for {addon}")
            return

        for commit in reversed(last_commits):
            if len(commit.parents) > 1:
                # print(f"Found merge commit: {commit.hexsha[:8]} - likely end of PR")
                break
            if ": " in commit.message and not commit.message.strip().split(": ")[
                0
            ].endswith(addon):
                break  # for some reason commit is for another module before any merge commit
            pr_commits.append(commit)

        # Display all commits in the PR
        print(f"\nFound {len(pr_commits)} commits for {addon} v{serie} migration")
        for i, commit in enumerate(pr_commits):
            print(
                f"{i + 1}. {commit.hexsha[:8]} - {commit.author.name} - {commit.message.splitlines()[0]}"
            )

        print("\n" + "=" * 80 + "\n")

        # Show diffs for each commit in the PR after the target
        target_index = next(
            (
                i
                for i, commit in enumerate(pr_commits)
                if commit.hexsha == target_commit.hexsha
            ),
            -1,
        )

        if target_index == -1:
            print("Error: Target commit not found in PR commits list")
            return

        for i in range(target_index + 1, len(pr_commits)):
            commit = pr_commits[i]
            if commit.parents:
                diff = commit.parents[0].diff(commit, create_patch=True)
                if diff:
                    for file_diff in diff:
                        diff_text = f"\nFile: {file_diff.a_path} -> {file_diff.b_path}"
                        diff_text += f"\nChange type: {file_diff.change_type}"
                        # Decode diff if it's bytes, otherwise use as is
                        if isinstance(file_diff.diff, bytes):
                            diff_text += "\n" + file_diff.diff.decode(
                                "utf-8", errors="replace"
                            )
                        else:
                            diff_text += "\n" + file_diff.diff
                    diffs_list.append(diff_text)

    except InvalidGitRepositoryError:
        print(f"The path '{repo_path}' is not a valid Git repository")
    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback

        traceback.print_exc()


def cli_entry_point():
    # Handle -o default value for session context
    args = sys.argv
    if "-o" in args:
        idx = args.index("-o")
        # Check if -o is followed by a value (not an option and not empty)
        if idx + 1 == len(args) or args[idx + 1].startswith("-"):
            args.insert(idx + 1, ".akaidoo/context/current.md")
    elif "--output-file" in args:
        idx = args.index("--output-file")
        if idx + 1 == len(args) or args[idx + 1].startswith("-"):
            args.insert(idx + 1, ".akaidoo/context/current.md")

    if len(sys.argv) > 1 and sys.argv[1] not in ["init", "addon", "serve", "--help", "--version"]:
        # Prepend 'addon' to sys.argv if not a known subcommand or global option
        sys.argv.insert(1, "addon")
    akaidoo_app()


if __name__ == "__main__":
    cli_entry_point()
