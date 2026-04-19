"""Factory that returns the configured LLM client.

Centralizes the "which provider?" decision. Agent code just asks the
factory for a client — it doesn't care whether it's OpenAI, Claude,
or a local model.
"""
from functools import lru_cache

from app.config import get_settings
from app.llm.interface import LLMClient
from app.llm.openai_client import OpenAIClient


@lru_cache
def get_llm_client() -> LLMClient:
    """Return the configured LLM client.

    Cached so we don't instantiate a new AsyncOpenAI (and its connection
    pool) on every request.
    """
    settings = get_settings()
    # Today: always OpenAI. Tomorrow: branch on settings.llm_provider
    return OpenAIClient(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.openai_model,
    )