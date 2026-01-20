"""
Akaidoo MCP Server

Provides MCP (Model Context Protocol) tools for AI agents to query Odoo codebases.
Uses AkaidooService for all operations.
"""

from typing import List, Optional
from pathlib import Path
from fastmcp import FastMCP

from .service import get_service
from .config import TOKEN_FACTOR

# Create an MCP server
mcp = FastMCP("Akaidoo")

# Get the service instance
_service = get_service()


@mcp.tool()
def get_context_map(addon: str) -> str:
    """
    Shows the dependency tree and file hints for an addon. ALWAYS call this first to orient yourself.
    It helps you understand module relationships before reading any code.
    """
    context = _service.resolve_context(addon)
    return _service.get_tree_string(context, use_ansi=False)


@mcp.tool()
def read_source_code(
    addon: str,
    focus_models: Optional[List[str]] = None,
    expand_models: Optional[List[str]] = None,
    context_budget_tokens: Optional[int] = None,
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
    4. **Budget Control:** Pass `context_budget_tokens` (e.g., 100000) to limit context size.
       Akaidoo will auto-escalate shrink modes to fit within the budget.
    """
    # Convert token budget to character budget
    budget_chars = None
    if context_budget_tokens is not None:
        budget_chars = int(context_budget_tokens / TOKEN_FACTOR)

    context = _service.resolve_context(
        addon,
        focus_models_str=",".join(focus_models) if focus_models else None,
        add_expand_str=",".join(expand_models) if expand_models else None,
        context_budget=budget_chars,
    )
    introduction = f"MCP Dump for {addon}"
    return _service.get_context_dump(context, introduction)


@mcp.tool()
def get_context_summary(addon: str) -> dict:
    """
    Get a summary of the context for an addon without the full dump.

    Returns key metrics about the context including token estimates,
    expanded models, and pruned addons.
    """
    context = _service.resolve_context(addon)
    return _service.get_context_summary(context)


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
