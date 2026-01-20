"""
Akaidoo Context Module

Contains the AkaidooContext dataclass and all context resolution logic.
This module is the core of akaidoo's business logic, independent of CLI specifics.
"""

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

import typer
from manifestoo import echo
import manifestoo.echo as manifestoo_echo_module
from manifestoo.addon_sorter import AddonSorterTopological
from manifestoo.addons_path import AddonsPath as ManifestooAddonsPath
from manifestoo.addons_selection import AddonsSelection
from manifestoo.commands.list_depends import list_depends_command
from manifestoo.exceptions import CycleErrorExit
from manifestoo.utils import print_list, comma_split
from manifestoo_core.addons_set import AddonsSet
from manifestoo_core.odoo_series import OdooSeries, detect_from_addons_set

from .config import (
    AUTO_EXPAND_THRESHOLD,
    BLACKLIST_AUTO_EXPAND,
    BLACKLIST_RELATION_EXPAND,
    BUDGET_ESCALATION_LEVELS,
    FRAMEWORK_ADDONS,
    PARENT_CHILD_AUTO_EXPAND,
    TOKEN_FACTOR,
)
from .scanner import (
    is_trivial_init_py,
    scan_addon_files,
    scan_directory_files,
)
from .shrinker import shrink_manifest
from .utils import get_model_relations, get_odoo_model_stats


@dataclass
class AkaidooContext:
    """Container for all context information gathered by akaidoo."""

    found_files_list: List[Path]
    shrunken_files_content: Dict[Path, str]
    shrunken_files_info: Dict[Path, Dict]
    addon_files_map: Dict[str, List[Path]]
    pruned_addons: Dict[str, str]
    addons_set: AddonsSet
    final_odoo_series: Optional[OdooSeries]
    selected_addon_names: Set[str]
    excluded_addons: Set[str]
    expand_models_set: Set[str]
    diffs: List[Dict]
    enriched_additions: Set[str] = field(default_factory=set)
    new_related: Set[str] = field(default_factory=set)
    # Budget enforcement tracking
    effective_shrink_mode: str = "soft"
    budget_escalation_level: int = 0
    context_size_chars: int = 0


def scan_extra_scripts(
    addon_name: str,
    openupgrade_path: Optional[Path],
    module_diff_path: Optional[Path],
) -> List[Path]:
    """Scan for OpenUpgrade and module diff scripts for an addon."""
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
                f"Scanning module diff scripts in {addon_diff_path} for {addon_name}..."
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
    if len(raw_inputs) == 1:
        path_str = raw_inputs[0]
        potential_path = Path(path_str)
        is_dir = potential_path.is_dir()
        ends_with_sep = path_str.endswith(os.path.sep)
        has_manifest = (potential_path / "__manifest__.py").is_file()

        if is_dir and (ends_with_sep or not has_manifest):
            if ends_with_sep:
                return set(), set(), True, potential_path

            # Check if container
            has_sub_addons = any(
                (sub / "__manifest__.py").is_file()
                for sub in potential_path.iterdir()
                if sub.is_dir()
            )
            if not has_sub_addons:
                return set(), set(), True, potential_path

    # Project/Addon Mode (Mode 2)
    for item in raw_inputs:
        path = Path(item)
        if path.is_dir():
            if (path / "__manifest__.py").is_file():
                name = path.name
                selected_addon_names.add(name)
                implicit_addons_paths.add(path.parent.resolve())
            else:
                found_any = False
                for sub in path.iterdir():
                    if sub.is_dir() and (sub / "__manifest__.py").is_file():
                        selected_addon_names.add(sub.name)
                        found_any = True

                if found_any:
                    implicit_addons_paths.add(path.resolve())
                else:
                    if not found_any:
                        selected_addon_names.add(item)
        else:
            selected_addon_names.add(item)

    return selected_addon_names, implicit_addons_paths, False, None


def resolve_addons_selection(
    selected_addon_names: Set[str],
    addons_set: AddonsSet,
    excluded_addons: Set[str],
) -> List[str]:
    """Resolve addon dependencies and return the filtered list."""
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

    intermediate_target_addons = []
    for dep_name in dependent_addons_list:
        if dep_name not in excluded_addons:
            intermediate_target_addons.append(dep_name)
        elif manifestoo_echo_module.verbosity >= 1:
            echo.info(f"Excluding addon: {dep_name}")
    return intermediate_target_addons


