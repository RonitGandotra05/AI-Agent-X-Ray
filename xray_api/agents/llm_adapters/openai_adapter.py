"""
OpenAI LLM Adapter
"""

import os
from typing import List, Dict, Tuple
from openai import OpenAI
from .base import LLMAdapter


class OpenAIAdapter(LLMAdapter):
    """
    Adapter for OpenAI API.
    
    Environment variables:
        OPENAI_API_KEY: Required API key
        OPENAI_MODEL: Model name (default: gpt-4o-mini)
    """
    
    def __init__(self):
        self.api_key = os.getenv('OPENAI_API_KEY')
        self._model = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
        
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        
        self.client = OpenAI(api_key=self.api_key)
    
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
        return "openai"
    
    @property
    def model_name(self) -> str:
        return self._model

