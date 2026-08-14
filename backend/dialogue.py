"""Скриптованный диалог: узлы с вариантами ответа, ветвление, механика
"выберите все варианты" и блок-посты.

Блок-пост — свойство УЗЛА (dialogue_nodes.is_block_post), а не варианта:
команда, попав в такой узел, видит "печатает..." без кнопок выбора, а
реплику персонажа в этот момент решает оператор — либо выбирает один из
заранее написанных в этом узле вариантов (dialogue_options здесь играют
роль не кнопок для команды, а кандидатов реплики для оператора), либо
пишет свой текст. Дальше всегда один и тот же next_node_id узла (тот же
столбец, что уже используют requires_all_options-узлы) — ветвления по
выбору оператора нет, оператор выбирает только ТЕКСТ, а не сюжетную ветку.

Выбор варианта на обычном узле, помимо продвижения по диалогу, всегда
добавляет 2 записи в общую историю чата (messages из chat.py) — реплику
команды и ответ персонажа — чтобы скриптованные и свободные сообщения были
видны в одной ленте. У блок-поста реплика команды уже добавлена тем
вариантом, который её сюда привёл — здесь добавляется только ответ
персонажа, когда оператор его пришлёт.
"""

from __future__ import annotations

from supabase_client import get_supabase_client
from tasks import TaskError, mark_stage_completed
from telegram_notify import notify_block_post_resolved, notify_if_block_post

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
    """Текущий узел диалога команды с персонажем: текст узла + доступные варианты
    (пусто и waiting_for_operator=true, если это блок-пост и команда ждёт оператора)."""
    client = get_supabase_client()

    state = _get_state(client, team_id, character_id)
    if not state or not state["current_node_id"]:
        return {"finished": True, "intro_message": "", "options": [], "waiting_for_operator": False}

    node_id = state["current_node_id"]
    node = client.table("dialogue_nodes").select("*").eq("id", node_id).execute().data[0]

    if node["is_block_post"]:
        return {
            "finished": False,
            "node_id": node_id,
            "intro_message": node["intro_message"],
            "options": [],
            "waiting_for_operator": True,
        }

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
        "waiting_for_operator": False,
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

    node = (
        client.table("dialogue_nodes")
        .select("requires_all_options, next_node_id, is_block_post, completion_stage_id, final_reply")
        .eq("id", state["current_node_id"])
        .execute()
        .data[0]
    )
    if node["is_block_post"]:
        # Фронтенд не должен был вообще показать кнопки на таком узле —
        # это подстраховка от рассинхронизации состояния на клиенте.
        raise DialogueError("Этот узел ждёт ответа оператора, вариант выбрать нельзя")

    sent_message = option.get("sent_message") or option["option_text"]
    client.table("messages").insert(
        {"chat_id": chat_id, "sender_type": CHOSEN_OPTION_SENDER, "content": sent_message}
    ).execute()

    reply_message = option["reply_message"]

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
        exhausted = all_option_ids <= used_ids
        if exhausted and node.get("final_reply"):
            # Реплика при закрывающем набор выборе не привязана к конкретному
            # варианту — её получает тот вариант, который команда выбрала
            # последним, каким бы он ни был (см. YAML-ключ узла final_reply).
            reply_message = node["final_reply"]
        next_node_id = node["next_node_id"] if exhausted else state["current_node_id"]
    else:
        next_node_id = option["next_node_id"]

    client.table("messages").insert(
        {"chat_id": chat_id, "sender_type": REPLY_SENDER, "content": reply_message}
    ).execute()

    _advance_to(client, team_id, character_id, next_node_id)
    if next_node_id is None:
        _complete_stage_if_set(client, team_id, node["completion_stage_id"])
    elif next_node_id != state["current_node_id"]:
        # Настоящий переход на другой узел (не зацикливание на том же самом
        # в ожидании остальных вариантов requires_all_options) - если у
        # узла есть intro, доставляем его как реплику персонажа.
        _deliver_node_intro(client, team_id, character_id, next_node_id)

    return {
        "reply": reply_message,
        "state": get_dialogue_state(team_id, character_id),
    }


def _advance_to(client, team_id: str, character_id: str, node_id: str | None) -> None:
    client.table("team_dialogue_state").update({"current_node_id": node_id}).eq(
        "team_id", team_id
    ).eq("character_id", character_id).execute()

    notify_if_block_post(client, team_id, character_id, node_id)

    if node_id is None:
        # Сценарный "кусок" диалога закончился (следующего узла нет) -
        # чат переходит в обычный операторский режим (не muted): команда
        # может писать дальше как в обычный чат, оператор может отвечать
        # вручную, пока не понадобится следующий кусок истории. Следующий
        # кусок сам включает scripted обратно (см. chat.jump_to_node) —
        # не требует ручного переключения оператором.
        client.table("chats").update({"mode": "operator"}).eq("team_id", team_id).eq(
            "character_id", character_id
        ).execute()


