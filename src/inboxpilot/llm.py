from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI

from inboxpilot.config import Settings


class ModelFactory:
    """Create a model client using either OpenAI or Nebius-compatible API."""

    @staticmethod
    def create(settings: Settings) -> Any:
        if settings.nebius_api_key:
            return ChatOpenAI(
                model=settings.nebius_model or "meta/llama-3.1-70b-instruct",
                api_key=settings.nebius_api_key,
                base_url=settings.nebius_base_url or "https://api.tokenfactory.nebius.com/v1/",
                temperature=0.0,
            )

        if settings.openai_api_key:
            return ChatOpenAI(
                model="gpt-4.1-mini",
                api_key=settings.openai_api_key,
                temperature=0.0,
            )

        raise RuntimeError("No model API key configured. Set either OPENAI_API_KEY or NEBIUS_API_KEY.")
