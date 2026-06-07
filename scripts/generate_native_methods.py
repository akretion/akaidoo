"""Generate native Odoo methods index by version."""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Set


def _extract_public_methods(tree: ast.AST) -> Set[str]:
    methods: Set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name.startswith("_"):
            continue
        methods.add(node.name)
    return methods


def _python_methods_from_file(path: Path) -> Set[str]:
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
    return _extract_public_methods(tree)


def find_models_file(odoo_root: Path, version: str) -> Path:
    major = int(float(version))
    if major >= 19:
        return odoo_root / "src" / "odoo" / "orm" / "models.py"
    return odoo_root / "src" / "odoo" / "models.py"


def generate_for_version(odoo_root: Path, version: str) -> Set[str]:
    models_file = find_models_file(odoo_root, version)
    return _python_methods_from_file(models_file)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Generate core ORM methods index by Odoo version.")
    parser.add_argument("odoo_root", type=Path, help="Path to the Odoo checkout root (contains odoo/ or odoo/src/odoo)")
    parser.add_argument("output_dir", type=Path, help="Output directory for JSON files")
    parser.add_argument(
        "--versions",
        default="16.0,17.0,18.0,19.0",
        help="Comma-separated Odoo versions",
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    versions = [v.strip() for v in args.versions.split(",") if v.strip()]

    for version in versions:
        methods = generate_for_version(args.odoo_root, version)
        out = args.output_dir / f"{version}.json"
        payload = {
            "version": version,
            "models_file": str(find_models_file(args.odoo_root, version)),
            "method_count": len(methods),
            "methods": sorted(methods),
        }
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {out} ({len(methods)} methods)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
