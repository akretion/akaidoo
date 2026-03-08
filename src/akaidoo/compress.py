"""
Akaidoo Compress Module

Implements the 2-pass "compress-for-prompt" workflow:
  Pass 1 – Run akaidoo with user options, dump full context to a string.
  LLM    – Send context + task to a fast/cheap LLM (default: Gemini Flash)
           and ask it to recommend filter options.
  Pass 2 – Re-run akaidoo with the recommended filters applied on top
           of the user's original options.

The LLM call is provider-agnostic via litellm.
"""

import json
import os
import re
from pathlib import Path
from typing import Optional

from manifestoo import echo

from .config import COMPRESS_DEFAULT_MODEL, COMPRESS_SYSTEM_PROMPT, TOKEN_FACTOR
from .types import CompressRecommendation


def resolve_task_description(compress_task: str) -> str:
    """
    Resolve a task description from either a file path or a literal string.

    If ``compress_task`` points to an existing file, its content is returned.
    Otherwise the string itself is used as the task description.
    """
    task_path = Path(compress_task)
    if task_path.is_file():
        try:
            return task_path.read_text(encoding="utf-8")
        except Exception:
            # Fall through to use the string as-is
            pass
    return compress_task


def _build_user_prompt(task_description: str, context_dump: str) -> str:
    """Build the user message that contains the task + the full Pass 1 dump."""
    tokens_est = int(len(context_dump) * TOKEN_FACTOR / 1000)
    return (
        f"## Developer Task\n\n{task_description}\n\n"
        f"## Full Odoo Context ({tokens_est}k tokens)\n\n"
        f"{context_dump}"
    )


def _extract_json(raw_text: str) -> dict:
    """
    Extract the first JSON object from *raw_text*.

    The LLM may wrap its answer in markdown fences (```json ... ```).
    We try several strategies in order:
      1. Direct ``json.loads`` on the full text.
      2. Strip markdown fences and try again.
      3. Regex for the first ``{ ... }`` block.
    """
    # 1. Try direct parse
    text = raw_text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Strip markdown fences
    if text.startswith("```"):
        # Remove opening fence (```json or ```)
        text = re.sub(r"^```(?:json)?\s*\n?", "", text, count=1)
        text = re.sub(r"\n?```\s*$", "", text, count=1)
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

    # 3. Regex for first JSON object
    match = re.search(r"\{[\s\S]*\}", raw_text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from LLM response:\n{raw_text[:500]}")


def call_compress_llm(
    task_description: str,
    context_dump: str,
    model: Optional[str] = None,
) -> CompressRecommendation:
    """
    Call the LLM to get compression recommendations.

    Args:
        task_description: What the developer wants to do.
        context_dump: Full Pass 1 context dump (string).
        model: litellm model string (default from config / env var).

    Returns:
        A CompressRecommendation with the LLM's filter suggestions.

    Raises:
        ImportError: If litellm is not installed.
        Exception: On LLM API errors (surfaced to caller for reporting).
    """
    try:
        from litellm import completion
    except ImportError:
        raise ImportError(
            "The 'litellm' package is required for --compress-task.\n"
            "Install it with: pip install akaidoo[compress]"
        )

    model = model or os.environ.get("AKAIDOO_COMPRESS_MODEL") or COMPRESS_DEFAULT_MODEL

    user_prompt = _build_user_prompt(task_description, context_dump)

    echo.info(f"Compress: calling {model} with ~{len(context_dump) // 1000}k chars...")

    response = completion(
        model=model,
        messages=[
            {"role": "system", "content": COMPRESS_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        # Gemini Flash supports up to 1M input tokens; keep output concise
        max_tokens=4096,
        temperature=0.1,
    )

    raw_text = response.choices[0].message.content or ""
    echo.debug(f"Compress: LLM raw response:\n{raw_text}")

    try:
        data = _extract_json(raw_text)
    except ValueError as e:
        echo.warning(f"Compress: failed to parse LLM response: {e}")
        return CompressRecommendation(reasoning="LLM response could not be parsed")

    # Build recommendation, tolerating missing / extra keys
    rec = CompressRecommendation(
        reasoning=data.get("reasoning", ""),
        exclude_addons=data.get("exclude_addons", []),
        rm_expand=data.get("rm_expand", []),
        expand=data.get("expand", []),
        prune_methods=data.get("prune_methods", []),
        shrink=data.get("shrink"),
    )

    # Validate shrink value
    valid_shrinks = {"none", "soft", "medium", "hard", "max"}
    if rec.shrink and rec.shrink not in valid_shrinks:
        echo.warning(
            f"Compress: LLM suggested invalid shrink '{rec.shrink}', ignoring."
        )
        rec.shrink = None

    return rec


def merge_compress_options(
    rec: CompressRecommendation,
    original_exclude_str: Optional[str],
    original_rm_expand_str: Optional[str],
    original_expand_str: Optional[str],
    original_prune_methods_str: Optional[str],
    original_shrink_mode: str,
) -> dict:
    """
    Merge LLM recommendations with the user's original CLI options.

    The LLM's suggestions are *additive* to user-specified filters:
    - exclude_addons: appended to the user's --exclude list.
    - rm_expand: appended to the user's --rm-expand list.
    - expand: REPLACES auto-expand only if user didn't specify --expand.
    - prune_methods: appended to the user's --prune-methods.
    - shrink: only applied if it's more aggressive than the user's.

    Returns a dict with keys matching the CLI option names:
      exclude_addons_str, rm_expand_str, expand_models_str,
      prune_methods_str, shrink_mode
    """
    # Merge exclude_addons
    excludes = set()
    if original_exclude_str:
        excludes.update(a.strip() for a in original_exclude_str.split(","))
    if rec.exclude_addons:
        excludes.update(rec.exclude_addons)
    merged_exclude = ",".join(sorted(excludes)) if excludes else original_exclude_str

    # Merge rm_expand
    rm_expands = set()
    if original_rm_expand_str:
        rm_expands.update(m.strip() for m in original_rm_expand_str.split(","))
    if rec.rm_expand:
        rm_expands.update(rec.rm_expand)
    merged_rm_expand = (
        ",".join(sorted(rm_expands)) if rm_expands else original_rm_expand_str
    )

    # Merge expand (LLM expand only applies if user didn't set --expand)
    merged_expand = original_expand_str
    if rec.expand and not original_expand_str:
        merged_expand = ",".join(rec.expand)

    # Merge prune_methods
    prune_methods = set()
    if original_prune_methods_str:
        prune_methods.update(m.strip() for m in original_prune_methods_str.split(","))
    if rec.prune_methods:
        prune_methods.update(rec.prune_methods)
    merged_prune = (
        ",".join(sorted(prune_methods)) if prune_methods else original_prune_methods_str
    )

    # Merge shrink (only escalate, never relax)
    shrink_order = ["none", "soft", "medium", "hard", "max"]
    merged_shrink = original_shrink_mode
    if rec.shrink:
        try:
            orig_idx = shrink_order.index(original_shrink_mode)
            rec_idx = shrink_order.index(rec.shrink)
            if rec_idx > orig_idx:
                merged_shrink = rec.shrink
        except ValueError:
            pass

    return {
        "exclude_addons_str": merged_exclude,
        "rm_expand_str": merged_rm_expand,
        "expand_models_str": merged_expand,
        "prune_methods_str": merged_prune,
        "shrink_mode": merged_shrink,
    }
