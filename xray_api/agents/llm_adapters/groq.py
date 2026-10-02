"""Groq adapter; configure GROQ_API_KEY/MODEL/BASE_URL."""
from .openai_compatible import OpenAICompatibleAdapter


class GroqAdapter(OpenAICompatibleAdapter):
    PROVIDER = "groq"
    DEFAULT_MODEL = "llama-3.3-70b-versatile"
    DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
