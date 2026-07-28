"""Загрузчик игрового контента из YAML в Supabase (этапы + граф + поля ответа).

Запуск (из папки backend, с активированным venv):
    python import_content.py [путь_к_файлу]
По умолчанию читает ../data/quest_content.yaml.

Идемпотентно: этапы обновляются по slug, поля — по (stage, field_key),
принятые ответы поля полностью пересоздаются из файла при каждом запуске.
НИЧЕГО не удаляется автоматически: если убрать этап из YAML, в базе он
останется (у команд может быть привязанный прогресс) — в конце скрипт
только предупредит о таких "осиротевших" этапах.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

from supabase_client import get_supabase_client

DEFAULT_CONTENT_PATH = Path(__file__).resolve().parent.parent / "data" / "quest_content.yaml"
VALID_COMPLETION_TYPES = ("actor", "answer", "checkbox", "manual_review")


class ContentError(Exception):
    """Ошибка в содержимом YAML-файла."""


def load_content(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("stages", [])


def validate(stages: list[dict[str, Any]]) -> None:
    all_slugs = {stage.get("slug") for stage in stages}
    seen_slugs: set[str] = set()

    for stage in stages:
        slug = stage.get("slug")
        if not slug:
            raise ContentError(f"У этапа нет slug: {stage}")
        if slug in seen_slugs:
            raise ContentError(f"Повторяющийся slug: {slug}")
        seen_slugs.add(slug)

        if not stage.get("title"):
            raise ContentError(f"Этап '{slug}': нет title")

        completion_type = stage.get("completion_type", "actor")
        if completion_type not in VALID_COMPLETION_TYPES:
            raise ContentError(
                f"Этап '{slug}': недопустимый completion_type '{completion_type}', "
                f"должен быть одним из {VALID_COMPLETION_TYPES}"
            )

        fields = stage.get("fields", [])
        if fields and completion_type != "answer":
            raise ContentError(
                f"Этап '{slug}': заданы fields, но completion_type='{completion_type}' "
                "(поля имеют смысл только при completion_type: answer)"
            )
        for field in fields:
            if not field.get("key") or not field.get("label"):
                raise ContentError(f"Этап '{slug}': у поля нет key или label: {field}")
            if not field.get("accepted"):
                raise ContentError(
                    f"Этап '{slug}', поле '{field.get('key')}': нет принятых ответов (accepted)"
                )

        for prerequisite in stage.get("requires", []):
            if prerequisite not in all_slugs:
                raise ContentError(f"Этап '{slug}' требует неизвестный этап '{prerequisite}'")


def import_content(path: Path = DEFAULT_CONTENT_PATH) -> None:
    stages = load_content(path)
    validate(stages)

    client = get_supabase_client()

    slug_to_id: dict[str, str] = {}
    for stage in stages:
        row = (
            client.table("stages")
            .upsert(
                {
                    "slug": stage["slug"],
                    "title": stage["title"],
                    "description": stage.get("description", ""),
                    "completion_type": stage.get("completion_type", "actor"),
                },
                on_conflict="slug",
            )
            .execute()
            .data[0]
        )
        slug_to_id[stage["slug"]] = row["id"]
        print(f"этап: {stage['slug']}")

    for stage in stages:
        stage_id = slug_to_id[stage["slug"]]

        for prerequisite_slug in stage.get("requires", []):
            client.table("stage_edges").upsert(
                {"from_stage_id": slug_to_id[prerequisite_slug], "to_stage_id": stage_id},
                on_conflict="from_stage_id,to_stage_id",
            ).execute()

        for field in stage.get("fields", []):
            field_row = (
                client.table("answer_fields")
                .upsert(
                    {
                        "stage_id": stage_id,
                        "field_key": field["key"],
                        "label": field["label"],
                        "hint": field.get("hint", ""),
                        "order_position": field.get("order", 1),
                        "order_sensitive": field.get("order_sensitive", True),
                    },
                    on_conflict="stage_id,field_key",
                )
                .execute()
                .data[0]
            )
            field_id = field_row["id"]

            client.table("answer_field_accepted_values").delete().eq(
                "field_id", field_id
            ).execute()
            client.table("answer_field_accepted_values").insert(
                [{"field_id": field_id, "value": value} for value in field["accepted"]]
            ).execute()

    db_slugs = {row["slug"] for row in client.table("stages").select("slug").execute().data}
    yaml_slugs = {stage["slug"] for stage in stages}
    missing = db_slugs - yaml_slugs
    if missing:
        print(
            f"\nПРЕДУПРЕЖДЕНИЕ: в базе есть этапы, которых нет в файле "
            f"(не удалены, проверьте сами): {sorted(missing)}"
        )

    print(f"\nГотово: {len(stages)} этапов обработано.")


if __name__ == "__main__":
    content_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CONTENT_PATH
    try:
        import_content(content_path)
    except ContentError as exc:
        print(f"Ошибка в контенте: {exc}")
        sys.exit(1)
