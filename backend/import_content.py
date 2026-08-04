"""Загрузчик игрового контента из YAML в Supabase
(персонажи + их скриптованные диалоги, этапы, граф, поля ответа,
телефонные номера/звонки).

Запуск (из папки backend, с активированным venv):
    python import_content.py [путь_к_файлу]
По умолчанию читает ../data/quest_content.yaml.

Идемпотентно: персонажи/этапы/номера обновляются по slug/number, поля — по
(stage, field_key), фазы звонка — по (номер, content_key), узлы диалога —
по (персонаж, content_key), варианты — по (узел, content_key). Принятые
ответы поля и связи success/failure фаз полностью пересоздаются из файла
при каждом запуске. НИЧЕГО не удаляется автоматически: если убрать этап,
персонажа, номер или узел диалога из YAML, в базе он останется (у команд
может быть привязанный прогресс/чаты) — в конце скрипт только предупредит
о таких "осиротевших" этапах/персонажах/номерах (не про отдельные узлы
диалога — это было бы избыточно для данного этапа).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

from supabase_client import get_supabase_client

DEFAULT_CONTENT_PATH = Path(__file__).resolve().parent.parent / "data" / "quest_content.yaml"
VALID_COMPLETION_TYPES = ("actor", "answer", "checkbox", "manual_review")

AUDIO_ASSETS_DIR = DEFAULT_CONTENT_PATH.parent / "audio"
AUDIO_BUCKET = "call-audio"
AUDIO_CONTENT_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
}


class ContentError(Exception):
    """Ошибка в содержимом YAML-файла."""


def load_content(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def validate_characters(characters: list[dict[str, Any]]) -> None:
    seen_slugs: set[str] = set()
    seen_nicknames: set[str] = set()

    for character in characters:
        slug = character.get("slug")
        if not slug:
            raise ContentError(f"У персонажа нет slug: {character}")
        if slug in seen_slugs:
            raise ContentError(f"Повторяющийся slug персонажа: {slug}")
        seen_slugs.add(slug)

        if not character.get("name") or not character.get("nickname"):
            raise ContentError(f"Персонаж '{slug}': нет name или nickname")

        nickname = character["nickname"]
        if nickname in seen_nicknames:
            raise ContentError(f"Повторяющийся nickname персонажа: {nickname}")
        seen_nicknames.add(nickname)


def validate_dialogues(characters: list[dict[str, Any]]) -> None:
    for character in characters:
        dialogue = character.get("dialogue")
        if not dialogue:
            continue
        slug = character["slug"]
        nodes = dialogue.get("nodes", [])
        if not nodes:
            raise ContentError(f"Персонаж '{slug}': dialogue указан, но нет nodes")

        node_keys = {node.get("key") for node in nodes}
        seen_node_keys: set[str] = set()
        entry_count = 0

        for node in nodes:
            key = node.get("key")
            if not key:
                raise ContentError(f"Персонаж '{slug}': у узла диалога нет key: {node}")
            if key in seen_node_keys:
                raise ContentError(f"Персонаж '{slug}': повторяющийся key узла '{key}'")
            seen_node_keys.add(key)
            if node.get("entry"):
                entry_count += 1

            node_next = node.get("next")
            if node_next and node_next not in node_keys:
                raise ContentError(
                    f"Персонаж '{slug}', узел '{key}': next ссылается "
                    f"на неизвестный узел '{node_next}'"
                )

            options = node.get("options", [])
            if not options:
                raise ContentError(f"Персонаж '{slug}', узел '{key}': нет options")

            seen_option_keys: set[str] = set()
            for option in options:
                okey = option.get("key")
                if not okey or not option.get("text") or not option.get("reply"):
                    raise ContentError(
                        f"Персонаж '{slug}', узел '{key}': у варианта нет key/text/reply: {option}"
                    )
                if okey in seen_option_keys:
                    raise ContentError(
                        f"Персонаж '{slug}', узел '{key}': повторяющийся key варианта '{okey}'"
                    )
                seen_option_keys.add(okey)

                option_next = option.get("next")
                if option_next and option_next not in node_keys:
                    raise ContentError(
                        f"Персонаж '{slug}', узел '{key}', вариант '{okey}': next "
                        f"ссылается на неизвестный узел '{option_next}'"
                    )

        if entry_count != 1:
            raise ContentError(
                f"Персонаж '{slug}': dialogue должен иметь ровно один входной узел "
                f"(entry: true), сейчас {entry_count}"
            )


def validate_stages(stages: list[dict[str, Any]]) -> None:
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
            if not field.get("accepted") and not field.get("accepted_contains"):
                raise ContentError(
                    f"Этап '{slug}', поле '{field.get('key')}': нет принятых ответов "
                    "(accepted и/или accepted_contains)"
                )

        for prerequisite in stage.get("requires", []):
            if prerequisite not in all_slugs:
                raise ContentError(f"Этап '{slug}' требует неизвестный этап '{prerequisite}'")


def validate_phone_numbers(phone_numbers: list[dict[str, Any]]) -> None:
    seen_numbers: set[str] = set()

    for phone in phone_numbers:
        number = phone.get("number")
        if not number:
            raise ContentError(f"У номера нет number: {phone}")
        if number in seen_numbers:
            raise ContentError(f"Повторяющийся номер: {number}")
        seen_numbers.add(number)

        phases = phone.get("phases", [])
        if not phases:
            raise ContentError(f"Номер '{number}': нет ни одной фазы (phases)")

        phase_keys = {phase.get("key") for phase in phases}
        entry_count = 0
        for phase in phases:
            key = phase.get("key")
            if not key:
                raise ContentError(f"Номер '{number}': у фазы нет key: {phase}")
            if not phase.get("audio"):
                raise ContentError(f"Номер '{number}', фаза '{key}': нет audio")
            if phase.get("entry"):
                entry_count += 1
            if phase.get("requires_password") and not phase.get("password"):
                raise ContentError(
                    f"Номер '{number}', фаза '{key}': requires_password=true, но нет password"
                )
            for link_field in ("on_success", "on_failure"):
                target = phase.get(link_field)
                if target and target not in phase_keys:
                    raise ContentError(
                        f"Номер '{number}', фаза '{key}': {link_field} ссылается "
                        f"на неизвестную фазу '{target}'"
                    )

        if entry_count != 1:
            raise ContentError(
                f"Номер '{number}': должна быть ровно одна входная фаза (entry: true), "
                f"сейчас {entry_count}"
            )


def _resolve_audio_url(client, audio: str) -> str:
    """Если рядом с YAML лежит настоящий аудиофайл (data/audio/<audio>) —
    загрузить его в Supabase Storage и вернуть публичную ссылку. Если файла
    нет (контент-автор ещё не записал звук для этой фазы), оставить строку
    как есть — фронтенд в этом случае просто покажет её текстом, как и
    раньше, до появления реального аудио."""
    local_path = AUDIO_ASSETS_DIR / audio
    if not local_path.is_file():
        return audio

    content_type = AUDIO_CONTENT_TYPES.get(local_path.suffix.lower(), "application/octet-stream")
    content = local_path.read_bytes()
    client.storage.from_(AUDIO_BUCKET).upload(
        audio, content, {"content-type": content_type, "upsert": "true"}
    )
    return client.storage.from_(AUDIO_BUCKET).get_public_url(audio)


def _backfill_existing_teams(
    client, character_slug_to_id: dict[str, str], character_start_node_id: dict[str, str]
) -> None:
    """Персонажа иногда добавляют в контент уже после того, как какие-то
    команды успели зарегистрироваться — а seed_team_chats/
    seed_team_dialogue_state (backend/chat.py, backend/dialogue.py)
    выполняются только один раз, в момент регистрации команды. Без этого
    шага у таких "старых" команд навсегда не появился бы чат с новым
    персонажем — они не были бы видны в разделе "Диалоги" ни при каком
    выборе персонажа, хотя сам персонаж существует и активен."""
    team_ids = [row["id"] for row in client.table("teams").select("id").execute().data]
    if not team_ids:
        return

    added_chats = 0
    added_dialogue_states = 0
    for slug, character_id in character_slug_to_id.items():
        existing_team_ids = {
            row["team_id"]
            for row in client.table("chats")
            .select("team_id")
            .eq("character_id", character_id)
            .execute()
            .data
        }
        missing_team_ids = [team_id for team_id in team_ids if team_id not in existing_team_ids]
        if missing_team_ids:
            client.table("chats").insert(
                [
                    {"team_id": team_id, "character_id": character_id, "chat_type": "character"}
                    for team_id in missing_team_ids
                ]
            ).execute()
            added_chats += len(missing_team_ids)

        start_node_id = character_start_node_id.get(slug)
        if not start_node_id:
            continue
        existing_state_team_ids = {
            row["team_id"]
            for row in client.table("team_dialogue_state")
            .select("team_id")
            .eq("character_id", character_id)
            .execute()
            .data
        }
        missing_state_team_ids = [
            team_id for team_id in team_ids if team_id not in existing_state_team_ids
        ]
        if missing_state_team_ids:
            client.table("team_dialogue_state").insert(
                [
                    {
                        "team_id": team_id,
                        "character_id": character_id,
                        "current_node_id": start_node_id,
                    }
                    for team_id in missing_state_team_ids
                ]
            ).execute()
            added_dialogue_states += len(missing_state_team_ids)

    if added_chats or added_dialogue_states:
        print(
            f"\nДозаполнено для уже зарегистрированных команд: {added_chats} чатов персонажей, "
            f"{added_dialogue_states} состояний диалога."
        )


def import_content(path: Path = DEFAULT_CONTENT_PATH) -> None:
    data = load_content(path)
    characters = data.get("characters", [])
    stages = data.get("stages", [])
    phone_numbers = data.get("phone_numbers", [])
    validate_characters(characters)
    validate_dialogues(characters)
    validate_stages(stages)
    validate_phone_numbers(phone_numbers)

    client = get_supabase_client()

    character_slug_to_id: dict[str, str] = {}
    for character in characters:
        row = (
            client.table("characters")
            .upsert(
                {
                    "slug": character["slug"],
                    "name": character["name"],
                    "nickname": character["nickname"],
                    "public_lore": character.get("public_lore", ""),
                },
                on_conflict="slug",
            )
            .execute()
            .data[0]
        )
        character_slug_to_id[character["slug"]] = row["id"]
        print(f"персонаж: {character['slug']}")

    character_start_node_id: dict[str, str] = {}
    for character in characters:
        dialogue = character.get("dialogue")
        if not dialogue:
            continue
        character_id = character_slug_to_id[character["slug"]]
        nodes = dialogue.get("nodes", [])

        # Первый проход: создать/обновить узлы без next_node_id (нужны id
        # остальных узлов, включая ещё не созданные).
        key_to_node_id: dict[str, str] = {}
        for node in nodes:
            row = (
                client.table("dialogue_nodes")
                .upsert(
                    {
                        "character_id": character_id,
                        "content_key": node["key"],
                        "intro_message": node.get("intro", ""),
                        "is_start": node.get("entry", False),
                        "requires_all_options": node.get("requires_all_options", False),
                    },
                    on_conflict="character_id,content_key",
                )
                .execute()
                .data[0]
            )
            key_to_node_id[node["key"]] = row["id"]
            if node.get("entry"):
                character_start_node_id[character["slug"]] = row["id"]

        # Второй проход: node.next_node_id (для requires_all_options) и все опции.
        for node in nodes:
            node_id = key_to_node_id[node["key"]]

            if node.get("next"):
                client.table("dialogue_nodes").update(
                    {"next_node_id": key_to_node_id[node["next"]]}
                ).eq("id", node_id).execute()

            for option in node.get("options", []):
                client.table("dialogue_options").upsert(
                    {
                        "node_id": node_id,
                        "content_key": option["key"],
                        "option_text": option["text"],
                        "reply_message": option["reply"],
                        "next_node_id": key_to_node_id.get(option.get("next")),
                        "requires_admin_approval": option.get("requires_admin_approval", False),
                    },
                    on_conflict="node_id,content_key",
                ).execute()

        print(f"диалог персонажа '{character['slug']}': {len(nodes)} узлов")

    _backfill_existing_teams(client, character_slug_to_id, character_start_node_id)

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
            accepted_rows = [
                {"field_id": field_id, "value": value, "match_mode": "exact"}
                for value in field.get("accepted", [])
            ] + [
                {"field_id": field_id, "value": value, "match_mode": "contains"}
                for value in field.get("accepted_contains", [])
            ]
            if accepted_rows:
                client.table("answer_field_accepted_values").insert(accepted_rows).execute()

    for phone in phone_numbers:
        character_slug = phone.get("character_slug")
        phone_row = (
            client.table("phone_numbers")
            .upsert(
                {
                    "number": phone["number"],
                    "character_id": character_slug_to_id.get(character_slug)
                    if character_slug
                    else None,
                },
                on_conflict="number",
            )
            .execute()
            .data[0]
        )
        phone_number_id = phone_row["id"]

        # Первый проход: создать/обновить фазы без ссылок на "следующую" фазу
        # (её id мы ещё не знаем для только что создаваемых фаз).
        key_to_phase_id: dict[str, str] = {}
        for phase in phone["phases"]:
            phase_row = (
                client.table("call_phases")
                .upsert(
                    {
                        "phone_number_id": phone_number_id,
                        "content_key": phase["key"],
                        "is_entry": phase.get("entry", False),
                        "audio_url": _resolve_audio_url(client, phase["audio"]),
                        "requires_password": phase.get("requires_password", False),
                        "correct_password": phase.get("password"),
                    },
                    on_conflict="phone_number_id,content_key",
                )
                .execute()
                .data[0]
            )
            key_to_phase_id[phase["key"]] = phase_row["id"]

        # Второй проход: проставить success_next/failure_next теперь,
        # когда все фазы этого номера уже существуют.
        for phase in phone["phases"]:
            client.table("call_phases").update(
                {
                    "success_next_phase_id": key_to_phase_id.get(phase.get("on_success")),
                    "failure_next_phase_id": key_to_phase_id.get(phase.get("on_failure")),
                }
            ).eq("id", key_to_phase_id[phase["key"]]).execute()

        print(f"номер: {phone['number']} ({len(phone['phases'])} фаз)")

    db_stage_slugs = {row["slug"] for row in client.table("stages").select("slug").execute().data}
    missing_stages = db_stage_slugs - {stage["slug"] for stage in stages}
    if missing_stages:
        print(
            f"\nПРЕДУПРЕЖДЕНИЕ: в базе есть этапы, которых нет в файле "
            f"(не удалены, проверьте сами): {sorted(missing_stages)}"
        )

    db_character_slugs = {
        row["slug"] for row in client.table("characters").select("slug").execute().data
    }
    missing_characters = db_character_slugs - {c["slug"] for c in characters}
    if missing_characters:
        print(
            f"\nПРЕДУПРЕЖДЕНИЕ: в базе есть персонажи, которых нет в файле "
            f"(не удалены, проверьте сами): {sorted(missing_characters)}"
        )

    db_numbers = {
        row["number"] for row in client.table("phone_numbers").select("number").execute().data
    }
    missing_numbers = db_numbers - {p["number"] for p in phone_numbers}
    if missing_numbers:
        print(
            f"\nПРЕДУПРЕЖДЕНИЕ: в базе есть номера, которых нет в файле "
            f"(не удалены, проверьте сами): {sorted(missing_numbers)}"
        )

    print(
        f"\nГотово: {len(characters)} персонажей, {len(stages)} этапов, "
        f"{len(phone_numbers)} номеров обработано."
    )


if __name__ == "__main__":
    content_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CONTENT_PATH
    try:
        import_content(content_path)
    except ContentError as exc:
        print(f"Ошибка в контенте: {exc}")
        sys.exit(1)
