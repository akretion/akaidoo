import re
import sys
import argparse
import ast
import pprint
from pathlib import Path
from typing import Optional, Set, Dict, Tuple
from .utils import _get_odoo_model_names_from_body, parser


def shrink_manifest(content: str, prune_mode: str = "soft") -> str:
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
        }
        if prune_mode in ("soft", "none"):
            keep_keys.add("data")

        new_manifest = {k: v for k, v in manifest.items() if k in keep_keys}

        return pprint.pformat(new_manifest, indent=4, sort_dicts=True)
    except Exception:
        return content


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
) -> Tuple[str, Set[str], Optional[str]]:
    """
    Shrinks Python code from a file.
    Returns (shrunken_content, actually_expanded_models, first_header_suffix).
    """
    if shrink_level is None:
        shrink_level = "hard" if aggressive else "soft"

    if shrink_level == "none" and not prune_methods:
        # NOTE: We need to handle headers even in 'none' mode now!
        # But for now, user didn't ask to change 'none' output (usually raw file).
        # Wait, if 'none' is used for TARGET addons (which are FULL), we DO want headers?
        # My plan said "update shrink_python_file to... Return the full string with headers embedded".
        # If I return raw file here, I skip header logic.
        # But wait, T_EXP is 'none' in 'soft' mode?
        # Yes. T_EXP is FULL.
        # So I MUST process the file even if shrink_level is none, to insert headers!
        pass

    code = Path(path).read_text(encoding="utf-8")
    code_bytes = bytes(code, "utf8")
    tree = parser.parse(code_bytes)
    root_node = tree.root_node

    shrunken_parts = []
    expand_models = expand_models or set()
    relevant_models = relevant_models or set()
    prune_methods = prune_methods or set()
    actually_expanded_models = set()

    # Pre-scan for Odoo models count
    odoo_models_count = 0
    for node in root_node.children:
        if node.type == "class_definition":
            body_node = node.child_by_field_name("body")
            if body_node:
                m_names = _get_odoo_model_names_from_body(body_node, code_bytes)
                if m_names:
                    odoo_models_count += 1

    # print(f"DEBUG: {path} models count: {odoo_models_count}", file=sys.stderr)

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

        if effective_level in ("hard", "extreme") and not should_prune_specifically:
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
            shrunken_parts.append(f"{indent}    pass  # shrunk")
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

            model_names = _get_odoo_model_names_from_body(body_node, code_bytes)
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

            if should_expand and not has_pruned_methods:
                actually_expanded_models.update(model_names & expand_models)

                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                line_range_str = f" (lines {start_line}-{end_line})"

                # print(f"DEBUG: Expanding {model_names}. Index {current_model_index}/{odoo_models_count}. Range {line_range_str}", file=sys.stderr)

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
                if should_expand:
                    effective_level = "none"
                    actually_expanded_models.update(model_names & expand_models)

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
                            if effective_level == "none":
                                line_bytes = code_bytes[
                                    child.start_byte : child.end_byte
                                ]
                                line_text = line_bytes.decode("utf8").strip()
                                shrunken_parts.append(f"    {line_text}")
                                continue

                            f_info = _get_field_info(child, code_bytes)
                            if f_info["is_field"] and effective_level == "extreme":
                                if f_info["compute"]:
                                    f_label = f"{f_info['name']} ({f_info['compute']})"
                                    computed_fields.append(f_label)
                                else:
                                    non_computed_fields.append(f_info["name"])

                                if f_info["comodel"] in relevant_models:
                                    line_bytes = code_bytes[
                                        child.start_byte : child.end_byte
                                    ]
                                    line_text = line_bytes.decode("utf8").strip()
                                    shrunken_parts.append(
                                        f"    {_strip_field_metadata(line_text)}"
                                    )
                            else:
                                line_bytes = code_bytes[
                                    child.start_byte : child.end_byte
                                ]
                                line_text = line_bytes.decode("utf8").strip()
                                shrunken_parts.append(f"    {clean_line(line_text)}")

                    elif child.type in ("function_definition", "decorated_definition"):
                        process_function(
                            child,
                            indent="    ",
                            context_models=model_names,
                            override_level=effective_level,
                        )

                if effective_level == "extreme":
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

    return (
        "\n".join(shrunken_parts) + "\n",
        actually_expanded_models,
        first_header_suffix,
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
        choices=["none", "soft", "hard", "extreme"],
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
    cli_parser.add_argument("-o", "--output", type=str)
    args = cli_parser.parse_args()

    expand_set = set(args.expand.split(",")) if args.expand else set()
    prune_set = set(args.prune_methods.split(",")) if args.prune_methods else set()

    try:
        shrunken_content, _, _ = shrink_python_file(
            args.input_file,
            aggressive=args.shrink_aggressive,
            shrink_level=args.shrink_level,
            expand_models=expand_set,
            prune_methods=prune_set,
            header_path=args.header_path,
        )
        if args.output:
            Path(args.output).write_text(shrunken_content, encoding="utf-8")
        else:
            sys.stdout.write(shrunken_content)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