def _deliver_node_intro(client, team_id: str, character_id: str, node_id: str) -> None:
    """Если у узла, на который только что перешёл диалог, задан intro —
    отправляет его в чат как обычную реплику персонажа. Раньше intro
    возвращался только в JSON-ответе на GET .../dialogue, а сам фронтенд
    его нигде не показывал — команда видела кнопки выбора без вопроса,
    на который они как бы отвечают. Вызывается только при настоящем
    переходе на другой узел, не на каждый опрос состояния."""
    node = client.table("dialogue_nodes").select("intro_message").eq("id", node_id).execute().data
    intro = node[0]["intro_message"] if node else ""
    if not intro:
        return
    chat_id, _ = _get_character_chat(client, team_id, character_id)
    client.table("messages").insert(
        {"chat_id": chat_id, "sender_type": REPLY_SENDER, "content": intro}
    ).execute()


def _complete_stage_if_set(client, team_id: str, stage_id: str | None) -> None:
    """Если узел, на котором закончился этот "кусок" диалога, размечен
    (YAML-ключ узла completes_stage) — сам отмечает соответствующий этап
    выполненным для команды, без участия актёра. Молча ничего не делает,
    если этап сейчас не в статусе 'available' (например, уже выполнен другим
    способом) — сбой этой привязки не должен ронять сам диалог."""
    if not stage_id:
        return

    try:
        mark_stage_completed(
            team_id=team_id,
            stage_id=stage_id,
            completed_by_admin_id=None,
            completion_method="dialogue",
        )
    except TaskError:
        pass


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


def list_pending_block_posts() -> list[dict]:
    """Очередь для вкладки 'Блок-посты': все команды, чьё текущее состояние
    диалога с каким-либо персонажем сейчас "заморожено" на блок-посте, вместе
    с кандидатами реплики (варианты этого узла) на выбор оператору."""
    client = get_supabase_client()

    states = (
        client.table("team_dialogue_state")
        .select(
            "team_id, character_id, current_node_id, "
            "teams(name), characters(name), dialogue_nodes(intro_message, is_block_post)"
        )
        .execute()
        .data
    )
    pending = [
        s for s in states if s["current_node_id"] and s["dialogue_nodes"] and s["dialogue_nodes"]["is_block_post"]
    ]
    if not pending:
        return []

    node_ids = list({s["current_node_id"] for s in pending})
    options_by_node: dict[str, list[dict]] = {}
    for row in (
        client.table("dialogue_options")
        .select("id, node_id, option_text, reply_message")
        .in_("node_id", node_ids)
        .execute()
        .data
    ):
        options_by_node.setdefault(row["node_id"], []).append(row)

    return [
        {
            "team_id": s["team_id"],
            "character_id": s["character_id"],
            "team_name": s["teams"]["name"] if s["teams"] else "?",
            "character_name": s["characters"]["name"] if s["characters"] else "?",
            "intro_message": s["dialogue_nodes"]["intro_message"],
            "options": [
                {"id": o["id"], "text": o["option_text"], "reply": o["reply_message"]}
                for o in options_by_node.get(s["current_node_id"], [])
            ],
        }
        for s in pending
    ]


def resolve_block_post(
    team_id: str,
    character_id: str,
    option_id: str | None,
    custom_text: str | None,
) -> None:
    """Оператор отправляет реплику персонажа на блок-посте — готовый вариант
    (option_id) или свой текст (custom_text, ровно один из двух должен быть
    задан). Дальше команда идёт по next_node_id узла — оператор выбирает
    только текст, не сюжетную ветку."""
    client = get_supabase_client()

    state = _get_state(client, team_id, character_id)
    if not state or not state["current_node_id"]:
        raise DialogueError("Диалог с этим персонажем сейчас не активен")

    node = client.table("dialogue_nodes").select("*").eq("id", state["current_node_id"]).execute().data[0]
    if not node["is_block_post"]:
        raise DialogueError("Команда сейчас не на блок-посте")

    if option_id:
        option_rows = client.table("dialogue_options").select("*").eq("id", option_id).execute().data
        if not option_rows or option_rows[0]["node_id"] != node["id"]:
            raise DialogueError("Такого варианта нет у этого узла")
        text = option_rows[0]["reply_message"]
    elif custom_text and custom_text.strip():
        text = custom_text.strip()
    else:
        raise DialogueError("Нужно выбрать готовый вариант или написать свой текст")

    chat_id, _ = _get_character_chat(client, team_id, character_id)
    client.table("messages").insert(
        {"chat_id": chat_id, "sender_type": REPLY_SENDER, "content": text}
    ).execute()
    notify_block_post_resolved(team_id, character_id)

    _advance_to(client, team_id, character_id, node["next_node_id"])
    if node["next_node_id"] is None:
        # На практике недостижимо: валидация (import_content.py) требует
        # у is_block_post узла обязательный next. Оставлено для симметрии
        # с choose_option и на случай будущих изменений этого правила.
        _complete_stage_if_set(client, team_id, node["completion_stage_id"])
    else:
        _deliver_node_intro(client, team_id, character_id, node["next_node_id"])
