from typing import List, Optional
from pathlib import Path
from fastmcp import FastMCP
from .cli import resolve_akaidoo_context, get_akaidoo_context_dump
from .tree import get_akaidoo_tree_string

# Create an MCP server
mcp = FastMCP("Akaidoo")


@mcp.tool()
def get_context_map(addon: str) -> str:
    """
    Shows the dependency tree and file hints for an addon. ALWAYS call this first to orient yourself.
    It helps you understand module relationships before reading any code.
    """
    context = resolve_akaidoo_context(addon_name=addon)
    tree_str = get_akaidoo_tree_string(
        root_addon_names=context.selected_addon_names,
        addons_set=context.addons_set,
        addon_files_map=context.addon_files_map,
        odoo_series=context.final_odoo_series,
        excluded_addons=context.excluded_addons,
        pruned_addons=context.pruned_addons,
        use_ansi=False,  # Important for machine-readable output
        shrunken_files_info=context.shrunken_files_info,
    )
    return tree_str


@mcp.tool()
def read_source_code(
    addon: str,
    focus_models: Optional[List[str]] = None,
    expand_models: Optional[List[str]] = None,
) -> str:
    """
    Retrieves Odoo source code. Use this AFTER looking at the map.

    STRATEGY GUIDE:
    1. **General Coding/Migration:** If writing a new feature or migrating, just provide `addon`.
       This gives you a broad view of the dependencies.
    2. **Debugging/Tracebacks:** If you have a traceback error on `account.move`, pass `focus_models=['account.move']`.
       This isolates the specific logic causing the crash while shrinking everything else.
    3. **Targeted Expansion:** If you need to see the full definition of a related model,
       pass `expand_models=['the.model.name']` to see its complete source across the dependency tree.
    """
    context = resolve_akaidoo_context(
        addon_name=addon,
        focus_models_str=",".join(focus_models) if focus_models else None,
        add_expand_str=",".join(expand_models) if expand_models else None,
    )
    introduction = f"MCP Dump for {addon}"
    return get_akaidoo_context_dump(context, introduction)


@mcp.tool()
def ping() -> str:
    """Check if the Akaidoo MCP server is running."""
    return "pong"


@mcp.resource("akaidoo://context/summary")
def get_summary() -> str:
    """Get the current Akaidoo session summary as a mission briefing."""
    summary_path = Path(".akaidoo/context/session.md")
    if summary_path.exists():
        return summary_path.read_text()
    else:
        return "# Akaidoo Session\n\nNo active session. Run `akaidoo <addon> --session` to start one."
