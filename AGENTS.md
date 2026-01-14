# AGENTS.md - Akaidoo Project Information

## Project Overview

**Akaidoo** is a CLI tool that enhances Odoo development by bridging the gap between Odoo codebases and Large Language Models (LLMs). It extends `manifestoo` to intelligently gather, filter, and process source code from Odoo addons and their deep dependency trees, providing precisely the right context for AI consumption.

### Key Purpose
- Feed exactly the right context (models, views, migration scripts) to AI LLMs like Gemini, Claude, or ChatGPT
- Support Odoo developers in understanding codebase scope, performing searches, and accelerating migrations
- Optimize context window usage through intelligent "shrinking" of Python code

**Current Version:** 1.3.0

## Project Structure

```
akaidoo/
├── src/akaidoo/           # Core package source
│   ├── __init__.py        # Version definition
│   ├── cli.py             # Main CLI entry point with typer
│   ├── main.py            # Alternative entry point
│   ├── scanner.py         # File discovery and scanning logic
│   ├── shrinker.py        # Token shrinking logic (tree-sitter based)
│   ├── tree.py            # Dependency tree visualization
│   └── utils.py           # Utility functions
├── tests/                 # Test suite (pytest)
├── conductor/             # Project management tracks
│   └── tracks/            # Feature plans and progress
├── pyproject.toml         # Project configuration
├── .pre-commit-config.yaml  # Linting hooks
└── README.md             # User documentation
```

## Key Technologies & Dependencies

### Core Dependencies
- **Python**: ≥3.8 (supports 3.8-3.12)
- **manifestoo**: Odoo addon discovery and dependency resolution
- **manifestoo-core**: Core addon management utilities
- **typer[all]**: CLI application framework (≥0.9.0)
- **tree-sitter**: Robust Python code parsing for shrinking
- **tree-sitter-python**: Python grammar for tree-sitter
- **GitPython**: Git operations (OpenUpgrade integration)
- **pyperclip**: Clipboard functionality

### Development & Testing
- **pytest**: Test framework
- **pytest-mock**: Mocking utilities
- **pre-commit**: Git hooks for code quality
- **ruff**: Likely linter (check .pre-commit-config.yaml)

## Core Concepts

### 1. Context Gathering
The primary goal is to collect all relevant `.py` and `.xml` files from:
- Target addon(s)
- All direct and transitive dependencies
- OpenUpgrade migration scripts (optional)
- Module diffs (optional)

### 2. Three Modes of Operation

**Mode 1: Directory Mode**
- `akaidoo some_dir/` - Scan directory recursively
- Skips `__pycache__`, `i18n`, hidden files, binary files
- Useful for arbitrary directory content collection

**Mode 2: Odoo Addon Mode (Project Mode)**
- `akaidoo addon_name` - Scan Odoo addon and dependencies
- Supports multiple addons: `akaidoo addon1,addon2`
- Can accept paths: `akaidoo /path/to/addon` or `akaidoo /path/to/custom_addons/`
- Auto-detects addons in directories and adds to addons_path

**Mode 3: Smart Path Detection**
- Automatically detects if input is:
  - An addon directory (uses directory name as addon name)
  - A container of addons (adds all addons inside)
  - A simple addon name

### 3. Shrinking (Token Optimization)
To fit more content into LLM context windows:

**Standard Shrinking (-s)**
- Shrinks only dependency Python files
- Keeps target addon(s) at full resolution
- Replaces method bodies with `pass # shrunk`
- Preserves class definitions, method signatures, and field definitions

**Aggressive Shrinking (-S)**
- Shrinks all Python files (including targets)
- Removes method bodies entirely
- Focuses on data model and API structure

**Model Expansion (--expand / --auto-expand)**
- Explicitly list models to keep at full resolution: `--expand model1,model2`
- Auto-expand models significantly extended in target addons (fields >5 or methods >2)
- Useful when you need full implementation for specific critical models

### 4. Smart Pruning (Context Optimization)
- Automatically prunes irrelevant modules (those not containing relevant models) from the output and tree.
- **Relevant Models**: Defined as the set of expanded models plus their relations (parents, comodels).
- **Pruned Modules**: Appear greyed out in the tree with no files or Path listed.
- Enabled by default. Disable with `--no-prune`.

