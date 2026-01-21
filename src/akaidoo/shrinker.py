import re
import sys
import argparse
import ast
import pprint
from pathlib import Path
from typing import Optional, Set, List, Dict, Tuple
from .utils import _get_odoo_model_names_from_body, parser
from .types import ShrinkResult


def shrink_manifest(content: str) -> str:
    """
    Shrinks a manifest content by keeping only essential keys.
    """
    try:
        manifest = ast.literal_eval(content)
        if not isinstance(manifest, dict):
            return content

        keep_keys = {
            "name",
            "summary",
            "depends",
            "external_dependencies",
            "pre_init_hook",
            "post_init_hook",
            "uninstall_hook",
            "data",
        }

        new_manifest = {k: v for k, v in manifest.items() if k in keep_keys}

        return pprint.pformat(new_manifest, indent=4, sort_dicts=True)
    except Exception:
        return content


STRUCTURAL_ATTRS = {
    "comodel_name",
    "inverse_name",
    "relation",
    "column1",
    "column2",
    "related",
    "compute",
    "store",
}


def _reconstruct_field_node(node, code_bytes: bytes) -> str:
    """
    Reconstructs a field definition keeping only positional args
    and whitelisted keyword args (STRUCTURAL_ATTRS).
    """
    try:
        assign = node.child(0)
        if not assign or assign.type != "assignment":
            return code_bytes[node.start_byte : node.end_byte].decode("utf-8").strip()

        # Extract Field Name (Left side)
        left = assign.child_by_field_name("left")
        field_name = code_bytes[left.start_byte : left.end_byte].decode("utf-8")

        # Extract Function Call (Right side)
        right = assign.child_by_field_name("right")
        if not right or right.type != "call":
            return code_bytes[node.start_byte : node.end_byte].decode("utf-8").strip()

        func_node = right.child_by_field_name("function")
        func_name = code_bytes[func_node.start_byte : func_node.end_byte].decode(
            "utf-8"
        )

        # Process Arguments
        args_node = right.child_by_field_name("arguments")
        clean_args = []

        if args_node:
            for arg in args_node.children:
                if arg.type in ("(", ")", ","):
                    continue

                if arg.type == "keyword_argument":
                    key_node = arg.child_by_field_name("name")
                    key = code_bytes[key_node.start_byte : key_node.end_byte].decode(
                        "utf-8"
                    )
                    if key in STRUCTURAL_ATTRS:
                        val_node = arg.child_by_field_name("value")
                        # Strip newlines/indentation from value to compact it
                        val = code_bytes[
                            val_node.start_byte : val_node.end_byte
                        ].decode("utf-8")
                        val = re.sub(r"\s+", " ", val).strip()
                        clean_args.append(f"{key}={val}")
                elif arg.type == "comment":
                    continue
                else:
                    # Keep positional arguments (usually comodel_name/inverse_name)
                    val = code_bytes[arg.start_byte : arg.end_byte].decode("utf-8")
                    val = re.sub(r"\s+", " ", val).strip()
                    clean_args.append(val)

        return f"{field_name} = {func_name}({', '.join(clean_args)})"
    except Exception:
        # Fallback to original text if parsing fails
        return code_bytes[node.start_byte : node.end_byte].decode("utf-8").strip()


