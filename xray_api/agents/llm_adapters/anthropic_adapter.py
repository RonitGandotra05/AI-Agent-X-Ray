"""Anthropic Messages adapter with bounded calls and checked completion."""

import os
from typing import Dict, List, Tuple
from .base import LLMAdapter
from .openai_compatible import provider_options


class AnthropicAdapter(LLMAdapter):
    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError("Install xray-sdk[anthropic] to use Anthropic") from exc
        self._model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        timeout, retries = provider_options()
        self.client = anthropic.Anthropic(api_key=self.api_key, timeout=timeout, max_retries=retries)

    def _prepare_messages(self, messages):
        return "\n".join(m["content"] for m in messages if m["role"] == "system"), [
            m for m in messages if m["role"] != "system"
        ]

    def chat_completion(self, messages: List[Dict[str, str]], temperature: float = 0.1,
                        max_tokens: int = 1000) -> str:
        return self.chat_completion_with_usage(messages, temperature, max_tokens)[0]

    def chat_completion_with_usage(self, messages: List[Dict[str, str]],
                                   temperature: float = 0.1,
                                   max_tokens: int = 1000) -> Tuple[str, Dict[str, int]]:
        system, user_messages = self._prepare_messages(messages)
        response = self.client.messages.create(model=self._model, max_tokens=max_tokens,
                                               temperature=temperature, system=system,
                                               messages=user_messages)
        if response.stop_reason != "end_turn":
            raise ValueError(f"LLM response was incomplete ({response.stop_reason})")
        text = "".join(block.text for block in response.content if block.type == "text")
        if not text.strip():
            raise ValueError("LLM returned empty text")
        usage = {}
        if response.usage:
            input_tokens = response.usage.input_tokens or 0
            output_tokens = response.usage.output_tokens or 0
            cached = getattr(response.usage, "cache_read_input_tokens", 0) or 0
            written = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
            usage = {"prompt_tokens": input_tokens + cached + written,
                     "completion_tokens": output_tokens,
                     "total_tokens": input_tokens + cached + written + output_tokens,
                     "cached_tokens": cached}
        return text, usage

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        return self._model