### 5. File Filtering
- **Include types**: models, views, wizards, reports, data
- **Exclude**: core addons (--exclude-core), framework addons (--exclude-framework)
- **Filter**: only models (--only-models), only views (--only-views)
- **Framework addons** (excluded by default): base, web, web_editor, web_tour, portal, mail, digest, bus, auth_signup, base_setup, http_routing, utm, uom, product

## Development Guidelines

### Code Style
- Follow existing code conventions
- Type hints are used in function signatures
- No excessive comments (keep it DRY)
- Use existing helper functions from `manifestoo` where possible

### Testing
- Tests are in `tests/` directory using pytest
- Use `pytest` to run tests
- Test configuration in `pytest.ini`
- Common test patterns: test CLI commands, test file scanning, test shrinking logic

### Code Organization

**cli.py (993 lines)**
- Main CLI entry point with typer
- Functions extracted for clarity:
  - `expand_inputs()`: Parse and expand addon/directory inputs
  - `resolve_addons_path()`: Build addons path from various sources
  - `resolve_addons_selection()`: Get dependency tree with filters
  - `scan_extra_scripts()`: Scan OpenUpgrade/module diff scripts
  - `process_and_output_files()`: Handle different output modes
  - `find_pr_commits_after_target()`: Git commit analysis
- Main command: `akaidoo_command_entrypoint()`

**scanner.py (218 lines)**
- `scan_directory_files()`: Recursive directory scan
- `scan_addon_files()`: Scan Odoo addon with filters
- `is_trivial_init_py()`: Skip trivial __init__.py files
- Handles all file type filtering and shrinking coordination

**shrinker.py**
- Uses tree-sitter to parse Python code
- `shrink_python_file()`: Main shrinking function
- Removes method bodies while preserving structure

**tree.py**
- Dependency tree visualization
- `print_akaidoo_tree()`: Print formatted tree of addons and files

**utils.py**
- `get_file_odoo_models()`: Extract Odoo model names from files
- `get_odoo_model_stats()`: Get model statistics (fields, methods count)

### Common Development Tasks

**Running Tests**
```bash
pytest
pytest tests/test_cli.py  # Run specific test file
pytest -v                 # Verbose output
```

**Code Quality**
```bash
# Pre-commit hooks are configured
pre-commit run --all-files

# Check for linting (verify exact command in .pre-commit-config.yaml)
ruff check src/
```

**Installation for Development**
```bash
pip install -e .
pip install -e ".[test]"  # With test dependencies
```

**Running the CLI**
```bash
# From source
python -m akaidoo <addon_name>

# After install
akaidoo <addon_name>
```

## Key File Locations

- **CLI Logic**: `src/akaidoo/cli.py:87-901` (main entry point)
- **Input Expansion**: `src/akaidoo/cli.py:267-343`
- **Addons Path Resolution**: `src/akaidoo/cli.py:389-412`
- **Dependency Resolution**: `src/akaidoo/cli.py:346-386`
- **File Scanning**: `src/akaidoo/scanner.py:60-217`
- **Shrinking Logic**: `src/akaidoo/shrinker.py`
- **Token Factor**: `0.27` (empirical factor for token estimation)

## Environment Variables
- `ODOO_RC` / `ODOO_CONFIG`: Odoo configuration file path
- `ODOO_VERSION` / `ODOO_SERIES`: Odoo version/series
- `EDITOR` / `VISUAL`: Default editor for --edit mode
- `VIRTUAL_ENV`: Auto-detect odoo.cfg in venv

## Important Constants
- **FRAMEWORK_ADDONS**: Tuple of framework module names to exclude (line 49-64 in cli.py)
- **AUTO_EXPANSION_BLACKLIST**: Tuple of model names that should never be auto-expanded (line 67-69 in cli.py)
- **PARENT_CHILD_AUTO_EXPAND**: Boolean to enable automatic parent/child model expansion (line 72 in cli.py)
  - Rule 1: Models ending with `.line` add parent (e.g., `sale.order.line` → `sale.order`)
  - Rule 2: Other models add `.line` child (e.g., `account.move` → `account.move.line`)
