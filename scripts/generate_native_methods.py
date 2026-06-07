"""Generate native Odoo methods index by version."""

import ast
import json
from pathlib import Path
from typing import Dict, List, Set


def _extract_methods_from_ast(tree: ast.AST) -> Set[str]:
    """Extract public method names from an AST module.

    Includes top-level functions and class methods.
    """
    methods: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            methods.add(node.name)
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and not item.name.startswith("_"):
                    methods.add(item.name)
    return methods


def _python_methods_from_file(path: Path) -> Set[str]:
    """Extract public method names from a Python file using AST."""
    if not path.exists():
        return set()
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()
    return _extract_methods_from_ast(tree)


def scan_models_py(odoo_root: Path, addon: str) -> Set[str]:
    """Extract methods from addon/models/*.py."""
    base = odoo_root / "addons" / addon / "models"
    if not base.is_dir():
        return set()
    methods: Set[str] = set()
    for py in base.rglob("*.py"):
        methods |= _python_methods_from_file(py)
    return methods


def generate_for_version(odoo_root: Path, version: str, addons: List[str]) -> Set[str]:
    """Generate native methods set for an Odoo version."""
    methods: Set[str] = set()
    for addon in addons:
        methods |= scan_models_py(odoo_root, addon)
    return methods


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Generate native Odoo methods index.")
    parser.add_argument("odoo_root", type=Path, help="Path to Odoo source root")
    parser.add_argument("output_dir", type=Path, help="Output directory for JSON files")
    parser.add_argument(
        "--versions",
        default="16.0,17.0,18.0,19.0",
        help="Comma-separated Odoo versions",
    )
    parser.add_argument(
        "--addons",
        default="base,mail,sale,account,purchase,stock,project",
        help="Comma-separated addons to scan",
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    versions = [v.strip() for v in args.versions.split(",")]
    addons = [a.strip() for a in args.addons.split(",")]

    for version in versions:
        methods = generate_for_version(args.odoo_root, version, addons)
        out = args.output_dir / f"{version}.json"
        payload = {
            "version": version,
            "addons": addons,
            "methods": sorted(methods),
        }
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {out} ({len(methods)} methods)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
