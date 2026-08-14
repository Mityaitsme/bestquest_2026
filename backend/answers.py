"""Поля ответа на этап ("кодовое слово" в окошке) — метод 2 из requirements.md.

Неправильные ответы нигде не сохраняются: строка в team_field_submissions
существует, только если команда УЖЕ ответила на это поле правильно. Поэтому
при повторном открытии окна с сервера подтягиваются только верно отвеченные
поля — остальные остаются пустыми на фронтенде, как и требовалось.
"""

from __future__ import annotations

from datetime import datetime, timezone

from supabase_client import get_supabase_client
from tasks import mark_stage_completed

VISIBLE_STAGE_STATUSES = ("available", "completed")


class AnswerError(Exception):
    """Ожидаемая ошибка (этап недоступен команде, поле не найдено и т.п.)."""


def _normalize(value: str) -> str:
    return value.strip().casefold()


def _matches(accepted_value: str, match_mode: str, normalized_submitted: str) -> bool:
    normalized_accepted = _normalize(accepted_value)
    if match_mode == "contains":
        return normalized_accepted in normalized_submitted
    return normalized_accepted == normalized_submitted


def get_stage_fields(team_id: str, stage_id: str) -> list[dict]:
    """Поля этапа + какие из них команда уже ответила верно (без самих ответов-эталонов)."""
    client = get_supabase_client()

    progress = (
        client.table("team_stage_progress")
        .select("status")
        .eq("team_id", team_id)
        .eq("stage_id", stage_id)
        .execute()
    )
    if not progress.data or progress.data[0]["status"] not in VISIBLE_STAGE_STATUSES:
        raise AnswerError("Этап недоступен этой команде")

    fields = (
        client.table("answer_fields")
        .select("id, field_key, label, hint, order_position")
        .eq("stage_id", stage_id)
        .order("order_position")
        .execute()
        .data
    )

    submissions = (
        client.table("team_field_submissions")
        .select("field_id, submitted_value")
        .eq("team_id", team_id)
        .in_("field_id", [f["id"] for f in fields])
        .execute()
        .data
        if fields
        else []
    )
    submitted_by_field = {row["field_id"]: row["submitted_value"] for row in submissions}

    for field in fields:
        field["correct"] = field["id"] in submitted_by_field
        field["submitted_value"] = submitted_by_field.get(field["id"])

    return fields


def submit_field_answer(team_id: str, stage_id: str, field_id: str, value: str) -> dict:
    """Проверить ответ на поле. Возвращает {"correct": bool, "stage_completed": bool}."""
    client = get_supabase_client()

    field_rows = (
        client.table("answer_fields")
        .select("id, stage_id")
        .eq("id", field_id)
        .execute()
        .data
    )
    if not field_rows or field_rows[0]["stage_id"] != stage_id:
        raise AnswerError("Такого поля нет у этого этапа")

    progress = (
        client.table("team_stage_progress")
        .select("status")
        .eq("team_id", team_id)
        .eq("stage_id", stage_id)
        .execute()
    )
    if not progress.data or progress.data[0]["status"] != "available":
        raise AnswerError("Этап сейчас недоступен этой команде")

    accepted_values = (
        client.table("answer_field_accepted_values")
        .select("value, match_mode")
        .eq("field_id", field_id)
        .execute()
        .data
    )
    normalized_submitted = _normalize(value)
    matched_value = next(
        (row for row in accepted_values if _matches(row["value"], row["match_mode"], normalized_submitted)),
        None,
    )

    if matched_value is None:
        return {"correct": False, "stage_completed": False}

    if _matches_another_fields_answer(client, team_id, stage_id, field_id, matched_value):
        # order-insensitive группа полей: этот же эталонный ответ уже принят
        # у ДРУГОГО поля этого этапа - нельзя вписать один и тот же ответ в
        # оба поля и засчитать оба.
        return {"correct": False, "stage_completed": False}

    client.table("team_field_submissions").upsert(
        {
            "team_id": team_id,
            "field_id": field_id,
            "submitted_value": value,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }
    ).execute()

    stage_completed = _maybe_complete_stage(team_id, stage_id)
    return {"correct": True, "stage_completed": stage_completed}


def _matches_another_fields_answer(
    client, team_id: str, stage_id: str, field_id: str, matched_value: dict
) -> bool:
    """Для order-insensitive группы полей (общий accepted-список на несколько
    полей) - проверяет, не отвечено ли уже ДРУГОЕ поле этого этапа тем же
    самым эталонным ответом (matched_value), что сейчас подошёл текущему
    полю. Без этой проверки можно было бы вписать один и тот же ответ в оба
    поля и засчитать сразу оба."""
    other_field_ids = [
        row["id"]
        for row in client.table("answer_fields")
        .select("id")
        .eq("stage_id", stage_id)
        .neq("id", field_id)
        .execute()
        .data
    ]
    if not other_field_ids:
        return False

    other_submissions = (
        client.table("team_field_submissions")
        .select("submitted_value")
        .eq("team_id", team_id)
        .in_("field_id", other_field_ids)
        .execute()
        .data
    )
    return any(
        _matches(matched_value["value"], matched_value["match_mode"], _normalize(row["submitted_value"]))
        for row in other_submissions
    )


def _maybe_complete_stage(team_id: str, stage_id: str) -> bool:
    """Если все поля этапа теперь отвечены верно — завершить этап автоматически."""
    client = get_supabase_client()

    all_field_ids = {
        row["id"]
        for row in client.table("answer_fields").select("id").eq("stage_id", stage_id).execute().data
    }
    if not all_field_ids:
        return False

    correct_field_ids = {
        row["field_id"]
        for row in client.table("team_field_submissions")
        .select("field_id")
        .eq("team_id", team_id)
        .in_("field_id", list(all_field_ids))
        .execute()
        .data
    }

    if all_field_ids <= correct_field_ids:
        mark_stage_completed(
            team_id=team_id,
            stage_id=stage_id,
            completed_by_admin_id=None,
            completion_method="answer",
        )
        return True

    return False
