"""Базовый чат: персонажи, чаты команды, сообщения.

Свободный текст команда может отправлять только в режимах operator/gpt.
В режиме scripted вместо текста используется отдельный механизм —
см. backend/dialogue.py (узлы/варианты ответа); режим gpt пока не даёт
автоматического ответа ChatGPT — это отдельный, ещё не реализованный шаг.
"""

from __future__ import annotations

from supabase_client import get_supabase_client

CHAT_MODES = ("scripted", "operator", "gpt", "muted")
TEAM_SENDABLE_MODES = ("operator", "gpt")


class ChatError(Exception):
    """Ожидаемая ошибка (чата нет у команды, режим не позволяет писать и т.п.)."""


def seed_team_chats(team_id: str) -> None:
    """При регистрации команды: чат с каждым персонажем + один чат техподдержки."""
    client = get_supabase_client()
    characters = client.table("characters").select("id").execute().data

    rows = [
        {"team_id": team_id, "character_id": c["id"], "chat_type": "character"}
        for c in characters
    ]
    rows.append({"team_id": team_id, "character_id": None, "chat_type": "support"})

    client.table("chats").insert(rows).execute()


def list_team_chats(team_id: str) -> list[dict]:
    client = get_supabase_client()
    return (
        client.table("chats")
        .select("id, chat_type, mode, characters(name, nickname)")
        .eq("team_id", team_id)
        .execute()
        .data
    )


def _get_own_chat(client, chat_id: str, team_id: str) -> dict:
    chat = (
        client.table("chats")
        .select("*")
        .eq("id", chat_id)
        .eq("team_id", team_id)
        .execute()
        .data
    )
    if not chat:
        raise ChatError("Такого чата нет у этой команды")
    return chat[0]


def get_character_id_for_chat(team_id: str, chat_id: str) -> str:
    """Для маршрутов скриптованного диалога: chat_id -> character_id, с проверкой
    что чат принадлежит команде и это действительно чат с персонажем."""
    client = get_supabase_client()
    chat = _get_own_chat(client, chat_id, team_id)
    if chat["chat_type"] != "character":
        raise ChatError("У чата техподдержки нет диалога с персонажем")
    return chat["character_id"]


def list_messages(team_id: str, chat_id: str) -> list[dict]:
    client = get_supabase_client()
    _get_own_chat(client, chat_id, team_id)
    return (
        client.table("messages")
        .select("id, sender_type, content, message_kind, created_at")
        .eq("chat_id", chat_id)
        .order("created_at")
        .execute()
        .data
    )


def list_new_messages_since(team_id: str, since: str) -> list[dict]:
    """Для лёгкого polling-опроса на фронтенде команды (уведомления о новых
    сообщениях): не от самой команды, во всех её чатах, появившиеся после
    `since` (ISO-время последнего опроса). Отдаём только chat_id/sender_type/
    created_at — этого достаточно, чтобы фронтенд понял, в каком чате
    появилось новое и стоит ли тихонько обновить открытый сейчас чат или
    показать тост; сам текст сообщения довеpяем обычной загрузке чата."""
    client = get_supabase_client()
    chat_ids = [
        row["id"] for row in client.table("chats").select("id").eq("team_id", team_id).execute().data
    ]
    if not chat_ids:
        return []

    return (
        client.table("messages")
        .select("chat_id, sender_type, created_at")
        .in_("chat_id", chat_ids)
        .neq("sender_type", "team")
        .gt("created_at", since)
        .order("created_at")
        .execute()
        .data
    )


def send_team_message(team_id: str, chat_id: str, content: str) -> dict:
    """Возвращает {"mode": ..., "character_id": ...} — чтобы вызывающий код
    мог решить, нужно ли после этого запускать автоответ ChatGPT (mode == 'gpt')."""
    client = get_supabase_client()
    chat = _get_own_chat(client, chat_id, team_id)
    if chat["mode"] not in TEAM_SENDABLE_MODES:
        raise ChatError(f"В этом чате сейчас нельзя писать (режим: {chat['mode']})")

    message_kind = "support_comment" if chat["chat_type"] == "support" else "normal"
    client.table("messages").insert(
        {
            "chat_id": chat_id,
            "sender_type": "team",
            "content": content,
            "message_kind": message_kind,
        }
    ).execute()

    return {"mode": chat["mode"], "character_id": chat["character_id"]}


