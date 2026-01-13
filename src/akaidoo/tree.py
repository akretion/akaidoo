from typing import Dict, List, Optional, Set, Iterable
from pathlib import Path
import typer
from manifestoo_core.addon import Addon
from manifestoo_core.core_addons import (
    is_core_addon,
    is_core_ce_addon,
    is_core_ee_addon,
)
from manifestoo_core.odoo_series import OdooEdition, OdooSeries
from manifestoo import echo

NodeKey = str

class AkaidooNode:
    def __init__(self, addon_name: str, addon: Optional[Addon], files: List[Path]):
        self.addon_name = addon_name
        self.addon = addon
        self.files = sorted(files)
        self.children = []  # type: List[AkaidooNode]

    @staticmethod
    def key(addon_name: str) -> NodeKey:
        return addon_name

    def print_tree(self, odoo_series: OdooSeries, fold_core_addons: bool) -> None:
        seen: Set[str] = set()

        def _print(indent: List[str], node: AkaidooNode, is_last: bool = False) -> None:
            SPACE = "    "
            BRANCH = "│   "
            TEE = "├── "
            LAST = "└── "
            
            # Print Addon Node
            prefix = "".join(indent)
            typer.echo(f"{prefix}{node.addon_name}", nl=False)
            
            if node.addon_name in seen:
                typer.secho(" ⬆", dim=True)
                return
            
            seen.add(node.addon_name)
            
            # Show path or version info
            if node.addon:
                path_info = f" [{node.addon.path.resolve()}]"
                typer.secho(path_info, dim=True)
            else:
                typer.secho(f" ({node.sversion(odoo_series)})", dim=True)

            # Prepare for children/files
            # We want to list files first, then children
            
            has_files = len(node.files) > 0
            has_children = len(node.children) > 0 and not (fold_core_addons and is_core_addon(node.addon_name, odoo_series))
            
            # Calculate indent for contents
            if not indent:
                new_indent_base = []
            else:
                # If we are the last child, our children are indented with SPACE
                # Otherwise with BRANCH
                new_indent_base = indent[:-1] + [(SPACE if is_last else BRANCH)]

            # Print Files
            if has_files:
                file_pointers = [TEE] * (len(node.files) - 1)
                if has_children:
                    file_pointers.append(TEE)
                else:
                    file_pointers.append(LAST)
                
                addon_path = node.addon.path.resolve() if node.addon else None
                for pointer, f in zip(file_pointers, node.files):
                    try:
                        rel_path = f.relative_to(addon_path) if addon_path else f
                    except ValueError:
                        rel_path = f
                    typer.echo(f"{''.join(new_indent_base)}{pointer}{rel_path}")

            # Print Children
            if has_children:
                sorted_children = sorted(node.children, key=lambda n: n.addon_name)
                child_pointers = [TEE] * (len(sorted_children) - 1) + [LAST]
                for pointer, child in zip(child_pointers, sorted_children):
                    _print(new_indent_base + [pointer], child, pointer == LAST)

        _print([], self, True)

    def sversion(self, odoo_series: OdooSeries) -> str:
        if not self.addon:
            return typer.style("✘ not installed", fg=typer.colors.RED)
        elif is_core_ce_addon(self.addon_name, odoo_series):
            return f"{odoo_series.value}+{OdooEdition.CE.value}"
        elif is_core_ee_addon(self.addon_name, odoo_series):
            return f"{odoo_series.value}+{OdooEdition.EE.value}"
        else:
            return self.addon.manifest.version or "no version"

def print_akaidoo_tree(
    root_addon_names: Iterable[str],
    addons_set: Dict[str, Addon],
    addon_files_map: Dict[str, List[Path]],
    odoo_series: OdooSeries,
    fold_core_addons: bool,
):
    nodes: Dict[NodeKey, AkaidooNode] = {}

    def get_node(addon_name: str) -> AkaidooNode:
        if addon_name in nodes:
            return nodes[addon_name]
        
        addon = addons_set.get(addon_name)
        files = addon_files_map.get(addon_name, [])
        node = AkaidooNode(addon_name, addon, files)
        nodes[addon_name] = node
        
        if addon:
            for depend in addon.manifest.depends:
                if depend == "base":
                    continue
                node.children.append(get_node(depend))
        return node

    for name in sorted(root_addon_names):
        if name == "base":
            continue
        root_node = get_node(name)
        root_node.print_tree(odoo_series, fold_core_addons)
