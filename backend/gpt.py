"""Автоответ ChatGPT для чатов в режиме gpt (см. chat.py: chats.mode).

Системный промпт собирается из трёх частей:
  1) персона персонажа — авторский текст (characters.gpt_persona_prompt),
     никогда не показывается игроку, только модели;
  2) прогресс команды — какие этапы квеста она уже прошла, чтобы GPT знал
     положение команды на графе событий, как и просили в требованиях;
  3) история сообщений этого чата — для связности разговора.

Если OPENAI_API_KEY не настроен или запрос к OpenAI не удался — поднимается
GptError, а не 500: остальной чат должен продолжать работать даже без GPT.
"""

from __future__ import annotations

from openai import OpenAI

from config import load_config
from supabase_client import get_supabase_client

MAX_HISTORY_MESSAGES = 20
DEFAULT_PERSONA_PROMPT = "Ты — персонаж квеста. Отвечай в характере, кратко."


class GptError(Exception):
    """Ожидаемая ошибка (ключ не настроен, сбой запроса к OpenAI и т.п.)."""


def _build_system_prompt(client, team_id: str, character_id: str) -> str:
    character = (
        client.table("characters")
        .select("gpt_persona_prompt")
        .eq("id", character_id)
        .execute()
        .data[0]
    )
    persona = character["gpt_persona_prompt"] or DEFAULT_PERSONA_PROMPT

    completed = (
        client.table("team_stage_progress")
        .select("stages(title)")
        .eq("team_id", team_id)
        .eq("status", "completed")
        .execute()
        .data
    )
    titles = [row["stages"]["title"] for row in completed if row.get("stages")]
    progress_context = (
        "Команда пока не прошла ни одного этапа квеста."
        if not titles
        else "Команда уже прошла следующие этапы квеста: " + ", ".join(titles) + "."
    )

    return f"{persona}\n\n{progress_context}\nОтвечай от лица персонажа, оставаясь в его характере."


def generate_reply(team_id: str, chat_id: str, character_id: str) -> str:
    """Сгенерировать и сохранить ответ персонажа. Возвращает текст ответа."""
    config = load_config()
    if not config.openai_api_key:
        raise GptError("OPENAI_API_KEY не настроен")

    client = get_supabase_client()
    system_prompt = _build_system_prompt(client, team_id, character_id)

    history = (
        client.table("messages")
        .select("sender_type, content")
        .eq("chat_id", chat_id)
        .order("created_at", desc=True)
        .limit(MAX_HISTORY_MESSAGES)
        .execute()
        .data
    )
    history.reverse()

    conversation = [{"role": "system", "content": system_prompt}]
    for message in history:
        role = "user" if message["sender_type"] == "team" else "assistant"
        conversation.append({"role": role, "content": message["content"]})

    openai_client = OpenAI(api_key=config.openai_api_key)
    try:
        response = openai_client.chat.completions.create(
            model=config.openai_model, messages=conversation
        )
    except Exception as exc:  # noqa: BLE001 — граница с внешним API
        raise GptError(f"Не удалось получить ответ от ChatGPT: {exc}") from exc

    reply_text = (response.choices[0].message.content or "").strip()
    if not reply_text:
        raise GptError("ChatGPT вернул пустой ответ")

    client.table("messages").insert(
        {"chat_id": chat_id, "sender_type": "character", "content": reply_text}
    ).execute()

    return reply_text
