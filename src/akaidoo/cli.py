import sys
from pathlib import Path
from typing import List, Optional, Set
import shlex
import subprocess
import os

import typer
from manifestoo_core.addons_set import AddonsSet
from manifestoo_core.core_addons import get_core_addons  # is_core_addon no longer used
from manifestoo_core.odoo_series import OdooSeries, detect_from_addons_set
from manifestoo.addon_sorter import AddonSorterTopological
from manifestoo.addons_path import AddonsPath as ManifestooAddonsPath
from manifestoo.addons_selection import AddonsSelection
from manifestoo.commands.list_depends import list_depends_command
from manifestoo import echo
from manifestoo.echo import verbosity  # Ensure verbosity is set
from manifestoo.exceptions import CycleErrorExit
from manifestoo.utils import ensure_odoo_series, print_list

try:
    # Use importlib.metadata (Python 3.8+) to get the version
    from importlib import metadata
except ImportError:
    # Fallback for Python < 3.8
    import importlib_metadata as metadata  # type: ignore

try:
    import pyperclip
except ImportError:
    pyperclip = None  # We'll check this later if --clipboard is used


try:
    __version__ = metadata.version("akaidoo")
except metadata.PackageNotFoundError:
    # Package is not installed (e.g., running from source)
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
    """
    Checks if an __init__.py file contains only comments, blank lines,
    or import statements.
    """
    try:
        with file_path.open("r", encoding="utf-8") as f:
            for line in f:
                stripped_line = line.strip()
                if not stripped_line:  # Skip blank lines
                    continue
                if stripped_line.startswith("#"):  # Skip comments
                    continue
                if stripped_line.startswith("import ") or stripped_line.startswith(
                    "from "
                ):  # Allow import statements
                    continue
                # If we find any other kind of line, it's not trivial
                return False
        # If we went through all lines and found only trivial content
        return True
    except Exception:
        # In case of reading errors, assume it's not trivial to be safe
        return False


