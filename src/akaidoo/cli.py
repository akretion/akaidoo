import sys
from pathlib import Path
from typing import List, Optional, Set
import shlex
import subprocess
import os

import typer
from manifestoo_core.addons_set import AddonsSet
from manifestoo_core.core_addons import get_core_addons
from manifestoo_core.odoo_series import OdooSeries, detect_from_addons_set
from manifestoo.addon_sorter import AddonSorterTopological
from manifestoo.addons_path import AddonsPath as ManifestooAddonsPath
from manifestoo.addons_selection import AddonsSelection
from manifestoo.commands.list_depends import list_depends_command
from manifestoo import echo
from manifestoo.echo import verbosity
from manifestoo.exceptions import CycleErrorExit
from manifestoo.utils import ensure_odoo_series, print_list

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
)


def is_trivial_init_py(file_path: Path) -> bool:
    try:
        with file_path.open("r", encoding="utf-8") as f:
            for line in f:
                stripped_line = line.strip()
                if (
                    not stripped_line
                    or stripped_line.startswith("#")
                    or stripped_line.startswith("import ")
                    or stripped_line.startswith("from ")
                ):
                    continue
                return False
        return True
    except Exception:
        return False


app = typer.Typer(
    help="Akaidoo: Lists relevant source files from an Odoo addon and its dependency tree.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
    no_args_is_help=True,  # If no args are provided, show help
)


def version_callback(value: bool) -> None:
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


