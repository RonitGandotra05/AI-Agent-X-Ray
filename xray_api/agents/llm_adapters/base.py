"""
Base LLM Adapter - Abstract interface for LLM providers
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any


class LLMAdapter(ABC):
    """
    Abstract base class for LLM providers.
    
    All LLM adapters must implement the chat_completion method.
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