def resolve_addons_path(
    addons_path_str: Optional[str],
    addons_path_from_import_odoo: bool,
    addons_path_python: str,
    odoo_cfg: Optional[Path],
) -> ManifestooAddonsPath:
    """Build the ManifestooAddonsPath from various sources."""
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


# --- Helper Functions for resolve_akaidoo_context ---


def _parse_includes(include_str: Optional[str]) -> Set[str]:
    """
    Parse the include string and return the set of content types to include.

    Returns a set containing combinations of: model, view, wizard, data,
    report, controller, security, static, test.
    """
    includes: Set[str] = {"model"}  # Always include models
    if include_str:
        raw_includes = {i.strip() for i in include_str.split(",")}
        if "all" in raw_includes:
            includes.update(
                {
                    "view",
                    "wizard",
                    "data",
                    "report",
                    "controller",
                    "security",
                    "static",
                    "test",
                }
            )
        else:
            includes.update(raw_includes)
    return includes


def _build_excluded_addons(
    exclude_addons_str: Optional[str],
    no_exclude_addons_str: Optional[str],
) -> Set[str]:
    """
    Build the set of addons to exclude.

    Starts with FRAMEWORK_ADDONS, adds user exclusions,
    then removes any explicitly un-excluded addons.
    """
    excluded = set(FRAMEWORK_ADDONS)
    if exclude_addons_str:
        excluded.update({a.strip() for a in exclude_addons_str.split(",")})
    if no_exclude_addons_str:
        excluded.difference_update(
            {a.strip() for a in no_exclude_addons_str.split(",")}
        )
    return excluded


def _parse_expansion_options(
    expand_models_str: Optional[str],
    add_expand_str: Optional[str],
    rm_expand_str: Optional[str],
    prune_methods_str: Optional[str],
    auto_expand: bool,
) -> tuple[Set[str], Set[str], Set[str], Set[str], Set[str], bool]:
    """
    Parse and validate expansion-related CLI options.

    Returns:
        (expand_models_set, focus_models_set, add_expand_set,
         rm_expand_set, prune_methods_set, auto_expand)
    """
    expand_models_set: Set[str] = set()
    focus_models_set: Set[str] = set()
    add_expand_set: Set[str] = set()
    rm_expand_set: Set[str] = set()
    prune_methods_set: Set[str] = set()

    if rm_expand_str:
        rm_expand_set = {m.strip() for m in rm_expand_str.split(",")}
    if prune_methods_str:
        prune_methods_set = {m.strip() for m in prune_methods_str.split(",")}

    if expand_models_str:
        # Explicit mode: disables auto-expand
        focus_models_set = {m.strip() for m in expand_models_str.split(",")}
        auto_expand = False
        expand_models_set = focus_models_set.copy()

    if add_expand_str:
        # Additive mode: works with auto-expand (or adds to explicit list if both used, though weird)
        add_expand_set = {m.strip() for m in add_expand_str.split(",")}

    return (
        expand_models_set,
        focus_models_set,
        add_expand_set,
        rm_expand_set,
        prune_methods_set,
        auto_expand,
    )


