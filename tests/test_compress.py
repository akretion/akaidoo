"""Tests for akaidoo.compress module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from akaidoo.compress import (
    _build_user_prompt,
    _extract_json,
    call_compress_llm,
    merge_compress_options,
    resolve_task_description,
)
from akaidoo.types import CompressRecommendation


# ─── resolve_task_description ────────────────────────────────────────────────


class TestResolveTaskDescription:
    def test_literal_string(self):
        """When the value is not a file path, return it as-is."""
        result = resolve_task_description("Fix the sale.order onchange method")
        assert result == "Fix the sale.order onchange method"

    def test_file_path(self, tmp_path):
        """When the value points to a file, return its content."""
        task_file = tmp_path / "my_task.txt"
        task_file.write_text("Migrate account_move to v18\nKeep all validators.")
        result = resolve_task_description(str(task_file))
        assert result == "Migrate account_move to v18\nKeep all validators."

    def test_nonexistent_file_treated_as_string(self):
        """A path that doesn't exist is treated as a literal string."""
        result = resolve_task_description("/no/such/file.txt")
        assert result == "/no/such/file.txt"

    def test_empty_string(self):
        assert resolve_task_description("") == ""


# ─── _build_user_prompt ─────────────────────────────────────────────────────


class TestBuildUserPrompt:
    def test_contains_task_and_context(self):
        prompt = _build_user_prompt(
            "Fix the sale order", "# FILEPATH: sale.py\nclass Sale: pass"
        )
        assert "## Developer Task" in prompt
        assert "Fix the sale order" in prompt
        assert "## Full Odoo Context" in prompt
        assert "# FILEPATH: sale.py" in prompt

    def test_token_estimate_shown(self):
        """The prompt should show an approximate token count label."""
        context_dump = "x" * 10000  # ~2.7k tokens
        prompt = _build_user_prompt("task", context_dump)
        assert "k tokens" in prompt


# ─── _extract_json ───────────────────────────────────────────────────────────


class TestExtractJson:
    def test_raw_json(self):
        raw = '{"reasoning": "remove web addons", "exclude_addons": ["web"]}'
        result = _extract_json(raw)
        assert result["reasoning"] == "remove web addons"
        assert result["exclude_addons"] == ["web"]

    def test_markdown_fenced_json(self):
        raw = '```json\n{"reasoning": "test", "shrink": "hard"}\n```'
        result = _extract_json(raw)
        assert result["reasoning"] == "test"
        assert result["shrink"] == "hard"

    def test_markdown_fenced_no_lang(self):
        raw = '```\n{"reasoning": "no lang tag"}\n```'
        result = _extract_json(raw)
        assert result["reasoning"] == "no lang tag"

    def test_json_embedded_in_text(self):
        """JSON surrounded by extra text should still be extracted."""
        raw = 'Here is my recommendation:\n{"reasoning": "embedded", "exclude_addons": ["mail"]}\nHope this helps!'
        result = _extract_json(raw)
        assert result["reasoning"] == "embedded"
        assert result["exclude_addons"] == ["mail"]

    def test_malformed_json_raises(self):
        with pytest.raises(ValueError, match="Could not parse JSON"):
            _extract_json("this is not json at all")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            _extract_json("")

    def test_whitespace_around_json(self):
        raw = '  \n  {"reasoning": "whitespace"}  \n  '
        result = _extract_json(raw)
        assert result["reasoning"] == "whitespace"


# ─── merge_compress_options ──────────────────────────────────────────────────


