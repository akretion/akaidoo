# Akaidoo

**Akaidoo** is a CLI tool designed to supercharge Odoo development with AI. It acts as a
bridge between your Odoo codebase and Large Language Models (LLMs) like Gemini, Claude,
or ChatGPT.

By extending `manifestoo`, Akaidoo intelligently gathers, filters, and processes source
code from Odoo addons and their deep dependency trees. It provides exactly the right
context—models, views, migration scripts—formatted for AI consumption.

## Project Structure

- **`src/akaidoo/`**: Core package source.
  - `cli.py`: Main entry point. Handles argument parsing (via `typer`) and high-level
    orchestration.
  - `scanner.py`: Handles file discovery, scanning logic, and filtering for both
    directories and addons.
  - `shrinker.py`: Implements "token shrinking" logic. Uses `tree-sitter` to parse
    Python code and reduce methods to their signatures.
  - `tree.py`: Logic for generating the hierarchical dependency tree output.
  - `utils.py`: General utility functions, including model name extraction.
  - `main.py`: Alternative entry point.
- **`tests/`**: Test suite (using `pytest`).
- **`pyproject.toml`**: Project configuration, dependencies, and build settings
  (setuptools).
- **`.pre-commit-config.yaml`**: Linting and formatting hooks.

## Key Technologies

- **Python**: Core language.
- **Typer**: CLI application framework.
- **Manifestoo**: Used for robust Odoo addon discovery and dependency resolution.
- **Tree-sitter**: Used in `shrinker.py` for robust, error-tolerant parsing of Python
  code.
- **GitPython**: For handling git operations (likely for OpenUpgrade integration).
- **Pytest**: Testing framework.

## Development & Usage

### Installation

```bash
# Install via pipx (recommended for isolation)
pipx install akaidoo

# Or editable install for development
pip install -e .
```

### Running Tests

```bash
pytest
```

### Key Features & Concepts

- **Smart Context Gathering**: Collects relevant `.py` and `.xml` files from target
  addons and their dependencies.
- **Hierarchical Tree Output**: The default output mode now displays a rich dependency
  tree.
  - Shows module dependencies recursively.
  - Displays files with their sizes.
  - **Model Hints**: Automatically extracts and displays Odoo model names defined in
    each file (e.g., `[Models: sale.order, sale.order.line]`).
  - **Deduplication**: Modules already displayed in the tree are marked with `⬆ [path]`
    to avoid redundancy.
- **Shrinking**: To fit more files into an LLM's context window, Akaidoo can "shrink"
  Python files.
  - **Standard (-s)**: Shrinks dependencies, keeps target full.
  - **Aggressive (-S)**: Shrinks everything.
  - **Auto-Expansion**: Automatically keeps models full if they are significantly
    extended in the target addon (configurable).
- **Smart Pruning**: Automatically prunes irrelevant modules (those not containing
  relevant models) from the output and tree, keeping the context focused.
  - Enabled by default (`--prune`). Disable with `--no-prune`.
  - Pruned modules appear greyed out in the tree with no files or Path listed.
- **Project Mode & Smart Paths**:
  - Automatically detects if an input is a single addon, a directory of addons, or a
    simple path.
  - Can scan arbitrary directories with intelligent filtering (skipping `i18n`,
    `__pycache__`).
- **MCP Server Support**: Exposes Akaidoo tools via the Model Context Protocol (MCP),
  allowing AI agents to query Odoo context dynamically.
  - Command: `akaidoo serve`
  - Tools: `get_odoo_structure`, `read_odoo_context`.
- **OpenUpgrade Integration**: Can fetch migration scripts from a separate OpenUpgrade
  repository.

### Common Commands

- `akaidoo <addon_name> -c <odoo.conf>`: Show the dependency tree and file listing
  (Default).
- `akaidoo <addon_name> -x`: Copy file contents to clipboard (with default shrinking
  applied).
- `akaidoo <addon_name> -s`: Shrink dependencies (keep target addon full).
- `akaidoo <addon_name> -S`: Shrink everything.
- `akaidoo <addon_name> -v`: Include views (XML files).
- `akaidoo <addon_name> --tree`: Explicitly force tree output (though it's now default).

### Contribution Guidelines

- Follow existing code styles (likely enforced by `ruff` or `pre-commit`).
- Ensure tests are added for new functionality.
- **Scanner Logic**: File scanning logic is centralized in `scanner.py`.
- **Tree Visualization**: Output formatting logic is in `tree.py`.
