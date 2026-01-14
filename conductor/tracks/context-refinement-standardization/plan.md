# Track: Context Refinement Standardization

## Context
Standardize the "Context Zoom" process by replacing ad-hoc flags with consistent, leveled enums for Pruning and Shrinking. 

## Goals
1. Implement enums for `--prune` and `--shrink` with clear leveled semantics.
2. Remove legacy flags (`--only-target-addon`, `-l`, `--shrink-aggressive`, `-S`, `--no-prune`) for cleaner API.
3. Complete the Expansion axis with `--rm-expand`.

## Tasks

### 1. Pruning Axis (`--prune=[none|soft|medium|hard]`)
- [ ] **Implementation**:
    - `none`: No pruning (keep all modules in tree and output).
    - `soft` (Default): Current behavior (Expanded + Parent/Child + Related models determine relevant modules).
    - `medium`: Expanded models only (Skip P/C and Related enrichment).
    - `hard`: Limit to target addons only (prune all non-target modules).
- [ ] **Cleanup**: Remove `--prune`, `--no-prune`, `-l`, `--only-target-addon` flags (breaking API change).

### 2. Shrinking Axis (`--shrink=[none|soft|medium|hard]`)
- [ ] **Implementation**:
    - `none`: No shrinking at all.
    - `soft` (Default): Current `-s` (Dependencies shrunk with `pass # shrunk`, Targets full).
    - `medium`: For **relevant models** (expanded + related):
        - In target addons: don't shrink anything (full content)
        - In other modules (dependencies): shrink method bodies (`pass # shrunk`)
      For **irrelevant models**:
        - Shrink aggressively everywhere (remove method bodies entirely, keep only class defs and fields)
    - `hard`: Current aggressive mode (All methods removed everywhere).
- [ ] **Cleanup**: Remove `-s`, `-S`, `--shrink-aggressive` flags (breaking API change).

### 3. Expansion Axis Tweak
- [ ] **Feature: `--rm-expand`**:
    - Allow explicitly removing a model from the auto-expand set (useful if a model passes the score threshold but is irrelevant noise).

### 4. Integration & Documentation
- [ ] Update `resolve_akaidoo_context` to handle the new enums.
- [ ] Update `AGENTS.md` and `README.md` with the "Context Zoom" table.
- [ ] Update `akaidoo serve` (MCP) tools to accept these enum strings.