class TestMergeCompressOptions:
    def test_empty_recommendation(self):
        """An empty recommendation should not change any options."""
        rec = CompressRecommendation()
        merged = merge_compress_options(
            rec=rec,
            original_exclude_str=None,
            original_rm_expand_str=None,
            original_expand_str=None,
            original_prune_methods_str=None,
            original_shrink_mode="soft",
        )
        assert merged["exclude_addons_str"] is None
        assert merged["rm_expand_str"] is None
        assert merged["expand_models_str"] is None
        assert merged["prune_methods_str"] is None
        assert merged["shrink_mode"] == "soft"

    def test_exclude_addons_additive(self):
        """LLM's exclude_addons are appended to the user's."""
        rec = CompressRecommendation(exclude_addons=["web", "mail"])
        merged = merge_compress_options(
            rec=rec,
            original_exclude_str="portal",
            original_rm_expand_str=None,
            original_expand_str=None,
            original_prune_methods_str=None,
            original_shrink_mode="soft",
        )
        excludes = set(merged["exclude_addons_str"].split(","))
        assert excludes == {"mail", "portal", "web"}

    def test_exclude_addons_from_none(self):
        """When user had no excludes, LLM's become the full set."""
        rec = CompressRecommendation(exclude_addons=["digest", "bus"])
        merged = merge_compress_options(
            rec=rec,
            original_exclude_str=None,
            original_rm_expand_str=None,
            original_expand_str=None,
            original_prune_methods_str=None,
            original_shrink_mode="soft",
        )
        excludes = set(merged["exclude_addons_str"].split(","))
        assert excludes == {"bus", "digest"}

    def test_rm_expand_additive(self):
        rec = CompressRecommendation(rm_expand=["res.partner"])
        merged = merge_compress_options(
            rec=rec,
            original_exclude_str=None,
            original_rm_expand_str="sale.order",
            original_expand_str=None,
            original_prune_methods_str=None,
            original_shrink_mode="soft",
        )
        rm_models = set(merged["rm_expand_str"].split(","))
        assert rm_models == {"res.partner", "sale.order"}

    def test_expand_replaces_only_when_user_didnt_specify(self):
        """LLM expand only takes effect if user didn't use --expand."""
        rec = CompressRecommendation(expand=["account.move", "sale.order"])

        # User did NOT specify --expand => LLM's replaces
        merged = merge_compress_options(
            rec=rec,
            original_exclude_str=None,
            original_rm_expand_str=None,
            original_expand_str=None,
            original_prune_methods_str=None,
            original_shrink_mode="soft",
        )
        assert merged["expand_models_str"] == "account.move,sale.order"

        # User DID specify --expand => LLM's is ignored
        merged2 = merge_compress_options(
            rec=rec,
            original_exclude_str=None,
            original_rm_expand_str=None,
            original_expand_str="purchase.order",
            original_prune_methods_str=None,
            original_shrink_mode="soft",
        )
        assert merged2["expand_models_str"] == "purchase.order"

    def test_prune_methods_additive(self):
        rec = CompressRecommendation(prune_methods=["sale.order._compute_total"])
        merged = merge_compress_options(
            rec=rec,
            original_exclude_str=None,
            original_rm_expand_str=None,
            original_expand_str=None,
            original_prune_methods_str="res.partner.name_get",
            original_shrink_mode="soft",
        )
        pruned = set(merged["prune_methods_str"].split(","))
        assert pruned == {"res.partner.name_get", "sale.order._compute_total"}

    def test_shrink_only_escalates(self):
        """Shrink should only escalate (never relax)."""
        rec = CompressRecommendation(shrink="hard")

        # soft -> hard: escalation accepted
        merged = merge_compress_options(
            rec=rec,
            original_exclude_str=None,
            original_rm_expand_str=None,
            original_expand_str=None,
            original_prune_methods_str=None,
            original_shrink_mode="soft",
        )
        assert merged["shrink_mode"] == "hard"

        # hard -> soft (via rec): relaxation rejected
        rec_relax = CompressRecommendation(shrink="soft")
        merged2 = merge_compress_options(
            rec=rec_relax,
            original_exclude_str=None,
            original_rm_expand_str=None,
            original_expand_str=None,
            original_prune_methods_str=None,
            original_shrink_mode="hard",
        )
        assert merged2["shrink_mode"] == "hard"

    def test_shrink_none_to_max(self):
        rec = CompressRecommendation(shrink="max")
        merged = merge_compress_options(
            rec=rec,
            original_exclude_str=None,
            original_rm_expand_str=None,
            original_expand_str=None,
            original_prune_methods_str=None,
            original_shrink_mode="none",
        )
        assert merged["shrink_mode"] == "max"

    def test_shrink_same_level_no_change(self):
        rec = CompressRecommendation(shrink="medium")
        merged = merge_compress_options(
            rec=rec,
            original_exclude_str=None,
            original_rm_expand_str=None,
            original_expand_str=None,
            original_prune_methods_str=None,
            original_shrink_mode="medium",
        )
        assert merged["shrink_mode"] == "medium"

    def test_shrink_none_recommendation(self):
        """If LLM doesn't recommend shrink (None), original is kept."""
        rec = CompressRecommendation(shrink=None)
        merged = merge_compress_options(
            rec=rec,
            original_exclude_str=None,
            original_rm_expand_str=None,
            original_expand_str=None,
            original_prune_methods_str=None,
            original_shrink_mode="soft",
        )
        assert merged["shrink_mode"] == "soft"

    def test_deduplication_in_exclude(self):
        """Same addon in both user and LLM lists should not duplicate."""
        rec = CompressRecommendation(exclude_addons=["web", "mail"])
        merged = merge_compress_options(
            rec=rec,
            original_exclude_str="web,portal",
            original_rm_expand_str=None,
            original_expand_str=None,
            original_prune_methods_str=None,
            original_shrink_mode="soft",
        )
        excludes = merged["exclude_addons_str"].split(",")
        assert len(excludes) == len(set(excludes)), "No duplicates expected"
        assert set(excludes) == {"mail", "portal", "web"}