- **TOKEN_FACTOR**: 0.27 (line 75 in cli.py) - for estimating token count from character count
- **BINARY_EXTS**: Tuple of binary file extensions to skip (line 9-22 in scanner.py)

## Project Management (Conductor)
- Feature plans tracked in `conductor/tracks/`
- Each track has a `plan.md` with tasks and checkboxes
- Current tracks:
  - [x] Multiple Addons Support
  - [ ] Workflow Enhancements

## Common CLI Patterns

**Basic Usage**
```bash
# Models only (new default)
akaidoo sale_stock -c odoo.conf

# Models + views (add back views)
akaidoo sale_stock -c odoo.conf -v

# Models + views + wizards
akaidoo sale_stock -c odoo.conf -v -w

# Copy to clipboard (auto-expand + shrinking enabled by default)
akaidoo sale_stock -c odoo.conf -x

# Only target addon, no dependencies
akaidoo sale_stock -c odoo.conf -l -x

# Open in editor
akaidoo project -c odoo.conf --exclude-core -e
```

**Advanced Usage**
```bash
# Multiple addons
akaidoo sale_stock,purchase_stock -c odoo.conf

# Focus on specific models (overrides auto-expand)
akaidoo sale_stock -c odoo.conf -F sale.order,account.move

# Auto-expand + add extra models
akaidoo sale_stock -c odoo.conf --add-expand stock.picking,stock.move

# Disable auto-expansion (all models shrunk)
akaidoo sale_stock -c odoo.conf --no-auto-expand

# Disable smart pruning (include unrelated modules)
akaidoo sale_stock -c odoo.conf --no-prune

# Prune unrelated modules (default)
akaidoo sale_stock -c odoo.conf

# Include OpenUpgrade scripts
akaidoo sale_stock -c odoo.conf -u ~/OpenUpgrade -o migration.txt

# Only models, no views
akaidoo sale_stock -c odoo.conf --only-models
```

## Notes for AI Agents

1. **Always run tests after changes**: Use `pytest` to verify
2. **Check existing patterns**: Look at similar functions/files before implementing new features
3. **Use manifestoo utilities**: Don't reinvent dependency resolution
4. **Respect filters**: Ensure new features work with --exclude-core, --exclude-framework, etc.
5. **Consider shrinking**: New features should work with both -s and -S modes
6. **Test multiple modes**: Directory mode, addon mode, project mode
7. **Type hints are important**: Add type hints to new functions
8. **Keep cli.py manageable**: Extract large functions to separate modules if they grow too large
9. **Error handling**: Use `echo.error()`, `echo.warning()`, `echo.info()`, `echo.debug()` for user feedback
10. **Path handling**: Always use `Path.resolve()` for consistent absolute paths

11. **Pruning considerations**: By default, akaidoo prunes modules that don't contain expanded models. Only manifests are kept from pruned modules. Use `--no-prune` to disable.

## Testing Best Practices

1. **Test different input types**: addon names, paths, multiple addons
2. **Test filtering**: --exclude-core, --exclude-framework, --only-models, etc.
3. **Test shrinking**: -s and -S modes
4. **Test output modes**: default, -x (clipboard), -o (file), -e (editor)
5. **Mock external dependencies**: Use pytest-mock for file system, git operations
6. **Test edge cases**: empty directories, missing addons, circular dependencies

## Performance Considerations

- File scanning is recursive; consider large codebases
- Shrinking uses tree-sitter which is fast but has overhead
- Token estimation uses empirical factor (0.27), not actual tokenization
- For very large projects, consider using `-o` (file output) instead of clipboard

## Common Issues & Solutions

1. **Addons not found**: Check --addons-path or -c (odoo.cfg)
2. **Missing dependencies**: Verify addons_path includes all required modules
3. **Shrinking not working**: Ensure tree-sitter-python is installed correctly
4. **Editor fails**: Check $EDITOR/$VISUAL env var or use --editor-cmd
5. **Clipboard fails**: Install pyperclip and system dependencies (xclip/xsel on Linux)

## Version Info
- akaidoo: 1.3.0
- manifestoo: (check with `akaidoo --version`)
- manifestoo-core: (check with `akaidoo --version`)
