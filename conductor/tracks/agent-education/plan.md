# Track: Agent Education & Prompts

## Context

The Agent has the tools (Akaidoo MCP), but needs the "Software" (Instructions) to use
them efficiently. We need to teach it "When to Map" and "When to Zoom."

## Goals

1. Write "Scenario-Based" docstrings for MCP tools.
2. Create the `agent_workflow.md` rule file.
3. Update existing Gemini Skills to leverage Akaidoo.

## Tasks

- [ ] **Enhance Server Docstrings (`server.py`)**

  - [ ] **`get_odoo_structure`:** Emphasize "Call this first" to orient.
  - [ ] **`read_source_code`:** Explain the difference between default shrink (overview)
        and `focus_models` (debugging/sniper mode). Add specific strategy guide (General
        vs Debugging vs Migration).

- [ ] **Create Doctrine Resource**

  - [ ] **File:** `.akaidoo/rules/agent_workflow.md`
  - [ ] **Content:** Define protocols:
    1. **"Map First" Protocol:** Always call `get_context_map` first.
    2. **"Sniper" Protocol:** Use `focus_models` for tracebacks.
    3. **"Broad Search" Protocol:** Use standard dump for migration/refactoring.
    4. **Pruned Modules:** Do not read unless explicitly adding dependencies.
  - [ ] **Mechanism:** Ensure MCP server exposes this file as a Resource
        (`akaidoo://rules/workflow`).

- [ ] **Update Odoo Skills**
  - [ ] **`odoo-migration`:** Add section on "Using Akaidoo for Debugging".
  - [ ] **`odoo-extensions`:** Add section on "Context Gathering".

## Verification

- Run a test conversation: "I have a traceback in sale.order."
- Verify the Agent calls `read_source_code(focus_models=['sale.order'])` instead of
  dumping everything.
