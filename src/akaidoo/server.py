from typing import List, Optional
from pathlib import Path
import os
from fastmcp import FastMCP
from .cli import resolve_akaidoo_context, get_akaidoo_context_dump, FRAMEWORK_ADDONS
from .tree import get_akaidoo_tree_string
import json

# Create an MCP server
mcp = FastMCP("Akaidoo")

@mcp.tool()
def get_odoo_structure(addon_name: str, recursive: bool = True) -> str:
    """
    Get the Odoo structure (dependency tree) for a given addon.
    Shows module relationships and file hints (models defined in files).
    """
    # Use default settings for resolving context for structure
    context = resolve_akaidoo_context(
        addon_name=addon_name,
        prune=True,
    )
    
    tree_str = get_akaidoo_tree_string(
        root_addon_names=context.selected_addon_names,
        addons_set=context.addons_set,
        addon_files_map=context.addon_files_map,
        odoo_series=context.final_odoo_series,
        exclude_core=context.exclude_core,
        fold_framework_addons=context.exclude_framework,
        framework_addons=FRAMEWORK_ADDONS,
        pruned_addons=context.pruned_addons,
    )
    return tree_str

@mcp.tool()
def read_odoo_context(
    addon_name: str, 
    focus_files: Optional[List[str]] = None, 
    expand_models: Optional[List[str]] = None
) -> str:
    """
    Dump the Odoo context (source code) for a given addon.
    Optionally focus on specific files or expand specific models.
    """
    expand_models_str = ",".join(expand_models) if expand_models else None
    
    context = resolve_akaidoo_context(
        addon_name=addon_name,
        expand_models_str=expand_models_str,
        shrink=True, # Always shrink in MCP dump by default to save tokens
        prune=True,
    )
    
    introduction = f"MCP Dump for {addon_name}"
    
    dump_str = get_akaidoo_context_dump(
        context=context,
        introduction=introduction,
        focus_files=focus_files,
    )
    return dump_str

@mcp.tool()
def ping() -> str:
    """Check if the Akaidoo MCP server is running."""
    return "pong"


@mcp.resource("akaidoo://context/summary")
def get_summary() -> str:
    """Get the current Akaidoo session summary."""
    summary_path = Path(".akaidoo/context/summary.json")
    summary_md = "# Akaidoo Session Summary\n\n"
    
    if summary_path.exists():
        try:
            data = json.loads(summary_path.read_text())
            addons = ", ".join(data.get("addons", []))
            focus = ", ".join(data.get("focus_models", []) or []) or "None"
            summary_md += f"- **Active Addons**: {addons}\n"
            summary_md += f"- **Focused Models**: {focus}\n"
        except Exception as e:
            summary_md += f"Error reading summary.json: {e}\n"
    else:
        summary_md += "No active session. Run `akaidoo init` to start one.\n"

    # Add environment info
    summary_md += "\n## Environment\n"
    summary_md += f"- **CWD**: {Path.cwd()}\n"
    if "ODOO_RC" in os.environ:
        summary_md += f"- **ODOO_RC**: {os.environ['ODOO_RC']}\n"
    
    return summary_md
