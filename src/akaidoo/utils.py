from typing import Optional, Set, Dict, Any
from pathlib import Path
from tree_sitter import Language, Parser
from tree_sitter_python import language as python_language

# --- Parser Initialization ---
parser = Parser()
parser.language = Language(python_language())

AUTO_EXPAND_THRESHOLD = 7

def get_odoo_model_stats(code: str) -> Dict[str, Dict[str, int]]:
    """
    Scans Python code for Odoo models (_name or _inherit) and returns 
    a dictionary of model stats: {model_name: {'fields': count, 'methods': count, 'score': int}}.
    Score calculation: fields=1 point, methods=3 points, 10 lines=2 points.
    """
    code_bytes = bytes(code, "utf8")
    tree = parser.parse(code_bytes)
    root_node = tree.root_node
    
    stats = {}
    
    def scan_node(node):
        if node.type == "class_definition":
            body = node.child_by_field_name("body")
            if body:
                model_name = _get_odoo_model_name_from_body(body, code_bytes)
                if model_name:
                    model_info = stats.get(model_name, {'fields': 0, 'methods': 0, 'score': 0})
                    
                    fields_count = 0
                    methods_count = 0
                    
                    for child in body.children:
                        if child.type == "expression_statement":
                            assign = child.child(0)
                            if assign and assign.type == "assignment":
                                left = assign.child_by_field_name("left")
                                # Simple check for field-like assignments (not starting with _)
                                if left and left.type == "identifier":
                                    name = code_bytes[left.start_byte : left.end_byte].decode("utf-8")
                                    if not name.startswith("_"):
                                        fields_count += 1
                        elif child.type in ("function_definition", "decorated_definition"):
                            methods_count += 1
                    
                    # Calculate lines of code in the class body
                    start_line = node.start_point[0]
                    end_line = node.end_point[0]
                    lines_count = max(0, end_line - start_line + 1)
                    
                    # Calculate score: fields=1, methods=3, 10 lines=2
                    score = fields_count * 1 + methods_count * 3 + (lines_count // 10) * 2
                            
                    model_info['fields'] += fields_count
                    model_info['methods'] += methods_count
                    model_info['score'] += score
                    stats[model_name] = model_info
                    
        for child in node.children:
            scan_node(child)
            
    scan_node(root_node)
    return stats

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
                        # Handle list of inherits
                        return val.strip("'\"") 
    return None

def get_file_odoo_models(path: Path) -> Set[str]:
    """Read file and extract Odoo model names (Legacy helper for tree output)."""
    try:
        content = path.read_text(encoding="utf-8")
        stats = get_odoo_model_stats(content)
        return set(stats.keys())
    except Exception:
        return set()
