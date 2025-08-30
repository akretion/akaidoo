import argparse
import sys
from pathlib import Path
from tree_sitter import Language, Parser
from tree_sitter_python import language as python_language

# --- Parser Initialization ---
# Initialize the parser with the Python language
parser = Parser()
parser.language = Language(python_language())


def shrink_python_file(path: str, aggressive: bool = False) -> str:
    """
    Shrinks Python code from a file to keep only class/function definitions
    (with decorators), class attributes, and field assignments.
    """
    # The parser works on bytes. All slicing must be done on the
    # byte array and then decoded. Using byte indices on the original string
    # will fail if there are multi-byte UTF-8 characters in the file.
    code = Path(path).read_text(encoding="utf-8")
    code_bytes = bytes(code, "utf8")
    tree = parser.parse(code_bytes)
    root_node = tree.root_node

    shrunken_parts = []

    def process_function(node, indent=""):
        """
        Correctly extracts the full header of a function (including decorators)
        and replaces its body with 'pass'.
        """
        func_def_node = node
        if node.type == "decorated_definition":
            definition = node.child_by_field_name("definition")
            if definition and definition.type == "function_definition":
                func_def_node = definition
            else:
                return  # This is a decorated class, not a function we should process.

        body_node = func_def_node.child_by_field_name("body")
        if not body_node:
            return  # No body found, skip.

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

    # --- Main Processing Loop ---
    for node in root_node.children:
        if node.type in ("import_statement", "import_from_statement"):
            continue

        if node.type == "class_definition":
            body_node = node.child_by_field_name("body")
            if not body_node:
                continue

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

    # Clean up any trailing newlines before joining
    while shrunken_parts and shrunken_parts[-1] == "":
        shrunken_parts.pop()

    return "\n".join(shrunken_parts) + "\n"


# --- Command-Line Entry Point ---
def main():
    """
    Main function to handle command-line arguments for the shrinker tool.
    """
    cli_parser = argparse.ArgumentParser(
        description="Shrink a Python file to its structural components (classes, methods, fields)."
    )
    cli_parser.add_argument(
        "input_file", type=str, help="The path to the Python file you want to shrink."
    )
    cli_parser.add_argument(
        "-S",
        "--shrink-aggressive",
        action="store_true",
        help="Enable aggressive shrinking, removing method bodies entirely.",
    )
    cli_parser.add_argument(
        "-o",
        "--output",
        type=str,
        help="Optional: The path to save the shrunken file. If not provided, prints to console.",
    )
    args = cli_parser.parse_args()

    try:
        shrunken_content = shrink_python_file(
            args.input_file, aggressive=args.shrink_aggressive
        )

        if args.output:
            # Write to the specified output file
            output_path = Path(args.output)
            output_path.write_text(shrunken_content, encoding="utf-8")
            print(
                f"Successfully shrunk '{args.input_file}' and saved to '{args.output}'"
            )
        else:
            # Print directly to standard output (the console)
            sys.stdout.write(shrunken_content)

    except FileNotFoundError:
        print(f"Error: The file '{args.input_file}' was not found.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
