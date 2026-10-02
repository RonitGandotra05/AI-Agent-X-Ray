"""OpenRouter adapter; configure OPENROUTER_API_KEY/MODEL/BASE_URL."""
from .openai_compatible import OpenAICompatibleAdapter


class OpenRouterAdapter(OpenAICompatibleAdapter):
    PROVIDER = "openrouter"
    DEFAULT_MODEL = "openai/gpt-4o-mini"
    DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
