"""Точка входа Flask-приложения."""

from __future__ import annotations

from datetime import timedelta

from flask import Flask, jsonify, request, session
from flask.typing import ResponseReturnValue

from auth import AuthError, login_admin, login_team, register_team
from config import load_config
from supabase_client import get_supabase_client

SESSION_LIFETIME_DAYS = 30


def create_app() -> Flask:
    """Собрать и сконфигурировать Flask-приложение."""
    config = load_config()

    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.secret_key
    app.permanent_session_lifetime = timedelta(days=SESSION_LIFETIME_DAYS)

    @app.get("/health")
    def health() -> ResponseReturnValue:
        return jsonify(status="ok")

    @app.get("/health/supabase")
    def health_supabase() -> ResponseReturnValue:
        if not config.supabase_url or not config.supabase_service_key:
            return jsonify(status="not_configured"), 200

        try:
            client = get_supabase_client()
            client.storage.list_buckets()
        except Exception as exc:  # noqa: BLE001 — граница с внешним API: любой сбой сети/авторизации должен вернуть понятный статус, а не упасть 500
            return jsonify(status="error", detail=str(exc)), 503

        return jsonify(status="ok"), 200

    @app.post("/auth/team/register")
    def team_register() -> ResponseReturnValue:
        data = request.get_json(silent=True) or {}
        name = str(data.get("name", "")).strip()
        password = str(data.get("password", ""))
        if not name or not password:
            return jsonify(status="error", detail="Укажите название команды и пароль"), 400

        try:
            team_session = register_team(name, password)
        except AuthError as exc:
            return jsonify(status="error", detail=str(exc)), 400

        session.permanent = True
        session["identity"] = "team"
        session["team_id"] = team_session.team_id

        return jsonify(
            status="ok",
            team_id=team_session.team_id,
            name=team_session.name,
            access_token=team_session.access_token,
            refresh_token=team_session.refresh_token,
        )

    @app.post("/auth/team/login")
    def team_login() -> ResponseReturnValue:
        data = request.get_json(silent=True) or {}
        name = str(data.get("name", "")).strip()
        password = str(data.get("password", ""))
        if not name or not password:
            return jsonify(status="error", detail="Укажите название команды и пароль"), 400

        try:
            team_session = login_team(name, password)
        except AuthError as exc:
            return jsonify(status="error", detail=str(exc)), 401

        session.permanent = True
        session["identity"] = "team"
        session["team_id"] = team_session.team_id

        return jsonify(
            status="ok",
            team_id=team_session.team_id,
            name=team_session.name,
            access_token=team_session.access_token,
            refresh_token=team_session.refresh_token,
        )

    @app.post("/auth/admin/login")
    def admin_login() -> ResponseReturnValue:
        data = request.get_json(silent=True) or {}
        username = str(data.get("username", "")).strip()
        password = str(data.get("password", ""))
        if not username or not password:
            return jsonify(status="error", detail="Укажите логин и пароль"), 400

        try:
            admin_session = login_admin(username, password)
        except AuthError as exc:
            return jsonify(status="error", detail=str(exc)), 401

        session.permanent = True
        session["identity"] = "admin"
        session["admin_id"] = admin_session.admin_id
        session["role"] = admin_session.role

        return jsonify(
            status="ok",
            admin_id=admin_session.admin_id,
            username=admin_session.username,
            role=admin_session.role,
            access_token=admin_session.access_token,
            refresh_token=admin_session.refresh_token,
        )

    @app.get("/auth/me")
    def auth_me() -> ResponseReturnValue:
        identity = session.get("identity")
        if identity == "team":
            return jsonify(status="ok", identity="team", team_id=session.get("team_id"))
        if identity == "admin":
            return jsonify(
                status="ok",
                identity="admin",
                admin_id=session.get("admin_id"),
                role=session.get("role"),
            )
        return jsonify(status="ok", identity=None)

    @app.post("/auth/logout")
    def logout() -> ResponseReturnValue:
        session.clear()
        return jsonify(status="ok")

    return app


app = create_app()

if __name__ == "__main__":
    config = load_config()
    app.run(host=config.host, port=config.port, debug=config.debug)
