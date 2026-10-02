"""Tests for the shared Summarizer utility."""

import json
from xray_shared.summarize import Summarizer


class TestSummarizer:
    """Unit tests for Summarizer."""

    def setup_method(self):
        self.summarizer = Summarizer(
            max_payload_size=1000,
            sample_size=10,
            min_sample_size=2,
            string_truncate=50,
        )

    def test_small_data_passes_through(self):
        """Data under budget should be returned unchanged."""
        data = {"key": "value", "count": 42}
        result = self.summarizer.ensure_within_budget(data)
        assert result == data

    def test_none_becomes_empty_dict(self):
        result = self.summarizer.ensure_within_budget(None)
        assert result == {}

    def test_large_list_gets_sampled(self):
        """Lists exceeding sample_size should be head/tail sampled."""
        # Each item is ~30 chars, 100 items = ~3000 chars, well over our 1000 budget
        data = {"items": [{"id": i, "val": f"item_{i}"} for i in range(100)]}
        result = self.summarizer.ensure_within_budget(data)
        # Should have total_count added and list trimmed
        assert "items_total_count" in result
        assert result["items_total_count"] == 100
        assert len(result["items"]) <= 10

    def test_long_string_gets_truncated(self):
        """Strings exceeding string_truncate should be cut."""
        # 2000 chars, well over the 1000 budget and 50 char truncate limit
        data = {"text": "a" * 2000}
        result = self.summarizer.ensure_within_budget(data)
        assert "truncated" in result["text"]
        assert len(result["text"]) < 2000

    def test_nested_dict_summarization(self):
        """Nested structures should be recursively summarized."""
        data = {
            "outer": {
                "inner_list": [{"id": i, "val": f"item_{i}"} for i in range(100)],
                "inner_text": "b" * 2000,
            }
        }
        result = self.summarizer.ensure_within_budget(data)
        assert len(result["outer"]["inner_list"]) <= 10
        assert "truncated" in result["outer"]["inner_text"]

    def test_iterative_budget_reduction(self):
        """When first pass is still too large, sample_size should decrease."""
        # Make max_payload_size very small to force multiple passes
        tiny = Summarizer(max_payload_size=100, sample_size=20, min_sample_size=2, string_truncate=20)
        data = {"items": [{"id": i, "name": f"item_{i}" * 10} for i in range(100)]}
        result = tiny.ensure_within_budget(data)
        size = len(json.dumps(result, default=str))
        assert size <= 100

    def test_wide_dictionary_and_huge_keys_are_bounded(self):
        for data in ({str(i): "x" * 200 for i in range(2000)}, {"k" * 2000: "x"}):
            result = self.summarizer.ensure_within_budget(data)
            assert len(json.dumps(result)) <= 1000
            assert "_xray_summary" in result

    def test_repeated_passes_preserve_original_list_count(self):
        data = {"items": [{"data": "x" * 500} for _ in range(1000)]}
        result = self.summarizer.ensure_within_budget(data)
        assert result["items_total_count"] == 1000
        assert result["_xray_summary"]["original_items"] == 1000

    def test_user_count_field_is_not_overwritten(self):
        data = {"items": ["a" * 50] * 100, "items_total_count": 999}
        result = self.summarizer.ensure_within_budget(data)
        assert result["items_total_count"] == 999
        assert result["_xray_summary"]["count_key_collisions"] == 1

    def test_head_tail_sampling_one_item_keeps_head(self):
        result = Summarizer(max_payload_size=1000, sample_size=1).ensure_within_budget({"items": list(range(1000))})
        assert result["items"] == [0]
        assert result["items_total_count"] == 1000

    def test_unicode_escaped_size_is_bounded(self):
        result = self.summarizer.ensure_within_budget({"text": "🚀" * 10000})
        assert len(json.dumps(result)) <= 1000

    def test_input_is_never_modified(self):
        data = {"items": list(range(1000))}
        self.summarizer.ensure_within_budget(data)
        assert len(data["items"]) == 1000
        assert "items_total_count" not in data

    def test_minimum_budget_is_strict(self):
        result = Summarizer(max_payload_size=64).ensure_within_budget({"k" * 1000: "x"})
        assert len(json.dumps(result)) <= 64

    def test_default_values(self):
        """Default Summarizer should have standard constants."""
        default = Summarizer()
        assert default.max_payload_size == 80000
        assert default.sample_size == 100
        assert default.min_sample_size == 10
        assert default.string_truncate == 2000
