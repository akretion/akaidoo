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

    def to_string(
        self,
        odoo_series: OdooSeries,
        excluded_addons: Iterable[str] = (),
        pruned_addons: Dict[str, str] = None,
        use_ansi: bool = False,
    ) -> str:
        lines = []
        current_line = []
        seen: Set[str] = set()
        if pruned_addons is None:
            pruned_addons = {}

        excluded_set = set(excluded_addons)

        def _append(text: str, nl: bool = True, dim: bool = False, fg: str = None):
            if use_ansi:
                styled_text = typer.style(text, dim=dim, fg=fg)
            else:
                styled_text = text

            current_line.append(styled_text)
            if nl:
                lines.append("".join(current_line))
                current_line.clear()

        def _traverse(indent: str, node: AkaidooNode, is_last: bool, is_root: bool) -> None:
            # Choose marker for this module node
            if is_root:
                marker = ""
            else:
                marker = "└── " if is_last else "├── "
            
            # Check pruning status
            pruning_reason = pruned_addons.get(node.addon_name)
            is_excluded = node.addon_name in excluded_set
            is_pruned = pruning_reason is not None or is_excluded
            
            # 1. Module Header
            _append(f"{indent}{marker}Module: {node.addon_name}", nl=False, dim=is_pruned)
            
            if node.addon_name in seen:
                _append(" ⬆", nl=True, dim=True)
                return
            seen.add(node.addon_name)
            
            # Pruning/Exclusion tags
            if is_excluded:
                _append(" [pruned (excluded)]", nl=False, dim=True)
            elif is_pruned:
                if pruning_reason == "framework":
                    _append(" [pruned (framework)]", nl=False, dim=True)
                else:
                    _append(" [pruned]", nl=False, dim=True)

            _append("") # New line
            
            # Determine indentation for contents and children of this module
            if is_root:
                content_indent = ""
            else:
                content_indent = indent + ("    " if is_last else "│   ")
            
            # 2. Path Header
            if node.addon and not is_pruned:
                path_to_print = node.addon.path.resolve()
                try:
                    path_to_print = path_to_print.relative_to(Path.cwd())
                except ValueError:
                    pass
                _append(f"{content_indent}Path: {path_to_print}")
            elif not node.addon:
                _append(f"{content_indent}Status: ({node.sversion(odoo_series)})", dim=True)

            has_files = len(node.files) > 0 and not is_pruned # Hide files if pruned
            
            should_fold = is_excluded
            
            # If pruned, we act as if we show children (to show structure), unless folded?
            has_children = len(node.children) > 0 and not should_fold
            
            # 3. Print Files
            if has_files:
                for i, f in enumerate(node.files):
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
                    
                    _append(f"{content_indent}{file_marker}{rel_path}{size_str}{model_hint}")

            # 4. Print Children (Dependencies)
            if has_children:
                if has_files:
                    _append(f"{content_indent}│")
                
                sorted_children = sorted(node.children, key=lambda n: n.addon_name)
                for i, child in enumerate(sorted_children):
                    is_last_child = (i == len(sorted_children) - 1)
                    _traverse(content_indent, child, is_last_child, False)

        _traverse("", self, True, True)
        return "\n".join(lines)

    def print_tree(
        self,
        odoo_series: OdooSeries,
        excluded_addons: Iterable[str] = (),
        pruned_addons: Dict[str, str] = None,
    ) -> None:
        tree_str = self.to_string(
            odoo_series,
            excluded_addons=excluded_addons,
            pruned_addons=pruned_addons,
            use_ansi=True,
        )
        typer.echo(tree_str)

    def sversion(self, odoo_series: OdooSeries) -> str:
        if not self.addon:
            return "✘ not installed"
        elif is_core_ce_addon(self.addon_name, odoo_series):
            return f"{odoo_series.value}+{OdooEdition.CE.value}"
        elif is_core_ee_addon(self.addon_name, odoo_series):
            return f"{odoo_series.value}+{OdooEdition.EE.value}"
        else:
            return self.addon.manifest.version or "no version"

def get_akaidoo_tree_string(
    root_addon_names: Iterable[str],
    addons_set: Dict[str, Addon],
    addon_files_map: Dict[str, List[Path]],
    odoo_series: OdooSeries,
    excluded_addons: Iterable[str] = (),
    pruned_addons: Dict[str, str] = None,
    use_ansi: bool = False,
) -> str:
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

    tree_strings = []
    for name in sorted(root_addon_names):
        if name == "base":
            continue
        root_node = get_node(name)
        tree_strings.append(root_node.to_string(
            odoo_series,
            excluded_addons=excluded_addons,
            pruned_addons=pruned_addons,
            use_ansi=use_ansi,
        ))
    return "\n".join(tree_strings)

def print_akaidoo_tree(
    root_addon_names: Iterable[str],
    addons_set: Dict[str, Addon],
    addon_files_map: Dict[str, List[Path]],
    odoo_series: OdooSeries,
    excluded_addons: Iterable[str] = (),
    pruned_addons: Dict[str, str] = None,
):
    tree_str = get_akaidoo_tree_string(
        root_addon_names,
        addons_set,
        addon_files_map,
        odoo_series,
        excluded_addons=excluded_addons,
        pruned_addons=pruned_addons,
        use_ansi=True,
    )
    typer.echo(tree_str)
