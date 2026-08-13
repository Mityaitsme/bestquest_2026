"""Список задач команды и авторазблокировка графа этапов (только AND)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from chat import jump_to_node, trigger_scripted_dialogue
from supabase_client import get_supabase_client

VISIBLE_STATUSES = ("available", "completed")
CompletionMethod = Literal["actor", "answer", "checkbox", "manual_review", "dialogue"]


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
    now = datetime.now(timezone.utc).isoformat()

    rows = [
        {
            "team_id": team_id,
            "stage_id": stage["id"],
            "status": "locked" if stage["id"] in stages_with_prerequisite else "available",
            "available_at": None if stage["id"] in stages_with_prerequisite else now,
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


def list_team_tasks_admin(team_id: str) -> list[dict]:
    """То же самое, что list_team_tasks, но с available_at — только для
    админки, чтобы посчитать время выполнения (completed_at - available_at)
    для вкладки "Выполненные". Команде это поле не нужно, поэтому не отдаём
    его в обычном list_team_tasks."""
    client = get_supabase_client()
    result = (
        client.table("team_stage_progress")
        .select(
            "stage_id, status, available_at, completed_at, completion_method, "
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
    _fire_dialogue_triggers(client, team_id, stage_id)
    _fire_dialogue_resumes(client, team_id, stage_id)


def _fire_dialogue_triggers(client, team_id: str, stage_id: str) -> None:
    """Автотриггер сценарного диалога (см. import_content.py: ключ этапа
    triggers_scripted_dialogue) — этап при выполнении сам переключает чат
    с указанным персонажем в режим scripted, без ручного шага оператора."""
    triggers = (
        client.table("stage_dialogue_triggers")
        .select("character_id")
        .eq("stage_id", stage_id)
        .execute()
        .data
    )
    for trigger in triggers:
        trigger_scripted_dialogue(team_id, trigger["character_id"])


def _fire_dialogue_resumes(client, team_id: str, stage_id: str) -> None:
    """Автопродолжение диалога (см. import_content.py: ключ этапа
    resumes_dialogue_at) — этап при выполнении молча передвигает указатель
    команды в диалоге персонажа на конкретный узел (следующий "кусок"
    истории). В отличие от _fire_dialogue_triggers выше, режим чата НЕ
    трогает — команда увидит новый кусок только когда оператор сам включит
    'сценарий' через dropdown, это осознанно оставлено ручным действием."""
    resumes = (
        client.table("stage_dialogue_resumes")
        .select("character_id, target_node_id")
        .eq("stage_id", stage_id)
        .execute()
        .data
    )
    for resume in resumes:
        jump_to_node(team_id, resume["character_id"], resume["target_node_id"])


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
            client.table("team_stage_progress").update(
                {"status": "available", "available_at": datetime.now(timezone.utc).isoformat()}
            ).eq("team_id", team_id).eq("stage_id", dependent_stage_id).eq(
                "status", "locked"
            ).execute()


def get_current_chapter(team_id: str) -> Optional[str]:
    """Название главы, которую команда сейчас проходит — по этапу с самым
    поздним available_at (последнему ОТКРЫВШЕМУСЯ этапу, а не последнему
    выполненному: "актуальная" глава должна смениться сразу, как только
    команде открылась первая задача следующей главы, не дожидаясь, пока она
    её выполнит). Locked-этапы не участвуют (available_at у них пустой).
    Если у самого свежего этапа chapter не задан (YAML), берём следующий по
    свежести с непустым chapter — так глава не "пропадает" из-за одного
    вспомогательного этапа без главы."""
    client = get_supabase_client()
    rows = (
        client.table("team_stage_progress")
        .select("available_at, stages(chapter)")
        .eq("team_id", team_id)
        .neq("status", "locked")
        .order("available_at", desc=True)
        .execute()
        .data
    )
    for row in rows:
        chapter = row["stages"]["chapter"] if row["stages"] else None
        if chapter:
            return chapter
    return None
