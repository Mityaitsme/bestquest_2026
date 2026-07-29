"""Скриптованный диалог: узлы с вариантами ответа, ветвление, блок-посты,
механика "выберите все варианты".

Выбор варианта, помимо продвижения по диалогу, всегда добавляет 2 записи
в общую историю чата (messages из chat.py) — реплику команды и ответ
персонажа — чтобы скриптованные и свободные сообщения были видны в одной
ленте.
"""

from __future__ import annotations

from datetime import datetime, timezone

from supabase_client import get_supabase_client

CHOSEN_OPTION_SENDER = "team"
REPLY_SENDER = "character"


class DialogueError(Exception):
    """Ожидаемая ошибка (не тот узел/вариант, диалог не начат и т.п.)."""


def seed_team_dialogue_state(team_id: str) -> None:
    """При регистрации команды: стартовый узел диалога для каждого персонажа,
    у которого он есть (диалог мог быть ещё не написан — тогда просто пропускаем)."""
    client = get_supabase_client()
    start_nodes = (
        client.table("dialogue_nodes")
        .select("id, character_id")
        .eq("is_start", True)
        .execute()
        .data
    )
    if not start_nodes:
        return

    rows = [
        {"team_id": team_id, "character_id": node["character_id"], "current_node_id": node["id"]}
        for node in start_nodes
    ]
    client.table("team_dialogue_state").insert(rows).execute()


def _get_state(client, team_id: str, character_id: str) -> dict | None:
    rows = (
        client.table("team_dialogue_state")
        .select("current_node_id")
        .eq("team_id", team_id)
        .eq("character_id", character_id)
        .execute()
        .data
    )
    return rows[0] if rows else None


def get_dialogue_state(team_id: str, character_id: str) -> dict:
    """Текущий узел диалога команды с персонажем: текст узла + доступные варианты."""
    client = get_supabase_client()

    state = _get_state(client, team_id, character_id)
    if not state or not state["current_node_id"]:
        return {"finished": True, "intro_message": "", "options": []}

    node_id = state["current_node_id"]
    node = client.table("dialogue_nodes").select("*").eq("id", node_id).execute().data[0]

    options = (
        client.table("dialogue_options")
        .select("id, content_key, option_text")
        .eq("node_id", node_id)
        .execute()
        .data
    )

    if node["requires_all_options"]:
        used = {
            row["option_id"]
            for row in client.table("team_dialogue_used_options")
            .select("option_id")
            .eq("team_id", team_id)
            .in_("option_id", [o["id"] for o in options])
            .execute()
            .data
        }
        options = [o for o in options if o["id"] not in used]

    return {
        "finished": False,
        "node_id": node_id,
        "intro_message": node["intro_message"],
        "options": [{"id": o["id"], "text": o["option_text"]} for o in options],
    }


def choose_option(team_id: str, character_id: str, option_id: str) -> dict:
    """Команда выбирает вариант ответа. Возвращает реплику персонажа и новое состояние."""
    client = get_supabase_client()

    state = _get_state(client, team_id, character_id)
    if not state or not state["current_node_id"]:
        raise DialogueError("Диалог с этим персонажем сейчас не активен")

    option_rows = (
        client.table("dialogue_options").select("*").eq("id", option_id).execute().data
    )
    if not option_rows:
        raise DialogueError("Такого варианта ответа нет")
    option = option_rows[0]
    if option["node_id"] != state["current_node_id"]:
        raise DialogueError("Этот вариант не относится к текущему узлу диалога")

    chat_id, chat_mode = _get_character_chat(client, team_id, character_id)
    if chat_mode != "scripted":
        raise DialogueError(f"Диалог сейчас не в режиме scripted (сейчас: {chat_mode})")

    client.table("messages").insert(
        {"chat_id": chat_id, "sender_type": CHOSEN_OPTION_SENDER, "content": option["option_text"]}
    ).execute()
    client.table("messages").insert(
        {"chat_id": chat_id, "sender_type": REPLY_SENDER, "content": option["reply_message"]}
    ).execute()

    if option["requires_admin_approval"]:
        client.table("dialogue_approvals").insert(
            {"team_id": team_id, "option_id": option_id}
        ).execute()
        return {
            "reply": option["reply_message"],
            "pending_approval": True,
            "state": get_dialogue_state(team_id, character_id),
        }

    node = (
        client.table("dialogue_nodes")
        .select("requires_all_options, next_node_id")
        .eq("id", state["current_node_id"])
        .execute()
        .data[0]
    )

    if node["requires_all_options"]:
        client.table("team_dialogue_used_options").upsert(
            {"team_id": team_id, "option_id": option_id}
        ).execute()

        all_option_ids = {
            o["id"]
            for o in client.table("dialogue_options")
            .select("id")
            .eq("node_id", state["current_node_id"])
            .execute()
            .data
        }
        used_ids = {
            row["option_id"]
            for row in client.table("team_dialogue_used_options")
            .select("option_id")
            .eq("team_id", team_id)
            .in_("option_id", list(all_option_ids))
            .execute()
            .data
        }
        next_node_id = node["next_node_id"] if all_option_ids <= used_ids else state["current_node_id"]
    else:
        next_node_id = option["next_node_id"]

    _advance_to(client, team_id, character_id, next_node_id)

    return {
        "reply": option["reply_message"],
        "pending_approval": False,
        "state": get_dialogue_state(team_id, character_id),
    }


def _advance_to(client, team_id: str, character_id: str, node_id: str | None) -> None:
    client.table("team_dialogue_state").update({"current_node_id": node_id}).eq(
        "team_id", team_id
    ).eq("character_id", character_id).execute()


def _get_character_chat(client, team_id: str, character_id: str) -> tuple[str, str]:
    chat = (
        client.table("chats")
        .select("id, mode")
        .eq("team_id", team_id)
        .eq("character_id", character_id)
        .execute()
        .data
    )
    if not chat:
        raise DialogueError("У команды нет чата с этим персонажем")
    return chat[0]["id"], chat[0]["mode"]


def list_pending_approvals() -> list[dict]:
    client = get_supabase_client()
    return (
        client.table("dialogue_approvals")
        .select("id, created_at, teams(name), dialogue_options(option_text, reply_message)")
        .eq("status", "pending")
        .order("created_at")
        .execute()
        .data
    )


def decide_approval(approval_id: str, admin_id: str, approve: bool) -> None:
    client = get_supabase_client()

    approval_rows = (
        client.table("dialogue_approvals")
        .select("id, team_id, option_id, status")
        .eq("id", approval_id)
        .execute()
        .data
    )
    if not approval_rows:
        raise DialogueError("Такой заявки нет")
    approval = approval_rows[0]
    if approval["status"] != "pending":
        raise DialogueError(f"Заявка уже обработана ({approval['status']})")

    client.table("dialogue_approvals").update(
        {
            "status": "approved" if approve else "rejected",
            "reviewer_admin_id": admin_id,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", approval_id).execute()

    if not approve:
        return

    option = (
        client.table("dialogue_options")
        .select("node_id, next_node_id")
        .eq("id", approval["option_id"])
        .execute()
        .data[0]
    )
    node = (
        client.table("dialogue_nodes")
        .select("character_id")
        .eq("id", option["node_id"])
        .execute()
        .data[0]
    )
    _advance_to(client, approval["team_id"], node["character_id"], option["next_node_id"])
