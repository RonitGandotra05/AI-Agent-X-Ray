"""
Anthropic LLM Adapter
"""

import os
from typing import List, Dict
from .base import LLMAdapter


class AnthropicAdapter(LLMAdapter):
    """
    Adapter for Anthropic Claude API.
    
    Environment variables:
        ANTHROPIC_API_KEY: Required API key
        ANTHROPIC_MODEL: Model name (default: claude-3-5-sonnet-20241022)
    """
    
    def __init__(self):
        try:
            import anthropic
        except ImportError:
            raise ImportError("anthropic package required. Install with: pip install anthropic")
        
        self.api_key = os.getenv('ANTHROPIC_API_KEY')
        self._model = os.getenv('ANTHROPIC_MODEL', 'claude-3-5-sonnet-20241022')
        
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")
        
        self.client = anthropic.Anthropic(api_key=self.api_key)
    
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 1000
    ) -> str:
        # Anthropic uses a different message format - separate system from user messages
        system_msg = None
        user_messages = []
        
        for msg in messages:
            if msg['role'] == 'system':
                system_msg = msg['content']
            else:
                user_messages.append(msg)
        
        response = self.client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system_msg or "",
            messages=user_messages
        )
        return response.content[0].text
    
    @property
    def provider_name(self) -> str:
        return "anthropic"
    
    @property
    def model_name(self) -> str:
        return self._model
