"""Клиент Supabase для серверной стороны (backend).

Два независимых фикса перемежающейся сетевой ошибки (httpx.ReadError
[WinError 10054] "удалённый хост разорвал соединение"), которая тянулась
с ранних этапов проекта:

1. Клиент больше не кэшируется на весь процесс (раньше был @lru_cache) —
   httpx держал keep-alive TCP-соединение в пуле, Supabase закрывал его на
   своей стороне после простоя, httpx продолжал считать его годным. Новый
   клиент на каждый вызов исключает саму возможность переиспользовать
   протухшее соединение — ценой одного лишнего TCP/TLS-рукопожатия на
   вызов, для нагрузки этого проекта несущественно.

2. Даже со свежим клиентом одиночный сетевой обрыв всё ещё изредка
   возможен — а бизнес-операции часто состоят из НЕСКОЛЬКИХ независимых
   .execute()-вызовов подряд (проверить статус, обновить его, разблокировать
   зависимые этапы...). Обрыв ровно между такими вызовами оставляет
   операцию "наполовину применённой" без единой видимой ошибки, кроме 500
   в ответе — например, этап помечался выполненным, но разблокировка
   следующего не происходила. Первая версия фикса вручную оборачивала
   retry_on_transient_error() вокруг конкретных вызовов — но это легко
   забыть в новом месте (и забывали дважды). Вместо этого патчим сам
   SyncQueryRequestBuilder.execute() один раз здесь — это единственный
   метод, через который проходят ВСЕ вызовы .table(...).execute() во всём
   проекте (select/insert/update/upsert/delete — общий базовый класс), так
   что повтор при обрыве соединения теперь встроен в сам клиент и не
   зависит от того, вспомнили ли обернуть конкретный вызов.
"""

from __future__ import annotations

import time

import httpx
from postgrest._sync.request_builder import SyncQueryRequestBuilder
from supabase import Client, create_client

from config import load_config

RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 0.3

_original_execute = SyncQueryRequestBuilder.execute


def _execute_with_retry(self, *args, **kwargs):
    last_error: Exception | None = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            return _original_execute(self, *args, **kwargs)
        except httpx.TransportError as exc:
            last_error = exc
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
    assert last_error is not None
    raise last_error


SyncQueryRequestBuilder.execute = _execute_with_retry


def get_supabase_client() -> Client:
    """Создать клиент Supabase (заново на каждый вызов — см. модульный docstring)."""
    config = load_config()
    return create_client(config.supabase_url, config.supabase_service_key)
