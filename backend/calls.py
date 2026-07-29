"""Эмуляция звонков.

Флоу без серверной "сессии звонка": клиент просто передаёт id фазы,
на которой сейчас находится (полученный из предыдущего ответа), когда
вводит пароль — это проще, чем хранить состояние активного звонка.
"""

from __future__ import annotations

import random

from supabase_client import get_supabase_client

RANDOM_OUTCOMES = ("nonexistent", "unavailable", "prank")


class CallError(Exception):
    """Ожидаемая ошибка (такой фазы нет, фаза не предполагает пароль и т.п.)."""


def _normalize(value: str) -> str:
    return value.strip().casefold()


def dial_number(team_id: str, number: str) -> dict:
    """Набрать номер. Возвращает, что произошло, и данные для проигрывания."""
    client = get_supabase_client()

    phone = client.table("phone_numbers").select("id").eq("number", number).execute().data
    if not phone:
        outcome = random.choice(RANDOM_OUTCOMES)
        client.table("call_logs").insert(
            {"team_id": team_id, "dialed_number": number, "outcome": outcome}
        ).execute()
        return {"connected": False, "outcome": outcome}

    phone_number_id = phone[0]["id"]
    entry_phase_rows = (
        client.table("call_phases")
        .select("id, audio_url, requires_password")
        .eq("phone_number_id", phone_number_id)
        .eq("is_entry", True)
        .execute()
        .data
    )
    if not entry_phase_rows:
        # Контент для этого номера ещё не готов (нет входной фазы) —
        # считаем недоступным, а не падаем с ошибкой.
        outcome = "unavailable"
        client.table("call_logs").insert(
            {
                "team_id": team_id,
                "dialed_number": number,
                "phone_number_id": phone_number_id,
                "outcome": outcome,
            }
        ).execute()
        return {"connected": False, "outcome": outcome}

    phase = entry_phase_rows[0]
    client.table("call_logs").insert(
        {
            "team_id": team_id,
            "dialed_number": number,
            "phone_number_id": phone_number_id,
            "outcome": "story",
            "reached_phase_id": phase["id"],
        }
    ).execute()

    return {
        "connected": True,
        "phone_number_id": phone_number_id,
        "phase_id": phase["id"],
        "audio_url": phase["audio_url"],
        "requires_password": phase["requires_password"],
    }


def submit_phase_password(team_id: str, phase_id: str, password: str) -> dict:
    """Ввести пароль на текущей фазе. Возвращает следующую фазу (если она есть)."""
    client = get_supabase_client()

    phase_rows = (
        client.table("call_phases")
        .select(
            "id, phone_number_id, requires_password, correct_password, "
            "success_next_phase_id, failure_next_phase_id"
        )
        .eq("id", phase_id)
        .execute()
        .data
    )
    if not phase_rows:
        raise CallError("Такой фазы звонка нет")

    phase = phase_rows[0]
    if not phase["requires_password"]:
        raise CallError("Эта фаза не предполагает ввод пароля")

    is_correct = _normalize(password) == _normalize(phase["correct_password"] or "")
    next_phase_id = (
        phase["success_next_phase_id"] if is_correct else phase["failure_next_phase_id"]
    )

    client.table("call_logs").insert(
        {
            "team_id": team_id,
            "phone_number_id": phase["phone_number_id"],
            "outcome": "story",
            "reached_phase_id": next_phase_id,
            "entered_password": password,
        }
    ).execute()

    if not next_phase_id:
        return {"correct": is_correct, "connected": False}

    next_phase = (
        client.table("call_phases")
        .select("id, audio_url, requires_password")
        .eq("id", next_phase_id)
        .execute()
        .data[0]
    )
    return {
        "correct": is_correct,
        "connected": True,
        "phase_id": next_phase["id"],
        "audio_url": next_phase["audio_url"],
        "requires_password": next_phase["requires_password"],
    }
