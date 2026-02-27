"""
Anthropic LLM Adapter
"""

import os
from typing import List, Dict, Tuple
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

    def _prepare_messages(self, messages):
        """Split system message from user messages (Anthropic format)."""
        system_msg = None
        user_messages = []
        for msg in messages:
            if msg['role'] == 'system':
                system_msg = msg['content']
            else:
                user_messages.append(msg)
        return system_msg, user_messages
    
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 1000
    ) -> str:
        system_msg, user_messages = self._prepare_messages(messages)
        response = self.client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system_msg or "",
            messages=user_messages
        )
        return response.content[0].text

    def chat_completion_with_usage(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 1000
    ) -> Tuple[str, Dict[str, int]]:
        system_msg, user_messages = self._prepare_messages(messages)
        response = self.client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system_msg or "",
            messages=user_messages
        )
        usage = {}
        if hasattr(response, 'usage') and response.usage:
            usage = {
                "prompt_tokens": getattr(response.usage, 'input_tokens', 0),
                "completion_tokens": getattr(response.usage, 'output_tokens', 0),
                "total_tokens": getattr(response.usage, 'input_tokens', 0)
                    + getattr(response.usage, 'output_tokens', 0),
            }
        return response.content[0].text, usage
    
    @property
    def provider_name(self) -> str:
        return "anthropic"
    
    @property
    def model_name(self) -> str:
        return self._model

