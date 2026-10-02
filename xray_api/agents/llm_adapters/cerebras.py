"""Cerebras adapter; configure CEREBRAS_API_KEY/MODEL/BASE_URL."""
from .openai_compatible import OpenAICompatibleAdapter


class CerebrasAdapter(OpenAICompatibleAdapter):
    PROVIDER = "cerebras"
    DEFAULT_MODEL = "gpt-oss-120b"
    DEFAULT_BASE_URL = "https://api.cerebras.ai/v1"
