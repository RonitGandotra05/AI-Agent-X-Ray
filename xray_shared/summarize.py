"""
Shared summarization utilities for X-Ray SDK and API.

Provides deterministic head/tail sampling of large data structures
to keep payloads within LLM context token limits.
"""

import json
import logging
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


class Summarizer:
    """
    Summarizes large data payloads using head/tail sampling.
    
    Used by both the SDK (client-side) and API (server-side safety net)
    to keep step inputs/outputs within the LLM's token context window.
    """
    
    DEFAULT_MAX_PAYLOAD_SIZE = 80000   # chars per step side (~20K tokens)
    DEFAULT_SAMPLE_SIZE = 100
    DEFAULT_MIN_SAMPLE_SIZE = 10
    DEFAULT_STRING_TRUNCATE = 2000
    
    def __init__(
        self,
        max_payload_size: int = DEFAULT_MAX_PAYLOAD_SIZE,
        sample_size: int = DEFAULT_SAMPLE_SIZE,
        min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
        string_truncate: int = DEFAULT_STRING_TRUNCATE,
    ):
        self.max_payload_size = max_payload_size
        self.sample_size = sample_size
        self.min_sample_size = min_sample_size
        self.string_truncate = string_truncate
    
    def ensure_within_budget(self, data: Any) -> Any:
        """Return data as-is if small enough, otherwise summarize it."""
        if data is None:
            return {}
        try:
            size = len(json.dumps(data, default=str))
        except Exception:
            size = self.max_payload_size + 1
        if size <= self.max_payload_size:
            return data
        logger.info("Summarizing large payload: %d chars -> MAX %d chars", size, self.max_payload_size)
        summarized = self._summarize_with_budget(data)
        new_size = len(json.dumps(summarized, default=str))
        logger.info("Summarization complete: %d -> %d chars", size, new_size)
        return summarized

    def _summarize_with_budget(self, data: Any) -> Any:
        """Iteratively summarize until payload fits under max_payload_size."""
        sample_size = self.sample_size
        summarized = data
        while True:
            summarized = self._summarize_once(summarized, sample_size)
            size = len(json.dumps(summarized, default=str))
            if size <= self.max_payload_size or sample_size <= self.min_sample_size:
                return summarized
            sample_size = max(self.min_sample_size, sample_size // 2)

    def _summarize_once(self, data: Any, sample_size: int) -> Any:
        """One-pass summarization with recursion and string truncation."""
        if isinstance(data, dict):
            summarized = {}
            for key, value in data.items():
                if isinstance(value, list):
                    summarized_list, total_count = self._summarize_list(value, sample_size)
                    summarized[key] = summarized_list
                    if total_count is not None:
                        summarized[f"{key}_total_count"] = total_count
                else:
                    summarized[key] = self._summarize_once(value, sample_size)
            return summarized
        if isinstance(data, list):
            summarized_list, _ = self._summarize_list(data, sample_size)
            return summarized_list
        if isinstance(data, str) and len(data) > self.string_truncate:
            overflow = len(data) - self.string_truncate
            return f"{data[:self.string_truncate]}...[truncated {overflow} chars]"
        return data

    def _summarize_list(self, items: List[Any], sample_size: int) -> Tuple[List[Any], Optional[int]]:
        """Summarize a list: sample if large, recurse into elements."""
        total_count = None
        if len(items) > sample_size:
            total_count = len(items)
            head_count = sample_size // 2
            tail_count = sample_size - head_count
            items = items[:head_count] + items[-tail_count:]
        return [self._summarize_once(item, sample_size) for item in items], total_count
