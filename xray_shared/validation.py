"""Small, dependency-free validators shared by capture and transport code."""

import json
import math
from typing import Any


def positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def name_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise ValueError(f"{name} must be a non-empty string of at most 255 characters")
    return value


def json_snapshot(value: Any, name: str = "data") -> Any:
    """Validate JSON and detach caller state without silently coercing objects."""
    active = set()

    def check(item: Any, depth: int) -> None:
        if depth > 64:
            raise ValueError(f"{name} exceeds the maximum nesting depth (64)")
        if isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ValueError(f"{name} must contain valid Unicode strings") from exc
            return
        if item is None or isinstance(item, (bool, int)):
            return
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError(f"{name} must contain only finite numbers")
            return
        if not isinstance(item, (dict, list, tuple)):
            raise ValueError(f"{name} must be JSON serializable; got {type(item).__name__}")
        identity = id(item)
        if identity in active:
            raise ValueError(f"{name} contains a circular reference")
        active.add(identity)
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError(f"{name} must contain only string dictionary keys")
                check(key, depth + 1)
                check(child, depth + 1)
        else:
            for child in item:
                check(child, depth + 1)
        active.remove(identity)

    check(value, 0)
    try:
        return json.loads(json.dumps(value, allow_nan=False, ensure_ascii=False))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be JSON serializable: {exc}") from exc