def list_characters() -> list[dict]:
    """Все игровые персонажи-боты — чтобы оператор выбрал, чьи чаты смотреть."""
    client = get_supabase_client()
    return client.table("characters").select("id, name, nickname").order("name").execute().data


def _chats_overview(client, chat_type: str, character_id: str | None = None) -> list[dict]:
    """Чаты одного типа (support/character) по ВСЕМ командам сразу, каждый —
    с именем команды, временем последнего сообщения и needs_reply (правда,
    если последнее сообщение — от команды, то есть ей ещё не ответили),
    отсортированные от самого недавнего к самому старому (чаты без единого
    сообщения — в конце)."""
    query = client.table("chats").select("id, team_id, mode, teams(name)").eq("chat_type", chat_type)
    if character_id is not None:
        query = query.eq("character_id", character_id)
    chats = query.execute().data

    chat_ids = [c["id"] for c in chats]
    last_message_by_chat: dict[str, dict] = {}
    if chat_ids:
        messages = (
            client.table("messages")
            .select("chat_id, created_at, sender_type")
            .in_("chat_id", chat_ids)
            .order("created_at", desc=True)
            .execute()
            .data
        )
        for message in messages:
            last_message_by_chat.setdefault(message["chat_id"], message)

    overview = [
        {
            "id": chat["id"],
            "team_id": chat["team_id"],
            "team_name": chat["teams"]["name"] if chat["teams"] else "?",
            "mode": chat["mode"],
            "last_message_at": last_message_by_chat.get(chat["id"], {}).get("created_at"),
            "needs_reply": last_message_by_chat.get(chat["id"], {}).get("sender_type") == "team",
        }
        for chat in chats
    ]
    overview.sort(key=lambda c: c["last_message_at"] or "", reverse=True)
    return overview


def list_support_chats_overview() -> list[dict]:
    """Раздел 'Техподдержка' в админке: чаты техподдержки всех команд сразу."""
    client = get_supabase_client()
    return _chats_overview(client, "support")


def list_character_chats_overview(character_id: str) -> list[dict]:
    """Раздел 'Диалоги' в админке: чаты конкретного персонажа-бота со всеми
    командами сразу (выбор персонажа — на фронтенде)."""
    client = get_supabase_client()
    return _chats_overview(client, "character", character_id)


def list_messages_admin(chat_id: str) -> list[dict]:
    client = get_supabase_client()
    return (
        client.table("messages")
        .select("id, sender_type, content, message_kind, created_at")
        .eq("chat_id", chat_id)
        .order("created_at")
        .execute()
        .data
    )


def send_admin_message(admin_id: str, chat_id: str, content: str) -> None:
    client = get_supabase_client()
    chat_rows = client.table("chats").select("*").eq("id", chat_id).execute().data
    if not chat_rows:
        raise ChatError("Такого чата нет")
    chat = chat_rows[0]

    if chat["mode"] != "operator":
        raise ChatError(f"Отвечать можно только в режиме operator (сейчас: {chat['mode']})")

    sender_type = "admin" if chat["chat_type"] == "support" else "character"
    message_kind = "support_comment" if chat["chat_type"] == "support" else "normal"

    client.table("messages").insert(
        {
            "chat_id": chat_id,
            "sender_type": sender_type,
            "sender_admin_id": admin_id,
            "content": content,
            "message_kind": message_kind,
        }
    ).execute()


def set_chat_mode(chat_id: str, mode: str) -> None:
    if mode not in CHAT_MODES:
        raise ChatError(f"Недопустимый режим: {mode}, должен быть одним из {CHAT_MODES}")

    client = get_supabase_client()
    result = client.table("chats").update({"mode": mode}).eq("id", chat_id).execute()
    if not result.data:
        raise ChatError("Такого чата нет")
