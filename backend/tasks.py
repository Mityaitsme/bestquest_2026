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
        .select(
            "stage_id, status, completed_at, completion_method, "
            "stages(slug, title, description, completion_type)"
        )
        .eq("team_id", team_id)
        .in_("status", VISIBLE_STATUSES)
        .execute()
    )
    return result.data


def list_team_graph(team_id: str) -> dict:
    """Полный граф этапов + статус команды по каждому (включая locked) — для
    второстепенного экрана 'граф прогресса' в админке (requirements.md
    называет его необязательным 'вторым экраном', в основном для десктопа).
    В отличие от list_team_tasks здесь нужны и locked-этапы тоже, иначе на
    графе не будет видно, что вообще идёт дальше."""
    client = get_supabase_client()

    progress = (
        client.table("team_stage_progress")
        .select("stage_id, status, stages(title, completion_type)")
        .eq("team_id", team_id)
        .execute()
        .data
    )
    edges = client.table("stage_edges").select("from_stage_id, to_stage_id").execute().data

    stages = [
        {
            "stage_id": row["stage_id"],
            "title": row["stages"]["title"] if row["stages"] else "Без названия",
            "completion_type": row["stages"]["completion_type"] if row["stages"] else None,
            "status": row["status"],
        }
        for row in progress
    ]
    return {"stages": stages, "edges": edges}


def list_teams_overview() -> list[dict]:
    """Для первой вкладки админки: все команды с % пройденных этапов и
    временем последней выполненной задачи. Команды, которые дольше всего
    не выполняли ни одной задачи (или ещё ни одной не выполнили), — первыми."""
    client = get_supabase_client()

    teams = client.table("teams").select("id, name, created_at").execute().data
    total_stages = len(client.table("stages").select("id").execute().data)
    progress_rows = (
        client.table("team_stage_progress").select("team_id, status, completed_at").execute().data
    )

    overview = []
    for team in teams:
        team_progress = [row for row in progress_rows if row["team_id"] == team["id"]]
        completed_ats = [
            row["completed_at"]
            for row in team_progress
            if row["status"] == "completed" and row["completed_at"]
        ]

        overview.append(
            {
                "team_id": team["id"],
                "name": team["name"],
                "registered_at": team["created_at"],
                "progress_percent": (
                    round(len(completed_ats) / total_stages * 100) if total_stages else 0
                ),
                "last_task_completed_at": max(completed_ats) if completed_ats else None,
            }
        )

    overview.sort(key=lambda t: t["last_task_completed_at"] or "")
    return overview


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


def complete_checkbox_stage(team_id: str, stage_id: str) -> None:
    """Метод 3: команда сама подтверждает выполнение (галочка/"далее"), без текста."""
    client = get_supabase_client()

    stage = client.table("stages").select("completion_type").eq("id", stage_id).execute().data
    if not stage:
        raise TaskError("Такого этапа нет")
    if stage[0]["completion_type"] != "checkbox":
        raise TaskError("Этот этап не поддерживает самостоятельное подтверждение")

    mark_stage_completed(
        team_id=team_id,
        stage_id=stage_id,
        completed_by_admin_id=None,
        completion_method="checkbox",
    )


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
