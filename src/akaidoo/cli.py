import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set
import shlex
import subprocess
import os
from git import Repo, InvalidGitRepositoryError

import typer
from manifestoo_core.odoo_series import OdooSeries
from manifestoo import echo
import manifestoo.echo as manifestoo_echo_module
from manifestoo.utils import print_list

from .utils import (
    get_odoo_model_stats,
    get_timestamp,
)
from .tree import print_akaidoo_tree, get_akaidoo_tree_string
from .config import TOKEN_FACTOR
from .context import (
    resolve_akaidoo_context,
)
from .service import get_service
from .banner import AKAIDOO_BANNER

try:
    from importlib import metadata
except ImportError:
    import importlib_metadata as metadata

try:
    import pyperclip
except ImportError:
    pyperclip = None

try:
    __version__ = metadata.version("akaidoo")
except metadata.PackageNotFoundError:
    __version__ = "0.0.0-dev"


def parse_context_budget(budget_str: Optional[str]) -> Optional[int]:
    """
    Parse a context budget string into character count.

    Supports formats:
    - "100k" or "100K" -> 100,000 tokens -> ~370,000 chars (using TOKEN_FACTOR)
    - "50000" -> 50,000 characters

    Returns character count or None if no budget specified.
    """
    if not budget_str:
        return None

    budget_str = budget_str.strip().lower()

    if budget_str.endswith("k"):
        # Token count (e.g., "100k" = 100,000 tokens)
        try:
            tokens = int(budget_str[:-1]) * 1000
            # Convert tokens to chars: chars = tokens / TOKEN_FACTOR
            return int(tokens / TOKEN_FACTOR)
        except ValueError:
            echo.error(
                f"Invalid budget format: {budget_str}. Use '100k' for tokens or '50000' for chars."
            )
            raise typer.Exit(1)
    else:
        # Character count
        try:
            return int(budget_str)
        except ValueError:
            echo.error(
                f"Invalid budget format: {budget_str}. Use '100k' for tokens or '50000' for chars."
            )
            raise typer.Exit(1)


def version_callback_for_run(value: bool):
    if value:
        m_version = "unknown"
        mc_version = "unknown"
        try:
            m_version = metadata.version("manifestoo")
        except metadata.PackageNotFoundError:
            pass
        try:
            mc_version = metadata.version("manifestoo-core")
        except metadata.PackageNotFoundError:
            pass
        typer.echo(f"akaidoo version: {__version__}")
        typer.echo(f"manifestoo version: {m_version}")
        typer.echo(f"manifestoo-core version: {mc_version}")
        raise typer.Exit()


