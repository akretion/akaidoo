from pathlib import Path
from typing import List, Set, Optional, Dict
from manifestoo import echo
import manifestoo.echo as manifestoo_echo_module
from .shrinker import shrink_python_file
from .types import ScanResult
from .utils import get_file_odoo_models
from .config import BINARY_EXTS, SHRINK_MATRIX, MAX_DATA_FILE_SIZE


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


def scan_directory_files(directory_path: Path) -> List[Path]:
    """Scan a directory recursively, skipping pycache, i18n, hidden files, and binaries."""
    found_files = []
    for item in directory_path.rglob("*"):
        if not item.is_file():
            continue

        rel = item.relative_to(directory_path)
        if (
            "__pycache__" in rel.parts
            or "i18n" in rel.parts
            or rel.parts[0].startswith(".")
            or item.suffix.lower() in BINARY_EXTS
        ):
            continue

        found_files.append(item)
    return found_files


def scan_addon_files(
    addon_dir: Path,
    addon_name: str,
    selected_addon_names: Set[str],
    includes: Set[str],
    excluded_addons: Set[str],
    shrink_mode: str = "none",
    expand_models_set: Optional[Set[str]] = None,
    relevant_models: Optional[Set[str]] = None,
    prune_methods: Optional[Set[str]] = None,
    skip_expanded: bool = False,
) -> ScanResult:
    """
    Scan an Odoo addon directory for relevant files based on filters.

    Returns a ScanResult containing:
    - found_files: List of file paths found
    - shrunken_content: Dict mapping file paths to their shrunken content
    - shrunken_info: Dict mapping file paths to shrink metadata
    """
    found_files: List[Path] = []
    shrunken_content: Dict[Path, str] = {}
    shrunken_info: Dict[Path, Dict] = {}

    # Normalize None to empty sets for simpler conditionals
    expand_models_set = expand_models_set or set()
    relevant_models = relevant_models or set()
    excluded_addons = excluded_addons or set()
    prune_methods = prune_methods or set()

    scan_roots: List[str] = []
    if "model" in includes:
        scan_roots.append("models")
        scan_roots.append(".")
    if "view" in includes:
        scan_roots.append("views")
    if "wizard" in includes:
        scan_roots.extend(["wizard", "wizards"])
    if "report" in includes:
        scan_roots.extend(["report", "reports"])
    if "data" in includes:
        scan_roots.append("data")
    if "controller" in includes:
        scan_roots.append("controllers")
    if "security" in includes:
        scan_roots.append("security")
    if "static" in includes:
        scan_roots.append("static")
    if "test" in includes:
        scan_roots.append("tests")

    current_addon_extensions: List[str] = []
    if "model" in includes:
        current_addon_extensions.append(".py")
    if "controller" in includes or "test" in includes:
        if ".py" not in current_addon_extensions:
            current_addon_extensions.append(".py")

    if (
        "view" in includes
        or "wizard" in includes
        or "report" in includes
        or "data" in includes
    ):
        if ".xml" not in current_addon_extensions:
            current_addon_extensions.append(".xml")
    if "data" in includes or "security" in includes:
        if ".csv" not in current_addon_extensions:
            current_addon_extensions.append(".csv")
    if "static" in includes:
        if ".js" not in current_addon_extensions:
            current_addon_extensions.append(".js")

    if not current_addon_extensions:
        return ScanResult()

    for root_name in set(scan_roots):
        scan_path_dir = addon_dir / root_name if root_name != "." else addon_dir
        if not scan_path_dir.is_dir():
            continue

        for ext in current_addon_extensions:
            files_to_check: List[Path] = []
            if root_name == ".":
                if ext == ".py":
                    files_to_check.extend(scan_path_dir.glob("*.py"))
            else:
                files_to_check.extend(scan_path_dir.glob(f"**/*{ext}"))

            for found_file in files_to_check:
                if not found_file.is_file():
                    continue

                relative_path_parts = found_file.relative_to(addon_dir).parts

                is_excluded_file = any(
                    f"/addons/{name}/" in str(found_file.resolve())
                    for name in excluded_addons
                )
                if is_excluded_file:
                    if manifestoo_echo_module.verbosity >= 3:
                        echo.info(f"Excluding file from excluded addon: {found_file}")
                    continue

                # Determine File Type
                is_model_file = "models" in relative_path_parts and ext == ".py"
                is_root_py_file = (
                    len(relative_path_parts) == 1
                    and relative_path_parts[0].endswith(".py")
                    and root_name == "."
                )
                is_view_file = "views" in relative_path_parts and ext == ".xml"
                is_wizard_file = (
                    "wizard" in relative_path_parts or "wizards" in relative_path_parts
                ) and (ext == ".xml" or ext == ".py")
                is_report_file = (
                    "report" in relative_path_parts or "reports" in relative_path_parts
                ) and (ext == ".xml" or ext == ".py")
                is_data_file = ("data" in relative_path_parts) and ext in (
                    ".csv",
                    ".xml",
                )
                is_controller_file = (
                    "controllers" in relative_path_parts and ext == ".py"
                )
                is_security_file = ("security" in relative_path_parts) and ext in (
                    ".csv",
                    ".xml",
                )
                is_static_file = "static" in relative_path_parts
                is_test_file = "tests" in relative_path_parts and ext == ".py"

                # Filtering
                should_include = False
                if "model" in includes and (is_model_file or is_root_py_file):
                    should_include = True
                elif "view" in includes and is_view_file:
                    should_include = True
                elif "wizard" in includes and is_wizard_file:
                    should_include = True
                elif "report" in includes and is_report_file:
                    should_include = True
                elif "data" in includes and is_data_file:
                    should_include = True
                elif "controller" in includes and is_controller_file:
                    should_include = True
                elif "security" in includes and is_security_file:
                    should_include = True
                elif "static" in includes and is_static_file:
                    should_include = True
                elif "test" in includes and is_test_file:
                    should_include = True

                if not should_include:
                    continue

                if found_file.name == "__init__.py" and is_trivial_init_py(found_file):
                    echo.debug(f"  Skipping trivial __init__.py: {found_file}")
                    continue

                abs_file_path = found_file.resolve()
                if abs_file_path not in found_files:
                    # Large Data File Truncation
                    if is_data_file or (ext == ".csv"):
                        try:
                            size = found_file.stat().st_size
                            if size > MAX_DATA_FILE_SIZE:
                                content = found_file.read_text(encoding="utf-8")[
                                    :MAX_DATA_FILE_SIZE
                                ]
                                content += f"\n\n# ... truncated by akaidoo (size > {MAX_DATA_FILE_SIZE / 1024}KB) ..."
                                shrunken_content[abs_file_path] = content
                        except Exception:
                            pass

                    # Python Processing (Pruning/Shrinking)
                    file_in_target_addon = addon_name in selected_addon_names
                    file_models = set()

                    if (
                        found_file.suffix == ".py"
                        and found_file.name != "__manifest__.py"
                    ):
                        need_models = shrink_mode != "none"
                        if need_models:
                            file_models = get_file_odoo_models(abs_file_path)

                    if shrink_mode != "none" and found_file.suffix == ".py":
                        if found_file.name != "__manifest__.py":
                            file_is_expanded = any(
                                m in expand_models_set for m in file_models
                            )
                            file_is_related = any(
                                m in relevant_models for m in file_models
                            )

                            category = "D_OTH"
                            if file_in_target_addon:
                                if file_is_expanded:
                                    category = "T_EXP"
                                else:
                                    category = "T_OTH"
                            else:
                                if file_is_expanded:
                                    category = "D_EXP"
                                elif file_is_related:
                                    category = "D_REL"
                                else:
                                    category = "D_OTH"

                            effort = shrink_mode.lower()
                            matrix_row = SHRINK_MATRIX.get(
                                effort, SHRINK_MATRIX["soft"]
                            )
                            shrink_level = matrix_row.get(category, "soft")

                            # Get per-category shrink levels for proper per-model handling
                            if file_in_target_addon:
                                expanded_shrink_level = matrix_row.get("T_EXP", "none")
                                related_shrink_level = matrix_row.get("T_OTH", "soft")
                                other_shrink_level = matrix_row.get("T_OTH", "soft")
                            else:
                                expanded_shrink_level = matrix_row.get("D_EXP", "none")
                                related_shrink_level = matrix_row.get("D_REL", "soft")
                                other_shrink_level = matrix_row.get("D_OTH", "max")

                            # Always run shrinker to support context headers/navigation
                            try:
                                header_path = abs_file_path.relative_to(Path.cwd())
                            except ValueError:
                                header_path = abs_file_path

                            shrink_result = shrink_python_file(
                                str(found_file),
                                shrink_level=shrink_level,
                                expand_models=expand_models_set,
                                skip_imports=(shrink_mode != "none"),
                                strip_metadata=(
                                    shrink_level in ("hard", "max", "prune")
                                ),
                                relevant_models=relevant_models,
                                prune_methods=prune_methods,
                                header_path=str(header_path),
                                skip_expanded_content=skip_expanded,
                                expanded_shrink_level=expanded_shrink_level,
                                related_shrink_level=related_shrink_level,
                                other_shrink_level=other_shrink_level,
                            )

                            has_content = bool(shrink_result.content.strip())
                            has_expanded_locs = bool(shrink_result.expanded_locations)

                            # Skip files with no content AND no expanded locations
                            if not has_content and not has_expanded_locs:
                                continue

                            # Store content only if non-empty
                            if has_content:
                                shrunken_content[abs_file_path] = shrink_result.content

                            # Always store info if there's content OR expanded locations
                            # (needed for token estimation in agent mode)
                            shrunken_info[abs_file_path] = {
                                "shrink_level": shrink_level,
                                "expanded_models": shrink_result.expanded_models,
                                "header_suffix": shrink_result.header_suffix or "",
                                "expanded_locations": shrink_result.expanded_locations,
                                "model_shrink_levels": shrink_result.model_shrink_levels,
                                "content_skipped": shrink_result.content_skipped,
                            }
                    found_files.append(abs_file_path)

    return ScanResult(
        found_files=found_files,
        shrunken_content=shrunken_content,
        shrunken_info=shrunken_info,
    )
