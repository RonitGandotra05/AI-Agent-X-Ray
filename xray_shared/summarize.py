"""Deterministic, explicitly lossy sampling with a hard serialized-size bound."""

import json
from typing import Any

from .validation import positive_int


class Summarizer:
    """Preserve small JSON values; sample oversized values without an LLM call.

    Limits are JSON characters, not model tokens. Samples cannot prove that omitted
    records are correct. Original counts and omission metadata make that explicit.
    """

    DEFAULT_MAX_PAYLOAD_SIZE = 80000
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
        self.max_payload_size = positive_int(max_payload_size, "max_payload_size")
        if max_payload_size < 64:
            raise ValueError("max_payload_size must be at least 64 characters")
        self.sample_size = positive_int(sample_size, "sample_size")
        # Retained for compatibility; a hard budget may require fewer items.
        self.min_sample_size = positive_int(min_sample_size, "min_sample_size")
        self.string_truncate = positive_int(string_truncate, "string_truncate")

    @staticmethod
    def _size(data: Any) -> int:
        return len(json.dumps(data, allow_nan=False))

    @staticmethod
    def _sample(items, count):
        if len(items) <= count:
            return items
        head = (count + 1) // 2
        tail = count // 2
        return items[:head] + (items[-tail:] if tail else [])

    def ensure_within_budget(self, data: Any) -> Any:
        if data is None:
            return {}
        original_size = self._size(data)
        if original_size <= self.max_payload_size:
            return data
        count = self.sample_size
        string_limit = self.string_truncate
        while True:
            omissions = {"sampled": True, "original_chars": original_size}
            result = self._project(data, count, string_limit, omissions)
            # Never overwrite a caller's reserved-looking field.
            if isinstance(result, dict) and "_xray_summary" not in result:
                result["_xray_summary"] = omissions
            else:
                result = {"sample": result, "_xray_summary": omissions}
            if self._size(result) <= self.max_payload_size:
                return result
            if count == 1 and string_limit == 1:
                # Huge keys/deep shapes can still exceed budget. Explicitly omit
                # the sample instead of silently returning an oversized value.
                omitted = {"_xray_summary": {"omitted": True, "original_chars": original_size}}
                if self._size(omitted) > self.max_payload_size:
                    omitted = {"_xray_summary": {"omitted": True}}
                return omitted
            count = max(1, count // 2)
            string_limit = max(1, string_limit // 2)

    def _project(self, data: Any, count: int, string_limit: int, omissions: dict) -> Any:
        if isinstance(data, dict):
            keys = list(data)
            sampled_keys = self._sample(keys, count)
            if len(sampled_keys) < len(keys):
                omissions["omitted_fields"] = omissions.get("omitted_fields", 0) + len(keys) - len(sampled_keys)
            result = {}
            for key in sampled_keys:
                value = data[key]
                result[key] = self._project(value, count, string_limit, omissions)
                if isinstance(value, (list, tuple)) and len(value) > count:
                    count_key = f"{key}_total_count"
                    if count_key not in data:
                        result[count_key] = len(value)
                    else:
                        omissions["count_key_collisions"] = omissions.get("count_key_collisions", 0) + 1
            return result
        if isinstance(data, (list, tuple)):
            sampled = self._sample(data, count)
            if len(sampled) < len(data):
                omissions["omitted_items"] = omissions.get("omitted_items", 0) + len(data) - len(sampled)
                omissions.setdefault("original_items", len(data))
            return [self._project(item, count, string_limit, omissions) for item in sampled]
        if isinstance(data, str) and len(data) > string_limit:
            omissions["truncated_strings"] = omissions.get("truncated_strings", 0) + 1
            return f"{data[:string_limit]}...[truncated {len(data) - string_limit} chars]"
        return data
