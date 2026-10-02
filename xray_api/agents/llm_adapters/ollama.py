"""
Ollama LLM Adapter - Local LLM support
"""

import os
import requests
from typing import List, Dict, Tuple
from .base import LLMAdapter
from .openai_compatible import provider_options


class OllamaAdapter(LLMAdapter):
    """
    Adapter for Ollama (local LLM).
    
    No API key required - runs locally.
    
    Environment variables:
        OLLAMA_BASE_URL: Ollama server URL (default: http://localhost:11434)
        OLLAMA_MODEL: Model name (default: llama3)
    """
    
    def __init__(self):
        self.base_url = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434').rstrip('/')
        self._model = os.getenv('OLLAMA_MODEL', 'llama3')
        self.timeout, _ = provider_options()
        self.session = requests.Session()

    def _make_request(self, messages, temperature, max_tokens):
        """Shared request logic for both completion methods."""
        response = self.session.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self._model,
                "messages": messages,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens
                }
            },
            timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or data.get("done") is not True:
            raise ValueError("Ollama returned an incomplete response")
        if data.get("done_reason") not in (None, "stop"):
            raise ValueError(f"Ollama response was incomplete ({data.get('done_reason')})")
        content = data.get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Ollama returned empty text")
        return data
    
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 1000
    ) -> str:
        data = self._make_request(messages, temperature, max_tokens)
        return data['message']['content']

    def chat_completion_with_usage(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 1000
    ) -> Tuple[str, Dict[str, int]]:
        data = self._make_request(messages, temperature, max_tokens)
        usage = {}
        prompt_tokens = data.get('prompt_eval_count', 0)
        completion_tokens = data.get('eval_count', 0)
        if prompt_tokens or completion_tokens:
            usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            }
        return data['message']['content'], usage
    
    @property
    def provider_name(self) -> str:
        return "ollama"
    
    @property
    def model_name(self) -> str:
        return self._model
