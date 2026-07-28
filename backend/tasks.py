"""Список задач команды и авторазблокировка графа этапов (только AND)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from supabase_client import get_supabase_client

VISIBLE_STATUSES = ("available", "completed")
CompletionMethod = Literal["actor", "answer", "checkbox", "manual_review"]


class TaskError(Exception):
    """Ожидаемая ошибка (неверный переход состояния и т.п.)."""


def seed_team_progress(team_id: str) -> None:
    """Создать строки прогресса для новой команды по всем существующим этапам.

    Корневые этапы (без предпосылок в stage_edges) сразу доступны, остальные — locked.
    Вызывается один раз при регистрации команды.
    """
    client = get_supabase_client()
    stages = client.table("stages").select("id").execute().data
    edges = client.table("stage_edges").select("to_stage_id").execute().data

    stages_with_prerequisite = {edge["to_stage_id"] for edge in edges}

    rows = [
        {
            "team_id": team_id,
            "stage_id": stage["id"],
            "status": "locked" if stage["id"] in stages_with_prerequisite else "available",
        }
        for stage in stages
    ]
    if rows:
        client.table("team_stage_progress").insert(rows).execute()


def list_team_tasks(team_id: str) -> list[dict]:
    """Задачи, видимые команде: доступные и выполненные (locked не показываем)."""
    client = get_supabase_client()
    result = (
        client.table("team_stage_progress")
        .select("stage_id, status, completed_at, completion_method, stages(slug, title, description)")
        .eq("team_id", team_id)
        .in_("status", VISIBLE_STATUSES)
        .execute()
    )
    return result.data


def mark_stage_completed(
    team_id: str,
    stage_id: str,
    completed_by_admin_id: Optional[str],
    completion_method: CompletionMethod,
) -> None:
    """Отметить этап выполненным для команды и разблокировать то, что теперь доступно."""
    client = get_supabase_client()

    current = (
        client.table("team_stage_progress")
        .select("status")
        .eq("team_id", team_id)
        .eq("stage_id", stage_id)
        .execute()
    )
    if not current.data:
        raise TaskError("У команды нет такого этапа")
    if current.data[0]["status"] != "available":
        raise TaskError(
            f"Этап сейчас в статусе '{current.data[0]['status']}', отметить выполненным нельзя"
        )

    client.table("team_stage_progress").update(
        {
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "completed_by_admin_id": completed_by_admin_id,
            "completion_method": completion_method,
        }
    ).eq("team_id", team_id).eq("stage_id", stage_id).execute()

    _unlock_dependents(team_id, stage_id)


def _unlock_dependents(team_id: str, stage_id: str) -> None:
    """После выполнения stage_id проверить всех "потомков" и открыть тех, у кого
    все предпосылки (AND) теперь выполнены командой."""
    client = get_supabase_client()

    dependent_edges = (
        client.table("stage_edges").select("to_stage_id").eq("from_stage_id", stage_id).execute()
    )

    for edge in dependent_edges.data:
        dependent_stage_id = edge["to_stage_id"]

        prerequisites = (
            client.table("stage_edges")
            .select("from_stage_id")
            .eq("to_stage_id", dependent_stage_id)
            .execute()
        )
        prerequisite_ids = [row["from_stage_id"] for row in prerequisites.data]

        progress_rows = (
            client.table("team_stage_progress")
            .select("status")
            .eq("team_id", team_id)
            .in_("stage_id", prerequisite_ids)
            .execute()
        )
        all_completed = len(progress_rows.data) == len(prerequisite_ids) and all(
            row["status"] == "completed" for row in progress_rows.data
        )

        if all_completed:
            client.table("team_stage_progress").update({"status": "available"}).eq(
                "team_id", team_id
            ).eq("stage_id", dependent_stage_id).eq("status", "locked").execute()
