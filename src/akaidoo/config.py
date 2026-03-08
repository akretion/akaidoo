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

# --- Agent Mode ---
# Expanded model classes whose source range is <= this many lines are inlined
# directly into background.md instead of being listed as read_file instructions.
# This avoids a round-trip tool call for tiny extensions.
AGENT_INLINE_THRESHOLD: int = 300

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

# --- Compress-for-Prompt (2-Pass Workflow) ---
# Default LLM model for the compression pass (litellm provider/model string).
# Override with AKAIDOO_COMPRESS_MODEL env var.
COMPRESS_DEFAULT_MODEL: str = "gemini/gemini-3.0-flash"

# System prompt template for the compression LLM.
# {task} is replaced with the user's task description.
# {context} is replaced with the full Pass 1 context dump.
COMPRESS_SYSTEM_PROMPT: str = """\
You are an expert Odoo developer assistant. You are given a large Odoo codebase \
context dump and a developer task. Your job is to recommend akaidoo CLI filter \
options that will reduce the context to only what is relevant for the task.

The goal is to achieve a 2x-3x reduction in context size while keeping everything \
the developer needs to accomplish their task. Be aggressive in pruning irrelevant \
modules and models, but NEVER remove something the developer will need.

You MUST output ONLY a valid JSON object with these fields (all optional, omit \
fields you don't want to change):

{
  "reasoning": "Brief explanation of your filtering decisions",
  "exclude_addons": ["addon1", "addon2"],
  "rm_expand": ["model.name1", "model.name2"],
  "expand": ["model.name1", "model.name2"],
  "prune_methods": ["model.name.method_name"],
  "shrink": "soft"
}

Rules:
- "exclude_addons": addons to EXCLUDE from the dependency tree. Only exclude addons \
whose code is clearly irrelevant to the task. NEVER exclude the target addon(s) or \
addons containing models directly referenced in the task.
- "rm_expand": models to REMOVE from the auto-expand set. These models will be \
shrunk instead of shown in full. Use this for models that were auto-expanded but \
are not relevant to the task.
- "expand": explicit list of models to expand (REPLACES auto-expand). Use this \
only if you want to be very selective. If you use this, ONLY these models will be \
expanded. Prefer "rm_expand" for surgical removal.
- "prune_methods": specific methods to prune in format "model.name.method_name". \
Use for large methods that are clearly not relevant. Be conservative here - the \
developer may need to trace call paths.
- "shrink": overall shrink level. One of: "none", "soft", "medium", "hard", "max". \
Only change if the context is still too large after other filters.
- "reasoning": briefly explain WHY you chose these filters.

IMPORTANT:
- Do NOT use both "expand" and "rm_expand" - pick one approach.
- Prefer "rm_expand" (subtractive) over "expand" (explicit) for safety.
- When in doubt, keep a model/addon rather than removing it.
- The developer task description is the primary guide for relevance.
"""
