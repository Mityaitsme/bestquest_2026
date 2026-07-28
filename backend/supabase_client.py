"""Клиент Supabase для серверной стороны (backend)."""

from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from config import load_config


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """Создать и закэшировать клиент Supabase.

    Использует service role key, который обходит Row Level Security —
    этот клиент предназначен только для backend и не должен передаваться
    во фронтенд (там будет отдельный клиент на anon key, см. следующие этапы).
    """
    config = load_config()
    return create_client(config.supabase_url, config.supabase_service_key)