def _get_field_info(node, code_bytes: bytes) -> Dict:
    """
    Extracts info from a field assignment node.
    """
    info = {
        "name": None,
        "type": None,
        "comodel": None,
        "compute": None,
        "store": None,
        "is_field": False,
    }

    if node.type != "expression_statement":
        return info
    assign = node.child(0)
    if not assign or assign.type != "assignment":
        return info

    left = assign.child_by_field_name("left")
    if not left or left.type != "identifier":
        return info

    info["name"] = code_bytes[left.start_byte : left.end_byte].decode("utf-8")
    if info["name"].startswith("_"):
        return info

    right = assign.child_by_field_name("right")
    if not right or right.type != "call":
        return info

    func = right.child_by_field_name("function")
    if not func or func.type != "attribute":
        return info

    obj = func.child_by_field_name("object")
    attr = func.child_by_field_name("attribute")

    if not obj or obj.type != "identifier" or not attr or attr.type != "identifier":
        return info

    obj_name = code_bytes[obj.start_byte : obj.end_byte].decode("utf-8")
    attr_name = code_bytes[attr.start_byte : attr.end_byte].decode("utf-8")

    if obj_name not in ("fields", "models"):
        return info

    info["is_field"] = True
    info["type"] = attr_name

    args = right.child_by_field_name("arguments")
    if args:
        if attr_name in ("Many2one", "One2many", "Many2many"):
            for arg in args.children:
                if arg.type == "string":
                    val = code_bytes[arg.start_byte : arg.end_byte].decode("utf-8")
                    info["comodel"] = val.strip("'\"")
                    break
                elif arg.type in (
                    "identifier",
                    "attribute",
                    "call",
                    "integer",
                    "float",
                ):
                    break

        for arg in args.children:
            if arg.type == "keyword_argument":
                key_node = arg.child_by_field_name("name")
                val_node = arg.child_by_field_name("value")
                if key_node and val_node:
                    key = code_bytes[key_node.start_byte : key_node.end_byte].decode(
                        "utf-8"
                    )
                    if key == "compute":
                        if val_node.type == "string":
                            val = code_bytes[
                                val_node.start_byte : val_node.end_byte
                            ].decode("utf-8")
                            info["compute"] = val.strip("'\"")
                    elif key == "store":
                        if val_node.type == "true":
                            info["store"] = True
                        elif val_node.type == "false":
                            info["store"] = False
                    elif key == "comodel_name" and val_node.type == "string":
                        val = code_bytes[
                            val_node.start_byte : val_node.end_byte
                        ].decode("utf-8")
                        info["comodel"] = val.strip("'\"")

    return info


