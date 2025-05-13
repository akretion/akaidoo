import sys
from pathlib import Path
from typing import List, Optional, Set

import typer
from manifestoo_core.addons_set import AddonsSet
from manifestoo_core.core_addons import get_core_addons, is_core_addon
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
    # Use importlib.metadata (Python 3.8+) to get the version
    from importlib import metadata
except ImportError:
    # Fallback for Python < 3.8
    import importlib_metadata as metadata # type: ignore

try:
    __version__ = metadata.version("akaidoo")
except metadata.PackageNotFoundError:
     # Package is not installed (e.g., running from source)
    __version__ = "0.0.0-dev"


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
        0, "--verbose", "-v", count=True, help="Increase verbosity.", show_default=False
    ),
    quiet: int = typer.Option(
        0, "--quiet", "-q", count=True, help="Decrease verbosity.", show_default=False
    ),
):
    """
    Common callback for setting verbosity.
    """
    # We mimic manifestoo's verbosity handling
    # verbosity.set(verbosity.get() + verbose - quiet)
    # Store common state if needed later, though manifestoo options are handled per-command
    # ctx.obj = {}


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
        "python",
        "--addons-path-python",
        show_default=False,
        metavar="PYTHON",
        help=(
            "The python executable to use when importing `odoo.addons.__path__`. "
            "Defaults to the `python` executable found in PATH."
        ),
    ),
    addons_path_from_odoo_cfg: Optional[Path] = typer.Option(
        None,
        "--odoo-cfg",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
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
    only_wizards: bool = typer.Option(
        False,
        "--only-wizards",
        help="Only list files under 'wizard/' or 'wizards/' directories.",
        show_default=False,
    ),
    exclude_core: bool = typer.Option(
        False,
        "--exclude-core/--no-exclude-core",
        help="Exclude files from Odoo core addons.",
    ),
    separator: str = typer.Option(
        "\n",
        "--separator",
        "-s",
        help="Separator character to use between filenames.",
    ),
) -> None:
    """
    Lists all relevant source files (.py, .xml) for an ADDON_NAME
    and its direct and transitive dependencies found in the addons path.
    """
    # 1. Prepare manifestoo options
    addons_path = ManifestooAddonsPath()
    if addons_path_str:
        addons_path.extend_from_addons_path(addons_path_str)
    if addons_path_from_import_odoo:
        addons_path.extend_from_import_odoo(addons_path_python)
    if addons_path_from_odoo_cfg:
        addons_path.extend_from_odoo_cfg(addons_path_from_odoo_cfg)

    if not addons_path:
        echo.error(
            "Could not determine addons path. "
            "Please provide one via --addons-path or --odoo-cfg, "
            "or ensure 'odoo' is importable."
        )
        raise typer.Exit(1)

    echo.info(str(addons_path), bold_intro="Using Addons path: ")

    addons_set = AddonsSet()
    addons_set.add_from_addons_dirs(addons_path)
    echo.info(str(addons_set), bold_intro="Found Addons set: ")

    # Resolve Odoo series
    if not odoo_series:
        detected_odoo_series = detect_from_addons_set(addons_set)
        if len(detected_odoo_series) == 1:
            odoo_series = detected_odoo_series.pop()
            echo.info(f"{odoo_series}", bold_intro="Auto-detected Odoo series: ")
        elif len(detected_odoo_series) > 1:
            echo.warning(
                f"Multiple Odoo series detected: {', '.join(s.value for s in detected_odoo_series)}. "
                "Please specify one using --odoo-series."
            )
            # We might still proceed if core addon handling isn't needed
        else:
             echo.warning(
                "Could not detect Odoo series. Core addon filtering might not work."
             )

    if exclude_core or odoo_series: # Need series for core addon check
        ensure_odoo_series(odoo_series) # Aborts if still None

    # 2. Use manifestoo to find dependencies
    selection = AddonsSelection({addon_name})
    sorter = AddonSorterTopological()

    try:
        dependent_addons, missing = list_depends_command(
            addons_selection=selection,
            addons_set=addons_set,
            transitive=True,
            include_selected=True, # Important: include the base addon itself
            addon_sorter=sorter,
        )
    except CycleErrorExit:
        # Error already printed by manifestoo
        raise typer.Exit(1)

    if missing:
        echo.warning(f"Missing dependencies found: {', '.join(sorted(missing))}")
        # Decide if this should be a hard error or just a warning
        # raise typer.Exit(1)

    dependent_addons_list = list(dependent_addons)
    echo.info(
        f"{len(dependent_addons_list)} addons in dependency tree (incl. {addon_name}).",
        bold=True
    )
    if verbosity.get() > 1: # Debug level
        print_list(dependent_addons_list, ", ")

    # 3. Filter core addons if requested
    target_addons: List[str] = []
    core_addons_set: Set[str] = set()
    if exclude_core:
        assert odoo_series is not None # Ensured earlier
        core_addons_set = get_core_addons(odoo_series)
        echo.info(f"Excluding {len(core_addons_set)} core addons for {odoo_series}.")

    for dep_name in dependent_addons_list:
        if exclude_core and dep_name in core_addons_set:
            continue
        target_addons.append(dep_name)

    echo.info(
        f"Processing {len(target_addons)} addons after filtering.", bold=True
    )

    # 4. Find files within the target addons' paths
    found_files: List[Path] = []
    processed_addons_count = 0
    for addon_to_scan in target_addons:
        addon = addons_set.get(addon_to_scan)
        if not addon:
            echo.warning(f"Addon '{addon_to_scan}' metadata not found, skipping file scan.")
            continue

        addon_dir = addon.path
        processed_addons_count += 1
        echo.debug(f"Scanning {addon_dir} for {addon_to_scan}...")

        # Determine which directories to scan based on flags
        scan_roots: List[str] = []
        if only_models:
            scan_roots.append("models")
        elif only_views:
            scan_roots.append("views")
        elif only_wizards:
            scan_roots.extend(["wizard", "wizards"]) # Common variations
        else:
            # Default: scan based on include flags
            if include_models:
                scan_roots.append("models")
            if include_views:
                scan_roots.append("views")
            if include_wizards:
                 scan_roots.extend(["wizard", "wizards"])
            # Also scan root for __init__.py etc. if no specific dir is targetted
            if not scan_roots or include_models: # Always include root if models needed
                 scan_roots.append(".") # Representing the root

        # Determine file extensions to look for
        extensions: List[str] = []
        if include_models or only_models:
            extensions.append(".py")
        if include_views or only_views or include_wizards or only_wizards:
            extensions.append(".xml")

        # Glob for files
        for root_name in set(scan_roots): # Use set to avoid duplicate scanning
             scan_path = addon_dir / root_name if root_name != "." else addon_dir
             if not scan_path.is_dir():
                 continue
             for ext in extensions:
                pattern = f"**/*{ext}" if root_name != "." else f"*{ext}" # Root only needs *
                if root_name == "models" and ext == ".py":
                    pattern = "**/*.py" # Include subdirectories like 'res'
                elif root_name in ("views", "wizard", "wizards") and ext == ".xml":
                    pattern = "**/*.xml"

                echo.debug(f"  Globbing in {scan_path} with pattern '{pattern}'")
                for found_file in scan_path.glob(pattern):
                    if found_file.is_file():
                        # Extra check: Ensure XMLs in 'views' are likely views
                        # and those in 'wizard' are likely wizards if filtering
                        # This is heuristic, __manifest__.py is the truth source
                        relative_path_parts = found_file.relative_to(addon_dir).parts
                        is_likely_model = "models" in relative_path_parts and ext == ".py"
                        is_likely_view = "views" in relative_path_parts and ext == ".xml"
                        is_likely_wizard = ("wizard" in relative_path_parts or "wizards" in relative_path_parts) and ext == ".xml"
                        is_root_py = len(relative_path_parts) == 1 and ext == ".py"

                        if only_models and not is_likely_model: continue
                        if only_views and not is_likely_view: continue
                        if only_wizards and not is_likely_wizard: continue

                        if not only_models and not only_views and not only_wizards:
                            # Apply include flags if not using 'only' flags
                            if not include_models and (is_likely_model or is_root_py): continue
                            if not include_views and is_likely_view: continue
                            if not include_wizards and is_likely_wizard: continue

                        # Avoid adding duplicates if scanning "." and specific dirs
                        if found_file not in found_files:
                             found_files.append(found_file)


    echo.info(
        f"Found {len(found_files)} files in {processed_addons_count} addons.", bold=True
    )

    # 5. Print the results
    print_list([str(f.resolve()) for f in sorted(found_files)], separator)


# Optional: Add a default command or alias if desired
# app.command("list")(list_files) # Make 'list' the default if no subcommand given


if __name__ == "__main__":
    app()