# ─── call_compress_llm ───────────────────────────────────────────────────────


class TestCallCompressLlm:
    def test_import_error_when_litellm_missing(self):
        """Should raise ImportError with helpful message if litellm not installed."""
        with patch.dict("sys.modules", {"litellm": None}):
            with pytest.raises(ImportError, match="litellm"):
                call_compress_llm("task", "context")

    def test_successful_call(self):
        """Mock litellm.completion and verify the returned CompressRecommendation."""
        response_json = json.dumps(
            {
                "reasoning": "Removing web modules",
                "exclude_addons": ["web", "web_editor"],
                "shrink": "medium",
            }
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = response_json

        with patch("akaidoo.compress.completion", create=True):
            # We need to patch the import inside the function
            mock_litellm = MagicMock()
            mock_litellm.completion = MagicMock(return_value=mock_response)

            with patch.dict("sys.modules", {"litellm": mock_litellm}):
                rec = call_compress_llm("Fix sale order", "# context dump")

        assert isinstance(rec, CompressRecommendation)
        assert rec.reasoning == "Removing web modules"
        assert rec.exclude_addons == ["web", "web_editor"]
        assert rec.shrink == "medium"

    def test_invalid_shrink_value_ignored(self):
        """If LLM returns an invalid shrink value, it should be set to None."""
        response_json = json.dumps(
            {
                "reasoning": "testing",
                "shrink": "ultra_mega_shrink",
            }
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = response_json

        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(return_value=mock_response)

        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            rec = call_compress_llm("task", "context")

        assert rec.shrink is None

    def test_unparseable_response_returns_default(self):
        """If LLM returns garbage, we get a default CompressRecommendation."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "I cannot help with that."

        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(return_value=mock_response)

        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            rec = call_compress_llm("task", "context")

        assert isinstance(rec, CompressRecommendation)
        assert rec.reasoning == "LLM response could not be parsed"
        assert rec.exclude_addons == []

    def test_model_from_env_var(self):
        """AKAIDOO_COMPRESS_MODEL env var should override the default."""
        response_json = json.dumps({"reasoning": "env test"})
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = response_json

        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(return_value=mock_response)

        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            with patch.dict(
                "os.environ", {"AKAIDOO_COMPRESS_MODEL": "openai/gpt-4o-mini"}
            ):
                call_compress_llm("task", "context")
                # Verify the model passed to completion
                call_kwargs = mock_litellm.completion.call_args
                assert call_kwargs[1]["model"] == "openai/gpt-4o-mini"

    def test_model_param_overrides_env(self):
        """Explicit model parameter should override env var."""
        response_json = json.dumps({"reasoning": "param test"})
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = response_json

        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(return_value=mock_response)

        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            with patch.dict(
                "os.environ", {"AKAIDOO_COMPRESS_MODEL": "openai/gpt-4o-mini"}
            ):
                call_compress_llm("task", "context", model="anthropic/claude-haiku")
                call_kwargs = mock_litellm.completion.call_args
                assert call_kwargs[1]["model"] == "anthropic/claude-haiku"
