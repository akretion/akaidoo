"""
Native Odoo methods index loader.

Loads generated JSON indexes and provides lookup helpers.
"""

import json
from pathlib import Path
from typing import Dict, Set

INDEX_DIR = Path(__file__).resolve().parent.parent / "data" / "native_methods"

_cache: Dict[str, Set[str]] = {}


def _load(version: str) -> Set[str]:
    path = INDEX_DIR / f"{version}.json"
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    return set(data.get("methods", []))


def get_native_methods(odoo_version: str) -> Set[str]:
    if odoo_version not in _cache:
        _cache[odoo_version] = _load(odoo_version)
    return set(_cache[odoo_version])


def is_native_method(odoo_version: str, method_key: str) -> bool:
    return method_key in get_native_methods(odoo_version)
