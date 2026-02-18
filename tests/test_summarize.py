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
        # Should be at or near the budget (or at min sample size floor)
        assert size <= 500  # generous upper bound since min_sample hits

    def test_default_values(self):
        """Default Summarizer should have standard constants."""
        default = Summarizer()
        assert default.max_payload_size == 80000
        assert default.sample_size == 100
        assert default.min_sample_size == 10
        assert default.string_truncate == 2000
