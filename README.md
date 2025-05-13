<img src="assets/akaidoo.png" alt="Logo" width="400"/>

# Akaidoo

<!-- [![Github-CI][github-ci]][github-link] -->
<!-- [![Coverage Status][codecov-badge]][codecov-link] -->
<!-- TODO: Replace with actual links once published and CI is set up -->

<!--- shortdesc-begin -->

A Python CLI package extending the [manifestoo](https://github.com/acsone/manifestoo) CLI to list all relevant source files from an Odoo addon and its entire dependency tree. Ideal for focused code browsing, context gathering for AI tools, or targeted analysis.

<!--- shortdesc-end -->

## Why Akaidoo?

The Odoo source code and the vast OCA ecosystem comprise millions of lines of code across hundreds of repositories. When working on a specific module, your focus is typically on that module and its direct and transitive dependencies – usually a manageable set of 20-30 modules.

Akaidoo helps you quickly identify and gather all the relevant Python and XML files from this dependency set, making it easier to:

*   Load relevant context into your code editor.
*   Feed the necessary source code to AI-powered development tools (like Cursor, Avante in Neovim, or Copilot).
*   Perform targeted searches or static analysis.
*   Understand the scope of changes for a given addon.

Akaidoo leverages `manifestoo` for its robust addon discovery and dependency resolution capabilities.

## Installation

<!--- install-begin -->

Using [pipx](https://pypi.org/project/pipx/) (recommended):

```console
pipx install akaidoo
```

## Features

Akaidoo provides one main command, list-files, with various options:

- Dependency Resolution: Uses manifestoo to find all direct and transitive dependencies of a specified Odoo addon.
- File Collection: Gathers all relevant files (Python models, XML views, XML wizards) from the target addon and its dependencies.
- Flexible Addons Path Configuration:
    - Specify addons paths directly (--addons-path).
    - Automatically use paths from an odoo.conf file (-c, --odoo-cfg).
    - Discover paths from an importable odoo package.
- Filtering:
    - Include/exclude models, views, and wizard files (--[no-]include-models, etc.).
    - Focus only on models, views, or wizards (--only-models, etc.).
    - Exclude Odoo core addons (--exclude-core).
    - Skip trivial __init__.py files (those with only comments/imports).
- Multiple Output Modes:
    - List paths to stdout (default).
    - Copy file contents to the system clipboard (-x, --clipboard), each prefixed with its path.
    - Write file contents to a specified output file (-o, --output-file), each prefixed with its path.
    - Open files directly in your preferred editor (-e, --edit), with configurable editor command (--editor-cmd).
    - Informative Output: Verbosity controls, clear information about addons processed and files found.

For a full list of commands and options, run akaidoo --help or akaidoo list-files --help.

## Quick Start

Let's assume you have an Odoo project structure and want to list all Python model files for the sale_management addon and its dependencies, excluding core Odoo addons. Your Odoo configuration is in ~/odoo/project.conf.

1. List relevant Python model file paths from sale_management and its non-core dependencies:

```console
akaidoo list-files sale_management -c ~/odoo/project.conf --only-models
```

 2. Open all view and wizard XML files for account in Neovim:


```console
akaidoo list-files account -c ~/odoo/project.conf --only-models -e nvim
```
