"""OpenAI adapter; configure OPENAI_API_KEY/MODEL/BASE_URL."""
from .openai_compatible import OpenAICompatibleAdapter


class OpenAIAdapter(OpenAICompatibleAdapter):
    PROVIDER = "openai"
    DEFAULT_MODEL = "gpt-4o-mini"
