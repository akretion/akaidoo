from typing import Dict, List, Optional, Set, Iterable
from pathlib import Path
import typer
import os
from manifestoo_core.addon import Addon
from manifestoo_core.core_addons import (
    is_core_addon,
    is_core_ce_addon,
    is_core_ee_addon,
)
from manifestoo_core.odoo_series import OdooEdition, OdooSeries
from .utils import get_file_odoo_models

NodeKey = str

def format_size(size_bytes: int) -> str:
    """Formats file size in human readable string."""
    for unit in ['B', 'KB', 'MB']:
        if size_bytes < 1024:
            return f"{size_bytes}{unit}"
        size_bytes //= 1024
    return f"{size_bytes}GB"

class AkaidooNode:
    def __init__(self, addon_name: str, addon: Optional[Addon], files: List[Path]):
        self.addon_name = addon_name
        self.addon = addon
        self.files = sorted(files)
        self.children = []  # type: List[AkaidooNode]

    @staticmethod
    def key(addon_name: str) -> NodeKey:
        return addon_name

    def print_tree(
        self,
        odoo_series: OdooSeries,
        fold_core_addons: bool,
        fold_framework_addons: bool = False,
        framework_addons: Iterable[str] = (),
        pruned_addons: Dict[str, str] = None,
    ) -> None:
        seen: Set[str] = set()
        if pruned_addons is None:
            pruned_addons = {}

        def _print(indent: str, node: AkaidooNode, is_last: bool, is_root: bool) -> None:
            # Choose marker for this module node
            if is_root:
                marker = ""
            else:
                marker = "└── " if is_last else "├── "
            
            # Check pruning status
            pruning_reason = pruned_addons.get(node.addon_name)
            is_pruned = pruning_reason is not None
            
            # 1. Module Header
            if is_pruned:
                typer.secho(f"{indent}{marker}Module: {node.addon_name}", nl=False, dim=True)
            else:
                typer.echo(f"{indent}{marker}Module: {node.addon_name}", nl=False)
            
            if node.addon_name in seen:
                typer.secho(" ⬆", nl=False, dim=True)
                if node.addon:
                    typer.secho(f" [{node.addon.path.resolve()}]", dim=True)
                else:
                    typer.echo("")
                return
            seen.add(node.addon_name)
            
            # Pruning tags
            if is_pruned:
                if pruning_reason == "framework":
                    typer.secho(" [pruned (framework)]", nl=False, dim=True)
                else:
                    typer.secho(" [pruned]", nl=False, dim=True)

            typer.echo("")
            
            # Determine indentation for contents and children of this module
            if is_root:
                content_indent = ""
            else:
                content_indent = indent + ("    " if is_last else "│   ")
            
            # 2. Path Header (Only show path for pruned, or everything? "only its PATH")
            # If pruned, we still show path.
            if node.addon:
                if is_pruned:
                    typer.secho(f"{content_indent}Path: {node.addon.path.resolve()}", dim=True)
                else:
                    typer.echo(f"{content_indent}Path: {node.addon.path.resolve()}")
            else:
                typer.secho(f"{content_indent}Status: ({node.sversion(odoo_series)})", dim=True)

            has_files = len(node.files) > 0 and not is_pruned # Hide files if pruned
            
            # Check for folding
            is_core = is_core_addon(node.addon_name, odoo_series)
            is_framework = node.addon_name in framework_addons
            
            should_fold = (fold_core_addons and is_core) or (fold_framework_addons and is_framework)
            
            # If pruned, we act as if we show children (to show structure), unless folded?
            # Pruning is a form of folding content, but structure remains.
            has_children = len(node.children) > 0 and not should_fold
            
            # 3. Print Files
            if has_files:
                for i, f in enumerate(node.files):
                    # Check if this file is the absolute last item in this branch (module files + module children)
                    is_last_file = (i == len(node.files) - 1) and not has_children
                    file_marker = "└── " if is_last_file else "├── "
                    
                    try:
                        rel_path = f.relative_to(node.addon.path.resolve()) if node.addon else f
                    except Exception:
                        rel_path = f
                    
                    size_str = ""
                    try:
                        size = f.stat().st_size
                        size_str = f" ({format_size(size)})"
                    except Exception:
                        pass
                    
                    model_hint = ""
                    if f.suffix == ".py":
                        models = get_file_odoo_models(f)
                        if models:
                            model_hint = f" [Models: {', '.join(sorted(models))}]"
                    
                    typer.echo(f"{content_indent}{file_marker}{rel_path}{size_str}{model_hint}")

            # 4. Print Children (Dependencies)
            if has_children:
                # Add a vertical connector if there were files before
                if has_files:
                    typer.echo(f"{content_indent}│")
                
                sorted_children = sorted(node.children, key=lambda n: n.addon_name)
                for i, child in enumerate(sorted_children):
                    is_last_child = (i == len(sorted_children) - 1)
                    _print(content_indent, child, is_last_child, False)

        _print("", self, True, True)

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
    fold_framework_addons: bool = False,
    framework_addons: Iterable[str] = (),
    pruned_addons: Dict[str, str] = None,
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
        root_node.print_tree(
            odoo_series,
            fold_core_addons,
            fold_framework_addons=fold_framework_addons,
            framework_addons=framework_addons,
            pruned_addons=pruned_addons,
        )
