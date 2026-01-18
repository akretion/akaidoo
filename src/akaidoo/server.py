from typing import List, Optional
from pathlib import Path
from fastmcp import FastMCP
from .cli import (
    resolve_akaidoo_context,
    get_akaidoo_context_dump,
    _build_rlm_payload,
    RLM_WORKER_PROMPT,
)
from .tree import get_akaidoo_tree_string
import os

try:
    from rlm import RLM
except ImportError:
    RLM = None  # Handle optional dependency gracefully if needed, or fail later

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
def ask_codebase(addon: str, question: str) -> str:
    """
    An AI Research Assistant with the entire '{addon}' module loaded in RAM.

    **GUIDELINES FOR THE SUPERVISOR:**
    1. **DO NOT** provide code snippets in the `question`. I already have them.
    2. **DO** ask for specific logic traces (e.g., "Find where `action_confirm` is called in `sale.order`").
    3. **DO** ask for architectural validation (e.g., "Check if `_compute_tax` depends on `amount_total`").

    **HOW IT WORKS:**
    I use a "Skeleton-First" search strategy to navigate millions of tokens of code efficiently using a REPL.
    """
    if RLM is None:
        return "Error: 'rlm' package is not installed. Install with 'pip install akaidoo[mcp]'."

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "Error: GEMINI_API_KEY not found in environment."

    try:
        rlm = RLM(
            backend="gemini",
            backend_kwargs={"model_name": "gemini-2.5-flash", "api_key": api_key},
            environment="local",  # Runs in the MCP process
            verbose=True,  # Helpful for debugging logs
            custom_system_prompt=RLM_WORKER_PROMPT,
        )
    except Exception as e:
        return f"Error initializing RLM: {e}"

    try:
        try:
            payload = _build_rlm_payload(addon)
        except (ValueError, SystemExit):
            return f"Error: Addon '{addon}' not found in path. Please check the name."

        result = rlm.completion(
            prompt=payload,
            root_prompt=f"Investigate this query for module '{addon}': {question}",
        )

        return result.response
    except Exception as e:
        return f"Error executing RLM agent: {e}"


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
