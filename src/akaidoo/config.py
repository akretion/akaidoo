"""
Akaidoo Configuration Module

Centralizes all constants, thresholds, and configuration values used across the package.
"""

from typing import Dict, List, Tuple

# --- Token Estimation ---
TOKEN_FACTOR = 0.27  # Empirical factor to estimate tokens from character count

# --- Mode Definitions ---
SHRINK_MODES: List[str] = ["none", "soft", "medium", "hard", "max"]

# --- Framework Addons ---
# These addons are excluded by default as they are part of the Odoo framework
# and typically don't need to be included in context dumps for module development.
FRAMEWORK_ADDONS: Tuple[str, ...] = (
    "base",
    "web",
    "web_editor",
    "web_tour",
    "portal",
    "mail",
    "digest",
    "bus",
    "auth_signup",
    "base_setup",
    "http_routing",
    "utm",
    "uom",
    "product",
)

# --- Auto-Expansion Configuration ---
AUTO_EXPAND_THRESHOLD = 7  # Score threshold for auto-expanding models
PARENT_CHILD_AUTO_EXPAND = True  # Whether to auto-expand parent/child (.line) models

# Models that should never be auto-expanded (too generic/noisy)
BLACKLIST_AUTO_EXPAND: Tuple[str, ...] = (
    "res.users",
    "res.groups",
    "res.company",
    "res.partner",
    "mail.thread",
    "mail.activity.mixin",
    "portal.mixin",
    "ir.ui.view",
    "ir.model",
    "ir.model.fields",
    "ir.model.data",
    "ir.attachment",
    "res.config.settings",
    "utm.mixin",
)

# Models whose relations should not trigger expansion (too common)
BLACKLIST_RELATION_EXPAND: Tuple[str, ...] = (
    "ir.attachment",
    "mail.activity.mixin",
    "mail.thread",
    "portal.mixin",
    "res.company",
    "res.currency",
    "res.partner",
    "res.partner.bank",
    "resource.calendar",
    "resource.resource",
    "sequence.mixin",
    "uom.uom",
    "utm.mixin",
)

# --- File Scanning Configuration ---
# Binary file extensions to skip during directory scans
BINARY_EXTS: Tuple[str, ...] = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".svg",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".pdf",
    ".map",
)

# Maximum size for data files before truncation (20KB)
MAX_DATA_FILE_SIZE = 20 * 1024

# --- Budget Escalation Levels ---
# Defines the progression of shrink_mode to try
# when context exceeds budget. Each level is more aggressive than the previous.
BUDGET_ESCALATION_LEVELS: List[str] = [
    "soft",  # Level 0
    "medium",  # Level 1
    "hard",  # Level 2
    "max",  # Level 3
]

# --- Shrink Matrix ---
# Defines how aggressively to shrink files based on:
# - File category (Target vs Dependency, Expanded vs Related vs Other)
# - Overall shrink effort level
#
# Categories:
#   T_EXP: Target addon, Expanded model
#   T_OTH: Target addon, Other (non-expanded) model
#   D_EXP: Dependency addon, Expanded model
#   D_REL: Dependency addon, Related model
#   D_OTH: Dependency addon, Other model
#
# Shrink levels: none, soft, hard, max, prune (prune = keep skeleton only)
SHRINK_MATRIX: Dict[str, Dict[str, str]] = {
    "none": {
        "T_EXP": "none",
        "T_OTH": "none",
        "D_EXP": "none",
        "D_REL": "none",
        "D_OTH": "none",
    },
    "soft": {
        "T_EXP": "none",
        "T_OTH": "none",
        "D_EXP": "none",
        "D_REL": "soft",
        "D_OTH": "max",
    },
    "medium": {
        "T_EXP": "none",
        "T_OTH": "soft",
        "D_EXP": "none",
        "D_REL": "max",
        "D_OTH": "prune",
    },
    "hard": {
        "T_EXP": "none",
        "T_OTH": "soft",
        "D_EXP": "soft",
        "D_REL": "max",
        "D_OTH": "prune",
    },
    "max": {
        "T_EXP": "none",
        "T_OTH": "soft",
        "D_EXP": "max",
        "D_REL": "max",
        "D_OTH": "prune",
    },
}