def shrink_python_file(
    path: str,
    aggressive: bool = False,
    expand_models: Optional[Set[str]] = None,
    skip_imports: bool = False,
    strip_metadata: bool = False,
    shrink_level: Optional[str] = None,
    relevant_models: Optional[Set[str]] = None,
    prune_methods: Optional[Set[str]] = None,
    header_path: Optional[str] = None,
    skip_expanded_content: bool = False,
    expanded_shrink_level: Optional[str] = None,
    related_shrink_level: Optional[str] = None,
    other_shrink_level: Optional[str] = None,
) -> ShrinkResult:
    """
    Shrinks Python code from a file.

    Per-model shrink levels:
    - expanded_shrink_level: Level for expanded models (default: "none")
    - related_shrink_level: Level for related models (default: shrink_level)
    - other_shrink_level: Level for other models (default: shrink_level)

    Returns ShrinkResult with shrunken content and metadata.
    """
    if shrink_level is None:
        shrink_level = "hard" if aggressive else "soft"

    # Set per-category defaults if not provided
    if expanded_shrink_level is None:
        expanded_shrink_level = "none"
    if related_shrink_level is None:
        related_shrink_level = shrink_level
    if other_shrink_level is None:
        other_shrink_level = shrink_level

    # Note: Even if 'none', we might need to parse to get line ranges or apply skip_expanded_content
    # So we only return early if we don't care about those features?
    # If skip_expanded_content is True, we MUST parse to find them.
    # If prune_methods is set, we MUST parse.
    # If header_path is set (implies we want context navigation), we MUST parse.
    # So basically always parse unless simple 'none' with no extras.
    if shrink_level == "none" and not prune_methods and not skip_expanded_content:
        # But wait, header logic is inside loop. If we skip parsing, we miss headers.
        # Assuming we always want context headers if header_path is provided.
        if not header_path:
            return ShrinkResult(content=Path(path).read_text(encoding="utf-8"))

    code = Path(path).read_text(encoding="utf-8")
    code_bytes = bytes(code, "utf8")
    tree = parser.parse(code_bytes)
    root_node = tree.root_node

    shrunken_parts = []
    expand_models = expand_models or set()
    relevant_models = relevant_models or set()
    prune_methods = prune_methods or set()
    actually_expanded_models = set()
    expanded_locations: Dict[str, List[Tuple[int, int, str]]] = {}
    model_shrink_levels: Dict[str, str] = {}  # Track effective shrink level per model
    any_content_skipped = False  # Track if any expanded content was skipped

    # Pre-scan for Odoo models count
    odoo_models_count = 0
    for node in root_node.children:
        if node.type == "class_definition":
            body_node = node.child_by_field_name("body")
            if body_node:
                m_map = _get_odoo_model_names_from_body(body_node, code_bytes)
                if m_map:
                    odoo_models_count += 1

    current_model_index = 0
    first_header_suffix = None

    def clean_line(line: str) -> str:
        if not strip_metadata:
            return line
        line = re.sub(r",?\s*help\s*=\s*(?P<q>['\"])(?:(?!\1).)*\1", "", line)
        line = line.replace(", ,", ",").replace(",, ", ", ")
        line = re.sub(r",\s*\)", ")", line)
        line = re.sub(r"#.*$", "", line)
        return line.strip()

    def process_function(
        node, indent="", context_models: Set[str] = None, override_level: str = None
    ):
        effective_level = override_level if override_level else shrink_level

        func_def_node = node
        if node.type == "decorated_definition":
            definition = node.child_by_field_name("definition")
            if definition and definition.type == "function_definition":
                func_def_node = definition
            else:
                return

        should_prune_specifically = False
        if context_models:
            func_name_node = func_def_node.child_by_field_name("name")
            if func_name_node:
                func_name = code_bytes[
                    func_name_node.start_byte : func_name_node.end_byte
                ].decode("utf-8")
                for m in context_models:
                    if f"{m}.{func_name}" in prune_methods:
                        should_prune_specifically = True
                        break

        if (
            effective_level in ("hard", "max", "prune")
            and not should_prune_specifically
        ):
            return

        body_node = func_def_node.child_by_field_name("body")
        if not body_node:
            return

        header_end = body_node.start_byte
        header_text = code_bytes[node.start_byte : header_end].decode("utf8").strip()

        if should_prune_specifically:
            for line in header_text.splitlines():
                stripped_line = line.strip()
                if stripped_line:
                    shrunken_parts.append(f"{indent}{stripped_line}")
            shrunken_parts.append(f"{indent}    pass  # pruned by request")
            return

        if effective_level == "soft":
            for line in header_text.splitlines():
                stripped_line = line.strip()
                if stripped_line:
                    shrunken_parts.append(f"{indent}{stripped_line}")
            start = node.start_point[0] + 1
            end = node.end_point[0] + 1
            shrunken_parts.append(f"{indent}    pass  # shrunk (lines {start}-{end})")
            return

        full_text = code_bytes[node.start_byte : node.end_byte].decode("utf-8")
        shrunken_parts.append(full_text)

    for node in root_node.children:
        if node.type in ("import_statement", "import_from_statement"):
            if not skip_imports:
                line_text = (
                    code_bytes[node.start_byte : node.end_byte].decode("utf8").strip()
                )
                shrunken_parts.append(line_text)
            continue

        if node.type == "class_definition":
            body_node = node.child_by_field_name("body")
            if not body_node:
                continue

            model_map = _get_odoo_model_names_from_body(body_node, code_bytes)
            model_names = set(model_map.keys())
            if model_names:
                current_model_index += 1

            should_expand = any(m in expand_models for m in model_names)

            has_pruned_methods = False
            for m in model_names:
                for pm in prune_methods:
                    if pm.startswith(f"{m}."):
                        has_pruned_methods = True
                        break
                if has_pruned_methods:
                    break

            if (
                should_expand
                and not has_pruned_methods
                and expanded_shrink_level == "none"
            ):
                actually_expanded_models.update(model_names & expand_models)

                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                line_range_str = f" (lines {start_line}-{end_line})"

                # Store location info and track effective shrink level
                for m in model_names & expand_models:
                    if m not in expanded_locations:
                        expanded_locations[m] = []
                    type_ = model_map[m]
                    expanded_locations[m].append((start_line, end_line, type_))
                    model_shrink_levels[m] = "none"  # Expanded = full content

                if skip_expanded_content:
                    any_content_skipped = True
                    continue

                if odoo_models_count > 1:
                    if current_model_index == 1:
                        first_header_suffix = line_range_str
                    elif header_path:
                        shrunken_parts.append("")
                        shrunken_parts.append(
                            f"# FILEPATH: {header_path}{line_range_str}"
                        )

                class_full_text = code_bytes[node.start_byte : node.end_byte].decode(
                    "utf-8"
                )
                shrunken_parts.append(class_full_text)
            else:
                effective_level = shrink_level

                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                line_range_str = f" (lines {start_line}-{end_line})"

                if odoo_models_count > 1:
                    if current_model_index == 1:
                        first_header_suffix = line_range_str
                    elif header_path:
                        shrunken_parts.append("")
                        shrunken_parts.append(
                            f"# FILEPATH: {header_path}{line_range_str}"
                        )

                if should_expand:
                    effective_level = expanded_shrink_level
                    actually_expanded_models.update(model_names & expand_models)

                    # Store location info even if pruned methods (it's still "expanded" category)
                    for m in model_names & expand_models:
                        if m not in expanded_locations:
                            expanded_locations[m] = []
                        type_ = model_map[m]
                        expanded_locations[m].append((start_line, end_line, type_))
                        model_shrink_levels[m] = expanded_shrink_level

                    # Only skip expanded content if it would be at full resolution (none)
                    # If expanded_shrink_level != "none", the content is shrunk and small,
                    # so we should include it rather than having the agent read full source
                    if skip_expanded_content and expanded_shrink_level == "none":
                        any_content_skipped = True
                        continue

                # Track shrink level for non-expanded models in this class
                # Each model gets its own level based on category
                for m in model_names:
                    if m not in model_shrink_levels:
                        if m in expand_models:
                            model_shrink_levels[m] = expanded_shrink_level
                        elif m in relevant_models:
                            model_shrink_levels[m] = related_shrink_level
                        else:
                            model_shrink_levels[m] = other_shrink_level

                # Recalculate effective level for the class based on contained models
                if not should_expand:
                    if not model_names:
                        effective_level = shrink_level
                    else:
                        priorities = {
                            "none": 0,
                            "soft": 1,
                            "hard": 2,
                            "max": 3,
                            "prune": 4,
                        }
                        min_prio = 5
                        best_level = "prune"

                        for m in model_names:
                            lvl = model_shrink_levels.get(m, "soft")
                            p = priorities.get(lvl, 1)
                            if p < min_prio:
                                min_prio = p
                                best_level = lvl

                        effective_level = best_level

                if effective_level == "prune":
                    # For pruned models, keep a minimal skeleton (header + structural attrs)
                    header_end = body_node.start_byte
                    class_header = (
                        code_bytes[node.start_byte : header_end].decode("utf8").strip()
                    )
                    shrunken_parts.append(class_header)

                    found_structural_attrs = False
                    for child in body_node.children:
                        if child.type == "expression_statement":
                            expr = child.child(0)
                            if expr and expr.type == "assignment":
                                left = expr.child_by_field_name("left")
                                if left and left.type == "identifier":
                                    attr_name = code_bytes[
                                        left.start_byte : left.end_byte
                                    ].decode("utf-8")
                                    if attr_name in ("_name", "_inherit", "_inherits"):
                                        line_bytes = code_bytes[
                                            child.start_byte : child.end_byte
                                        ]
                                        line_text = line_bytes.decode("utf8").strip()
                                        shrunken_parts.append(
                                            f"    {clean_line(line_text)}"
                                        )
                                        found_structural_attrs = True

                    if not found_structural_attrs:
                        shrunken_parts.append("    pass  # pruned")

                    shrunken_parts.append("")
                    continue

                if effective_level == "none":
                    class_full_text = code_bytes[
                        node.start_byte : node.end_byte
                    ].decode("utf-8")
                    shrunken_parts.append(class_full_text)
                else:
                    header_end = body_node.start_byte
                    class_header = (
                        code_bytes[node.start_byte : header_end].decode("utf8").strip()
                    )
                    shrunken_parts.append(class_header)

                    non_computed_fields = []
                    computed_fields = []

                    for child in body_node.children:
                        if child.type == "expression_statement":
                            expr = child.child(0)
                            if expr and expr.type == "assignment":
                                f_info = _get_field_info(child, code_bytes)
                                if f_info["is_field"] and effective_level == "max":
                                    if f_info["compute"]:
                                        f_label = (
                                            f"{f_info['name']} ({f_info['compute']})"
                                        )
                                        computed_fields.append(f_label)
                                    else:
                                        non_computed_fields.append(f_info["name"])

                                    if f_info["comodel"] in relevant_models:
                                        # Use tree-sitter reconstruction to strip UI attributes
                                        clean_def = _reconstruct_field_node(
                                            child, code_bytes
                                        )
                                        shrunken_parts.append(f"    {clean_def}")
                                else:
                                    line_bytes = code_bytes[
                                        child.start_byte : child.end_byte
                                    ]
                                    line_text = line_bytes.decode("utf8").strip()
                                    shrunken_parts.append(
                                        f"    {clean_line(line_text)}"
                                    )

                        elif child.type in (
                            "function_definition",
                            "decorated_definition",
                        ):
                            process_function(
                                child,
                                indent="    ",
                                context_models=model_names,
                                override_level=effective_level,
                            )

                    if effective_level == "max":
                        if non_computed_fields:
                            shrunken_parts.append(
                                f"    # Shrunk non computed fields: {', '.join(non_computed_fields)}"
                            )
                        if computed_fields:
                            shrunken_parts.append(
                                f"    # Shrunk computed_fields: {', '.join(computed_fields)}"
                            )

            shrunken_parts.append("")

        elif node.type in ("function_definition", "decorated_definition"):
            process_function(node, indent="")
            if shrink_level == "soft":
                shrunken_parts.append("")

        elif node.type == "expression_statement":
            expr = node.child(0)
            if expr and expr.type == "assignment":
                line_bytes = code_bytes[node.start_byte : node.end_byte]
                line_text = line_bytes.decode("utf8").strip()
                shrunken_parts.append(clean_line(line_text))

    while shrunken_parts and shrunken_parts[-1] == "":
        shrunken_parts.pop()

    return ShrinkResult(
        content="\n".join(shrunken_parts) + "\n",
        expanded_models=actually_expanded_models,
        header_suffix=first_header_suffix,
        expanded_locations=expanded_locations,
        model_shrink_levels=model_shrink_levels,
        content_skipped=any_content_skipped,
    )


