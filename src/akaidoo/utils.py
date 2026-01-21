import datetime
from typing import Set, Dict
from pathlib import Path
from tree_sitter import Language, Parser
from tree_sitter_python import language as python_language

# --- Parser Initialization ---
parser = Parser()
parser.language = Language(python_language())


def _get_odoo_model_names_from_body(body_node, code_bytes: bytes) -> Dict[str, str]:
    """
    Scans a class body for _name and _inherit to determine model names and their type.
    Returns a dict {model_name: 'Base'|'Ext'}.
    """
    name = None
    inherits = []

    for child in body_node.children:
        if child.type == "expression_statement":
            assign = child.child(0)
            if assign and assign.type == "assignment":
                left = assign.child_by_field_name("left")
                if left and left.type == "identifier":
                    var_name = code_bytes[left.start_byte : left.end_byte].decode(
                        "utf-8"
                    )
                    right = assign.child_by_field_name("right")
                    if not right:
                        continue

                    if var_name == "_name":
                        if right.type == "string":
                            val = code_bytes[right.start_byte : right.end_byte].decode(
                                "utf-8"
                            )
                            name = val.strip("'\"")
                    elif var_name == "_inherit":
                        if right.type == "string":
                            val = code_bytes[right.start_byte : right.end_byte].decode(
                                "utf-8"
                            )
                            inherits.append(val.strip("'\""))
                        elif right.type == "list":
                            for element in right.children:
                                if element.type == "string":
                                    val = code_bytes[
                                        element.start_byte : element.end_byte
                                    ].decode("utf-8")
                                    inherits.append(val.strip("'\""))

    models = {}
    if name:
        # If _name is present, it's Base unless it's also in _inherit (extension pattern)
        if name in inherits:
            models[name] = "Ext"
        else:
            models[name] = "Base"
    elif inherits:
        # No _name, only _inherit: it's an extension of all inherited models
        for i in inherits:
            models[i] = "Ext"

    return models


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
                model_map = _get_odoo_model_names_from_body(body, code_bytes)
                if model_map:
                    model_names = set(model_map.keys())
                    fields_count = 0
                    methods_count = 0

                    for child in body.children:
                        if child.type == "expression_statement":
                            assign = child.child(0)
                            if assign and assign.type == "assignment":
                                left = assign.child_by_field_name("left")
                                # Simple check for field-like assignments (not starting with _)
                                if left and left.type == "identifier":
                                    name = code_bytes[
                                        left.start_byte : left.end_byte
                                    ].decode("utf-8")
                                    if not name.startswith("_"):
                                        fields_count += 1
                        elif child.type in (
                            "function_definition",
                            "decorated_definition",
                        ):
                            methods_count += 1

                    # Calculate lines of code in the class body
                    start_line = node.start_point[0]
                    end_line = node.end_point[0]
                    lines_count = max(0, end_line - start_line + 1)

                    # Calculate score: fields=1, methods=3, 10 lines=2
                    score = (
                        fields_count * 1 + methods_count * 3 + (lines_count // 10) * 2
                    )

                    for model_name in model_names:
                        model_info = stats.get(
                            model_name, {"fields": 0, "methods": 0, "score": 0}
                        )
                        model_info["fields"] += fields_count
                        model_info["methods"] += methods_count
                        model_info["score"] += score
                        stats[model_name] = model_info

        for child in node.children:
            scan_node(child)

    scan_node(root_node)
    return stats


def get_model_relations(code: str) -> Dict[str, Dict[str, Set[str]]]:
    """
    Scans Python code and returns a dictionary mapping model names defined/extended in the code
    to their relations: {'parents': set(), 'comodels': set()}.
    """
    code_bytes = bytes(code, "utf8")
    tree = parser.parse(code_bytes)
    root_node = tree.root_node

    relations: Dict[str, Dict[str, Set[str]]] = {}

    def scan_node(node):
        if node.type == "class_definition":
            body = node.child_by_field_name("body")
            if body:
                # 1. Identify the model(s) being defined/extended
                current_models = set()
                parents = set()

                # Scan for _name, _inherit, _inherits
                for child in body.children:
                    if child.type == "expression_statement":
                        assign = child.child(0)
                        if assign and assign.type == "assignment":
                            left = assign.child_by_field_name("left")
                            right = assign.child_by_field_name("right")

                            if left and left.type == "identifier":
                                var_name = code_bytes[
                                    left.start_byte : left.end_byte
                                ].decode("utf-8")

                                if var_name == "_name":
                                    if right.type == "string":
                                        val = code_bytes[
                                            right.start_byte : right.end_byte
                                        ].decode("utf-8")
                                        current_models.add(val.strip("'\""))

                                elif var_name == "_inherit":
                                    if right.type == "string":
                                        val = code_bytes[
                                            right.start_byte : right.end_byte
                                        ].decode("utf-8")
                                        parents.add(val.strip("'\""))
                                    elif right.type == "list":
                                        for element in right.children:
                                            if element.type == "string":
                                                val = code_bytes[
                                                    element.start_byte : element.end_byte
                                                ].decode("utf-8")
                                                parents.add(val.strip("'\""))

                                elif var_name == "_inherits":
                                    # _inherits = {'a.model': 'field_id'}
                                    if right.type == "dictionary":
                                        for pair in right.children:
                                            if pair.type == "pair":
                                                key = pair.child_by_field_name("key")
                                                if key and key.type == "string":
                                                    val = code_bytes[
                                                        key.start_byte : key.end_byte
                                                    ].decode("utf-8")
                                                    parents.add(val.strip("'\""))

                # If _name is present, that's the primary model.
                # If only _inherit is present, we are extending those models.
                target_models = current_models if current_models else parents
                if not target_models:
                    # Not an Odoo model class or weird structure
                    return

                # Initialize relations for these models
                for m in target_models:
                    if m not in relations:
                        relations[m] = {"parents": set(), "comodels": set()}
                    # A model should not be its own parent in this context
                    relations[m]["parents"].update(p for p in parents if p != m)

                # 2. Scan for fields to find comodels
                for child in body.children:
                    if child.type == "expression_statement":
                        assign = child.child(0)
                        if assign and assign.type == "assignment":
                            right = assign.child_by_field_name("right")

                            if right and right.type == "call":
                                func = right.child_by_field_name("function")
                                if func and func.type == "attribute":
                                    obj = func.child_by_field_name("object")
                                    attr = func.child_by_field_name("attribute")

                                    if (
                                        obj
                                        and obj.type == "identifier"
                                        and attr
                                        and attr.type == "identifier"
                                    ):
                                        obj_name = code_bytes[
                                            obj.start_byte : obj.end_byte
                                        ].decode("utf-8")
                                        attr_name = code_bytes[
                                            attr.start_byte : attr.end_byte
                                        ].decode("utf-8")

                                        if obj_name in (
                                            "fields",
                                            "models",
                                        ) and attr_name in (
                                            "Many2one",
                                            "One2many",
                                            "Many2many",
                                        ):
                                            # Extract first argument
                                            args = right.child_by_field_name(
                                                "arguments"
                                            )
                                            if args:
                                                for arg in args.children:
                                                    if arg.type == "string":
                                                        val = code_bytes[
                                                            arg.start_byte : arg.end_byte
                                                        ].decode("utf-8")
                                                        comodel = val.strip("'\"")
                                                        for m in target_models:
                                                            relations[m][
                                                                "comodels"
                                                            ].add(comodel)
                                                        break
                                                    elif arg.type in (
                                                        "identifier",
                                                        "attribute",
                                                        "call",
                                                        "integer",
                                                        "float",
                                                    ):
                                                        # First arg might not be a string (e.g. variable or number), skip
                                                        break

        for child in node.children:
            scan_node(child)

    scan_node(root_node)
    return relations


def get_file_odoo_models(path: Path) -> Set[str]:
    """Read file and extract Odoo model names (Legacy helper for tree output)."""
    try:
        content = path.read_text(encoding="utf-8")
        stats = get_odoo_model_stats(content)
        return set(stats.keys())
    except Exception:
        return set()


def get_timestamp() -> str:
    """Returns a UTC timestamp string."""
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
