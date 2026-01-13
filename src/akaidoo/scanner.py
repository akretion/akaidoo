import re
from pathlib import Path
from typing import List, Set, Optional, Dict
from manifestoo_core.addons_set import Addon
from manifestoo import echo
import manifestoo.echo as manifestoo_echo_module
from .shrinker import shrink_python_file

BINARY_EXTS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".svg",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".pdf",
    ".map",
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
    target_addon_names: Set[str],
    include_models: bool = True,
    include_views: bool = True,
    include_wizards: bool = True,
    include_reports: bool = False,
    include_data: bool = False,
    only_models: bool = False,
    only_views: bool = False,
    exclude_framework: bool = True,
    framework_addons: tuple = (),
    shrink: bool = False,
    shrink_aggressive: bool = False,
    expand_models_set: Set[str] = None,
    shrunken_files_content: Dict[Path, str] = None,
) -> List[Path]:
    """Scan an Odoo addon directory for relevant files based on filters."""
    found_files = []
    shrunken_files_content = shrunken_files_content if shrunken_files_content is not None else {}
    expand_models_set = expand_models_set or set()
    
    scan_roots: List[str] = []
    if only_models:
        scan_roots.append("models")
        if include_data:
            scan_roots.append("data")
    elif only_views:
        scan_roots.append("views")
    else:
        if include_models:
            scan_roots.append("models")
        if include_views:
            scan_roots.append("views")
        if include_wizards:
            scan_roots.extend(["wizard", "wizards"])
        if include_reports:
            scan_roots.extend(["report", "reports"])
        if include_data:
            scan_roots.append("data")
        if not scan_roots or include_models:
            scan_roots.append(".")

    current_addon_extensions: List[str] = []
    if include_models or only_models:
        current_addon_extensions.append(".py")
    if include_views or only_views or include_wizards or include_reports:
        if ".xml" not in current_addon_extensions:
            current_addon_extensions.append(".xml")

    if not current_addon_extensions:
        return []

    for root_name in set(scan_roots):
        scan_path_dir = addon_dir / root_name if root_name != "." else addon_dir
        if not scan_path_dir.is_dir():
            continue

        for ext in current_addon_extensions:
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
            elif root_name in ("report", "reports"):
                if ext == ".xml":
                    files_to_check.extend(scan_path_dir.glob("**/*.xml"))
            elif root_name == "data":
                if ext in (".csv", ".xml"):
                    files_to_check.extend(scan_path_dir.glob("**/*.csv"))
                    files_to_check.extend(scan_path_dir.glob("**/*.xml"))

            for found_file in files_to_check:
                if not found_file.is_file():
                    continue
                
                relative_path_parts = found_file.relative_to(addon_dir).parts
                
                is_framework_file = any(
                    f"/addons/{name}/" in str(found_file.resolve())
                    for name in framework_addons
                )
                if is_framework_file and exclude_framework:
                    if manifestoo_echo_module.verbosity >= 3:
                        echo.info(f"Excluding framework file: {found_file}")
                    continue

                is_model_file = ("models" in relative_path_parts and ext == ".py")
                is_view_file = ("views" in relative_path_parts and ext == ".xml")
                is_wizard_file = (
                    "wizard" in relative_path_parts or "wizards" in relative_path_parts
                ) and ext == ".xml"
                is_report_file = (
                    "report" in relative_path_parts or "reports" in relative_path_parts
                ) and ext == ".xml"
                is_data_file = ("data" in relative_path_parts) and ext in (".csv", ".xml")
                is_root_py_file = (
                    len(relative_path_parts) == 1
                    and relative_path_parts[0].endswith(".py")
                    and root_name == "."
                )

                if only_models and not (is_model_file or is_data_file):
                    continue
                if only_views and not is_view_file:
                    continue

                if not (only_models or only_views):
                    file_type_matches_include = False
                    if include_models and (is_model_file or is_root_py_file):
                        file_type_matches_include = True
                    if include_views and is_view_file:
                        file_type_matches_include = True
                    if include_wizards and is_wizard_file:
                        file_type_matches_include = True
                    if include_reports and is_report_file:
                        file_type_matches_include = True
                    if include_data and is_data_file:
                        file_type_matches_include = True
                    
                    if root_name == "." and not is_root_py_file and not (
                        is_model_file or is_view_file or is_wizard_file or is_report_file
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
                    if (shrink or shrink_aggressive) and found_file.suffix == ".py":
                        if shrink_aggressive or addon_name not in target_addon_names:
                            shrunken_content = shrink_python_file(
                                str(found_file),
                                aggressive=shrink_aggressive,
                                expand_models=expand_models_set,
                            )
                            shrunken_files_content[abs_file_path] = shrunken_content
                    found_files.append(abs_file_path)
    
    return found_files
