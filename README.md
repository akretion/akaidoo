<p align="center">
  <img src="assets/akaidoo.png" alt="Akaidoo Logo" width="300"/>
</p>

<h1 align="center">Akaidoo - Odoo Context Dumper for AI</h1>

<p align="center">
  <a href="https://pypi.org/project/akaidoo/"><img src="https://img.shields.io/pypi/v/akaidoo.svg" alt="PyPI version"></a>
  <a href="https://pypi.org/project/akaidoo/"><img src="https://img.shields.io/pypi/pyversions/akaidoo.svg" alt="Python versions"></a>
  <a href="LICENSE"><img src="https://img.shields.io/pypi/l/akaidoo.svg" alt="License"></a>
</p>

<p align="center">
  <i>The "Context Map & Dump" Workflow for Odoo AI Agents.</i>
</p>

---

**Akaidoo** is the ultimate bridge between your Odoo codebase and Large Language Models (LLMs). It extends [manifestoo](https://github.com/acsone/manifestoo) to intelligently survey, filter, prune, and dump Odoo source code, providing highly optimized context for AI-driven development.

It is designed around a powerful **2-Stage Workflow**: first **Map** the context, then **Dump** it.

## The 2-Stage Workflow

### Stage 1: The Context Map (Survey) 🗺️

Before you dump thousands of lines of code into an LLM, use Akaidoo to visualize the scope. Running Akaidoo without output flags (`-x` or `-o`) generates a hierarchical dependency tree.

```console
akaidoo sale_stock -c odoo.conf
```

**What you get:**
- A visual **Dependency Tree** showing module relationships.
- **Smart Hints**: Shows which Odoo models (`sale.order`, `account.move`) are defined in each file.
- **Smart Pruning**: Automatically greys out modules that don't contain relevant models (based on relations), keeping the focus sharp.
- **File Sizes**: Helps you estimate token usage before dumping.

### Stage 2: The Context Dump (Act) 📥

Once you're satisfied with your selection, dump the actual content. Akaidoo formats it perfectly for LLMs (with file path headers) and applies intelligent shrinking to save tokens.

```console
akaidoo sale_stock -c odoo.conf -x
```

**What you get:**
- **Clipboard Content** (or file with `-o`) ready to paste into Gemini/Claude/ChatGPT.
- **Token Optimization**: Method bodies in dependencies are "shrunk" (replaced with `pass # shrunk`) to save space while preserving API structure.
- **Auto-Expansion**: Models you are working on (or their relations) are automatically kept in full detail.

---

## Key Features

### 🧠 Smart Pruning (New!)
Akaidoo understands Odoo code. It analyzes `_inherit`, `Many2one`, etc., to build a graph of "Relevant Models".
- **Auto-Pruning**: Modules that don't contain any relevant models are automatically "pruned" (files hidden) from both the tree and the dump.
- **Control**: Enabled by default (`--prune`). Disable with `--no-prune` if you want everything.

### 📉 Intelligent Shrinking
Don't waste tokens on implementation details of dependencies.
- **Standard Shrinking (`-s`)**: Keeps target modules full, but reduces dependencies to class definitions and method signatures.
- **Aggressive Shrinking (`-S`)**: Shrinks everything (useful for pure data modeling tasks).
- **Auto-Expansion**: Automatically detects which models are being extended in your target addon and keeps their full hierarchy expanded.

### 🎯 Granular Filtering
- **Project Mode**: `akaidoo .` or `akaidoo my_addon` automatically detects addon paths.
- **Filters**: `--only-models`, `--only-views`, `--exclude-core`, `--exclude-framework`.
- **Migration Ready**: Use `-u ~/OpenUpgrade` to include relevant migration scripts alongside the code.

## Installation

Recommended: Install via [pipx](https://pypi.org/project/pipx/) for isolation.

```console
pipx install akaidoo
```

Or via pip:

```console
pip install akaidoo
```

*Note: Clipboard support (`-x`) requires `pyperclip` (and `xclip`/`xsel` on Linux).*

## Usage Examples

**1. The "Quick Survey" (Stage 1)**
See what `sale_timesheet` pulls in:
```console
akaidoo sale_timesheet -c odoo.conf
```

**2. The "Focused Dump" (Stage 2)**
Copy context for `sale_timesheet`, shrinking dependencies, but keeping `project.task` fully expanded:
```console
akaidoo sale_timesheet -c odoo.conf --expand project.task -x
```

**3. Open in Editor**
Open all relevant files in your editor (e.g., Neovim/VSCode) for manual review:
```console
akaidoo project -c odoo.conf --exclude-core -e
```

**4. Migration Context**
Gather code + migration scripts for an upgrade:
```console
akaidoo sale_stock -c odoo.conf -u ~/OpenUpgrade -o migration_context.txt
```

**5. Directory Mode**
Scan any folder (not just addons):
```console
akaidoo ./scripts/
```

## Contributing

Contributions are welcome! Please open an issue or submit a PR on GitHub.

## License

MIT License.