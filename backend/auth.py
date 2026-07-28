"""Аутентификация команд и админов поверх Supabase Auth.

У команды/админа нет настоящего email — для входа используется человеко-
читаемое имя (название команды / логин админа). Supabase Auth требует
email, поэтому backend сам генерирует синтетический адрес вида
"<uuid>@team.quest.local" и хранит его в таблице (teams.auth_email /
admins.auth_email), чтобы при входе по имени найти нужный email.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from supabase_auth.errors import AuthApiError

from supabase_client import get_supabase_client

AUTH_EMAIL_DOMAIN = "team.quest.local"
ADMIN_ROLES = ("actor", "operator")


class AuthError(Exception):
    """Ожидаемая ошибка регистрации или входа (неверные данные и т.п.)."""


@dataclass(frozen=True)
class Session:
    """Результат успешного входа: кто вошёл + токены для Supabase-клиента фронтенда."""

    access_token: str
    refresh_token: str


@dataclass(frozen=True)
class TeamSession(Session):
    team_id: str
    name: str


@dataclass(frozen=True)
class AdminSession(Session):
    admin_id: str
    username: str
    role: str


def _synthetic_email(entity_id: uuid.UUID) -> str:
    return f"{entity_id}@{AUTH_EMAIL_DOMAIN}"


def _sign_in(email: str, password: str) -> Session:
    client = get_supabase_client()
    try:
        result = client.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
    except AuthApiError as exc:
        raise AuthError("Неверное название команды/логин или пароль") from exc

    return Session(
        access_token=result.session.access_token,
        refresh_token=result.session.refresh_token,
    )


def register_team(name: str, password: str) -> TeamSession:
    """Создать новую команду: пользователь в Supabase Auth + строка в teams."""
    client = get_supabase_client()
    team_id = uuid.uuid4()
    email = _synthetic_email(team_id)

    try:
        auth_user = client.auth.admin.create_user(
            {"email": email, "password": password, "email_confirm": True}
        )
    except AuthApiError as exc:
        raise AuthError(f"Не удалось создать команду: {exc}") from exc

    try:
        client.table("teams").insert(
            {
                "id": str(team_id),
                "name": name,
                "auth_user_id": auth_user.user.id,
                "auth_email": email,
            }
        ).execute()
    except Exception as exc:  # noqa: BLE001 — если запись в teams не удалась (например,
        # имя занято), нужно откатить уже созданного auth-пользователя, иначе
        # останется "команда-призрак" без строки в teams.
        client.auth.admin.delete_user(auth_user.user.id)
        raise AuthError(f"Не удалось зарегистрировать команду: {exc}") from exc

    session = _sign_in(email, password)
    return TeamSession(
        team_id=str(team_id),
        name=name,
        access_token=session.access_token,
        refresh_token=session.refresh_token,
    )


def login_team(name: str, password: str) -> TeamSession:
    """Войти под уже существующей командой по названию и паролю."""
    client = get_supabase_client()
    result = client.table("teams").select("id, auth_email").eq("name", name).execute()
    if not result.data:
        raise AuthError("Неверное название команды/логин или пароль")

    team_row = result.data[0]
    session = _sign_in(team_row["auth_email"], password)
    return TeamSession(
        team_id=team_row["id"],
        name=name,
        access_token=session.access_token,
        refresh_token=session.refresh_token,
    )


def register_admin(username: str, password: str, role: str) -> AdminSession:
    """Создать нового админа. Не вызывается из HTTP — только из create_admin.py."""
    if role not in ADMIN_ROLES:
        raise AuthError(f"Роль должна быть одной из {ADMIN_ROLES}, получено: {role}")

    client = get_supabase_client()
    admin_id = uuid.uuid4()
    email = _synthetic_email(admin_id)

    try:
        auth_user = client.auth.admin.create_user(
            {"email": email, "password": password, "email_confirm": True}
        )
    except AuthApiError as exc:
        raise AuthError(f"Не удалось создать админа: {exc}") from exc

    try:
        client.table("admins").insert(
            {
                "id": str(admin_id),
                "username": username,
                "role": role,
                "auth_user_id": auth_user.user.id,
                "auth_email": email,
            }
        ).execute()
    except Exception as exc:  # noqa: BLE001 — та же логика отката, что и в register_team
        client.auth.admin.delete_user(auth_user.user.id)
        raise AuthError(f"Не удалось зарегистрировать админа: {exc}") from exc

    session = _sign_in(email, password)
    return AdminSession(
        admin_id=str(admin_id),
        username=username,
        role=role,
        access_token=session.access_token,
        refresh_token=session.refresh_token,
    )


def login_admin(username: str, password: str) -> AdminSession:
    client = get_supabase_client()
    result = (
        client.table("admins")
        .select("id, role, auth_email")
        .eq("username", username)
        .execute()
    )
    if not result.data:
        raise AuthError("Неверный логин или пароль")

    admin_row = result.data[0]
    session = _sign_in(admin_row["auth_email"], password)
    return AdminSession(
        admin_id=admin_row["id"],
        username=username,
        role=admin_row["role"],
        access_token=session.access_token,
        refresh_token=session.refresh_token,
    )