@app.callback(invoke_without_command=True)
def akaidoo_main_cmd(
    ctx: typer.Context,
    # Main positional argument first
    addon_name: str = typer.Argument(
        ...,
        help="The name of the target Odoo addon.",
    ),
    # Then global-like options
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Show the version and exit.",
        show_default=False,
    ),
    verbose: int = typer.Option(
        0,
        "--verbose",
        "-V",
        count=True,
        help="Increase verbosity (can be used multiple times).",
        show_default=False,
    ),
    quiet: int = typer.Option(
        0,
        "--quiet",
        "-q",
        count=True,
        help="Decrease verbosity (can be used multiple times).",
        show_default=False,
    ),
    # Then other specific options
    addons_path_str: Optional[str] = typer.Option(
        None,
        "--addons-path",
        help="Comma-separated list of directories to add to the addons path.",
        show_default=False,
    ),
    addons_path_from_import_odoo: bool = typer.Option(
        True,
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
    include_models: bool = typer.Option(
        True, "--include-models/--no-include-models", help="Include Python model files."
    ),
    include_views: bool = typer.Option(
        True, "--include-views/--no-include-views", help="Include XML view files."
    ),
    include_wizards: bool = typer.Option(
        True, "--include-wizards/--no-include-wizards", help="Include XML wizard files."
    ),
    only_models: bool = typer.Option(
        False,
        "--only-models",
        help="Only list files under 'models/' directories.",
        show_default=False,
    ),
    only_views: bool = typer.Option(
        False,
        "--only-views",
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
        "\n", "--separator", "-s", help="Separator character between filenames."
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
    only_target_addon: bool = typer.Option(
        False,
        "--only-target-addon",
        "-l",
        help="Only list files from the target addon.",
        show_default=False,
    ),
):
    """
    (This docstring can be used by Typer for the main help if no subcommands exist)
    Akaidoo: Lists relevant source files from an Odoo addon and its dependency tree.
    """
    # This check ensures that if you ever add a subcommand later, this main logic
    # doesn't run when that subcommand is invoked.
    if ctx.invoked_subcommand:
        return

    # Set verbosity (this was correct before)
    # new_level = verbosity.get() + verbose - quiet
    # verbosity.set(new_level)
    # echo.debug(f"Effective verbosity: {verbosity.get()}")

    # ... (rest of your existing logic from akaidoo_main_cmd) ...
    m_addons_path = ManifestooAddonsPath()
    if addons_path_str:
        m_addons_path.extend_from_addons_path(addons_path_str)
    if addons_path_from_import_odoo:
        m_addons_path.extend_from_import_odoo(addons_path_python)
    if odoo_cfg:
        m_addons_path.extend_from_odoo_cfg(odoo_cfg)

    if not m_addons_path:
        echo.error("Could not determine addons path. Please provide one.")
        raise typer.Exit(1)
    echo.info(str(m_addons_path), bold_intro="Using Addons path: ")

    addons_set = AddonsSet()
    addons_set.add_from_addons_dirs(m_addons_path)
    if not addons_set:
        echo.error("No addons found in the specified addons path(s).")
        raise typer.Exit(1)
    echo.info(str(addons_set), bold_intro="Found Addons set: ")

    final_odoo_series = odoo_series
    if not final_odoo_series:
        detected_odoo_series = detect_from_addons_set(addons_set)
        if len(detected_odoo_series) == 1:
            final_odoo_series = detected_odoo_series.pop()
        elif len(detected_odoo_series) > 1:
            echo.warning(
                f"Multiple Odoo series detected: {', '.join(s.value for s in detected_odoo_series)}. Specify with --odoo-series."
            )
        else:
            echo.warning("Could not detect Odoo series. Core filtering might not work.")
    if exclude_core and not final_odoo_series:
        ensure_odoo_series(final_odoo_series)

    if addon_name not in addons_set:
        echo.error(
            f"Addon '{addon_name}' not found. Available: {', '.join(sorted(addons_set)) or 'None'}"
        )
        raise typer.Exit(1)

    selection = AddonsSelection({addon_name})
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
        f"{len(dependent_addons_list)} addons in dependency tree (incl. {addon_name}).",
        bold=True,
    )
    if verbosity >= 2:
        print_list(dependent_addons_list, ", ", intro="Dependency list: ")

    intermediate_target_addons: List[str] = []
    if exclude_core:
        assert final_odoo_series is not None
        core_addons_set = get_core_addons(final_odoo_series)
        echo.info(
            f"Excluding {len(core_addons_set)} core addons for {final_odoo_series}."
        )  # Corrected variable name
        for dep_name in dependent_addons_list:
            if dep_name not in core_addons_set:
                intermediate_target_addons.append(dep_name)
            elif verbosity.get() >= 1:
                echo.info(f"Excluding core addon: {dep_name}")
    else:
        intermediate_target_addons = dependent_addons_list

    target_addons: List[str]
    if only_target_addon:
        if addon_name in intermediate_target_addons:
            target_addons = [addon_name]
            echo.info(f"Focusing only on the target addon: {addon_name}", bold=True)
        else:
            target_addons = []
            echo.warning(
                f"Target addon '{addon_name}' excluded by other filters. No files processed."
            )
    else:
        target_addons = intermediate_target_addons
    echo.info(
        f"Will scan files from {len(target_addons)} addons after all filters.",
        bold=True,
    )

    found_files: List[Path] = []
    processed_addons_count = 0
    for addon_to_scan in target_addons:
        addon = addons_set.get(addon_to_scan)
        if not addon:
            echo.warning(
                f"Addon '{addon_to_scan}' metadata not found, skipping file scan."
            )
            continue
        addon_dir = addon.path.resolve()
        processed_addons_count += 1
        echo.debug(f"Scanning {addon_dir} for {addon_to_scan}...")
        scan_roots: List[str] = []
        if only_models:
            scan_roots.append("models")
        elif only_views:
            scan_roots.append("views")
        else:
            if include_models:
                scan_roots.append("models")
            if include_views:
                scan_roots.append("views")
            if include_wizards:
                scan_roots.extend(["wizard", "wizards"])
            if not scan_roots or include_models:
                scan_roots.append(".")
        extensions: List[str] = []
        if include_models or only_models:
            extensions.append(".py")
        if include_views or only_views or include_wizards:
            extensions.append(".xml")
        extensions = list(set(extensions))  # Deduplicate
        if not extensions:
            echo.debug(
                f"No specific file types for {addon_to_scan}, skipping globbing."
            )
            continue
        for root_name in set(scan_roots):
            scan_path_dir = addon_dir / root_name if root_name != "." else addon_dir
            if not scan_path_dir.is_dir():
                continue
            for ext in extensions:
                files_to_check: List[Path] = []
                if root_name == ".":
                    if ext == ".py":
                        files_to_check.extend(scan_path_dir.glob("*.py"))
                elif root_name == "models":
                    if ext == ".py":
                        files_to_check.extend(scan_path_dir.glob("**/*.py"))
                elif root_name == "views":
                    if ext == ".xml":
                        files_to_check.extend(scan_path_dir.glob("**/*.xml"))
                elif root_name in ("wizard", "wizards"):
                    if ext == ".xml":
                        files_to_check.extend(scan_path_dir.glob("**/*.xml"))
                for found_file in files_to_check:
                    if not found_file.is_file():
                        continue
                    relative_path_parts = found_file.relative_to(addon_dir).parts
                    is_framework_file = any(
                        f"/addons/{name}/" in str(found_file.resolve())
                        for name in FRAMEWORK_ADDONS
                    )
                    is_model_file = "models" in relative_path_parts and ext == ".py"
                    is_view_file = "views" in relative_path_parts and ext == ".xml"
                    is_wizard_file = (
                        "wizard" in relative_path_parts
                        or "wizards" in relative_path_parts
                    ) and ext == ".xml"
                    is_root_py_file = (
                        len(relative_path_parts) == 1
                        and relative_path_parts[0].endswith(".py")
                        and root_name == "."
                    )
                    if only_models and not is_model_file:
                        continue
                    if only_views and not is_view_file:
                        continue
                    if is_framework_file and exclude_framework:
                        if verbosity >= 1:
                            echo.info(f"Excluding framework file: {found_file}")
                        continue
                    if not (only_models or only_views):
                        file_type_matches_include = False
                        if include_models and (is_model_file or is_root_py_file):
                            file_type_matches_include = True
                        if include_views and is_view_file:
                            file_type_matches_include = True
                        if include_wizards and is_wizard_file:
                            file_type_matches_include = True
                        if (
                            root_name == "."
                            and not is_root_py_file
                            and not (is_model_file or is_view_file or is_wizard_file)
                        ):
                            if not file_type_matches_include:
                                continue
                        elif not file_type_matches_include:
                            continue
                    if (
                        found_file.name == "__init__.py"
                        and (is_model_file or is_root_py_file)
                        and is_trivial_init_py(found_file)
                    ):
                        echo.debug(f"  Skipping trivial __init__.py: {found_file}")
                        continue
                    abs_file_path = found_file.resolve()
                    if abs_file_path not in found_files:
                        found_files.append(abs_file_path)

    echo.info(
        f"Found {len(found_files)} files in {processed_addons_count} scanned addons.",
        bold=True,
    )
    if not found_files:
        echo.info("No files matched the criteria.")
        raise typer.Exit()
    sorted_file_paths = sorted(found_files)

    output_actions_count = sum([edit_in_editor, bool(output_file), clipboard])
    if output_actions_count > 1:
        actions = [
            name
            for flag, name in [
                (edit_in_editor, "--edit"),
                (output_file, "--output-file"),
                (clipboard, "--clipboard"),
            ]
            if flag
        ]
        echo.error(
            f"Please choose only one primary output action from: {', '.join(actions)}."
        )
        raise typer.Exit(1)

    if edit_in_editor:
        cmd_to_use = (
            editor_command_str
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
    elif clipboard:
        if pyperclip is None:
            echo.error("Clipboard requires 'pyperclip'. Install it and try again.")
            if not output_file:
                print_list(
                    [str(p) for p in sorted_file_paths],
                    separator,
                    intro="Fallback: File paths:",
                )
            raise typer.Exit(1)
        all_content_for_clipboard = []  # Initialize list
        for fp in sorted_file_paths:  # Iterate to build content
            try:
                header = f"# FILEPATH: {fp}\n"
                content = fp.read_text(encoding="utf-8")
                all_content_for_clipboard.append(header + content)
            except Exception as e:
                echo.warning(f"Could not read file {fp} for clipboard: {e}")

        clipboard_text = "\n\n".join(all_content_for_clipboard)
        try:
            pyperclip.copy(clipboard_text)
            echo.info(
                f"Content of {len(sorted_file_paths)} files ({len(clipboard_text) / 1024:.2f} KB) copied to clipboard."
            )
        except Exception as e:
            echo.error(f"Clipboard operation failed: {e}")
            if not output_file:
                print_list(
                    [str(p) for p in sorted_file_paths],
                    separator,
                    intro="Fallback: File paths:",
                )
            raise typer.Exit(1)
    elif output_file:
        echo.info(
            f"Writing content of {len(sorted_file_paths)} files to {output_file}..."
        )
        total_size = 0
        try:
            with output_file.open("w", encoding="utf-8") as f:
                for i, file_path in enumerate(sorted_file_paths):
                    try:
                        header = f"# FILEPATH: {file_path}\n"
                        content = file_path.read_text(encoding="utf-8")
                        f.write(header + content + "\n\n")
                        total_size += len(header) + len(content) + 2
                        if len(sorted_file_paths) > 50 and (i + 1) % 25 == 0:
                            echo.info(
                                f"  Written {i+1}/{len(sorted_file_paths)} files ({total_size / 1024:.2f} KB)..."
                            )
                    except Exception as e:
                        echo.warning(
                            f"Could not read or write file {file_path}: {e}"
                        )  # Corrected variable
            echo.info(f"Successfully wrote {total_size / 1024:.2f} KB to {output_file}")
        except Exception as e:
            echo.error(f"Error writing to {output_file}: {e}")
            raise typer.Exit(1)
    else:
        print_list([str(p) for p in sorted_file_paths], separator)


# @app.command()
# def do_something(
#     some_arg: str = typer.Argument(...),
#     some_option: bool = typer.Option(False, "--some-option"),
# ):
#     """
#     Does something else.
#     """
#     echo.info(f"Doing something with {some_arg} and option: {some_option}")


if __name__ == "__main__":
    app()
