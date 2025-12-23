import sys
from pathlib import Path
from typing import List, Optional, Set
from tree_sitter import Language, Parser
from tree_sitter_python import language as python_language

# --- Parser Initialization ---
parser = Parser()
parser.language = Language(python_language())


def get_odoo_model_name(body_node, code_bytes: bytes) -> Optional[str]:
    """
    Scans a class body for an assignment to _name or _inherit and returns the string value.
    """
    for child in body_node.children:
        if child.type == "expression_statement":
            assign = child.child(0)
            if assign and assign.type == "assignment":
                left = assign.child_by_field_name("left")
                if (
                    left
                    and left.type == "identifier"
                    and code_bytes[left.start_byte : left.end_byte].decode("utf-8")
                    == "_name"
                ):
                    right = assign.child_by_field_name("right")
                    if right and right.type == "string":
                        # Extract and strip quotes
                        val = code_bytes[right.start_byte : right.end_byte].decode(
                            "utf-8"
                        )
                        return val.strip("'\"")
                elif (
                    left
                    and left.type == "identifier"
                    and code_bytes[left.start_byte : left.end_byte].decode("utf-8")
                    == "_inherit"
                ):
                    right = assign.child_by_field_name("right")
                    if right and right.type == "string":
                        # Extract and strip quotes
                        val = code_bytes[right.start_byte : right.end_byte].decode(
                            "utf-8"
                        )
                        return val.strip("'\"")
    return None


def shrink_python_file(
    path: str, aggressive: bool = False, expand_models: Optional[Set[str]] = None
) -> str:
    """
    Shrinks Python code from a file. If a class matches a model name in 
    expand_models, its full content is preserved.
    """
    code = Path(path).read_text(encoding="utf-8")
    code_bytes = bytes(code, "utf8")
    tree = parser.parse(code_bytes)
    root_node = tree.root_node

    shrunken_parts = []
    expand_models = expand_models or set()

    def process_function(node, indent=""):
        func_def_node = node
        if node.type == "decorated_definition":
            definition = node.child_by_field_name("definition")
            if definition and definition.type == "function_definition":
                func_def_node = definition
            else:
                return

        body_node = func_def_node.child_by_field_name("body")
        if not body_node:
            return

        start_byte = node.start_byte
        end_byte = body_node.start_byte

        header_bytes = code_bytes[start_byte:end_byte]
        header_text = header_bytes.decode("utf8").strip()

        for line in header_text.splitlines():
            stripped_line = line.strip()
            if stripped_line:
                shrunken_parts.append(f"{indent}{stripped_line}")
        if not aggressive:
            shrunken_parts.append(f"{indent}    pass  # shrunk")

    for node in root_node.children:
        if node.type in ("import_statement", "import_from_statement"):
            continue

        if node.type == "class_definition":
            body_node = node.child_by_field_name("body")
            if not body_node:
                continue

            model_name = get_odoo_model_name(body_node, code_bytes)
            should_expand = model_name in expand_models

            if should_expand:
                # Copy the whole class definition including header and body
                class_full_text = code_bytes[node.start_byte : node.end_byte].decode(
                    "utf-8"
                )
                shrunken_parts.append(class_full_text)
            else:
                # Standard shrinking logic
                header_end = body_node.start_byte
                class_header = (
                    code_bytes[node.start_byte : header_end].decode("utf8").strip()
                )
                shrunken_parts.append(class_header)

                for child in body_node.children:
                    if child.type == "expression_statement":
                        expr = child.child(0)
                        if expr and expr.type == "assignment":
                            line_bytes = code_bytes[child.start_byte : child.end_byte]
                            line_text = line_bytes.decode("utf8").strip()
                            shrunken_parts.append(f"    {line_text}")
                    elif (
                        child.type in ("function_definition", "decorated_definition")
                        and not aggressive
                    ):
                        shrunken_parts.append("")
                        process_function(child, indent="    ")
            shrunken_parts.append("")

        elif (
            node.type in ("function_definition", "decorated_definition")
            and not aggressive
        ):
            process_function(node, indent="")
            shrunken_parts.append("")

        elif node.type == "expression_statement":
            expr = node.child(0)
            if expr and expr.type == "assignment":
                line_bytes = code_bytes[node.start_byte : node.end_byte]
                line_text = line_bytes.decode("utf8").strip()
                shrunken_parts.append(line_text)

    while shrunken_parts and shrunken_parts[-1] == "":
        shrunken_parts.pop()

    return "\n".join(shrunken_parts) + "\n"


def main():
    cli_parser = argparse.ArgumentParser(
        description="Shrink a Python file to its structural components."
    )
    cli_parser.add_argument("input_file", type=str)
    cli_parser.add_argument("-S", "--shrink-aggressive", action="store_true")
    cli_parser.add_argument("-E", "--expand", type=str, help="Comma separated models to expand.")
    cli_parser.add_argument("-o", "--output", type=str)
    args = cli_parser.parse_args()

    expand_set = set(args.expand.split(",")) if args.expand else set()

    try:
        shrunken_content = shrink_python_file(
            args.input_file, aggressive=args.shrink_aggressive, expand_models=expand_set
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