def _strip_field_metadata(line: str) -> str:
    line = re.sub(r",?\s*help\s*=\s*(?P<q>['\"])(?:(?!\1).)*\1", "", line)
    line = re.sub(r",?\s*string\s*=\s*(?P<q>['\"])(?:(?!\1).)*\1", "", line)
    line = line.replace(", ,", ",").replace(",, ", ", ")
    line = re.sub(r",\s*\)", ")", line)
    line = re.sub(r"#.*$", "", line)
    return line.strip()


def main():
    cli_parser = argparse.ArgumentParser(
        description="Shrink a Python file to its structural components."
    )
    cli_parser.add_argument("input_file", type=str)
    cli_parser.add_argument("-S", "--shrink-aggressive", action="store_true")
    cli_parser.add_argument(
        "-L",
        "--shrink-level",
        type=str,
        choices=["none", "soft", "hard", "max", "prune"],
        default=None,
    )
    cli_parser.add_argument(
        "-E", "--expand", type=str, help="Comma separated models to expand."
    )
    cli_parser.add_argument(
        "-P",
        "--prune-methods",
        type=str,
        help="Comma separated methods to prune (Model.method).",
    )
    cli_parser.add_argument(
        "-H", "--header-path", type=str, help="File path for headers."
    )
    cli_parser.add_argument(
        "--skip-expanded", action="store_true", help="Skip content of expanded models."
    )
    cli_parser.add_argument("-o", "--output", type=str)
    args = cli_parser.parse_args()

    expand_set = set(args.expand.split(",")) if args.expand else set()
    prune_set = set(args.prune_methods.split(",")) if args.prune_methods else set()

    try:
        result = shrink_python_file(
            args.input_file,
            aggressive=args.shrink_aggressive,
            shrink_level=args.shrink_level,
            expand_models=expand_set,
            prune_methods=prune_set,
            header_path=args.header_path,
            skip_expanded_content=args.skip_expanded,
        )
        if args.output:
            Path(args.output).write_text(result.content, encoding="utf-8")
        else:
            sys.stdout.write(result.content)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