def process_and_output_files(
    files_to_process: List[Path],
    output_file_opt: Optional[Path],
    clipboard_opt: bool,
    edit_in_editor_opt: bool,
    editor_command_str_opt: Optional[str],
    separator_char: str,
    shrunken_files_content: Dict[Path, str],
    diffs: List[str],
    introduction: str,
):
    """Helper function to handle the output of found files."""
    if not files_to_process:
        echo.info("No files matched the criteria.")
        raise typer.Exit()

    sorted_file_paths = sorted(files_to_process)

    output_actions_count = sum(
        [edit_in_editor_opt, bool(output_file_opt), clipboard_opt]
    )
    if output_actions_count > 1:
        actions = [
            name
            for flag, name in [
                (edit_in_editor_opt, "--edit"),
                (output_file_opt, "--output-file"),
                (clipboard_opt, "--clipboard"),
            ]
            if flag
        ]
        echo.error(
            f"Please choose only one primary output action from: {', '.join(actions)}."
        )
        raise typer.Exit(1)

    if edit_in_editor_opt:
        cmd_to_use = (
            editor_command_str_opt
            or os.environ.get("VISUAL")
            or os.environ.get("EDITOR")
            or "nvim"
        )
        try:
            editor_parts = shlex.split(cmd_to_use)
        except ValueError as e:
            echo.error(f"Error parsing editor command '{cmd_to_use}': {e}")
            raise typer.Exit(1)
        if not editor_parts:
            echo.error(f"Editor command '{cmd_to_use}' invalid.")
            raise typer.Exit(1)
        full_command = editor_parts + [str(p) for p in sorted_file_paths]
        echo.info(f"Executing: {' '.join(shlex.quote(str(s)) for s in full_command)}")
        try:
            process = subprocess.run(full_command, check=False)
            if process.returncode != 0:
                echo.warning(f"Editor exited with status {process.returncode}.")
        except FileNotFoundError:
            echo.error(f"Editor command not found: {shlex.quote(editor_parts[0])}")
            raise typer.Exit(1)
        except Exception as e:
            echo.error(f"Failed to execute editor: {e}")
            raise typer.Exit(1)
    elif clipboard_opt:
        if pyperclip is None:
            echo.error("Clipboard requires 'pyperclip'. Install it and try again.")
            if not output_file_opt:
                echo.warning("Fallback: File paths:")
                print_list(
                    [str(p) for p in sorted_file_paths],
                    separator_char,
                )
            raise typer.Exit(1)
        all_content_for_clipboard = []
        for fp in sorted_file_paths:
            try:
                try:
                    header_path = fp.resolve().relative_to(Path.cwd())
                except ValueError:
                    header_path = fp.resolve()
                header = f"# FILEPATH: {header_path}\n"
                content = shrunken_files_content.get(
                    fp.resolve(),
                    re.sub(r"^(?:#.*\n)+", "", fp.read_text(encoding="utf-8")),
                )
                all_content_for_clipboard.append(header + content)
            except Exception as e:
                echo.warning(f"Could not read file {fp} for clipboard: {e}")
        for diff in diffs:
            all_content_for_clipboard.append(diff)

        clipboard_text = introduction + "\n\n".join(all_content_for_clipboard)
        try:
            pyperclip.copy(clipboard_text)
            print(
                f"Content of {len(sorted_file_paths)} files ({len(clipboard_text) / 1024:.2f} KB - {len(clipboard_text) * TOKEN_FACTOR / 1000.0:.0f}k TOKENS) copied to clipboard."
            )
        except Exception as e:  # Catch pyperclip specific errors
            echo.error(f"Clipboard operation failed: {e}")
            if not output_file_opt:
                echo.warning("Fallback: File paths:")
                print_list(
                    [str(p) for p in sorted_file_paths],
                    separator_char,
                )
            raise typer.Exit(1)
    elif output_file_opt:
        output_file_opt.parent.mkdir(parents=True, exist_ok=True)
        echo.info(
            f"Writing content of {len(sorted_file_paths)} files to {output_file_opt}..."
        )
        total_size = 0
        try:
            with output_file_opt.open("w", encoding="utf-8") as f:
                f.write(introduction + "\n\n")
                for fp in sorted_file_paths:
                    try:
                        try:
                            header_path = fp.resolve().relative_to(Path.cwd())
                        except ValueError:
                            header_path = fp.resolve()
                        header = f"# FILEPATH: {header_path}\n"
                        content = shrunken_files_content.get(
                            fp.resolve(),
                            re.sub(
                                r"^(?:#.*\n)+",
                                "",
                                fp.read_text(encoding="utf-8"),
                            ),
                        )
                        f.write(header + content + "\n\n")
                        total_size += len(header) + len(content) + 2
                    except Exception as e:
                        echo.warning(f"Could not read or write file {fp}: {e}")
                for diff in diffs:
                    f.write(diff)
                    total_size += len(diff)
            print(
                f"Successfully wrote {total_size / 1024:.2f} KB - {total_size * TOKEN_FACTOR / 1000.0:.0f}k TOKENS to {output_file_opt}"
            )
        except Exception as e:
            echo.error(f"Error writing to {output_file_opt}: {e}")
            raise typer.Exit(1)
    else:  # Default: print paths
        print_list([str(p.resolve()) for p in sorted_file_paths], separator_char)


akaidoo_app = typer.Typer(help="Akaidoo: win your Odoo AI context fight!")