def _harvest_auto_expand_models(
    target_names: Set[str],
    addons_set: AddonsSet,
    existing_expand_set: Set[str],
) -> Set[str]:
    """
    Scan target addons for models that should be auto-expanded.

    Models are selected based on their complexity score (fields, methods, etc.)
    exceeding AUTO_EXPAND_THRESHOLD.

    Returns a new set containing the harvested models.
    """
    expand_set = set(existing_expand_set)

    echo.debug(
        f"Auto-expand: Scanning {len(target_names)} target addon(s) for models "
        f"with score >= {AUTO_EXPAND_THRESHOLD}"
    )

    for addon_name in target_names:
        addon_meta = addons_set.get(addon_name)
        if not addon_meta:
            continue

        addon_dir = addon_meta.path.resolve()
        dirs_to_scan = [
            addon_dir / "models",
            addon_dir / "wizard",
            addon_dir / "wizards",
        ]

        for scan_dir in dirs_to_scan:
            if not scan_dir.exists() or not scan_dir.is_dir():
                continue

            echo.debug(
                f"Auto-expand: Harvesting from addon '{addon_name}' in {scan_dir}"
            )

            for py_file in scan_dir.rglob("*.py"):
                if not py_file.is_file() or "__pycache__" in py_file.parts:
                    continue
                try:
                    stats = get_odoo_model_stats(py_file.read_text(encoding="utf-8"))
                    if manifestoo_echo_module.verbosity >= 1:
                        echo.info(
                            f"Auto-expand: Scanning {py_file.relative_to(addon_dir)}"
                        )

                    for model_name, info in stats.items():
                        score = info.get("score", 0)
                        if score >= AUTO_EXPAND_THRESHOLD:
                            if model_name not in expand_set:
                                if model_name in BLACKLIST_AUTO_EXPAND:
                                    if manifestoo_echo_module.verbosity >= 1:
                                        echo.info(
                                            f"Skipping model '{model_name}' - blacklisted"
                                        )
                                    continue
                                if manifestoo_echo_module.verbosity >= 1:
                                    echo.info(
                                        f"Auto-expanding '{model_name}' "
                                        f"(score: {score}, fields: {info['fields']}, "
                                        f"methods: {info['methods']})"
                                    )
                                expand_set.add(model_name)
                        elif manifestoo_echo_module.verbosity >= 1:
                            echo.info(
                                f"Skipping '{model_name}' - score {score} below threshold"
                            )
                except Exception:
                    continue

    return expand_set


def _discover_model_relations(
    target_addon_names: List[str],
    addons_set: AddonsSet,
) -> tuple[Dict[str, Dict[str, Set[str]]], Dict[str, Set[str]], Set[str]]:
    """
    Discover all model relationships across target addons.

    Returns:
        (all_relations, addon_models, all_discovered_models)

        - all_relations: Dict mapping model name -> {"parents": set, "comodels": set}
        - addon_models: Dict mapping addon name -> set of model names
        - all_discovered_models: Set of all model names found
    """
    all_relations: Dict[str, Dict[str, Set[str]]] = {}
    addon_models: Dict[str, Set[str]] = {}
    all_discovered_models: Set[str] = set()

    discovery_scan_roots = ["models", ".", "wizard", "wizards"]

    for addon_name in target_addon_names:
        addon_meta = addons_set.get(addon_name)
        if not addon_meta:
            continue

        addon_dir = addon_meta.path.resolve()
        addon_models[addon_name] = set()

        for root_name in discovery_scan_roots:
            scan_path_dir = addon_dir / root_name if root_name != "." else addon_dir
            if not scan_path_dir.is_dir():
                continue

            for py_file in scan_path_dir.rglob("*.py"):
                if (
                    not py_file.is_file()
                    or "__pycache__" in py_file.parts
                    or is_trivial_init_py(py_file)
                ):
                    continue
                try:
                    content = py_file.read_text(encoding="utf-8")
                    rels = get_model_relations(content)
                    if rels:
                        addon_models[addon_name].update(rels.keys())
                        all_discovered_models.update(rels.keys())
                        for m, r_dict in rels.items():
                            if m not in all_relations:
                                all_relations[m] = {"parents": set(), "comodels": set()}
                            all_relations[m]["parents"].update(
                                r_dict.get("parents", set())
                            )
                            all_relations[m]["comodels"].update(
                                r_dict.get("comodels", set())
                            )
                except Exception:
                    continue

    return all_relations, addon_models, all_discovered_models


def _enrich_parent_child_models(
    expand_models_set: Set[str],
    all_discovered_models: Set[str],
) -> Set[str]:
    """
    Enrich expansion set with parent/child (.line) models.

    If a model ends with '.line', add its parent.
    Otherwise, add the '.line' child if it exists.

    Returns the set of enriched additions (not the full expand set).
    """
    if not PARENT_CHILD_AUTO_EXPAND or not expand_models_set:
        return set()

    potential_additions: Set[str] = set()

    for m in list(expand_models_set):
        if m.endswith(".line"):
            parent = m[:-5]
            if (
                parent
                and parent not in expand_models_set
                and parent not in BLACKLIST_AUTO_EXPAND
            ):
                potential_additions.add(parent)
        else:
            child = f"{m}.line"
            if child not in expand_models_set and child not in BLACKLIST_AUTO_EXPAND:
                potential_additions.add(child)

    # Only include models that actually exist
    enriched = {p for p in potential_additions if p in all_discovered_models}
    return enriched


