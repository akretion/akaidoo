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

**Akaidoo** is the ultimate bridge between your Odoo codebase and Large Language Models
(LLMs). It extends [manifestoo](https://github.com/acsone/manifestoo) to intelligently
survey, filter, prune, and dump Odoo source code, providing highly optimized context for
AI-driven development.

It is designed around a powerful **2-Stage Workflow**: first **Map** the context, then
**Dump** it.

## How Akaidoo Thinks: The Core Algorithm

Akaidoo uses a multi-pass system to make intelligent decisions about what code to
include and how to format it. Understanding this process is key to mastering its
powerful features.

### Pass 1: Discovery (Build the Knowledge Graph)

Before any action is taken, Akaidoo performs a comprehensive survey of the entire
codebase (target addons + all dependencies).

1.  **Scan All Python Files**: It quickly parses every `.py` file in the addons path.
2.  **Map All Relations**: It builds a complete in-memory graph (`all_relations`) that
    maps every Odoo model to its parents (`_inherit`, `_inherits`) and its comodels
    (from `Many2one`, `One2many`, `Many2many` fields).

This initial pass solves the "chicken-and-egg" problem: to know which dependencies are
relevant, you first need a complete map of all relationships.

### Pass 2: Expansion (Define What's "Relevant")

Once the graph is built, Akaidoo determines the set of `relevant_models` that will guide
the rest of the process.

1.  **Initial Seed**: The process starts with a seed set of models from:
    - `--auto-expand`: Models in target addons with a high "complexity score" (based on
      number of fields, methods, and lines of code).
    - `--focus-models` or `--expand`: Models you explicitly specify.
2.  **Recursive Parent Expansion**: Akaidoo walks up the inheritance tree. If a model is
    in the set, and it `_inherit`s another model (e.g., `portal.mixin`), then that
    parent model is also added to the set of models to be expanded. This continues
    recursively until all ancestors are included (unless they are in a blacklist).
3.  **Child Enrichment**: It also looks for `*.line` models (e.g., `sale.order.line`)
    and adds their parents to the expansion set, ensuring master-detail relationships
    are complete.
4.  **Neighbor Resolution**: Finally, it finds all **comodels** related to the
    now-expanded set. These neighbors are considered "related" but are not themselves
    fully expanded, providing a layer of context without pulling in unrelated modules.

### Pass 3: Action (Prune, Shrink, and Dump)

With a clear definition of `relevant_models`, Akaidoo takes action:

1.  **Pruning**: It iterates through each addon in the dependency tree and decides
    whether to keep or discard it based on the `--prune` mode. In `soft` mode (the
    default), any addon that contains a file defining a `relevant_model` is kept.
2.  **Shrinking**: For each file in the final, pruned list, it applies the `--shrink`
    logic:
    - **Target addons are NEVER shrunk** (unless in `hard` mode). Your primary code is
      always preserved.
    - In dependencies, the shrinking is granular:
      - Files with relevant models are shrunk `soft` (method bodies become
        `pass # shrunk`).
      - Files with irrelevant models are shrunk `hard` (methods are removed entirely,
        along with comments and `help=` tags).
3.  **Dumping**: The final, processed content is assembled with file path headers and
    delivered to your clipboard, a file, or the editor.

### Final Output: The Summary

After the tree or dump, Akaidoo provides a summary to help you understand the context
you've built:

- **Model Lists**: `Auto-expanded`, `Enriched`, and `Other Related` models are listed,
  sorted by their estimated token size.
- **Token Highlighting**: Any model contributing more than 5% of the total token count
  is highlighted in yellow, making it easy to spot and potentially exclude with
  `--rm-expand`.
- **Context Size**: A final estimate of the total size in KB and tokens.

---

## 🎛️ Control Specifications

### Shrink Modes (`--shrink`)

_Controls the "Resolution" or level of detail._

| Mode         | Target Addons | Relevant Dependency Models        | Irrelevant Dependency Models | Imports & Metadata |
| :----------- | :------------ | :-------------------------------- | :--------------------------- | :----------------- |
| **`none`**   | **Full Code** | **Full Code**                     | **Full Code**                | Kept               |
| **`soft`**   | **Full Code** | _Shrunken_ (keeps method headers) | _Shrunken_                   | Kept               |
| **`medium`** | **Full Code** | _Shrunken_                        | **Hard Shrunk**              | **Removed**        |
| **`hard`**   | _Hard Shrunk_ | **Hard Shrunk**                   | **Hard Shrunk**              | **Removed**        |

- **Shrunken**: Method bodies are replaced with `pass  # shrunk`.
- **Hard Shrunk**: Method definitions are removed entirely. Comments and field `help`
  attributes are also stripped.

### Prune Modes (`--prune`)

_Controls the "Framing" or scope of included addons._

| Mode         | Scope          | Description                                                                                          | Use Case                                 |
| :----------- | :------------- | :--------------------------------------------------------------------------------------------------- | :--------------------------------------- |
| **`none`**   | **Wide Angle** | Includes **ALL** dependencies.                                                                       | Debugging obscure framework issues.      |
| **`soft`**   | **Portrait**   | **Default.** Includes target addons + dependencies containing any `relevant_model`.                  | Most development tasks.                  |
| **`medium`** | **Close-up**   | Includes target addons + dependencies containing only models from the initial auto-expand/focus set. | Focused work on specific business logic. |
| **`hard`**   | **Macro**      | Includes **only** the Target Addons.                                                                 | Unit testing, independent module work.   |

### Exclusion Logic

_Removes "well-known" clutter to focus on your custom code._

Akaidoo excludes a default list of stable framework modules (`base`, `web`, `mail`,
etc.) that an LLM should already know well. This is a major token-saving feature.

- Use `--exclude addon_name` to add to the exclusion list.
- Use `--no-exclude addon_name` to force the inclusion of a default-excluded addon.

## Usage Examples

**1. The "Quick Survey" (Stage 1)** See what `sale_timesheet` pulls in:

```console
akaidoo sale_timesheet -c odoo.conf
```

**2. The "Focused Dump" (Stage 2)** Standard Context for `sale_timesheet`, shrinking
dependencies, but keeping `project.task` fully expanded:

```console
akaidoo sale_timesheet -c odoo.conf --expand project.task -x
```

**3. Open Models and Views in Editor** Open all relevant files (including views) in your
editor:

```console
akaidoo project -c odoo.conf --include view -e
```

**4. "High-Level Architecture"** See the data model and API surface of `account` without
implementation details:

```console
akaidoo account -c odoo.conf --shrink hard -x
```

**5. Migration Context** Gather code + migration scripts for an upgrade:

```console
akaidoo sale_stock -c odoo.conf -u ~/OpenUpgrade -o migration_context.txt
```

**6. Include Everything** Include models, views, wizards, data, tests, etc.:

```console
akaidoo my_module -c odoo.conf --include all
```

## Contributing

Contributions are welcome! Please open an issue or submit a PR on GitHub.

## License

MIT License.