@akaidoo_app.command(name="init")
def init_command():
    """Initialize Akaidoo state directory."""
    dot_akaidoo = Path(".akaidoo")
    if dot_akaidoo.exists():
        echo.info(".akaidoo/ already exists.")
    else:
        dot_akaidoo.mkdir()
        echo.info("Created .akaidoo/ directory.")

    rules_dir = dot_akaidoo / "rules"
    rules_dir.mkdir(exist_ok=True)

    guidelines_file = rules_dir / "oca_guidelines.md"
    if not guidelines_file.exists():
        guidelines_file.write_text(
            "# OCA Guidelines\n\n"
            "- Follow PEP8.\n"
            "- Use 4 spaces for indentation.\n"
            "- No tabs.\n"
            "- Use single quotes for strings unless they contain single quotes.\n"
            "- Models should have a `_description`.\n"
            "- Fields should have strings.\n"
            "- XML files should be indented with 2 spaces.\n"
            "- Use `odoo.addons.<module_name>` for imports.\n"
        )
        echo.info(f"Created {guidelines_file}")

    (dot_akaidoo / "context").mkdir(exist_ok=True)


@akaidoo_app.command(name="serve")
def serve_command(
    transport: str = typer.Option("stdio", help="Transport mechanism (stdio or sse)"),
):
    """Start the Akaidoo MCP server."""
    try:
        from .server import mcp
    except ImportError:
        missing_deps = []
        try:
            import mcp  # noqa: F401
        except ImportError:
            missing_deps.append("mcp")
        try:
            import fastmcp  # noqa: F401
        except ImportError:
            missing_deps.append("fastmcp")

        echo.error(
            f"MCP dependencies are not installed: {', '.join(missing_deps)}\n"
            f"To install MCP support, run: pip install akaidoo[mcp]"
        )
        raise typer.Exit(1)

    echo.info(f"Starting Akaidoo MCP server using {transport}...")
    mcp.run(transport=transport)


@akaidoo_app.callback()
def global_callback(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=version_callback_for_run,
        is_eager=True,
        help="Show the version and exit.",
        show_default=False,
    ),
):
    """Akaidoo: win your Odoo AI context fight!"""
    pass


