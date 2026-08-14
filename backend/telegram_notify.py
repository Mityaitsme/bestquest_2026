"""Уведомления в Telegram-чат админов о новых событиях, требующих внимания
оператора/актёра: заявка на проверку, блок-пост, новое сообщение команды в
чате (техподдержка или диалог с персонажем в режиме operator — сценарные
диалоги и GPT-режим оператора не отвлекают).

Каждое событие — одно сообщение от бота; когда событие разрешается (заявка
принята/отклонена, блок-пост отвечен, оператор ответил в чате), бот удаляет
своё же сообщение, чтобы в чате оставались только реально висящие дела —
если сообщений много, это сигнал, что ответственные не справляются.

Fire-and-forget: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID могут быть не настроены
(тогда всё тихо no-op) или Telegram может быть временно недоступен — это
никогда не должно ронять основное действие команды/оператора, только
логируется в stderr.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from config import load_config
from supabase_client import get_supabase_client

API_URL = "https://api.telegram.org/bot{token}/{method}"
REQUEST_TIMEOUT_SECONDS = 5
# Москва не переходит на летнее время с 2014 года - фиксированный сдвиг
# проще и надёжнее, чем zoneinfo (на Windows требует отдельного пакета tzdata).
MOSCOW_TZ = timezone(timedelta(hours=3))


def _now_hhmm() -> str:
    return datetime.now(MOSCOW_TZ).strftime("%H:%M")


def _call(method: str, payload: dict, token: str) -> dict | None:
    url = API_URL.format(token=token, method=method)
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        print(f"[telegram_notify] {method} failed: {exc}")
        return None

    if not result.get("ok"):
        print(f"[telegram_notify] {method} returned ok=false: {result}")
    return result


def _notify(kind: str, event_key: str, text: str) -> None:
    """Отправить сообщение и запомнить его id — но только если по этому
    (kind, event_key) ещё нет висящего уведомления (чтобы несколько
    сообщений команды подряд в один и тот же чат не плодили дубликаты)."""
    config = load_config()
    if not config.telegram_bot_token or not config.telegram_chat_id:
        return

    client = get_supabase_client()
    existing = (
        client.table("telegram_notifications")
        .select("id")
        .eq("kind", kind)
        .eq("event_key", event_key)
        .execute()
        .data
    )
    if existing:
        return

    result = _call(
        "sendMessage",
        {"chat_id": config.telegram_chat_id, "text": text},
        config.telegram_bot_token,
    )
    if not result or not result.get("ok"):
        return

    try:
        client.table("telegram_notifications").insert(
            {
                "kind": kind,
                "event_key": event_key,
                "telegram_message_id": result["result"]["message_id"],
            }
        ).execute()
    except Exception as exc:  # noqa: BLE001 — граница с внешним сервисом, не роняем вызывающий код
        print(f"[telegram_notify] failed to store tracking row: {exc}")


def _resolve(kind: str, event_key: str) -> None:
    """Удалить уведомление(-я) для этого события, если есть."""
    config = load_config()
    if not config.telegram_bot_token or not config.telegram_chat_id:
        return

    client = get_supabase_client()
    rows = (
        client.table("telegram_notifications")
        .select("id, telegram_message_id")
        .eq("kind", kind)
        .eq("event_key", event_key)
        .execute()
        .data
    )
    for row in rows:
        _call(
            "deleteMessage",
            {"chat_id": config.telegram_chat_id, "message_id": row["telegram_message_id"]},
            config.telegram_bot_token,
        )
        client.table("telegram_notifications").delete().eq("id", row["id"]).execute()


# ---- Публичные функции по каждому виду события ----


def notify_review_submitted(review_id: str, team_name: str, stage_title: str) -> None:
    _notify(
        "review",
        review_id,
        f"{_now_hhmm()}: Новая заявка на проверку от команды «{team_name}»! "
        f"Задание: «{stage_title}»",
    )


def notify_review_resolved(review_id: str) -> None:
    _resolve("review", review_id)


def notify_block_post_created(
    team_id: str, character_id: str, team_name: str, character_name: str
) -> None:
    _notify(
        "block_post",
        f"{team_id}:{character_id}",
        f"{_now_hhmm()}: Блок-пост ждёт ответа — команда «{team_name}», "
        f"персонаж «{character_name}»",
    )


def notify_block_post_resolved(team_id: str, character_id: str) -> None:
    _resolve("block_post", f"{team_id}:{character_id}")


def notify_if_block_post(client, team_id: str, character_id: str, node_id: str | None) -> None:
    """Общая проверка для мест, где диалог может "приземлиться" на
    блок-пост (обычный переход по next_node_id и телепорт через
    resumes_dialogue_at) — если узел блок-постовый, шлёт уведомление."""
    if not node_id:
        return
    node = client.table("dialogue_nodes").select("is_block_post").eq("id", node_id).execute().data
    if not node or not node[0]["is_block_post"]:
        return

    team = client.table("teams").select("name").eq("id", team_id).execute().data
    character = client.table("characters").select("name").eq("id", character_id).execute().data
    notify_block_post_created(
        team_id,
        character_id,
        team[0]["name"] if team else "?",
        character[0]["name"] if character else "?",
    )


def notify_chat_message(
    chat_id: str, team_name: str, chat_type: str, character_name: str | None
) -> None:
    if chat_type == "support":
        label = "в техподдержку"
    else:
        label = f"в диалоге с «{character_name}»" if character_name else "в диалоге"
    _notify(
        "chat",
        chat_id,
        f"{_now_hhmm()}: Новое сообщение {label} от команды «{team_name}»!",
    )


def notify_chat_resolved(chat_id: str) -> None:
    _resolve("chat", chat_id)
