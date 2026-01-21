"""
Akaidoo Types Module

Dataclasses and type definitions for reducing mutable state and improving type safety.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class ShrinkResult:
    """
    Return type from shrink_python_file().

    Groups all outputs from the shrinking operation instead of returning a tuple.
    This makes the return value self-documenting and easier to extend.
    """

    content: str
    expanded_models: Set[str] = field(default_factory=set)
    header_suffix: Optional[str] = None
    # Maps model name -> list of (start_line, end_line, type) tuples
    expanded_locations: Dict[str, List[Tuple[int, int, str]]] = field(
        default_factory=dict
    )
    # Maps model name -> effective shrink level applied (none/soft/hard/max)
    model_shrink_levels: Dict[str, str] = field(default_factory=dict)
    # True if expanded content was skipped (agent mode)
    content_skipped: bool = False


@dataclass
class ScanResult:
    """
    Return type from scan_addon_files().

    Replaces the pattern of mutating passed-in dicts. Instead, callers
    receive this result and can merge it into their state explicitly.
    """

    found_files: List[Path] = field(default_factory=list)
    shrunken_content: Dict[Path, str] = field(default_factory=dict)
    shrunken_info: Dict[Path, Dict] = field(default_factory=dict)


@dataclass
class ExpansionState:
    """
    Groups all expansion-related state.

    This consolidates the scattered sets used during model expansion:
    - expand_models: Models that are fully expanded (not shrunk)
    - related_models: Models related to expanded models (neighbors)
    - enriched_additions: Models added via parent/child enrichment
    - new_related: Subset of related_models that are not in expand_models

    TODO: Consider using this dataclass in context.py instead of raw dicts/sets
    to improve type safety and self-documentation.
    """

    expand_models: Set[str] = field(default_factory=set)
    related_models: Set[str] = field(default_factory=set)
    enriched_additions: Set[str] = field(default_factory=set)
    new_related: Set[str] = field(default_factory=set)

    @property
    def relevant_models(self) -> Set[str]:
        """Returns the union of expanded and related models."""
        return self.expand_models | self.related_models


@dataclass
class ModelRelations:
    """
    Holds relationship data for a single Odoo model.

    Extracted from the all_relations dict pattern.
    """

    parents: Set[str] = field(default_factory=set)
    comodels: Set[str] = field(default_factory=set)


@dataclass
class DiscoveryResult:
    """
    Return type from the discovery pass.

    Contains the model relationship graph and per-addon model mapping
    built during the discovery phase.

    TODO: Consider using this dataclass in context.py instead of raw dicts
    to improve type safety and self-documentation.
    """

    # Maps model name -> ModelRelations
    all_relations: Dict[str, ModelRelations] = field(default_factory=dict)
    # Maps addon name -> set of model names defined in that addon
    addon_models: Dict[str, Set[str]] = field(default_factory=dict)
    # All model names discovered across all addons
    all_discovered_models: Set[str] = field(default_factory=set)