@akaidoo_app.command(name="addon")
def akaidoo_command_entrypoint(
    addon_name: str = typer.Argument(
        ...,
        help="The name of the target Odoo addon, or a path to a directory.",
    ),
    verbose_level_count: int = typer.Option(
        0,
        "--verbose",
        "-V",
        count=True,
        help="Increase verbosity (can be used multiple times).",
        show_default=False,
    ),
    quiet_level_count: int = typer.Option(
        0,
        "--quiet",
        "-q",
        count=True,
        help="Decrease verbosity (can be used multiple times).",
        show_default=False,
    ),
    addons_path_str: Optional[str] = typer.Option(
        None,
        "--addons-path",
        help="Comma-separated list of directories to add to the addons path.",
        show_default=False,
    ),
    addons_path_from_import_odoo: bool = typer.Option(
        True,
        "--addons-path-from-import-odoo/--no-addons-path-from-import-odoo",
        help="Expand addons path by trying to `import odoo` and looking at `odoo.addons.__path__`.",
        show_default=True,
    ),
    addons_path_python: str = typer.Option(
        sys.executable,
        "--addons-path-python",
        show_default=True,
        metavar="PYTHON",
        help="The python executable for importing `odoo.addons.__path__`.",
    ),
    odoo_cfg: Optional[Path] = typer.Option(
        None,
        "-c",
        "--odoo-cfg",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        envvar="ODOO_RC",
        help="Expand addons path from Odoo configuration file.",
        show_default=False,
    ),
    odoo_series: Optional[OdooSeries] = typer.Option(
        None,
        envvar=["ODOO_VERSION", "ODOO_SERIES"],
        help="Odoo series to use, if not autodetected.",
        show_default=False,
    ),
    openupgrade_path: Optional[Path] = typer.Option(
        None,
        "--openupgrade",
        "-u",
        help="Path to the OpenUpgrade clone. If provided, includes migration scripts.",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        show_default=False,
    ),
    module_diff_path: Optional[Path] = typer.Option(
        None,
        "--module-diff",
        "-D",
        help="Path to the odoo-module-diff clone. If provided, includes pseudo version diffs",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        show_default=False,
    ),
    migration_commits: bool = typer.Option(
        False, "--migration-commits", help="Include deps migration commits"
    ),
    include: Optional[str] = typer.Option(
        None,
        "--include",
        "-i",
        help="Comma-separated list of content to include: view, wizard, data, report, controller, security, static, test, all. Models are always included.",
        show_default=False,
    ),
    exclude_addons_str: Optional[str] = typer.Option(
        None,
        "--exclude",
        help="Comma-separated list of addons to add to the default exclusion list.",
    ),
    no_exclude_addons_str: Optional[str] = typer.Option(
        None,
        "--no-exclude",
        help="Comma-separated list of addons to remove from the exclusion list (i.e., to force include).",
    ),
    separator: str = typer.Option(
        "\n", "--separator", help="Separator character between filenames."
    ),
    shrink_mode: str = typer.Option(
        "soft",
        "--shrink",
        help="Shrink effort: none (no shrink), soft (deps shrunk, targets full), medium (relevant deps soft, others hard), hard (targets soft, deps hard), max (max shrink everywhere).",
        case_sensitive=False,
    ),
    rm_expand_str: Optional[str] = typer.Option(
        None,
        "--rm-expand",
        help="Remove models from auto-expand set. Comma-separated list.",
        show_default=False,
    ),
    expand_models_str: Optional[str] = typer.Option(
        None,
        "--expand",
        "-E",
        help="Only expand specific models (explicit mode, disables auto-expand). Comma-separated list.",
        show_default=False,
    ),
    add_expand_str: Optional[str] = typer.Option(
        None,
        "--add-expand",
        help="Add models to auto-expand set. Comma-separated list.",
        show_default=False,
    ),
    output_file: Optional[Path] = typer.Option(
        None,
        "--output-file",
        "-o",
        help="File path to write output to.",
        writable=True,
        file_okay=True,
        dir_okay=False,
    ),
    clipboard: bool = typer.Option(
        False,
        "--clipboard",
        "-x",
        help="Copy file contents to clipboard.",
        show_default=True,
    ),
    edit_in_editor: bool = typer.Option(
        False, "--edit", "-e", help="Open found files in an editor.", show_default=False
    ),
    editor_command_str: Optional[str] = typer.Option(
        None,
        "--editor-cmd",
        help="Editor command (e.g., 'code -r'). Defaults to $VISUAL, $EDITOR, then 'nvim'.",
    ),
    prune_methods_str: Optional[str] = typer.Option(
        None,
        "--prune-methods",
        "-P",
        help="Comma-separated list of methods to force prune (e.g. 'Model.method').",
    ),
    session: bool = typer.Option(
        False,
        "--session",
        help="Create a session.md file with the context map and command.",
        show_default=False,
    ),
    agent_mode: bool = typer.Option(
        False,
        "--agent",
        help="Activate Agent Mode: separate background context and provide source reading instructions.",
        show_default=False,
    ),
    context_budget: Optional[str] = typer.Option(
        None,
        "--context-budget",
        "-B",
        help="Target context size budget (e.g., '100k' for 100k tokens, '50000' for 50000 chars). Akaidoo will auto-escalate shrink modes to fit.",
        show_default=False,
    ),
):
    manifestoo_echo_module.verbosity = (
        manifestoo_echo_module.verbosity + verbose_level_count - quiet_level_count
    )
    echo.debug(f"Effective verbosity: {manifestoo_echo_module.verbosity}")

    if agent_mode:
        if not output_file:
            output_file = Path(".akaidoo/context/background.md")

    # When using --context-budget, default to output file if no output mode specified
    if context_budget and not output_file and not clipboard and not edit_in_editor:
        output_file = Path(".akaidoo/context/current.md")

    # Parse context budget
    budget_chars = parse_context_budget(context_budget)

    context = resolve_akaidoo_context(
        addon_name=addon_name,
        addons_path_str=addons_path_str,
        addons_path_from_import_odoo=addons_path_from_import_odoo,
        addons_path_python=addons_path_python,
        odoo_cfg=odoo_cfg,
        odoo_series=odoo_series,
        openupgrade_path=openupgrade_path,
        module_diff_path=module_diff_path,
        migration_commits=migration_commits,
        include=include,
        exclude_addons_str=exclude_addons_str,
        no_exclude_addons_str=no_exclude_addons_str,
        shrink_mode=shrink_mode,
        expand_models_str=expand_models_str,
        add_expand_str=add_expand_str,
        rm_expand_str=rm_expand_str,
        prune_methods_str=prune_methods_str,
        skip_expanded=agent_mode,
        context_budget=budget_chars,
    )

    edit_mode = edit_in_editor
    # Mutual exclusivity check
    output_modes_count = sum([bool(output_file), bool(clipboard), bool(edit_mode)])
    if output_modes_count > 1:
        echo.error(
            "Please choose only one primary output action: --output-file, --clipboard, or --edit."
        )
        raise typer.Exit(1)

    cmd_call = shlex.join(sys.argv)
    if agent_mode:
        introduction = """# ODOO CONTEXT MAP (SECONDARY MODELS)

## ⚠️ READING PROTOCOL
1.  **LOW RESOLUTION:** This file contains **shrunken** versions of secondary models.
2.  **PURPOSE:** Use this ONLY to understand fields, relations, and inheritance hierarchy.
3.  **NO ACTION REQUIRED:** Do **NOT** attempt to `read_file` the original sources of these models unless explicitly instructed by a future user query (e.g., a traceback).
4.  **ASSUME CORRECTNESS:** Assume the methods marked `# shrunk` function correctly. Do not investigate them yet.

---
"""

    else:
        introduction = f"""Role: Senior Odoo Architect enforcing OCA standards.
Context: The following is a codebase dump produced by the akaidoo CLI.
Command: {cmd_call}
Conventions:
1. Files start with `# FILEPATH: [path]`.
2. Some files were filtered out to save tokens; ask for them if you need."""
        if shrink_mode != "none":
            introduction += """
3. `# shrunk` indicates code removed to save tokens; ask for full content if a specific logic flow is unclear."""
        if shrink_mode == "hard":
            introduction += """
4. Method definitions were eventually entirely skipped to save tokens and focus on the data model only."""

    edit_mode = edit_in_editor
    show_tree = not (output_file or clipboard or edit_mode)
    # If we are in directory mode (no selected addons), we don't show a tree
    if not context.selected_addon_names:
        show_tree = False

    # Display Tree View
    if show_tree:
        print_akaidoo_tree(
            root_addon_names=context.selected_addon_names,
            addons_set=context.addons_set,
            addon_files_map=context.addon_files_map,
            odoo_series=context.final_odoo_series,
            excluded_addons=set(),
            pruned_addons=context.pruned_addons,
            shrunken_files_info=context.shrunken_files_info,
        )

    # Token and Size Summary (use pre-calculated context size for consistency)
    # Build model_chars_map for per-model size attribution (display purposes)
    model_chars_map: Dict[str, int] = {}

    for f in context.found_files_list:
        abs_path = f.resolve()
        content = context.shrunken_files_content.get(abs_path)
        info = context.shrunken_files_info.get(abs_path)

        # For files with expanded_locations (agent mode), calculate size from source ranges
        if info and info.get("expanded_locations"):
            try:
                file_content = f.read_text(encoding="utf-8")
                lines = file_content.split("\n")
                for model_name, ranges in info["expanded_locations"].items():
                    for start_line, end_line, _ in ranges:
                        start_idx = max(0, start_line - 1)
                        end_idx = min(len(lines), end_line)
                        range_content = "\n".join(lines[start_idx:end_idx])
                        model_chars_map[model_name] = model_chars_map.get(
                            model_name, 0
                        ) + len(range_content)
            except Exception:
                pass

        # For regular content (non-expanded models)
        if content is None:
            try:
                content = f.read_text(encoding="utf-8")
            except Exception:
                content = ""

        file_size = len(content) if content else 0

        # Attribute size to models defined in this file (for non-expanded content)
        if f.suffix == ".py" and file_size > 0:
            try:
                # We use the shrunken info if available, otherwise scan
                if info and "model_shrink_levels" in info:
                    # Only count models that are NOT in expanded_locations
                    expanded_models = set(info.get("expanded_locations", {}).keys())
                    models_in_file = [
                        m
                        for m in info["model_shrink_levels"].keys()
                        if m not in expanded_models
                    ]
                elif info and "models" in info:
                    models_in_file = info["models"].keys()
                else:
                    models_in_file = get_odoo_model_stats(content).keys()

                if models_in_file:
                    # Simple attribution: distribute file size among models
                    per_model_size = (
                        file_size // len(models_in_file) if models_in_file else 0
                    )
                    for m in models_in_file:
                        model_chars_map[m] = model_chars_map.get(m, 0) + per_model_size
            except Exception:
                pass

    # Use pre-calculated context size for consistency with budget enforcement
    total_chars = context.context_size_chars
    if total_chars == 0:
        # Fallback if context_size_chars wasn't set (e.g., directory mode)
        total_chars = sum(
            len(context.shrunken_files_content.get(f.resolve(), "")) or f.stat().st_size
            for f in context.found_files_list
        )

    total_kb = total_chars / 1024
    total_tokens = int(total_chars * TOKEN_FACTOR / 1000)
    threshold_chars = total_chars * 0.05

    def format_model_list(models_set: Set[str]) -> str:
        if not models_set:
            return ""

        # Sort by total chars descending, then by name
        sorted_models = sorted(
            models_set, key=lambda m: (model_chars_map.get(m, 0), m), reverse=True
        )

        formatted_items = []
        for m in sorted_models:
            m_chars = model_chars_map.get(m, 0)
            if m_chars > threshold_chars and m_chars > 0:
                m_tokens = int(m_chars * TOKEN_FACTOR / 1000)
                item_str = f"{m} ({m_tokens}k tokens)"
                # Highlight large models in yellow
                formatted_items.append(typer.style(item_str, fg=typer.colors.YELLOW))
            else:
                formatted_items.append(m)

        return ", ".join(formatted_items)

    # Detailed Expansion Reporting
    # We show these always, as requested
    typer.echo()  # Blank line after tree
    original_auto_expanded = context.expand_models_set - context.enriched_additions
    if original_auto_expanded:
        label = typer.style(
            f"Auto-expanded {len(original_auto_expanded)} models:", bold=True
        )
        typer.echo(f"{label} {format_model_list(original_auto_expanded)}")

    if context.enriched_additions:
        label = typer.style(
            f"Enriched parent/child models ({len(context.enriched_additions)}):",
            bold=True,
        )
        typer.echo(f"{label} {format_model_list(context.enriched_additions)}")

    if context.new_related:
        label = typer.style(
            f"Other Related models (neighbors/parents) ({len(context.new_related)}):",
            bold=True,
        )
        typer.echo(f"{label} {format_model_list(context.new_related)}")

    typer.echo(
        typer.style(f"Found {len(context.found_files_list)} total files.", bold=True)
    )
    typer.echo(
        typer.style(
            f"Estimated context size: {total_kb:.2f} KB ({total_tokens}k Tokens)",
            bold=True,
        )
    )

    if session:
        session_path = Path(".akaidoo/context/session.md")
        session_path.parent.mkdir(parents=True, exist_ok=True)
        tree_str = get_akaidoo_tree_string(
            root_addon_names=context.selected_addon_names,
            addons_set=context.addons_set,
            addon_files_map=context.addon_files_map,
            odoo_series=context.final_odoo_series,
            excluded_addons=set(),
            pruned_addons=context.pruned_addons,
            shrunken_files_info=context.shrunken_files_info,
        )
        session_content = f"""# Akaidoo Session: {', '.join(context.selected_addon_names)}

> **Command:** `{' '.join(sys.argv)}`
> **Timestamp:** {get_timestamp()}
> **Odoo Series:** {context.final_odoo_series}

## 🗺️ Context Map
This map shows the active scope. "Pruned" modules are hidden to save focus.

```text
{tree_str}
```
"""
        session_path.write_text(session_content, encoding="utf-8")
        typer.echo(typer.style(f"Session map written to {session_path}", bold=True))

    if (
        not output_file
        and not clipboard
        and not edit_mode
        and not show_tree
        and not session
    ):
        typer.echo("Files list (no output mode selected):")
        for f in context.found_files_list:
            typer.echo(f"- {f}")

    if edit_mode:
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nvim"
        if editor_command_str:
            editor = editor_command_str
        subprocess.run(shlex.split(editor) + [str(f) for f in context.found_files_list])

    if output_file or clipboard:
        service = get_service()
        dump = service.get_context_dump(context, introduction)
        if output_file:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(dump, encoding="utf-8")
            typer.echo(
                typer.style(f"Codebase dump written to {output_file}", bold=True)
            )
        if clipboard:
            if pyperclip:
                pyperclip.copy(dump)
                typer.echo(typer.style("Codebase dump copied to clipboard.", bold=True))
            else:
                echo.error("pyperclip not installed. Cannot copy to clipboard.")

    if agent_mode:
        locations_by_model = {}
        for fp, info in context.shrunken_files_info.items():
            # Only include expanded locations if content was actually skipped
            # (i.e., the LLM needs to read the full source, not the shrunk version)
            if not info.get("content_skipped", False):
                continue
            locs = info.get("expanded_locations")
            if locs:
                try:
                    rel_path = fp.relative_to(Path.cwd())
                except ValueError:
                    rel_path = fp
                for model_name, ranges in locs.items():
                    if model_name not in locations_by_model:
                        locations_by_model[model_name] = []
                    for start, end, type_ in ranges:
                        locations_by_model[model_name].append(
                            {
                                "path": str(rel_path),
                                "start": start,
                                "end": end,
                                "type": type_,
                            }
                        )

        # Generate dependency tree string (modules only, no files)
        tree_str = get_akaidoo_tree_string(
            root_addon_names=context.selected_addon_names,
            addons_set=context.addons_set,
            addon_files_map={},  # Empty to hide files
            odoo_series=context.final_odoo_series,
            excluded_addons=set(),
            pruned_addons=context.pruned_addons,
            shrunken_files_info=context.shrunken_files_info,
            use_ansi=False,
        )

        typer.echo(
            "\n"
            + typer.style(
                "--- AGENT INSTRUCTIONS (CONTEXT INGESTION) ---",
                fg=typer.colors.CYAN,
                bold=True,
            )
        )

        # 1. Project Structure (Global Map)
        typer.echo(typer.style("\n## 1. GLOBAL ODOO MODULES DEPENDENCY MAP", bold=True))
        typer.echo(
            "The following tree defines the execution order. Logic in lower modules overrides parents."
        )
        typer.echo("```text")
        typer.echo(tree_str)
        typer.echo("```")

        # 2. Background Context (Secondary Models)
        # We explicitly label this as "Secondary" so the LLM knows it's just supporting data
        typer.echo(
            typer.style("\n## 2. SECONDARY CONTEXT (Schema & Relations)", bold=True)
        )
        typer.echo(f"**ACTION:** Use `read_file` to ingest ENTIRELY: `{output_file}`")
        typer.echo(
            "   *   Contains: Structural skeletons of dependencies and secondary models."
        )
        typer.echo(
            "   *   **DO NOT EXPAND:** Do NOT try to read the full source of files found in this map yet!"
        )
        typer.echo(
            "   *   **USE AS INDEX:** Only use these paths later if a specific traceback/query requires it."
        )

        # 3. Primary Context (The Focus)
        # We clarify that THIS is the "Main" part the user cares about
        if locations_by_model:
            typer.echo(
                typer.style("\n## 3. PRIMARY FOCUS (Logic & Implementation)", bold=True)
            )
            typer.echo(
                "**ACTION:** Use your `read_file` tool to ingest the following source code ranges IN PARALLEL."
            )
            typer.echo("These are the core models relevant to the current task.")

            for m in sorted(locations_by_model.keys()):
                entries = locations_by_model[m]
                # Sort: Base first, then by path
                entries.sort(
                    key=lambda x: (
                        0 if x["type"] == "Base" else 1,
                        x["path"],
                        x["start"],
                    )
                )

                typer.echo(typer.style(f"\n## Model: {m}", bold=True))
                typer.echo("| Type | Path | Range |")
                typer.echo("| :--- | :--- | :--- |")

                for entry in entries:
                    start = entry["start"]
                    if start < 20:
                        start = 1
                    typer.echo(
                        f"| {entry['type']} | {entry['path']} | {start}-{entry['end']} |"
                    )

            typer.echo(
                typer.style(
                    "\n--- END INSTRUCTIONS ---", fg=typer.colors.CYAN, bold=True
                )
            )