def _expand_parents_recursively(
    seed_models: Set[str],
    all_relations: Dict[str, Dict[str, Set[str]]],
    blacklist: Set[str],
) -> Set[str]:
    """
    Recursively expand parent models.

    Starting from the seed models, walk up the inheritance tree
    and add all parent models to the result set.

    Returns a new set containing all expanded models (including seeds).
    """
    result = set(seed_models)
    queue = list(seed_models)
    seen = set(seed_models)

    while queue:
        m = queue.pop(0)
        if m in all_relations:
            parents = all_relations[m].get("parents", set())
            for parent in parents:
                if parent not in seen and parent not in blacklist:
                    seen.add(parent)
                    result.add(parent)
                    queue.append(parent)

    return result


def _resolve_related_models(
    expand_models_set: Set[str],
    all_relations: Dict[str, Dict[str, Set[str]]],
) -> tuple[Set[str], Set[str]]:
    """
    Resolve related models (comodels) from the expansion set.

    Returns:
        (related_models_set, new_related)

        - related_models_set: All comodels of expanded models
        - new_related: Subset that are not in expand_models_set
    """
    related_models_set: Set[str] = set()

    for m in expand_models_set:
        if m in all_relations:
            comodels = all_relations[m].get("comodels", set())
            filtered = {n for n in comodels if n not in BLACKLIST_RELATION_EXPAND}
            related_models_set.update(filtered)

    new_related = related_models_set - expand_models_set
    return related_models_set, new_related


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
    include: Optional[str] = None,
    exclude_addons_str: Optional[str] = None,
    no_exclude_addons_str: Optional[str] = None,
    shrink_mode: str = "none",
    expand_models_str: Optional[str] = None,
    add_expand_str: Optional[str] = None,
    rm_expand_str: Optional[str] = None,
    prune_methods_str: Optional[str] = None,
    skip_expanded: bool = False,
    context_budget: Optional[int] = None,
) -> AkaidooContext:
    """
    Main function to resolve the akaidoo context.

    This function orchestrates the entire process of:
    1. Parsing inputs and determining the mode
    2. Resolving addons and dependencies
    3. Discovering models and relationships
    4. Scanning and processing files
    5. Building the final context

    Returns an AkaidooContext containing all gathered information.
    """
    found_files_list: List[Path] = []
    addon_files_map: Dict[str, List[Path]] = {}
    shrunken_files_content: Dict[Path, str] = {}
    shrunken_files_info: Dict[Path, Dict] = {}
    diffs = []

    # Use helper functions to parse options
    includes = _parse_includes(include)
    excluded_addons = _build_excluded_addons(exclude_addons_str, no_exclude_addons_str)

    (
        expand_models_set,
        focus_models_set,
        add_expand_set,
        rm_expand_set,
        prune_methods_set,
        auto_expand,
    ) = _parse_expansion_options(
        expand_models_str,
        add_expand_str,
        rm_expand_str,
        prune_methods_str,
        True,
    )

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
            shrunken_files_info={},
            addon_files_map={},
            pruned_addons={},
            addons_set=AddonsSet(),
            final_odoo_series=None,
            selected_addon_names=set(),
            excluded_addons=set(),
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

    # Never exclude explicitly selected targets
    excluded_addons.difference_update(selected_addon_names)

    missing_addons = selected_addon_names - set(addons_set.keys())
    if missing_addons:
        echo.error(
            f"Addon(s) '{', '.join(missing_addons)}' not found in configured Odoo addons paths. "
            f"Available: {', '.join(sorted(addons_set)) or 'None'}"
        )
        raise typer.Exit(1)

    intermediate_target_addons = resolve_addons_selection(
        selected_addon_names, addons_set, excluded_addons
    )

    target_addon_names: List[str] = intermediate_target_addons
    echo.info(
        f"Will scan files from {len(target_addon_names)} Odoo addons after all filters.",
        bold=True,
    )

    # Initialize relevant_models as empty set for first pass
    relevant_models: Set[str] = set()

    # Auto-expand harvesting using helper function
    if auto_expand:
        expand_models_set = _harvest_auto_expand_models(
            selected_addon_names, addons_set, expand_models_set
        )
        if manifestoo_echo_module.verbosity >= 1:
            if expand_models_set:
                echo.info(
                    f"Auto-expanded {len(expand_models_set)} models: "
                    f"{', '.join(sorted(expand_models_set))}"
                )
            else:
                echo.info("Auto-expand: No models met the threshold criteria.")
    elif focus_models_set:
        if manifestoo_echo_module.verbosity >= 1:
            echo.info(
                f"Focus mode: Expanding {len(focus_models_set)} specified models: "
                f"{', '.join(sorted(focus_models_set))}"
            )

    if add_expand_set:
        expand_models_set.update(add_expand_set)
        if manifestoo_echo_module.verbosity >= 1:
            echo.info(
                f"Added {len(add_expand_set)} models to expand set: "
                f"{', '.join(sorted(add_expand_set))}"
            )

    # --- Pass 1: Discovery (Build Model Map and Relations) ---
    pruned_addons: Dict[str, str] = {}
    all_relations, addon_models, all_discovered_models = _discover_model_relations(
        target_addon_names, addons_set
    )

    # --- Late Enrichment: Validate Parent/Child existence ---
    enriched_additions = _enrich_parent_child_models(
        expand_models_set, all_discovered_models
    )
    if enriched_additions:
        expand_models_set.update(enriched_additions)

    # --- Pass 2: Relationship Resolution & Relevant Models ---
    # 1. Recursive Parent Expansion
    expand_models_set = _expand_parents_recursively(
        expand_models_set, all_relations, BLACKLIST_AUTO_EXPAND
    )

    # 2. Comodel (Relation) Resolution
    related_models_set, new_related = _resolve_related_models(
        expand_models_set, all_relations
    )

    # Apply user overrides
    if rm_expand_set:
        expand_models_set -= rm_expand_set
        related_models_set -= rm_expand_set
        new_related -= rm_expand_set
        if manifestoo_echo_module.verbosity >= 1:
            echo.info(
                f"Removed {len(rm_expand_set)} models from expand/related sets: "
                f"{', '.join(sorted(rm_expand_set))}"
            )

    relevant_models = expand_models_set | related_models_set

    # --- Pass 3: Action (Scanning, Shrinking and Filtering) ---
    processed_addons_count = 0
    for addon_to_scan_name in target_addon_names:
        addon_meta = addons_set.get(addon_to_scan_name)
        if addon_meta:
            addon_dir = addon_meta.path.resolve()

            # Pruning Decision - only check if addon is explicitly excluded
            reason = None
            if addon_to_scan_name in excluded_addons:
                reason = "excluded"

            if reason:
                pruned_addons[addon_to_scan_name] = reason
                if manifestoo_echo_module.verbosity >= 1:
                    echo.info(f"Pruning addon '{addon_to_scan_name}' ({reason})")

            # Content Gathering
            if addon_dir.parts[-1] not in FRAMEWORK_ADDONS:
                manifest_path = addon_dir / "__manifest__.py"
                found_files_list.append(manifest_path)

                # Shrink manifest for dependencies
                is_dependency = addon_to_scan_name not in selected_addon_names
                if is_dependency and shrink_mode != "none":
                    try:
                        content = manifest_path.read_text(encoding="utf-8")
                        shrunken = shrink_manifest(content)
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
                    # manifest_dict = ast.literal_eval(content)
                    # serie = manifest_dict.get("version").split(".")[0]
                    # Note: find_pr_commits_after_target remains in cli.py (git-specific)
                    # This is a known limitation - we pass diffs but don't populate it here

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
                echo.info(
                    f"Scanning {addon_dir} for Odoo addon {addon_to_scan_name}..."
                )

            # Files for the Tree
            scan_result = scan_addon_files(
                addon_dir=addon_dir,
                addon_name=addon_to_scan_name,
                selected_addon_names=selected_addon_names,
                includes=includes,
                excluded_addons=set(),
                shrink_mode=shrink_mode,
                expand_models_set=expand_models_set,
                relevant_models=relevant_models,
                prune_methods=prune_methods_set,
                skip_expanded=skip_expanded,
            )
            # Merge scan results into the main collections
            shrunken_files_content.update(scan_result.shrunken_content)
            shrunken_files_info.update(scan_result.shrunken_info)
            addon_files = scan_result.found_files
            addon_files_map[addon_to_scan_name] = addon_files

            # Files for the Dump
            if not reason:
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

    context = AkaidooContext(
        found_files_list=found_files_list,
        shrunken_files_content=shrunken_files_content,
        shrunken_files_info=shrunken_files_info,
        addon_files_map=addon_files_map,
        pruned_addons=pruned_addons,
        addons_set=addons_set,
        final_odoo_series=final_odoo_series,
        selected_addon_names=selected_addon_names,
        excluded_addons=excluded_addons,
        expand_models_set=expand_models_set,
        diffs=diffs,
        enriched_additions=enriched_additions,
        new_related=new_related,
        effective_shrink_mode=shrink_mode,
    )

    # Calculate and store context size
    # Only include expanded files size in agent mode (skip_expanded=True)
    # because in normal mode, expanded content is already in shrunken_files_content
    context.context_size_chars = calculate_context_size(context, skip_expanded)

    # Budget enforcement with escalation
    if context_budget is not None and context.context_size_chars > context_budget:
        # Find current escalation level
        current_level = 0
        try:
            current_level = BUDGET_ESCALATION_LEVELS.index(shrink_mode)
        except ValueError:
            # If current mode is not in levels (e.g. "none"), start from beginning if we need to escalate
            pass

        # Try escalating until we fit or run out of levels
        while (
            context.context_size_chars > context_budget
            and current_level < len(BUDGET_ESCALATION_LEVELS) - 1
        ):
            current_level += 1
            next_shrink = BUDGET_ESCALATION_LEVELS[current_level]

            budget_tokens = int(context_budget * TOKEN_FACTOR / 1000)
            current_tokens = int(context.context_size_chars * TOKEN_FACTOR / 1000)
            echo.info(
                f"Context size {current_tokens}k tokens exceeds budget {budget_tokens}k. "
                f"Escalating to shrink={next_shrink}..."
            )

            # Recursively rebuild with new modes (without budget to avoid infinite loop)
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
                include=include,
                exclude_addons_str=exclude_addons_str,
                no_exclude_addons_str=no_exclude_addons_str,
                shrink_mode=next_shrink,
                expand_models_str=expand_models_str,
                add_expand_str=add_expand_str,
                rm_expand_str=rm_expand_str,
                prune_methods_str=prune_methods_str,
                skip_expanded=skip_expanded,
                context_budget=None,  # Don't recurse with budget
            )
            context.context_size_chars = calculate_context_size(context, skip_expanded)
            context.budget_escalation_level = current_level
            context.effective_shrink_mode = next_shrink

        # Report final status
        final_tokens = int(context.context_size_chars * TOKEN_FACTOR / 1000)
        budget_tokens = int(context_budget * TOKEN_FACTOR / 1000)
        if context.context_size_chars <= context_budget:
            echo.info(
                f"Budget met: {final_tokens}k tokens <= {budget_tokens}k budget "
                f"(shrink={context.effective_shrink_mode})",
                bold=True,
            )
        else:
            echo.warning(
                f"Could not meet budget: {final_tokens}k tokens > {budget_tokens}k budget "
                f"even at maximum escalation (shrink={context.effective_shrink_mode})"
            )

    return context


