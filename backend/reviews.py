"""Ручная проверка ответа (метод 4): команда отправляет ответ (+фото),
оператор в специальной очереди принимает или отклоняет его.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from supabase_client import get_supabase_client
from tasks import mark_stage_completed
from telegram_notify import notify_review_resolved, notify_review_submitted

PHOTO_BUCKET = "manual-review-photos"
MAX_PHOTO_SIZE_BYTES = 20 * 1024 * 1024  # тот же лимит, что настроен на самом бакете в Supabase
ALLOWED_PHOTO_CONTENT_TYPES = ("image/jpeg", "image/png", "image/webp", "image/heic", "image/heif")
# Некоторые браузеры/ОС не умеют определить MIME-тип HEIC/HEIF-файла и
# присылают content_type пустым или общим ("application/octet-stream") —
# тогда используем расширение файла как резервный способ определить тип.
EXTENSION_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heif",
}
SIGNED_URL_TTL_SECONDS = 300


class ReviewError(Exception):
    """Ожидаемая ошибка (этап не для ручной проверки, неподходящий файл и т.п.)."""


def upload_review_photo(content: bytes, content_type: str, filename: str = "") -> str:
    """Загрузить фото в приватный бакет, вернуть путь внутри бакета (не публичный URL)."""
    resolved_content_type = content_type
    if resolved_content_type not in ALLOWED_PHOTO_CONTENT_TYPES:
        guessed = EXTENSION_CONTENT_TYPES.get(Path(filename).suffix.lower())
        if guessed:
            resolved_content_type = guessed

    if resolved_content_type not in ALLOWED_PHOTO_CONTENT_TYPES:
        raise ReviewError(f"Неподдерживаемый тип файла: {content_type or 'неизвестен'}")
    if len(content) > MAX_PHOTO_SIZE_BYTES:
        raise ReviewError("Файл слишком большой (максимум 20 МБ)")

    client = get_supabase_client()
    extension = resolved_content_type.split("/")[-1]
    path = f"{uuid.uuid4()}.{extension}"
    client.storage.from_(PHOTO_BUCKET).upload(
        path, content, {"content-type": resolved_content_type, "upsert": "true"}
    )
    return path


def submit_manual_review(
    team_id: str, stage_id: str, text: str, photo_path: Optional[str] = None
) -> str:
    """Создать заявку на ручную проверку. Возвращает id заявки."""
    client = get_supabase_client()

    stage = client.table("stages").select("completion_type, title").eq("id", stage_id).execute().data
    if not stage:
        raise ReviewError("Такого этапа нет")
    if stage[0]["completion_type"] != "manual_review":
        raise ReviewError("Этот этап не предполагает ручную проверку")

    progress = (
        client.table("team_stage_progress")
        .select("status")
        .eq("team_id", team_id)
        .eq("stage_id", stage_id)
        .execute()
    )
    if not progress.data or progress.data[0]["status"] != "available":
        raise ReviewError("Этап сейчас недоступен этой команде")

    review = (
        client.table("manual_reviews")
        .insert(
            {
                "team_id": team_id,
                "stage_id": stage_id,
                "submitted_text": text,
                "photo_path": photo_path,
            }
        )
        .execute()
        .data[0]
    )

    team = client.table("teams").select("name").eq("id", team_id).execute().data
    notify_review_submitted(
        review["id"], team[0]["name"] if team else "?", stage[0]["title"]
    )

    return review["id"]


def list_pending_reviews() -> list[dict]:
    """Очередь для вкладки 'Верификация': непроверенные заявки, старые сверху."""
    client = get_supabase_client()
    return (
        client.table("manual_reviews")
        .select("id, submitted_text, photo_path, created_at, teams(name), stages(title)")
        .eq("status", "pending")
        .order("created_at")
        .execute()
        .data
    )


def get_photo_signed_url(review_id: str) -> str:
    """Временная ссылка на фото заявки (бакет приватный)."""
    client = get_supabase_client()
    review = (
        client.table("manual_reviews").select("photo_path").eq("id", review_id).execute().data
    )
    if not review or not review[0]["photo_path"]:
        raise ReviewError("У этой заявки нет фото")

    signed = client.storage.from_(PHOTO_BUCKET).create_signed_url(
        review[0]["photo_path"], SIGNED_URL_TTL_SECONDS
    )
    url = signed.get("signedURL") or signed.get("signedUrl")
    if not url:
        raise ReviewError("Не удалось получить ссылку на фото")
    return url


def review_decision(
    review_id: str, admin_id: str, accept: bool, comment: Optional[str]
) -> None:
    """Оператор принимает или отклоняет заявку."""
    client = get_supabase_client()

    review = (
        client.table("manual_reviews")
        .select("team_id, stage_id, status, stages(title)")
        .eq("id", review_id)
        .execute()
        .data
    )
    if not review:
        raise ReviewError("Такой заявки нет")
    if review[0]["status"] != "pending":
        raise ReviewError(f"Заявка уже обработана ({review[0]['status']})")

    new_status = "accepted" if accept else "rejected"
    client.table("manual_reviews").update(
        {
            "status": new_status,
            "reviewer_admin_id": admin_id,
            "comment": comment,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", review_id).execute()

    if accept:
        mark_stage_completed(
            team_id=review[0]["team_id"],
            stage_id=review[0]["stage_id"],
            completed_by_admin_id=admin_id,
            completion_method="manual_review",
        )

    _notify_team_of_review_decision(
        client,
        team_id=review[0]["team_id"],
        stage_title=review[0]["stages"]["title"] if review[0]["stages"] else "этап",
        accept=accept,
        comment=comment,
        admin_id=admin_id,
    )
    notify_review_resolved(review_id)


def _notify_team_of_review_decision(
    client, team_id: str, stage_title: str, accept: bool, comment: Optional[str], admin_id: str
) -> None:
    """Решение по проверке всегда должно быть видно команде — раньше
    сообщение в техподдержку уходило только если оператор оставил
    комментарий, и команда узнавала о принятой/отклонённой заявке только
    перезагрузив страницу и увидев, что задача сама стала выполненной (или
    не стала). Кладём "отбивку" в чат техподдержки отдельным "служебным"
    сообщением (message_kind=support_comment, тот же вид, что и у ручных
    ответов техподдержки, но sender_type=system, т.к. это не оператор
    печатает вручную, а автоматическое следствие его решения) при любом
    решении, с комментарием или без."""
    support_chat = (
        client.table("chats")
        .select("id")
        .eq("team_id", team_id)
        .eq("chat_type", "support")
        .execute()
        .data
    )
    if not support_chat:
        return

    verdict = "принят" if accept else "отклонён"
    text = f"Ответ по заданию «{stage_title}» {verdict}."
    if comment:
        text += f" {comment}"

    client.table("messages").insert(
        {
            "chat_id": support_chat[0]["id"],
            "sender_type": "system",
            "sender_admin_id": admin_id,
            "content": text,
            "message_kind": "support_comment",
        }
    ).execute()
