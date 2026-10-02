"""Shared transport for providers implementing the Chat Completions API."""

import math
import os
from typing import Dict, List, Tuple

from .base import LLMAdapter


def provider_options() -> Tuple[float, int]:
    """Bound provider calls explicitly; provider SDKs own their retry loop."""
    try:
        timeout = float(os.getenv("XRAY_LLM_TIMEOUT", "20"))
        retries = int(os.getenv("XRAY_LLM_MAX_RETRIES", "0"))
    except ValueError as exc:
        raise ValueError("XRAY_LLM_TIMEOUT and XRAY_LLM_MAX_RETRIES must be numbers") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("XRAY_LLM_TIMEOUT must be a positive finite number")
    if not 0 <= retries <= 5:
        raise ValueError("XRAY_LLM_MAX_RETRIES must be between 0 and 5")
    return timeout, retries


class OpenAICompatibleAdapter(LLMAdapter):
    """Reuse one provider client and validate its response before analysis."""

    PROVIDER = "openai"
    DEFAULT_MODEL = "gpt-4o-mini"
    DEFAULT_BASE_URL = None
    JSON_MODE = True

    def __init__(self):
        prefix = self.PROVIDER.upper()
        api_key = os.getenv(f"{prefix}_API_KEY")
        if not api_key:
            raise ValueError(f"{prefix}_API_KEY environment variable not set")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError("Install xray-sdk[openai] to use OpenAI-compatible providers") from exc
        timeout, retries = provider_options()
        self.api_key = api_key
        self._model = os.getenv(f"{prefix}_MODEL", self.DEFAULT_MODEL)
        self.base_url = os.getenv(f"{prefix}_BASE_URL", self.DEFAULT_BASE_URL)
        options = {"api_key": api_key, "timeout": timeout, "max_retries": retries}
        if self.base_url:
            options["base_url"] = self.base_url
        self.client = OpenAI(**options)

    def chat_completion(self, messages: List[Dict[str, str]], temperature: float = 0.1,
                        max_tokens: int = 1000) -> str:
        return self.chat_completion_with_usage(messages, temperature, max_tokens)[0]

    def chat_completion_with_usage(self, messages: List[Dict[str, str]],
                                   temperature: float = 0.1,
                                   max_tokens: int = 1000) -> Tuple[str, Dict[str, int]]:
        options = {"model": self._model, "messages": messages, "temperature": temperature,
                   "max_tokens": max_tokens}
        if self.JSON_MODE and os.getenv("XRAY_LLM_JSON_MODE", "true").lower() in ("1", "true", "yes"):
            options["response_format"] = {"type": "json_object"}
        if self.PROVIDER == "cerebras" and self._model == "gpt-oss-120b":
            options["extra_body"] = {"reasoning_effort": "low"}
        response = self.client.chat.completions.create(**options)
        if not response.choices:
            raise ValueError("LLM returned no choices")
        choice = response.choices[0]
        if choice.finish_reason != "stop":
            raise ValueError(f"LLM response was incomplete ({choice.finish_reason})")
        if getattr(choice.message, "refusal", None):
            raise ValueError("LLM declined to analyze this run")
        content = choice.message.content
        if not isinstance(content, str) or not content.strip():
            raise ValueError("LLM returned empty text")
        usage = {}
        if response.usage:
            usage = {key: getattr(response.usage, key, 0) or 0 for key in
                     ("prompt_tokens", "completion_tokens", "total_tokens")}
            details = getattr(response.usage, "prompt_tokens_details", None)
            if details is not None:
                usage["cached_tokens"] = getattr(details, "cached_tokens", 0) or 0
        return content, usage

    @property
    def provider_name(self) -> str:
        return self.PROVIDER

    @property
    def model_name(self) -> str:
        return self._model
