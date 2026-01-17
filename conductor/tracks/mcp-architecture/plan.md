# Track: MCP Server Architecture

## Context
Transition akaidoo from a pure CLI tool to a persistent Model Context Protocol (MCP) server. This allows AI agents (Cursor, Claude, Gemini CLI) to query Odoo context dynamically without generating massive intermediate files.

## Goals
1. Implement `akaidoo serve` command using the python `mcp` SDK.
2. Expose "The Map" (Tree) and "The Territory" (Source) as callable Tools.
3. Manage the `.akaidoo` directory state.

## Tasks

- [x] **Scaffold MCP Server**
    - [x] Add `mcp` dependency.
    - [x] Create `src/akaidoo/server.py`.
    - [x] Implement `akaidoo serve` entrypoint in `cli.py`.

- [x] **Tool: `get_odoo_structure` (The Map)**
    - [x] **Input:** `addon_name` (str), `recursive` (bool).
    - [x] **Logic:** Adapt `tree.py` logic to return a string representation of the dependency tree.
    - [x] **Output:** The textual tree (optimized as per analysis).

- [x] **Tool: `read_odoo_context` (The Dump)**
    - [x] **Input:** `addon_name` (str), `focus_files` (optional list[str]), `expand_models` (optional list[str]).
    - [x] **Logic:** Adapt `scan_addon_files` and `process_and_output_files`.
    - [x] **Feature:** Instead of printing to stdout, return the concatenated string directly.
    - [x] **Feature:** Support "Partial Dump" (e.g., "Give me only `models/sale_order.py` from `sale`").

- [x] **Resource: `.akaidoo/context/summary.md`**
    - [x] Create a persistent resource that summarizes the current project (Odoo version, root addons, active configuration).
    - [x] Allow the Agent to subscribe to this to know "where it is".

- [ ] **Maintenance: Synchronize with CLI API**
    - [ ] Update `resolve_akaidoo_context` calls in `server.py` to match new signature (two-pass, new args).
    - [ ] Update `tree.py` usage (imports, `print_akaidoo_tree` vs string return).
    - [ ] Implement `read_odoo_context` strategies (Sniper vs Shotgun) by exposing `focus_models`, `shrink_mode` correctly.

## Reference
- Existing `cli.py` logic for dependency traversal.
- `print_akaidoo_tree` in `tree.py` needs to return string instead of printing.