def calculate_context_size(
    context: AkaidooContext, include_expanded_files: bool = True
) -> int:
    """
    Calculate the total size of the context to be generated.

    Args:
        context: The AkaidooContext to measure
        include_expanded_files: If True, also calculate the size of expanded model files
                               that the LLM will need to read separately (agent mode).
                               This gives a more accurate total context size.
    """
    total_size = 0

    # Size of files in found_files_list (the dump content)
    for fp in context.found_files_list:
        abs_path = fp.resolve()

        # Get content from shrunken_files_content if available
        content = context.shrunken_files_content.get(abs_path)

        # Check if this file has expanded content that was skipped
        info = context.shrunken_files_info.get(abs_path, {})
        has_expanded_locs = bool(info.get("expanded_locations"))

        if content is None:
            if has_expanded_locs and include_expanded_files:
                # In agent mode: file has only expanded models, content is empty
                # The expanded content will be counted by _calculate_expanded_files_size()
                # So we just add header overhead, not file content
                try:
                    header_path = abs_path.relative_to(Path.cwd())
                except ValueError:
                    header_path = abs_path
                header = f"# FILEPATH: {header_path}\n"
                total_size += len(header) + 2
                continue
            else:
                # Fallback: read file directly (normal mode or no expanded content)
                # Only strip leading comments from Python files (shebang/license)
                try:
                    raw_content = fp.read_text(encoding="utf-8")
                    if fp.suffix == ".py":
                        content = re.sub(r"^(?:#.*\n)+", "", raw_content)
                    else:
                        content = raw_content
                except Exception:
                    content = ""

        try:
            header_path = abs_path.relative_to(Path.cwd())
        except ValueError:
            header_path = abs_path
        header = f"# FILEPATH: {header_path}\n"
        total_size += len(header) + len(content) + 2

    # Size of diffs
    for diff in context.diffs:
        total_size += len(diff)

    # If include_expanded_files, calculate the size of expanded model locations
    # that the LLM will need to read separately.
    # BUT only if content was actually skipped (expanded_shrink_level == "none")
    # Otherwise, the shrunk content is already included in the dump.
    if include_expanded_files:
        # Check if any files actually had content skipped
        has_skipped_content = any(
            info.get("content_skipped", False)
            for info in context.shrunken_files_info.values()
        )
        if has_skipped_content:
            expanded_files_size = _calculate_expanded_files_size(context)
            total_size += expanded_files_size

    return total_size


