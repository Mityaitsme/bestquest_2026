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


@dataclass(frozen=True)
class Config:
    """Настройки Flask-приложения."""

    secret_key: str
    debug: bool
    host: str
    port: int


def load_config() -> Config:
    """Собрать конфигурацию из переменных окружения (.env для локальной разработки)."""
    return Config(
        secret_key=os.environ.get("FLASK_SECRET_KEY", DEFAULT_SECRET_KEY),
        debug=os.environ.get("FLASK_DEBUG", DEFAULT_DEBUG).lower() == "true",
        host=os.environ.get("FLASK_HOST", DEFAULT_HOST),
        port=int(os.environ.get("FLASK_PORT", DEFAULT_PORT)),
    )
