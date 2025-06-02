<p align="center">
  <img src="assets/akaidoo.png" alt="Akaidoo Logo" width="300"/>
</p>

<h1 align="center">Akaidoo</h1>

<p align="center">
  <!-- TODO: Uncomment and update badges once set up -->
  <!-- <a href="YOUR_GITHUB_ACTIONS_LINK"><img src="YOUR_GITHUB_ACTIONS_BADGE_SVG" alt="Build Status"></a> -->
  <!-- <a href="YOUR_CODECOV_LINK"><img src="YOUR_CODECOV_BADGE_SVG" alt="Coverage Status"></a> -->
  <a href="https://pypi.org/project/akaidoo/"><img src="https://img.shields.io/pypi/v/akaidoo.svg" alt="PyPI version"></a>
  <a href="https://pypi.org/project/akaidoo/"><img src="https://img.shields.io/pypi/pyversions/akaidoo.svg" alt="Python versions"></a>
  <a href="LICENSE"><img src="https://img.shields.io/pypi/l/akaidoo.svg" alt="License"></a>
</p>

<p align="center">
  <i>Navigate the Odoo & OCA Maze: Instantly Gather Relevant Modules Files.</i>
</p>

---

**Akaidoo** extends the [manifestoo](https://github.com/acsone/manifestoo) CLI to list
and copy all relevant source files (Python models, XML views, wizards, reports, and even
OpenUpgrade migration scripts) from a specific Odoo addon and its _entire_ dependency
tree. It's designed to streamline your development workflow by quickly providing the
focused context you need; for AI LLMs for instance.

Akaidoo bridges this gap by helping you:

- 🔍 **Focus Your View:** Instantly see only the files relevant to your current task.
- 🤖 **Boost AI Tools:** Feed precisely the right context to AI assistants like GitHub
  Copilot, Cursor, or Neovim's Avante for more accurate suggestions, especially powerful
  when including OpenUpgrade scripts for migration tasks.
- 📝 **Streamline Editing:** Open all pertinent files in your editor with a single
  command.
- 🧩 **Understand Scope:** Quickly grasp the breadth of an addon's interactions.
- 🛠️ **Target Analysis:** Perform searches
  (`akaidoo sale_stock -c ~/DEV/odoo16/odoo.cfg | xargs grep "def _compute_price_unit"`)
  or static analysis on a well-defined subset of code.
- 🚀 **Accelerate Migrations:** Gather module code, dependencies, and their
  corresponding OpenUpgrade migration scripts in one go.

## Key Features

- **Deep Dependency Traversal:** Leverages `manifestoo` to accurately resolve all direct
  and transitive dependencies.
- **Intelligent File Collection:** Gathers `.py` (models, root files) and `.xml` (views,
  wizards, reports) from the identified addons.
- **OpenUpgrade Script Integration:** Optionally include all migration scripts from a
  specified OpenUpgrade repository for the target addon and its dependencies
  (`-u, --openupgrade`).
- **Flexible Addon Discovery:**
  - Use Odoo configuration files (`-c, --odoo-cfg`).
  - Specify addon paths directly (`--addons-path`).
  - Auto-detect from an importable `odoo` package.
- **Granular Filtering:**
  - Include/exclude specific file types (models, views, wizards, reports).
  - Focus _only_ on models or views.
  - Exclude Odoo core addons (`--exclude-core`) or common framework addons
    (`--exclude-framework`).
  - Intelligently skip trivial `__init__.py` files.
- **Versatile Output Modes:**
  - **List Paths:** Print file paths to `stdout` (default).
  - **To Clipboard:** Copy the _content_ of all found files to your clipboard
    (`-x, --clipboard`), each prefixed with its relative path – perfect for AI prompts!
  - **To File:** Dump all file contents into a single output file (`-o, --output-file`).
  - **To Editor:** Directly open all found files in your preferred editor
    (`-e, --edit`).

## Installation

<!--- install-begin -->

The recommended way to install Akaidoo is using [pipx](https://pypi.org/project/pipx/)
(to install it in an isolated environment):

```console
pipx install akaidoo
```

Alternatively, using pip:

```console
pip install --user akaidoo
```

For clipboard functionality (`-x`): Akaidoo uses `pyperclip`. You might need to install
it and its dependencies:

```console
pip install pyperclip
# On Linux, you may also need:
# sudo apt-get install xclip  # or xsel
```

<!--- install-end -->

## Quick Start

Imagine you're working on the `sale_timesheet` addon in an Odoo project.

1.  **Get all relevant file paths for `sale_timesheet` and its dependencies:** (Using
    your project's Odoo configuration file)

```console
akaidoo sale_timesheet -c ~/path/to/your/odoo.conf
```

2.  **Copy all Python model code for `sale_timesheet` (and its deps) to your clipboard
    for an AI prompt:**

```console
akaidoo sale_timesheet -c odoo.conf --only-models -x
```

    *(Each file's content in the clipboard will be prefixed with `# FILEPATH: path/to/file.py`)*

3.  **Open all Python and XML view files for `project` and its direct dependencies
    (excluding core) in Neovim (use --editor-cmd or EDITOR env var to specify a
    different editor):**

```console
akaidoo project -c odoo.conf --exclude-core --no-include-wizards --no-include-reports -e
```

    *(This uses the `nvim -p` command to open files in tabs. It's especially handy when using AI plugins like Avante.)*

4.  **Get only the files from the `mrp` addon itself, ignoring its dependencies, and
    save their content to a file (useful if you outgrow the clipboard size):**

```console
akaidoo mrp -c odoo.conf --only-target-addon -o mrp_context.txt
```

5.  **Gather `sale_stock` files, its dependencies, AND its OpenUpgrade migration
    scripts:** (Assuming your OpenUpgrade clone is at `~/OpenUpgrade`)

```console
akaidoo sale_stock -c odoo.conf -u ~/OpenUpgrade -o sale_stock_migration_context.txt
```

    This will collect all standard module files for `sale_stock` and its dependencies, plus all files from `~/OpenUpgrade/openupgrade_scripts/scripts/sale_stock/`, `~/OpenUpgrade/openupgrade_scripts/scripts/ADDON_DEPENDENCY_1/`, etc., into `sale_stock_migration_context.txt`. This is powerful for feeding comprehensive context to an AI for migration tasks.

6.  Gather the files from any source directory:

```console
akaidoo some_directory
```

    If some_directory is not an Odoo addon, then for convenience, akaidoo will select all the files from some_directory (recursively) and copy their content to the clipboard (-x) or to a file (-o) according to the options. It will skip hidden files and __pycache__.

**Exploring All Options:** For a full list of options:

```console
akaidoo --help
```

## Contributing

Contributions, bug reports, and feature requests are very welcome! Please feel free to
open an issue or submit a pull request on the GitHub repository.

## License

Akaidoo is licensed under the MIT License.
