"""
OpenRouter LLM Adapter
"""

import os
from typing import List, Dict, Tuple
from openai import OpenAI
from .base import LLMAdapter


class OpenRouterAdapter(LLMAdapter):
    """
    Adapter for OpenRouter API (OpenAI-compatible).
    
    OpenRouter provides access to many models (Claude, GPT, Llama, Mistral, etc.)
    through a unified API.
    
    Environment variables:
        OPENROUTER_API_KEY: Required API key
        OPENROUTER_MODEL: Model name (default: anthropic/claude-3.5-sonnet)
    
    Popular models:
        - anthropic/claude-3.5-sonnet
        - openai/gpt-4o
        - google/gemini-pro-1.5
        - meta-llama/llama-3.1-70b-instruct
        - mistralai/mistral-large
    """
    
    def __init__(self):
        self.api_key = os.getenv('OPENROUTER_API_KEY')
        self._model = os.getenv('OPENROUTER_MODEL', 'anthropic/claude-3.5-sonnet')
        
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable not set")
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://openrouter.ai/api/v1"
        )
    
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 1000
    ) -> str:
        response = self.client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        return response.choices[0].message.content

    def chat_completion_with_usage(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 1000
    ) -> Tuple[str, Dict[str, int]]:
        response = self.client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens or 0,
                "completion_tokens": response.usage.completion_tokens or 0,
                "total_tokens": response.usage.total_tokens or 0,
            }
        return response.choices[0].message.content, usage
    
    @property
    def provider_name(self) -> str:
        return "openrouter"
    
    @property
    def model_name(self) -> str:
        return self._model

