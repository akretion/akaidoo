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
def read_module_source(
    addon: str,
    shrink_mode: str = "soft",
    expand_models: Optional[List[str]] = None,
    add_expand_models: Optional[List[str]] = None,
    context_budget_tokens: Optional[int] = None,
) -> str:
    """
    Retrieves Odoo addon source code with intelligent context optimization.

    QUICK START: Just provide the `addon` name - akaidoo handles the rest with smart defaults.

    OPTIONS:
    - `shrink_mode`: Controls code compression (default: "soft")
      - "none": Full code, no shrinking
      - "soft": Shrink dependencies only (recommended for most tasks)
      - "medium": More aggressive shrinking
      - "hard": Very aggressive shrinking
      - "max": Maximum compression, structure only

    - `expand_models`: EXPLICIT mode - ONLY expand these models (disables auto-expand)
      Use for debugging specific models, e.g., ["account.move"] for a traceback

    - `add_expand_models`: ADDITIVE mode - Add models to the auto-expand set
      Use when you need more detail on related models, e.g., ["stock.picking"]

    - `context_budget_tokens`: Target context size (e.g., 100000)
      Akaidoo auto-escalates shrink modes to fit within budget

    STRATEGY GUIDE:
    1. **General exploration**: Just provide addon name with defaults
    2. **Debugging traceback**: Use expand_models=["the.failing.model"]
    3. **Need more context on a model**: Use add_expand_models=["related.model"]
    4. **Context too large**: Use context_budget_tokens or increase shrink_mode
    """
    # Convert token budget to character budget
    budget_chars = None
    if context_budget_tokens is not None:
        budget_chars = int(context_budget_tokens / TOKEN_FACTOR)

    context = _service.resolve_context(
        addon,
        shrink_mode=shrink_mode,
        expand_models_str=",".join(expand_models) if expand_models else None,
        add_expand_str=",".join(add_expand_models) if add_expand_models else None,
        context_budget=budget_chars,
    )
    introduction = f"MCP Dump for {addon}"
    return _service.get_context_dump(context, introduction)


@mcp.tool()
def get_context_map(addon: str) -> str:
    """
    Optional: Shows the dependency tree for an addon.

    Call this if you need to understand module relationships before reading code.
    For most tasks, you can skip this and go directly to `read_module_source`.

    Returns a tree visualization showing:
    - Direct and transitive dependencies
    - File counts per addon
    - Which files are shrunk vs expanded
    """
    context = _service.resolve_context(addon)
    return _service.get_tree_string(context, use_ansi=False)


@mcp.tool()
def get_context_summary(addon: str) -> dict:
    """
    Get metrics about addon context without the full source dump.

    Use this to plan your context window before calling read_module_source.

    Returns:
        - addon_names: Target addons
        - odoo_series: Detected Odoo version
        - total_files: Number of files in context
        - total_tokens: Estimated token count
        - expand_models: Models that will be fully expanded
        - effective_shrink_mode: Applied shrink level
        - And more...
    """
    context = _service.resolve_context(addon)
    return _service.get_context_summary(context)


@mcp.tool()
def ping() -> str:
    """Check if the Akaidoo MCP server is running."""
    return "pong"


@mcp.resource("akaidoo://context/summary")
def get_summary() -> str:
    """
    Get the current Akaidoo session summary.

    Reads `.akaidoo/context/session.md` which is created by running:
    `akaidoo <addon> --session`

    This provides a mission briefing for the current development session.
    """
    summary_path = Path(".akaidoo/context/session.md")
    if summary_path.exists():
        return summary_path.read_text()
    else:
        return "# Akaidoo Session\n\nNo active session. Run `akaidoo <addon> --session` to start one."
