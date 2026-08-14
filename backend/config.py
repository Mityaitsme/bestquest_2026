"""Конфигурация приложения, загружаемая из переменных окружения."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

DEFAULT_SECRET_KEY = "dev-secret-key"
DEFAULT_DEBUG = "false"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = "5000"
DEFAULT_SUPABASE_URL = ""
DEFAULT_SUPABASE_SERVICE_KEY = ""
DEFAULT_OPENAI_API_KEY = ""
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_TELEGRAM_BOT_TOKEN = ""
DEFAULT_TELEGRAM_CHAT_ID = ""


@dataclass(frozen=True)
class Config:
    """Настройки Flask-приложения."""

    secret_key: str
    debug: bool
    host: str
    port: int
    supabase_url: str
    supabase_service_key: str
    openai_api_key: str
    openai_model: str
    telegram_bot_token: str
    telegram_chat_id: str


def load_config() -> Config:
    """Собрать конфигурацию из переменных окружения (.env для локальной разработки)."""
    return Config(
        secret_key=os.environ.get("FLASK_SECRET_KEY", DEFAULT_SECRET_KEY),
        debug=os.environ.get("FLASK_DEBUG", DEFAULT_DEBUG).lower() == "true",
        host=os.environ.get("FLASK_HOST", DEFAULT_HOST),
        port=int(os.environ.get("FLASK_PORT", DEFAULT_PORT)),
        supabase_url=os.environ.get("SUPABASE_URL", DEFAULT_SUPABASE_URL),
        supabase_service_key=os.environ.get(
            "SUPABASE_SERVICE_KEY", DEFAULT_SUPABASE_SERVICE_KEY
        ),
        openai_api_key=os.environ.get("OPENAI_API_KEY", DEFAULT_OPENAI_API_KEY),
        openai_model=os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
        telegram_bot_token=os.environ.get(
            "TELEGRAM_BOT_TOKEN", DEFAULT_TELEGRAM_BOT_TOKEN
        ),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", DEFAULT_TELEGRAM_CHAT_ID),
    )
