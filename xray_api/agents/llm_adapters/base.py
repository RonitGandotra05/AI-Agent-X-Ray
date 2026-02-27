"""
Base LLM Adapter - Abstract interface for LLM providers
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Tuple


class LLMAdapter(ABC):
    """
    Abstract base class for LLM providers.
    
    All LLM adapters must implement the chat_completion method.
    Adapters that can return token usage should also override
    chat_completion_with_usage for cost tracking.
    """
    
    @abstractmethod
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 1000
    ) -> str:
        """
        Send a chat completion request to the LLM.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens in response
            
        Returns:
            The LLM's response text
        """
        pass

    def chat_completion_with_usage(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 1000
    ) -> Tuple[str, Dict[str, int]]:
        """
        Send a chat completion and return token usage alongside response.
        
        Override in subclasses to extract real token counts from the
        provider's response. Default falls back to chat_completion.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens in response
            
        Returns:
            Tuple of (response_text, usage_dict) where usage_dict contains
            prompt_tokens, completion_tokens, total_tokens (all optional)
        """
        text = self.chat_completion(messages, temperature, max_tokens)
        return text, {}
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the name of this provider (e.g., 'cerebras', 'openai')"""
        pass
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model being used"""
        pass

