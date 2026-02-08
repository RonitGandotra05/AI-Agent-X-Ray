"""
Cerebras LLM Adapter
"""

import os
from typing import List, Dict
from openai import OpenAI
from .base import LLMAdapter


class CerebrasAdapter(LLMAdapter):
    """
    Adapter for Cerebras API (uses OpenAI-compatible client).
    
    Environment variables:
        CEREBRAS_API_KEY: Required API key
        CEREBRAS_BASE_URL: API endpoint (default: https://api.cerebras.ai/v1)
        CEREBRAS_MODEL: Model name (default: llama-3.3-70b)
    """
    
    def __init__(self):
        self.api_key = os.getenv('CEREBRAS_API_KEY')
        self.base_url = os.getenv('CEREBRAS_BASE_URL', 'https://api.cerebras.ai/v1')
        self._model = os.getenv('CEREBRAS_MODEL', 'llama-3.3-70b')
        
        if not self.api_key:
            raise ValueError("CEREBRAS_API_KEY environment variable not set")
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
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
    
    @property
    def provider_name(self) -> str:
        return "cerebras"
    
    @property
    def model_name(self) -> str:
        return self._model
