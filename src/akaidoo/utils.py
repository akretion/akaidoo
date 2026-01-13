from typing import Optional, Set
from pathlib import Path
from tree_sitter import Language, Parser
from tree_sitter_python import language as python_language

# --- Parser Initialization ---
parser = Parser()
parser.language = Language(python_language())

def get_odoo_model_names(code: str) -> Set[str]:
    """
    Scans Python code for Odoo models (_name or _inherit) and returns the set of names.
    """
    code_bytes = bytes(code, "utf8")
    tree = parser.parse(code_bytes)
    root_node = tree.root_node
    
    models = set()
    
    def scan_node(node):
        if node.type == "class_definition":
            body = node.child_by_field_name("body")
            if body:
                model_name = _get_odoo_model_name_from_body(body, code_bytes)
                if model_name:
                    models.add(model_name)
        for child in node.children:
            scan_node(child)
            
    scan_node(root_node)
    return models

def _get_odoo_model_name_from_body(body_node, code_bytes: bytes) -> Optional[str]:
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
                        val = code_bytes[right.start_byte : right.end_byte].decode("utf-8")
                        return val.strip("'\"")
                elif (
                    left
                    and left.type == "identifier"
                    and code_bytes[left.start_byte : left.end_byte].decode("utf-8")
                    == "_inherit"
                ):
                    right = assign.child_by_field_name("right")
                    if right and right.type == "string":
                        val = code_bytes[right.start_byte : right.end_byte].decode("utf-8")
                        return val.strip("'\"")
    return None

def get_file_odoo_models(path: Path) -> Set[str]:
    """Read file and extract Odoo model names."""
    try:
        content = path.read_text(encoding="utf-8")
        return get_odoo_model_names(content)
    except Exception:
        return set()