app = typer.Typer(
    help="List files from Odoo addon dependencies using manifestoo.",
    context_settings={"help_option_names": ["-h", "--help"]},
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
        typer.echo.info(f"akaidoo version: {__version__}")
        typer.echo.info(f"manifestoo version: {m_version}")
        typer.echo.info(f"manifestoo-core version: {mc_version}")

        raise typer.Exit()


@app.callback()
def common(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
    verbose: int = typer.Option(
        0,
        "--verbose",
        "-V",
        count=True,
        help="Increase verbosity (can be used multiple times).",
        show_default=False,  # Changed -v to -V to avoid clash if -c is ever needed at top level
    ),
    quiet: int = typer.Option(
        0,
        "--quiet",
        "-q",
        count=True,
        help="Decrease verbosity (can be used multiple times).",
        show_default=False,
    ),
):
    """
    Common callback for setting verbosity.
    """
    # We mimic manifestoo's verbosity handling
    # manifestoo's echo.py has a global verbosity level.
    # We adjust it here.
    current_verbosity = verbosity
    # verbosity.set(current_verbosity + verbose - quiet)
    # ctx.obj = {} # Not needed for now


@app.command()
def list_files(
    addon_name: str = typer.Argument(
        ...,
        help="The name of the target Odoo addon.",
    ),
    addons_path_str: Optional[str] = typer.Option(
        None,
        "--addons-path",
        help="Comma-separated list of directories to add to the addons path.",
        show_default=False,
    ),
    addons_path_from_import_odoo: bool = typer.Option(
        True,
        help=(
            "Expand addons path by trying to `import odoo` and "
            "looking at `odoo.addons.__path__`. Useful when "
            "addons are installed via pip."
        ),
        show_default=True,
    ),
    addons_path_python: str = typer.Option(
        sys.executable,  # Use current python by default
        "--addons-path-python",
        show_default=True,
        metavar="PYTHON",
        help=(
            "The python executable to use when importing `odoo.addons.__path__`. "
            "Defaults to the current Python interpreter."
        ),
    ),
    odoo_cfg: Optional[
        Path
    ] = typer.Option(  # Renamed variable for clarity, was addons_path_from_odoo_cfg
        None,
        "-c",  # <<< Added this short option
        "--odoo-cfg",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,  # Good practice for file paths
        envvar="ODOO_RC",
        help=(
            "Expand addons path by looking into the provided Odoo configuration file. "
            "Uses ODOO_RC env var if set."
        ),
        show_default=False,
    ),
    odoo_series: Optional[OdooSeries] = typer.Option(
        None,
        envvar=["ODOO_VERSION", "ODOO_SERIES"],
        help="Odoo series to use, in case it is not autodetected from addons.",
        show_default=False,
    ),
    include_models: bool = typer.Option(
        True, "--include-models/--no-include-models", help="Include Python model files."
    ),
    include_views: bool = typer.Option(
        True, "--include-views/--no-include-views", help="Include XML view files."
    ),
    include_wizards: bool = typer.Option(
        True,
        "--include-wizards/--no-include-wizards",
        help="Include XML wizard files.",
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
        "--exclude_framework/--no-exclude-framework",
        help=f"Exclude {FRAMEWORK_ADDONS} from Odoo base addon",
    ),
    separator: str = typer.Option(
        "\n",
        "--separator",
        "-s",
        help="Separator character to use between filenames.",
    ),
    output_file: Optional[Path] = typer.Option(
        None,
        "--output-file",
        "-o",
        help="File path to write the output to. If provided, content will be written here instead of stdout or clipboard.",
        writable=True,
        file_okay=True,
        dir_okay=False,
    ),
    clipboard: bool = typer.Option(
        False,
        "--clipboard",
        "-x",  # Short for eXtract to clipboard or copy (c is taken by odoo-cfg)
        help="Copy the content of all found files to the clipboard, each prefixed with its path.",
        show_default=True,
    ),
    edit_in_editor: bool = typer.Option(
        False,
        "--edit",
        "-e",
        help="Open the found files in an editor.",
        show_default=False,  # Typically not default
    ),
    editor_command_str: Optional[str] = typer.Option(
        None,
        "--editor-cmd",
        help=(
            "Specify the editor command (e.g., 'code -r' or 'vim'). "
            "If not provided when --edit is used, it defaults to $VISUAL, then $EDITOR, "
            "then 'nvim' as a fallback. "
            "This option is only used if --edit is active."
        ),
    ),
    only_target_addon: bool = typer.Option(
        False,
        "--only-target-addon",
        "-s",
        help="Only list files from the addon directly passed as argument (ignore dependencies for file listing).",
        show_default=False,
    ),
) -> None:
    """
    Lists all relevant source files (.py, .xml) for an ADDON_NAME
    and its direct and transitive dependencies found in the addons path.
    """
    # 1. Prepare manifestoo options
    # Note: The verbosity set in the `common` callback will be used by manifestoo's echo
    echo.debug(f"Initial verbosity: {verbosity}")

    m_addons_path = ManifestooAddonsPath()  # Renamed to avoid conflict
    if addons_path_str:
        m_addons_path.extend_from_addons_path(addons_path_str)
    if addons_path_from_import_odoo:
        m_addons_path.extend_from_import_odoo(addons_path_python)
    if odoo_cfg:  # Use the renamed variable
        m_addons_path.extend_from_odoo_cfg(odoo_cfg)

    if not m_addons_path:
        echo.error(
            "Could not determine addons path. "
            "Please provide one via --addons-path, -c/--odoo-cfg, "
            "or ensure 'odoo' is importable."
        )
        raise typer.Exit(1)

    echo.info(str(m_addons_path), bold_intro="Using Addons path: ")

    addons_set = AddonsSet()
    addons_set.add_from_addons_dirs(m_addons_path)
    if not addons_set:
        echo.error(
            "No addons found in the specified addons path(s). Please check your paths."
        )
        raise typer.Exit(1)
    echo.info(str(addons_set), bold_intro="Found Addons set: ")

    # Resolve Odoo series
    final_odoo_series = odoo_series  # Use a different variable name
    if not final_odoo_series:
        detected_odoo_series = detect_from_addons_set(addons_set)
        if len(detected_odoo_series) == 1:
            final_odoo_series = detected_odoo_series.pop()
            echo.info(f"{final_odoo_series}", bold_intro="Auto-detected Odoo series: ")
        elif len(detected_odoo_series) > 1:
            echo.warning(
                f"Multiple Odoo series detected: {', '.join(s.value for s in detected_odoo_series)}. "
                "Please specify one using --odoo-series."
            )
            # We might still proceed if core addon handling isn't needed
        else:
            echo.warning(
                "Could not detect Odoo series. Core addon filtering might not work if enabled."
            )

    # Ensure odoo_series is set if exclude_core is True
    if exclude_core and not final_odoo_series:
        ensure_odoo_series(
            final_odoo_series
        )  # This will exit if final_odoo_series is None

    # 2. Use manifestoo to find dependencies
    selection = AddonsSelection({addon_name})
    if addon_name not in addons_set:
        echo.error(
            f"Addon '{addon_name}' not found in the addons path. "
            f"Available addons: {', '.join(sorted(addons_set)) or 'None'}"
        )
        raise typer.Exit(1)

    sorter = AddonSorterTopological()

    try:
        # Ensure verbosity is passed or used globally by manifestoo
        # list_depends_command uses manifestoo.echo internally
        dependent_addons, missing = list_depends_command(
            addons_selection=selection,
            addons_set=addons_set,
            transitive=True,
            include_selected=True,  # Important: include the base addon itself
            addon_sorter=sorter,
            # odoo_series_str=(final_odoo_series.value if final_odoo_series else None), # Pass series if known
        )
    except CycleErrorExit:
        # Error already printed by manifestoo
        raise typer.Exit(1)

    if missing:
        echo.warning(f"Missing dependencies found: {', '.join(sorted(missing))}")
        # Consider if this should be a hard error based on a new flag perhaps

    dependent_addons_list = list(dependent_addons)
    echo.info(
        f"{len(dependent_addons_list)} addons in dependency tree (incl. {addon_name}).",
        bold=True,
    )
    if verbosity >= 2:  # manifestoo verbosity levels: 0=normal, 1=verbose, 2=debug
        echo.info("Dependency list:", nl=False)  # Use echo.info for consistency
        print_list(dependent_addons_list, ", ")

    # 3. Determine the final list of addons to scan based on filters
    intermediate_target_addons: List[str] = []

    core_addons_set: Set[str] = set()
    if exclude_core:
        assert final_odoo_series is not None  # Ensured earlier
        core_addons_set = get_core_addons(final_odoo_series)
        echo.info(
            f"Excluding {len(core_addons_set)} core addons for {final_odoo_series}."
        )

    for dep_name in dependent_addons_list:
        if exclude_core and dep_name in core_addons_set:
            if verbosity >= 1:
                echo.info(f"Excluding core addon: {dep_name}")
            continue
        #        target_addons.append(dep_name)

        #    echo.info(f"Processing {len(target_addons)} addons after filtering.", bold=True)

        # TODO: A similar block for exclude_framework could be added here if
        # it's determined by addon name rather than file path.
        intermediate_target_addons.append(dep_name)

    target_addons: List[str]
    if only_target_addon:
        if addon_name in intermediate_target_addons:
            target_addons = [addon_name]
            echo.info(f"Focusing only on the target addon: {addon_name}", bold=True)
        else:
            # This implies addon_name itself was filtered out by a previous step (e.g., --exclude-core)
            target_addons = []
            echo.warning(
                f"Target addon '{addon_name}' was excluded by other filters (e.g., --exclude-core). "
                "No files will be processed from it."
            )
    else:
        target_addons = intermediate_target_addons

    echo.info(
        f"Will scan files from {len(target_addons)} addons after all filters.",
        bold=True,
    )

    # 4. Find files within the target addons' paths
    found_files: List[Path] = []
    processed_addons_count = 0
    for addon_to_scan in target_addons:
        addon = addons_set.get(addon_to_scan)
        if not addon:
            echo.warning(
                f"Addon '{addon_to_scan}' metadata not found, skipping file scan."
            )
            continue

        addon_dir = addon.path.resolve()  # Resolve to absolute path
        processed_addons_count += 1
        echo.debug(f"Scanning {addon_dir} for {addon_to_scan}...")

        # Determine which directories to scan based on flags
        scan_roots: List[str] = []
        if only_models:
            scan_roots.append("models")
        elif only_views:
            scan_roots.append("views")
        else:
            # Default: scan based on include flags
            if include_models:
                scan_roots.append("models")
            if include_views:
                scan_roots.append("views")
            if include_wizards:
                scan_roots.extend(["wizard", "wizards"])
            # Also scan root for __init__.py, etc. if models are included or no specific parts are targetted
            if not scan_roots or include_models:
                scan_roots.append(".")  # Representing the root

        # Determine file extensions to look for
        extensions: List[str] = []
        if include_models or only_models:
            if ".py" not in extensions:
                extensions.append(".py")
        if include_views or only_views or include_wizards:
            if ".xml" not in extensions:
                extensions.append(".xml")

        # If no specific types are included/only, default to common files
        if (
            not extensions
        ):  # e.g. --no-include-models --no-include-views --no-include-wizards
            echo.debug(
                f"No specific file types selected for {addon_to_scan}, skipping file globbing."
            )
            continue

        # Glob for files
        for root_name in set(scan_roots):  # Use set to avoid duplicate scanning
            scan_path = addon_dir / root_name if root_name != "." else addon_dir
            if not scan_path.is_dir():
                echo.debug(f"  Directory {scan_path} does not exist, skipping.")
                continue

            for ext in extensions:
                # Refined glob patterns
                files_to_check: List[Path] = []
                if root_name == ".":  # Root of the addon
                    if ext == ".py":  # __init__.py, main.py etc.
                        files_to_check.extend(scan_path.glob("*.py"))
                    # Generally, XML files are not expected at the root for models/views/wizards
                elif root_name == "models":
                    if ext == ".py":
                        files_to_check.extend(scan_path.glob("**/*.py"))
                elif root_name == "views":
                    if ext == ".xml":
                        files_to_check.extend(scan_path.glob("**/*.xml"))
                elif root_name in ("wizard", "wizards"):
                    if ext == ".xml":
                        files_to_check.extend(scan_path.glob("**/*.xml"))
                else:  # Should not happen with current logic, but for safety
                    files_to_check.extend(scan_path.glob(f"**/*{ext}"))

                echo.debug(
                    f"  Globbing in {scan_path} for *{ext} (specific patterns for subdir type)"
                )
                for found_file in files_to_check:
                    if not found_file.is_file():
                        continue

                    # Heuristics for filtering based on path and extension
                    # This is mainly for when specific --only-X flags are NOT used.
                    # If --only-X is used, we are more strict.
                    relative_path_parts = found_file.relative_to(addon_dir).parts

                    is_framework_file = any(
                        f"/addons/{name}/" in str(scan_path)
                        for name in FRAMEWORK_ADDONS
                    )

                    is_model_file = "models" in relative_path_parts and ext == ".py"
                    is_view_file = "views" in relative_path_parts and ext == ".xml"
                    is_wizard_file = (
                        "wizard" in relative_path_parts
                        or "wizards" in relative_path_parts
                    ) and ext == ".xml"
                    # Python files in root (e.g. __init__.py) are often relevant with models
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
                        continue

                    # If not using 'only' flags, apply 'include' flags
                    if not (only_models or only_views):
                        file_type_matches_include = False
                        if include_models and (is_model_file or is_root_py_file):
                            file_type_matches_include = True
                        if include_views and is_view_file:
                            file_type_matches_include = True
                        if include_wizards and is_wizard_file:
                            file_type_matches_include = True

                        # If we scanned root '.', and this is not a root py file,
                        # and it's not a model/view/wizard of an included type, skip it.
                        # This prevents picking up random XML/PY files from other subdirs if '.' was scanned.
                        if (
                            root_name == "."
                            and not is_root_py_file
                            and not is_model_file
                            and not is_view_file
                            and not is_wizard_file
                        ):
                            if (
                                not file_type_matches_include
                            ):  # if it's some other file type not explicitly included
                                continue
                        elif not file_type_matches_include:
                            continue

                    if found_file.name == "__init__.py":
                        # This check is relevant if models are included (as __init__.py are Python files)
                        # or if no specific 'only_' flags are set and include_models is true.
                        if (
                            is_model_file or is_root_py_file
                        ):  # ensure it would have been included based on type
                            if is_trivial_init_py(found_file):
                                echo.debug(
                                    f"  Skipping trivial __init__.py: {found_file}"
                                )
                                continue  # Skip this file

                    # Avoid adding duplicates if scanning "." and specific dirs might overlap
                    # (though refined globbing should reduce this)
                    abs_file_path = found_file.resolve()
                    if abs_file_path not in found_files:
                        found_files.append(abs_file_path)

    echo.info(
        f"Found {len(found_files)} files in {processed_addons_count} scanned addons.",
        bold=True,
    )

    # 5. Output the results (print or copy to clipboard)
    if not found_files:
        echo.info("No files matched the criteria.")
        raise typer.Exit()

    sorted_file_paths = sorted(found_files)  # Already resolved Path objects

    # Mutual exclusivity checks for output/action options
    output_actions_count = sum([edit_in_editor, bool(output_file), clipboard])
    if output_actions_count > 1:
        actions = []
        if edit_in_editor:
            actions.append("--edit")
        if output_file:
            actions.append("--output-file")
        if clipboard:
            actions.append("--clipboard")
        echo.error(
            f"Please choose only one primary output action from: {', '.join(actions)}."
        )
        raise typer.Exit(1)

    if edit_in_editor:
        if not sorted_file_paths:
            echo.info("No files found to open in editor.")
            raise typer.Exit()

        cmd_to_use = editor_command_str
        if (
            not cmd_to_use
        ):  # If --editor-cmd was not provided, try environment variables
            cmd_to_use = os.environ.get("VISUAL")
        if not cmd_to_use:
            cmd_to_use = os.environ.get("EDITOR")
        if not cmd_to_use:
            cmd_to_use = "nvim"  # Sensible default

        try:
            editor_parts = shlex.split(cmd_to_use)
        except ValueError as e:
            echo.error(f"Error parsing editor command '{cmd_to_use}': {e}")
            raise typer.Exit(1)

        if not editor_parts:
            echo.error(
                f"Editor command '{cmd_to_use}' is invalid or empty after parsing."
            )
            raise typer.Exit(1)

        files_to_open_str = [str(p) for p in sorted_file_paths]
        full_command = editor_parts + files_to_open_str

        # Use shlex.quote for printing to handle spaces/special chars in command parts correctly
        printable_command = " ".join(shlex.quote(str(s)) for s in full_command)
        echo.info(f"Executing: {printable_command}")
        try:
            process = subprocess.run(full_command, check=False)  # Let editor take over
            if process.returncode != 0:
                echo.warning(f"Editor command exited with status {process.returncode}.")
        except FileNotFoundError:
            echo.error(f"Editor command not found: {shlex.quote(editor_parts[0])}")
            echo.info(
                "Please ensure it's in your PATH or provide the full path via --editor-cmd."
            )
            raise typer.Exit(1)
        except Exception as e:
            echo.error(f"Failed to execute editor command: {e}")
            raise typer.Exit(1)
        raise typer.Exit()  # Successfully launched editor, so exit.
    elif clipboard and output_file:
        echo.error("Cannot use --output-file (-o) and --clipboard (-x) simultaneously.")
        echo.info("Please choose one output method.")
        raise typer.Exit(1)

    if clipboard:
        if pyperclip is None:
            echo.error(
                "The --clipboard (-x) option requires the 'pyperclip' library. "
                "Please install it (e.g., 'pip install pyperclip') and try again."
            )
            echo.info("Printing file paths to console instead as a fallback:")
            print_list([str(p) for p in sorted_file_paths], separator)
            raise typer.Exit(1)

        all_content_for_clipboard = []
        total_size = 0
        for file_path in sorted_file_paths:
            try:
                header = f"# FILEPATH: {file_path}\n"
                content = file_path.read_text(encoding="utf-8")
                all_content_for_clipboard.append(header + content)
                total_size += len(header) + len(content)
            except Exception as e:
                echo.warning(f"Could not read file {file_path}: {e}")

        clipboard_text = "\n\n".join(all_content_for_clipboard)
        pyperclip.copy(clipboard_text)
        echo.info(
            f"Content of {len(sorted_file_paths)} files ({total_size / 1024:.2f} KB) copied to clipboard!"
        )

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
                        f.write(header)
                        f.write(content)
                        f.write("\n\n")  # Separator between files
                        total_size += len(header) + len(content) + 2
                        if len(sorted_file_paths) > 50 and (i + 1) % 25 == 0:
                            echo.info(
                                f"  Written {i+1}/{len(sorted_file_paths)} files ({total_size / 1024:.2f} KB)..."
                            )
                    except Exception as e:
                        echo.warning(f"Could not read or write file {file_path}: {e}")
            echo.info(f"Successfully wrote {total_size / 1024:.2f} KB to {output_file}")
        except Exception as e:
            echo.error(f"Error writing to output file {output_file}: {e}")
            raise typer.Exit(1)

    else:
        print_list([str(p) for p in sorted_file_paths], separator)


# Optional: Add a default command or alias if desired
# app.command("list")(list_files) # Make 'list' the default if no subcommand given


if __name__ == "__main__":
    app()