def _calculate_expanded_files_size(context: AkaidooContext) -> int:
    """
    Calculate the size of expanded model file ranges that the LLM will read separately.

    This is needed in agent mode where expanded models are NOT included in the dump
    but the LLM is instructed to read them from the source files.

    IMPORTANT: Only count files where content_skipped=True. If content was NOT skipped
    (i.e., expanded content is included in the shrunk output), we should NOT add
    the original source ranges - that would cause double-counting.
    """
    total_size = 0
    seen_ranges: set = set()  # Avoid double-counting overlapping ranges

    for fp, info in context.shrunken_files_info.items():
        # Only count expanded locations if content was actually skipped
        # (i.e., the expanded content is NOT in the dump and LLM needs to read it)
        if not info.get("content_skipped", False):
            continue

        locs = info.get("expanded_locations")
        if not locs:
            continue

        try:
            # Read the file content
            file_content = Path(fp).read_text(encoding="utf-8")
            lines = file_content.split("\n")
        except Exception:
            continue

        for model_name, ranges in locs.items():
            for start_line, end_line, type_ in ranges:
                # Create a unique key for this range to avoid double-counting
                range_key = (fp, start_line, end_line)
                if range_key in seen_ranges:
                    continue
                seen_ranges.add(range_key)

                # Calculate the size of this range
                # Adjust for 1-based line numbers
                start_idx = max(0, start_line - 1)
                end_idx = min(len(lines), end_line)
                range_content = "\n".join(lines[start_idx:end_idx])

                # Add header overhead (FILEPATH + line range info)
                try:
                    rel_path = Path(fp).relative_to(Path.cwd())
                except ValueError:
                    rel_path = Path(fp)
                header = f"# FILEPATH: {rel_path} (lines {start_line}-{end_line})\n"

                total_size += len(header) + len(range_content) + 2

    return total_size


def get_akaidoo_context_dump(
    context: AkaidooContext,
    introduction: str,
    focus_files: Optional[List[str]] = None,
) -> str:
    """Generate the context dump string from an AkaidooContext."""
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

            suffix = context.shrunken_files_info.get(fp.resolve(), {}).get(
                "header_suffix", ""
            )
            header = f"# FILEPATH: {header_path}{suffix}\n"

            # Get content from shrunken_files_content if available
            content = context.shrunken_files_content.get(fp.resolve())
            if content is None:
                # Fallback: read file directly
                # Only strip leading comments from Python files (shebang/license)
                raw_content = fp.read_text(encoding="utf-8")
                if fp.suffix == ".py":
                    content = re.sub(r"^(?:#.*\n)+", "", raw_content)
                else:
                    content = raw_content
            all_content.append(header + content)
        except Exception:
            continue

    for diff in context.diffs:
        all_content.append(diff)

    return "\n\n".join(all_content)
