"""
LLM Adapters - Pluggable LLM providers for X-Ray analysis
"""

from .base import LLMAdapter
from .cerebras import CerebrasAdapter
from .openai_adapter import OpenAIAdapter
from .anthropic_adapter import AnthropicAdapter
from .ollama import OllamaAdapter


def get_adapter(provider: str = None) -> LLMAdapter:
    """
    Factory function to get the appropriate LLM adapter.
    
    Args:
        provider: Provider name (cerebras, openai, anthropic, ollama)
                  Defaults to LLM_PROVIDER env var, then 'cerebras'
    
    Returns:
        LLMAdapter instance
    """
    import os
    
    if provider is None:
        provider = os.getenv('LLM_PROVIDER', 'cerebras').lower()
    
    adapters = {
        'cerebras': CerebrasAdapter,
        'openai': OpenAIAdapter,
        'anthropic': AnthropicAdapter,
        'ollama': OllamaAdapter,
    }
    
    adapter_class = adapters.get(provider)
    if not adapter_class:
        raise ValueError(f"Unknown LLM provider: {provider}. Available: {list(adapters.keys())}")
    
    return adapter_class()


__all__ = [
    'LLMAdapter',
    'CerebrasAdapter', 
    'OpenAIAdapter',
    'AnthropicAdapter',
    'OllamaAdapter',
    'get_adapter',
]
