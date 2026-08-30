from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    app_name: str = "InboxPilot"
    log_level: str = "INFO"
    openai_api_key: str | None = None
    nebius_api_key: str | None = None
    nebius_base_url: str | None = None
    nebius_model: str | None = None
    langsmith_api_key: str | None = None
    langsmith_tracing: bool = False
    langsmith_project: str | None = None
    gmail_token: str | None = None
    gmail_secret: str | None = None
    gmail_email: str | None = None
    google_calendar_id: str = "primary"
    mem0_api_key: str | None = None
    mem0_host: str | None = None


def load_settings(env_file: str | Path | None = None) -> Settings:
    if env_file is not None:
        load_dotenv(env_file, override=False)
    else:
        load_dotenv()

    return Settings(
        app_name=os.getenv("APP_NAME", "InboxPilot"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        nebius_api_key=os.getenv("NEBIUS_API_KEY"),
        nebius_base_url=os.getenv("NEBIUS_BASE_URL"),
        nebius_model=os.getenv("NEBIUS_MODEL"),
        langsmith_api_key=os.getenv("LANGSMITH_API_KEY"),
        langsmith_tracing=os.getenv("LANGSMITH_TRACING", "false").lower() == "true",
        langsmith_project=os.getenv("LANGSMITH_PROJECT"),
        gmail_token=os.getenv("GMAIL_TOKEN"),
        gmail_secret=os.getenv("GMAIL_SECRET"),
        gmail_email=os.getenv("GMAIL_EMAIL"),
        google_calendar_id=os.getenv("GOOGLE_CALENDAR_ID", "primary"),
        mem0_api_key=os.getenv("MEM0_API_KEY"),
        mem0_host=os.getenv("MEM0_HOST"),
    )
