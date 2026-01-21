"""
Akaidoo Service Layer

Provides a clean, stateless API for Odoo context operations.
This is the primary interface for both CLI and MCP server.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .config import TOKEN_FACTOR
from .context import (
    AkaidooContext,
    resolve_akaidoo_context,
    get_akaidoo_context_dump,
    calculate_context_size,
    _calculate_expanded_files_size,
)
from .tree import get_akaidoo_tree_string, print_akaidoo_tree


@dataclass
class ContextOptions:
    """Configuration options for context resolution."""

    # Addons path configuration
    addons_path_str: Optional[str] = None
    addons_path_from_import_odoo: bool = True
    addons_path_python: str = "python"
    odoo_cfg: Optional[Path] = None
    odoo_series: Optional[str] = None

    # Extra scripts
    openupgrade_path: Optional[Path] = None
    module_diff_path: Optional[Path] = None
    migration_commits: bool = False

    # Include/Exclude filters
    include: Optional[str] = None
    exclude_addons_str: Optional[str] = None
    no_exclude_addons_str: Optional[str] = None

    # Shrink and prune modes
    shrink_mode: str = "soft"
    prune_methods_str: Optional[str] = None

    # Model expansion
    expand_models_str: Optional[str] = None
    add_expand_str: Optional[str] = None
    rm_expand_str: Optional[str] = None

    # Agent mode
    skip_expanded: bool = False

    # Budget
    context_budget: Optional[int] = None


class AkaidooService:
    """
    Stateless service for Odoo context operations.

    This service provides a clean API that both CLI and MCP server can use.
    It wraps the lower-level functions from context.py and tree.py.

    Example usage:
        service = AkaidooService()
        context = service.resolve_context("sale_stock", shrink_mode="soft")
        dump = service.get_context_dump(context)
        tokens = service.estimate_tokens(context)
    """

    def resolve_context(
        self,
        addon: str,
        *,
        addons_path_str: Optional[str] = None,
        addons_path_from_import_odoo: bool = True,
        addons_path_python: Optional[str] = None,
        odoo_cfg: Optional[Path] = None,
        odoo_series: Optional[str] = None,
        openupgrade_path: Optional[Path] = None,
        module_diff_path: Optional[Path] = None,
        migration_commits: bool = False,
        include: Optional[str] = None,
        exclude_addons_str: Optional[str] = None,
        no_exclude_addons_str: Optional[str] = None,
        shrink_mode: str = "soft",
        prune_methods_str: Optional[str] = None,
        expand_models_str: Optional[str] = None,
        add_expand_str: Optional[str] = None,
        rm_expand_str: Optional[str] = None,
        skip_expanded: bool = False,
        context_budget: Optional[int] = None,
    ) -> AkaidooContext:
        """
        Build context for addon(s) with given options.

        Args:
            addon: Addon name(s), comma-separated, or path to addon directory
            addons_path_str: Comma-separated list of addons directories
            addons_path_from_import_odoo: Try to import odoo.addons for paths
            addons_path_python: Python executable for importing odoo
            odoo_cfg: Path to Odoo configuration file
            odoo_series: Odoo version series (e.g., "16.0")
            openupgrade_path: Path to OpenUpgrade clone
            module_diff_path: Path to module-diff clone
            migration_commits: Include migration commits
            include: Content types to include (view, wizard, data, etc.)
            exclude_addons_str: Addons to exclude
            no_exclude_addons_str: Addons to force include
            shrink_mode: none, soft, medium, hard, max
            prune_methods_str: Methods to prune (e.g., "Model.method")
            expand_models_str: Models to fully expand
            auto_expand: Auto-expand high-score models
            add_expand_str: Add models to auto-expand set
            rm_expand_str: Remove models from expand set
            skip_expanded: Skip expanded content (for agent mode)
            context_budget: Target context size in characters

        Returns:
            AkaidooContext with all gathered context information
        """
        import sys

        return resolve_akaidoo_context(
            addon_name=addon,
            addons_path_str=addons_path_str,
            addons_path_from_import_odoo=addons_path_from_import_odoo,
            addons_path_python=addons_path_python or sys.executable,
            odoo_cfg=odoo_cfg,
            odoo_series=odoo_series,
            openupgrade_path=openupgrade_path,
            module_diff_path=module_diff_path,
            migration_commits=migration_commits,
            include=include,
            exclude_addons_str=exclude_addons_str,
            no_exclude_addons_str=no_exclude_addons_str,
            shrink_mode=shrink_mode,
            prune_methods_str=prune_methods_str,
            expand_models_str=expand_models_str,
            add_expand_str=add_expand_str,
            rm_expand_str=rm_expand_str,
            skip_expanded=skip_expanded,
            context_budget=context_budget,
        )

    def resolve_context_from_options(
        self, addon: str, options: ContextOptions
    ) -> AkaidooContext:
        """
        Build context using a ContextOptions dataclass.

        This is an alternative to resolve_context() that uses a dataclass
        for options, which can be useful for storing/restoring configurations.
        """
        import sys

        return resolve_akaidoo_context(
            addon_name=addon,
            addons_path_str=options.addons_path_str,
            addons_path_from_import_odoo=options.addons_path_from_import_odoo,
            addons_path_python=options.addons_path_python or sys.executable,
            odoo_cfg=options.odoo_cfg,
            odoo_series=options.odoo_series,
            openupgrade_path=options.openupgrade_path,
            module_diff_path=options.module_diff_path,
            migration_commits=options.migration_commits,
            include=options.include,
            exclude_addons_str=options.exclude_addons_str,
            no_exclude_addons_str=options.no_exclude_addons_str,
            shrink_mode=options.shrink_mode,
            prune_methods_str=options.prune_methods_str,
            expand_models_str=options.expand_models_str,
            add_expand_str=options.add_expand_str,
            rm_expand_str=options.rm_expand_str,
            skip_expanded=options.skip_expanded,
            context_budget=options.context_budget,
        )

    def get_context_dump(
        self,
        context: AkaidooContext,
        introduction: str = "",
        focus_files: Optional[List[str]] = None,
    ) -> str:
        """
        Generate the context dump string.

        Args:
            context: The AkaidooContext to dump
            introduction: Introduction text to prepend
            focus_files: Optional list of file patterns to filter

        Returns:
            The formatted context dump as a string
        """
        return get_akaidoo_context_dump(
            context=context,
            introduction=introduction,
            focus_files=focus_files,
        )

    def get_tree_string(
        self,
        context: AkaidooContext,
        use_ansi: bool = False,
    ) -> str:
        """
        Generate the tree visualization string.

        Args:
            context: The AkaidooContext to visualize
            use_ansi: Whether to include ANSI color codes

        Returns:
            The tree visualization as a string
        """
        return get_akaidoo_tree_string(
            root_addon_names=context.selected_addon_names,
            addons_set=context.addons_set,
            addon_files_map=context.addon_files_map,
            odoo_series=context.final_odoo_series,
            excluded_addons=context.excluded_addons,
            pruned_addons=context.pruned_addons,
            use_ansi=use_ansi,
            shrunken_files_info=context.shrunken_files_info,
        )

    def print_tree(
        self,
        context: AkaidooContext,
        prune_mode: str = "soft",
    ) -> None:
        """
        Print the tree visualization to stdout with ANSI colors.

        Args:
            context: The AkaidooContext to visualize
            prune_mode: The prune mode used (for display purposes)
        """
        print_akaidoo_tree(
            root_addon_names=context.selected_addon_names,
            addons_set=context.addons_set,
            addon_files_map=context.addon_files_map,
            odoo_series=context.final_odoo_series,
            excluded_addons=context.excluded_addons if prune_mode != "none" else set(),
            pruned_addons=context.pruned_addons,
            shrunken_files_info=context.shrunken_files_info,
        )

    def estimate_tokens(
        self,
        context: AkaidooContext,
        include_expanded_files: bool = True,
    ) -> int:
        """
        Estimate token count for the context.

        Args:
            context: The AkaidooContext to estimate
            include_expanded_files: Include expanded files in agent mode

        Returns:
            Estimated token count
        """
        chars = calculate_context_size(context, include_expanded_files)
        return int(chars * TOKEN_FACTOR / 1000) * 1000  # Round to nearest 1000

    def calculate_size_chars(
        self,
        context: AkaidooContext,
        include_expanded_files: bool = True,
    ) -> int:
        """
        Calculate context size in characters.

        Args:
            context: The AkaidooContext to measure
            include_expanded_files: Include expanded files in agent mode

        Returns:
            Total size in characters
        """
        return calculate_context_size(context, include_expanded_files)

    def calculate_expanded_files_size(self, context: AkaidooContext) -> int:
        """
        Calculate the size of expanded files that LLM will read separately.

        Useful in agent mode to understand how much additional content
        the LLM will need to read beyond the main dump.

        Args:
            context: The AkaidooContext to measure

        Returns:
            Size of expanded files in characters
        """
        return _calculate_expanded_files_size(context)

    def get_context_summary(self, context: AkaidooContext) -> Dict:
        """
        Get a summary of the context for reporting.

        Returns a dictionary with key metrics about the context.

        Args:
            context: The AkaidooContext to summarize

        Returns:
            Dictionary with summary information
        """
        total_chars = self.calculate_size_chars(context)
        expanded_chars = self.calculate_expanded_files_size(context)
        dump_chars = total_chars - expanded_chars

        return {
            "addon_names": sorted(context.selected_addon_names),
            "odoo_series": str(context.final_odoo_series)
            if context.final_odoo_series
            else None,
            "total_files": len(context.found_files_list),
            "total_chars": total_chars,
            "total_tokens": int(total_chars * TOKEN_FACTOR),
            "dump_chars": dump_chars,
            "dump_tokens": int(dump_chars * TOKEN_FACTOR),
            "expanded_chars": expanded_chars,
            "expanded_tokens": int(expanded_chars * TOKEN_FACTOR),
            "expand_models": sorted(context.expand_models_set),
            "enriched_additions": sorted(context.enriched_additions),
            "related_models": sorted(context.new_related),
            "pruned_addons": list(context.pruned_addons.keys()),
            "effective_shrink_mode": context.effective_shrink_mode,
            "budget_escalation_level": context.budget_escalation_level,
        }


# Singleton instance for convenience
_default_service: Optional[AkaidooService] = None


def get_service() -> AkaidooService:
    """Get the default AkaidooService instance."""
    global _default_service
    if _default_service is None:
        _default_service = AkaidooService()
    return _default_service
