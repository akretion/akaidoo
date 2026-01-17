import re
from pathlib import Path
from typing import List, Set, Optional, Dict
from manifestoo_core.addons_set import Addon
from manifestoo import echo
import manifestoo.echo as manifestoo_echo_module
from .shrinker import shrink_python_file
from .utils import get_file_odoo_models


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

MAX_DATA_FILE_SIZE = 50 * 1024

def scan_addon_files(
    addon_dir: Path,
    addon_name: str,
    selected_addon_names: Set[str],
    includes: Set[str],
    excluded_addons: Set[str],
    shrink_mode: str = "none",
    expand_models_set: Optional[Set[str]] = None,
    shrunken_files_content: Optional[Dict[Path, str]] = None,
    relevant_models: Optional[Set[str]] = None,
    prune_mode: str = "soft",
    shrunken_files_info: Optional[Dict[Path, Dict]] = None,
) -> List[Path]:
    """Scan an Odoo addon directory for relevant files based on filters."""
    found_files = []
    shrunken_files_content = (
        shrunken_files_content if shrunken_files_content is not None else {}
    )
    shrunken_files_info = (
        shrunken_files_info if shrunken_files_info is not None else {}
    )
    expand_models_set = expand_models_set if expand_models_set is not None else set()
    relevant_models = relevant_models if relevant_models is not None else set()
    excluded_addons = excluded_addons if excluded_addons is not None else set()

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
    
    if "view" in includes or "wizard" in includes or "report" in includes or "data" in includes:
        if ".xml" not in current_addon_extensions:
            current_addon_extensions.append(".xml")
    if "data" in includes or "security" in includes:
        if ".csv" not in current_addon_extensions:
            current_addon_extensions.append(".csv")
    if "static" in includes:
        if ".js" not in current_addon_extensions:
            current_addon_extensions.append(".js")
        # Static can also have .xml (qweb) but usually in static/src/xml or similar
        # We recursively scan roots, so if we add static, we might need more extensions?
        # For now, let's keep it simple or match standard Odoo static assets.
        # But 'scan_addon_files' iterates 'ext'.
        # If I add .js, scan_path_dir.glob("*.js") works.

    if not current_addon_extensions:
        return []

    for root_name in set(scan_roots):
        scan_path_dir = addon_dir / root_name if root_name != "." else addon_dir
        if not scan_path_dir.is_dir():
            continue

        for ext in current_addon_extensions:
            files_to_check: List[Path] = []
            # Glob logic based on root_name and ext
            if root_name == ".":
                if ext == ".py":
                    files_to_check.extend(scan_path_dir.glob("*.py"))
            else:
                # Recursive scan for subdirs
                # Note: scan_path_dir.glob(f"**/*{ext}")
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
                is_model_file = ("models" in relative_path_parts and ext == ".py")
                is_root_py_file = (
                    len(relative_path_parts) == 1
                    and relative_path_parts[0].endswith(".py")
                    and root_name == "."
                )
                is_view_file = ("views" in relative_path_parts and ext == ".xml")
                is_wizard_file = (
                    "wizard" in relative_path_parts or "wizards" in relative_path_parts
                ) and (ext == ".xml" or ext == ".py") # Wizards have py and xml!
                is_report_file = (
                    "report" in relative_path_parts or "reports" in relative_path_parts
                ) and (ext == ".xml" or ext == ".py") # Reports have py and xml
                is_data_file = ("data" in relative_path_parts) and ext in (".csv", ".xml")
                is_controller_file = ("controllers" in relative_path_parts and ext == ".py")
                is_security_file = ("security" in relative_path_parts) and ext in (".csv", ".xml")
                is_static_file = ("static" in relative_path_parts)
                is_test_file = ("tests" in relative_path_parts and ext == ".py")

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

                if (
                    found_file.name == "__init__.py"
                    and is_trivial_init_py(found_file)
                ):
                    echo.debug(f"  Skipping trivial __init__.py: {found_file}")
                    continue

                abs_file_path = found_file.resolve()
                if abs_file_path not in found_files:
                    
                    # Large Data File Truncation
                    if is_data_file or (ext == ".csv"): # Security CSVs too?
                        try:
                            size = found_file.stat().st_size
                            if size > MAX_DATA_FILE_SIZE:
                                content = found_file.read_text(encoding="utf-8")[:MAX_DATA_FILE_SIZE]
                                content += f"\n\n# ... truncated by akaidoo (size > {MAX_DATA_FILE_SIZE/1024}KB) ..."
                                shrunken_files_content[abs_file_path] = content
                        except Exception:
                            pass

                    # Python Processing (Pruning/Shrinking)
                    file_in_target_addon = addon_name in selected_addon_names
                    file_models = set()

                    if (
                        found_file.suffix == ".py"
                        and found_file.name != "__manifest__.py"
                    ):
                        need_models = (
                            prune_mode == "medium" and not file_in_target_addon
                        ) or (shrink_mode != "none")
                        if need_models:
                            file_models = get_file_odoo_models(abs_file_path)

                    # File-level Pruning (Medium)
                    if (
                        prune_mode == "medium"
                        and not file_in_target_addon
                        and found_file.suffix == ".py"
                        and found_file.name != "__manifest__.py"
                    ):
                        if not (file_models & relevant_models):
                            continue

                    if shrink_mode != "none" and found_file.suffix == ".py":
                        # Manifests are handled specially in cli.py
                        if found_file.name != "__manifest__.py":
                            file_is_relevant = any(
                                model in relevant_models for model in file_models
                            )

                            should_shrink = False
                            aggressive = False

                            if shrink_mode == "soft":
                                should_shrink = not file_in_target_addon
                                aggressive = False

                            elif shrink_mode == "medium":
                                if file_is_relevant and file_in_target_addon:
                                    should_shrink = False
                                elif file_is_relevant:
                                    should_shrink = True
                                    aggressive = False
                                else:
                                    should_shrink = True
                                    aggressive = True

                            elif shrink_mode == "hard":
                                should_shrink = True
                                aggressive = True

                            if should_shrink:
                                shrunken_content, actually_expanded = shrink_python_file(
                                    str(found_file),
                                    aggressive=aggressive,
                                    expand_models=expand_models_set,
                                )
                                shrunken_files_content[abs_file_path] = shrunken_content
                                shrunken_files_info[abs_file_path] = {
                                    "aggressive": aggressive,
                                    "expanded_models": actually_expanded
                                }
                    found_files.append(abs_file_path)

    return found_files