def find_pr_commits_after_target(
    diffs_list, repo_path, addon, serie, target_message=None
):
    if target_message is None:
        target_message = f" {addon}: Migration to {serie}"
    try:
        # Open the repository
        repo = Repo(repo_path)

        pr_commits = []

        # Find the target commit
        target_commit = None
        last_commits = []
        for commit in repo.iter_commits():
            last_commits.append(commit)
            if target_message in commit.message:
                target_commit = commit
                break

        if target_commit is None:
            print(f"no migration found for {addon}")
            return

        for commit in reversed(last_commits):
            if len(commit.parents) > 1:
                # print(f"Found merge commit: {commit.hexsha[:8]} - likely end of PR")
                break
            if ": " in commit.message and not commit.message.strip().split(": ")[
                0
            ].endswith(addon):
                break  # for some reason commit is for another module before any merge commit
            pr_commits.append(commit)

        # Display all commits in the PR
        print(f"\nFound {len(pr_commits)} commits for {addon} v{serie} migration")
        for i, commit in enumerate(pr_commits):
            print(
                f"{i + 1}. {commit.hexsha[:8]} - {commit.author.name} - {commit.message.splitlines()[0]}"
            )

        print("\n" + "=" * 80 + "\n")

        # Show diffs for each commit in the PR after the target
        target_index = next(
            (
                i
                for i, commit in enumerate(pr_commits)
                if commit.hexsha == target_commit.hexsha
            ),
            -1,
        )

        if target_index == -1:
            print("Error: Target commit not found in PR commits list")
            return

        for i in range(target_index + 1, len(pr_commits)):
            commit = pr_commits[i]
            if commit.parents:
                diff = commit.parents[0].diff(commit, create_patch=True)
                if diff:
                    for file_diff in diff:
                        diff_text = f"\nFile: {file_diff.a_path} -> {file_diff.b_path}"
                        diff_text += f"\nChange type: {file_diff.change_type}"
                        # Decode diff if it's bytes, otherwise use as is
                        if isinstance(file_diff.diff, bytes):
                            diff_text += "\n" + file_diff.diff.decode(
                                "utf-8", errors="replace"
                            )
                        else:
                            diff_text += "\n" + file_diff.diff
                    diffs_list.append(diff_text)

    except InvalidGitRepositoryError:
        print(f"The path '{repo_path}' is not a valid Git repository")
    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback

        traceback.print_exc()


def cli_entry_point():
    args = sys.argv
    if "--help" in args:
        # Highlight Akretion in blue
        blue_akretion = typer.style("Akretion", fg=typer.colors.BLUE)
        print(AKAIDOO_BANNER.replace("Akretion", blue_akretion))

    # Handle -o default value for session context
    if "-o" in args:
        idx = args.index("-o")
        # Check if -o is followed by a value (not an option and not empty)
        if idx + 1 == len(args) or args[idx + 1].startswith("-"):
            args.insert(idx + 1, ".akaidoo/context/current.md")
    elif "--output-file" in args:
        idx = args.index("--output-file")
        if idx + 1 == len(args) or args[idx + 1].startswith("-"):
            args.insert(idx + 1, ".akaidoo/context/current.md")

    if len(sys.argv) > 1 and sys.argv[1] not in [
        "init",
        "addon",
        "serve",
        "--help",
        "--version",
    ]:
        # Prepend 'addon' to sys.argv if not a known subcommand or global option
        sys.argv.insert(1, "addon")
    akaidoo_app(prog_name="akaidoo")


if __name__ == "__main__":
    cli_entry_point()
