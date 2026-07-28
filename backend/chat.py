"""Базовый чат: персонажи, чаты команды, сообщения.

Пока только режимы operator/muted реально функциональны для отправки:
scripted (скриптованный диалог) и gpt (авто-ответ ChatGPT) — это
отдельные, ещё не реализованные механизмы; чат можно переключить в эти
режимы, но команда в них может только читать, пока соответствующая
логика не появится.
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


def send_team_message(team_id: str, chat_id: str, content: str) -> None:
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


def list_team_chats_admin(team_id: str) -> list[dict]:
    client = get_supabase_client()
    return (
        client.table("chats")
        .select("id, chat_type, mode, characters(name, nickname)")
        .eq("team_id", team_id)
        .execute()
        .data
    )


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
