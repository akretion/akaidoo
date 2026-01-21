<p align="center">
  <img src="assets/akaidoo.png" alt="Akaidoo Logo" width="300"/>
</p>

<h1 align="center">Akaidoo: win your Odoo AI context fight!</h1>

<p align="center">
  <a href="https://pypi.org/project/akaidoo/"><img src="https://img.shields.io/pypi/v/akaidoo.svg" alt="PyPI version"></a>
  <a href="https://pypi.org/project/akaidoo/"><img src="https://img.shields.io/pypi/pyversions/akaidoo.svg" alt="Python versions"></a>
  <a href="LICENSE"><img src="https://img.shields.io/pypi/l/akaidoo.svg" alt="License"></a>
</p>

<p align="center">
  <i>The ultimate bridge between your Odoo codebase and Large Language Models.</i>
</p>

---

**Akaidoo** extends [manifestoo](https://github.com/acsone/manifestoo) to intelligently
survey, filter, and dump Odoo source code, providing highly optimized context for
AI-driven development. It solves the critical problem of fitting relevant Odoo code into
LLM context windows while preserving the information AI needs to help you.

## Quick Start

```bash
# Install
pip install akaidoo

# Survey your addon (shows dependency tree)
akaidoo sale_stock -c odoo.conf

# Dump context to clipboard (smart defaults)
akaidoo sale_stock -c odoo.conf -x

# Dump with budget constraint (auto-escalates shrink)
akaidoo sale_stock -c odoo.conf -B 100k -o context.md
```

## Core Concepts

### The 2-Stage Workflow: Map, then Dump

1. **Map**: Survey the codebase to understand scope and relationships
2. **Dump**: Generate optimized context for your AI assistant

### How Akaidoo Thinks

Akaidoo uses a multi-pass algorithm:

1. **Discovery**: Scans all Python files to build a complete model relationship graph
2. **Expansion**: Determines which models are "relevant" based on complexity scores
3. **Action**: Shrinks code intelligently based on model category and relevance

## Usage Examples

### Basic Operations

```bash
# Survey addon (tree view, no dump)
akaidoo sale_stock -c odoo.conf

# Dump to clipboard
akaidoo sale_stock -c odoo.conf -x

# Dump to file
akaidoo sale_stock -c odoo.conf -o context.md

# Open in editor
akaidoo sale_stock -c odoo.conf -e
```

### Controlling Expansion

```bash
# Auto-expand (default) - akaidoo picks high-score models
akaidoo sale_stock -c odoo.conf -x

# Explicit mode - ONLY expand specific models (disables auto-expand)
akaidoo sale_stock -c odoo.conf -E sale.order,stock.picking -x

# Additive mode - add models to auto-expand set
akaidoo sale_stock -c odoo.conf --add-expand account.move -x

# Remove from auto-expand set
akaidoo sale_stock -c odoo.conf --rm-expand mail.thread -x
```

### Controlling Context Size

```bash
# Set shrink level manually
akaidoo sale_stock -c odoo.conf --shrink=hard -x

# Budget mode - auto-escalate shrink to fit token budget
akaidoo sale_stock -c odoo.conf -B 100k -o context.md

# Max shrink - data model skeleton only
akaidoo sale_stock -c odoo.conf --shrink=max -x
```

### Advanced Usage

```bash
# Multiple addons
akaidoo sale_stock,purchase_stock -c odoo.conf -x

# Include views and wizards
akaidoo sale_stock -c odoo.conf --include=view,wizard -x

# Include OpenUpgrade migration scripts
akaidoo sale_stock -c odoo.conf -u ~/OpenUpgrade -o migration.md

# Prune specific large methods
akaidoo sale_stock -c odoo.conf --prune-methods sale.order._compute_amounts -x
```

## Shrink Modes

The `--shrink` option controls how aggressively code is compressed:

| Level                | Target Addons  | Dependency Addons          | Use Case            |
| :------------------- | :------------- | :------------------------- | :------------------ |
| **`none`**           | Full code      | Full code                  | Maximum detail      |
| **`soft`** (default) | Full code      | Shrunk (methods -> `pass`) | General development |
| **`medium`**         | Lightly shrunk | Heavily shrunk             | Moderate context    |
| **`hard`**           | Shrunk         | Very shrunk                | Focused debugging   |
| **`max`**            | Skeleton only  | Skeleton only              | Data model overview |

### What Gets Shrunk?

- **Full**: Complete code with all logic preserved
- **Soft**: Method bodies replaced with `pass # shrunk`, signatures kept
- **Hard**: Methods removed entirely, only fields and class structure
- **Max**: Fields summarized, only relational fields to relevant models detailed

## Expansion Options

Akaidoo intelligently decides which models to show in full detail ("expand") vs shrink.

### Auto-Expand (Default)

By default, akaidoo scans your target addons and auto-expands models with high
"complexity scores" (based on fields, methods, and lines of code).

### Explicit Mode (`--expand` / `-E`)

Use when you want ONLY specific models expanded. This **disables auto-expand**:

```bash
# Only expand sale.order - everything else gets shrunk
akaidoo sale_stock -E sale.order -x
```

**Use case**: Debugging a specific model, investigating a traceback.

### Additive Mode (`--add-expand`)

Add models to the auto-expand set without disabling auto-expand:

```bash
# Auto-expand + also expand stock.move
akaidoo sale_stock --add-expand stock.move -x
```

**Use case**: Need more context on a related model.

### Remove from Expansion (`--rm-expand`)

Remove noisy models from auto-expand set:

```bash
# Don't expand mail.thread even if it scores high
akaidoo sale_stock --rm-expand mail.thread -x
```

## Agent Mode

Agent mode (`--agent`) produces context optimized for AI agents that can read files
directly. Instead of including full source in the dump, it provides:

1. **Schema Map**: Summarized data model structure (fields, relations)
2. **Read Instructions**: File paths and line ranges for the agent to read and use
   context caching

```bash
akaidoo sale_stock -c odoo.conf --agent -o .akaidoo/context/background.md
```

### Output Structure

```
## 1. PROJECT STRUCTURE (Dependency Order)
[Module tree showing inheritance order]

## 2. SCHEMA MAP
Path: .akaidoo/context/background.md
(Summarized models - use for navigation, not implementation details)

## 3. LOGIC & SOURCE CODE
| Model | Type | Path | Range |
| sale.order | Ext | addons/sale/models/sale.py | 45-320 |
```

**Use case**: AI coding assistants (Claude, Cursor) that have file reading capabilities.

## MCP Server

Akaidoo can run as a persistent
[Model Context Protocol](https://modelcontextprotocol.io/) server, allowing AI agents to
dynamically query your Odoo codebase.

### Starting the Server

```bash
akaidoo serve
```

### Available Tools

#### `read_module_source` (Primary)

Retrieves Odoo addon source code with intelligent context optimization.

```python
read_module_source(
    addon="sale_stock",                    # Required
    shrink_mode="soft",                    # none/soft/medium/hard/max
    expand_models=["sale.order"],          # Explicit mode (disables auto-expand)
    add_expand_models=["stock.move"],      # Additive mode (works with auto-expand)
    context_budget_tokens=100000,          # Auto-escalate shrink to fit
)
```

#### `get_context_map` (Optional)

Shows dependency tree before committing to full dump:

```python
get_context_map(addon="sale_stock")
```

#### `get_context_summary` (Optional)

Returns metrics (token counts, expanded models) for planning:

```python
get_context_summary(addon="sale_stock")
# Returns: {"total_tokens": 85000, "expand_models": ["sale.order"], ...}
```

### Integration Example (Claude Desktop)

Add to your Claude Desktop config
(`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "akaidoo": {
      "command": "akaidoo",
      "args": ["serve"]
    }
  }
}
```

## Tree View

When running without output flags, akaidoo shows a tree view with:

- Module dependency structure
- File sizes
- Per-model shrink indicators with color coding:
  - **Red (full)**: Complete code preserved
  - **Yellow (soft)**: Method bodies shrunk
  - **Cyan (hard)**: Only fields and API
  - **Dim (max)**: Skeleton only

```
Module: sale_stock
Path: addons/sale_stock
├── models/sale_order.py (12KB) [Models: sale.order (full), stock.picking (soft)]
├── models/stock_move.py (8KB) [Models: stock.move (hard)]
│
└── Module: sale
    Path: addons/sale
    ├── models/sale.py (45KB) [Models: sale.order (full)]
```

## Framework Exclusions

By default, akaidoo excludes well-known framework addons that LLMs typically know:

`base`, `web`, `web_editor`, `web_tour`, `portal`, `mail`, `digest`, `bus`,
`auth_signup`, `base_setup`, `http_routing`, `utm`, `uom`, `product`

```bash
# Add to exclusion list
akaidoo sale_stock --exclude my_addon -x

# Force include a default-excluded addon
akaidoo sale_stock --no-exclude mail -x
```

## Directory Mode

Pass a directory path (with trailing `/`) to scan arbitrary directories:

```bash
# Scan directory recursively (not Odoo mode)
akaidoo ./my_scripts/ -o dump.md
```

## Environment Variables

| Variable                       | Purpose                          |
| :----------------------------- | :------------------------------- |
| `ODOO_RC` / `ODOO_CONFIG`      | Odoo configuration file path     |
| `ODOO_VERSION` / `ODOO_SERIES` | Odoo version/series              |
| `EDITOR` / `VISUAL`            | Default editor for `--edit` mode |

## Installation

```bash
# Basic installation
pip install akaidoo

# With MCP server support
pip install akaidoo[mcp]

# Development installation
pip install -e ".[test]"
```

## Contributing

Contributions are welcome! Please open an issue or submit a PR on GitHub.

```bash
# Run tests
pytest tests/

# Run with verbose output
pytest tests/ -v
```

## License

MIT
