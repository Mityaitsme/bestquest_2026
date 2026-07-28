"""Точка входа Flask-приложения."""

from __future__ import annotations

from datetime import timedelta

from flask import Flask, jsonify, request, session
from flask.typing import ResponseReturnValue

from answers import AnswerError, get_stage_fields, submit_field_answer
from auth import AuthError, login_admin, login_team, register_team
from chat import (
    ChatError,
    list_messages,
    list_messages_admin,
    list_team_chats,
    list_team_chats_admin,
    seed_team_chats,
    send_admin_message,
    send_team_message,
    set_chat_mode,
)
from config import load_config
from reviews import (
    ReviewError,
    get_photo_signed_url,
    list_pending_reviews,
    review_decision,
    submit_manual_review,
    upload_review_photo,
)
from supabase_client import get_supabase_client
from tasks import (
    TaskError,
    complete_checkbox_stage,
    list_team_tasks,
    mark_stage_completed,
    seed_team_progress,
)

SESSION_LIFETIME_DAYS = 30
MAX_UPLOAD_CONTENT_LENGTH = 9 * 1024 * 1024


def create_app() -> Flask:
    """Собрать и сконфигурировать Flask-приложение."""
    config = load_config()

    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.secret_key
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_CONTENT_LENGTH
    app.permanent_session_lifetime = timedelta(days=SESSION_LIFETIME_DAYS)

    def require_operator() -> ResponseReturnValue | None:
        if session.get("identity") != "admin" or session.get("role") != "operator":
            return jsonify(status="error", detail="Требуется вход как оператор"), 403
        return None

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
            seed_team_progress(team_session.team_id)
            seed_team_chats(team_session.team_id)
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

    @app.get("/tasks")
    def get_tasks() -> ResponseReturnValue:
        if session.get("identity") != "team":
            return jsonify(status="error", detail="Требуется вход как команда"), 401
        return jsonify(status="ok", tasks=list_team_tasks(session["team_id"]))

    @app.get("/admin/teams/<team_id>/tasks")
    def admin_get_team_tasks(team_id: str) -> ResponseReturnValue:
        if session.get("identity") != "admin":
            return jsonify(status="error", detail="Требуется вход как админ"), 401
        return jsonify(status="ok", tasks=list_team_tasks(team_id))

    @app.post("/admin/teams/<team_id>/stages/<stage_id>/complete")
    def admin_complete_stage(team_id: str, stage_id: str) -> ResponseReturnValue:
        if session.get("identity") != "admin":
            return jsonify(status="error", detail="Требуется вход как админ"), 401

        try:
            mark_stage_completed(
                team_id=team_id,
                stage_id=stage_id,
                completed_by_admin_id=session["admin_id"],
                completion_method="actor",
            )
        except TaskError as exc:
            return jsonify(status="error", detail=str(exc)), 400

        return jsonify(status="ok")

    @app.get("/tasks/<stage_id>/fields")
    def get_task_fields(stage_id: str) -> ResponseReturnValue:
        if session.get("identity") != "team":
            return jsonify(status="error", detail="Требуется вход как команда"), 401

        try:
            fields = get_stage_fields(session["team_id"], stage_id)
        except AnswerError as exc:
            return jsonify(status="error", detail=str(exc)), 400

        return jsonify(status="ok", fields=fields)

    @app.post("/tasks/<stage_id>/fields/<field_id>/submit")
    def submit_task_field(stage_id: str, field_id: str) -> ResponseReturnValue:
        if session.get("identity") != "team":
            return jsonify(status="error", detail="Требуется вход как команда"), 401

        data = request.get_json(silent=True) or {}
        value = str(data.get("value", ""))
        if not value.strip():
            return jsonify(status="error", detail="Пустой ответ"), 400

        try:
            result = submit_field_answer(session["team_id"], stage_id, field_id, value)
        except AnswerError as exc:
            return jsonify(status="error", detail=str(exc)), 400

        return jsonify(status="ok", **result)

    @app.post("/tasks/<stage_id>/checkbox-complete")
    def checkbox_complete_task(stage_id: str) -> ResponseReturnValue:
        if session.get("identity") != "team":
            return jsonify(status="error", detail="Требуется вход как команда"), 401

        try:
            complete_checkbox_stage(session["team_id"], stage_id)
        except TaskError as exc:
            return jsonify(status="error", detail=str(exc)), 400

        return jsonify(status="ok")

    @app.post("/tasks/<stage_id>/manual-review")
    def submit_task_manual_review(stage_id: str) -> ResponseReturnValue:
        if session.get("identity") != "team":
            return jsonify(status="error", detail="Требуется вход как команда"), 401

        text = request.form.get("text", "").strip()
        photo_path = None
        photo_file = request.files.get("photo")
        if photo_file and photo_file.filename:
            try:
                photo_path = upload_review_photo(photo_file.read(), photo_file.mimetype)
            except ReviewError as exc:
                return jsonify(status="error", detail=str(exc)), 400

        if not text and not photo_path:
            return jsonify(status="error", detail="Нужен текст ответа или фото"), 400

        try:
            review_id = submit_manual_review(session["team_id"], stage_id, text, photo_path)
        except ReviewError as exc:
            return jsonify(status="error", detail=str(exc)), 400

        return jsonify(status="ok", review_id=review_id)

    @app.get("/admin/reviews")
    def admin_list_reviews() -> ResponseReturnValue:
        denied = require_operator()
        if denied:
            return denied
        return jsonify(status="ok", reviews=list_pending_reviews())

    @app.get("/admin/reviews/<review_id>/photo-url")
    def admin_review_photo_url(review_id: str) -> ResponseReturnValue:
        denied = require_operator()
        if denied:
            return denied

        try:
            url = get_photo_signed_url(review_id)
        except ReviewError as exc:
            return jsonify(status="error", detail=str(exc)), 400

        return jsonify(status="ok", url=url)

    @app.post("/admin/reviews/<review_id>/decision")
    def admin_review_decision(review_id: str) -> ResponseReturnValue:
        denied = require_operator()
        if denied:
            return denied

        data = request.get_json(silent=True) or {}
        accept = bool(data.get("accept"))
        comment = data.get("comment")

        try:
            review_decision(review_id, session["admin_id"], accept, comment)
        except ReviewError as exc:
            return jsonify(status="error", detail=str(exc)), 400

        return jsonify(status="ok")

    @app.get("/chats")
    def get_chats() -> ResponseReturnValue:
        if session.get("identity") != "team":
            return jsonify(status="error", detail="Требуется вход как команда"), 401
        return jsonify(status="ok", chats=list_team_chats(session["team_id"]))

    @app.get("/chats/<chat_id>/messages")
    def get_chat_messages(chat_id: str) -> ResponseReturnValue:
        if session.get("identity") != "team":
            return jsonify(status="error", detail="Требуется вход как команда"), 401

        try:
            messages = list_messages(session["team_id"], chat_id)
        except ChatError as exc:
            return jsonify(status="error", detail=str(exc)), 400

        return jsonify(status="ok", messages=messages)

    @app.post("/chats/<chat_id>/messages")
    def post_chat_message(chat_id: str) -> ResponseReturnValue:
        if session.get("identity") != "team":
            return jsonify(status="error", detail="Требуется вход как команда"), 401

        data = request.get_json(silent=True) or {}
        content = str(data.get("content", "")).strip()
        if not content:
            return jsonify(status="error", detail="Пустое сообщение"), 400

        try:
            send_team_message(session["team_id"], chat_id, content)
        except ChatError as exc:
            return jsonify(status="error", detail=str(exc)), 400

        return jsonify(status="ok")

    @app.get("/admin/teams/<team_id>/chats")
    def admin_get_team_chats(team_id: str) -> ResponseReturnValue:
        denied = require_operator()
        if denied:
            return denied
        return jsonify(status="ok", chats=list_team_chats_admin(team_id))

    @app.get("/admin/chats/<chat_id>/messages")
    def admin_get_chat_messages(chat_id: str) -> ResponseReturnValue:
        denied = require_operator()
        if denied:
            return denied
        return jsonify(status="ok", messages=list_messages_admin(chat_id))

    @app.post("/admin/chats/<chat_id>/messages")
    def admin_post_chat_message(chat_id: str) -> ResponseReturnValue:
        denied = require_operator()
        if denied:
            return denied

        data = request.get_json(silent=True) or {}
        content = str(data.get("content", "")).strip()
        if not content:
            return jsonify(status="error", detail="Пустое сообщение"), 400

        try:
            send_admin_message(session["admin_id"], chat_id, content)
        except ChatError as exc:
            return jsonify(status="error", detail=str(exc)), 400

        return jsonify(status="ok")

    @app.post("/admin/chats/<chat_id>/mode")
    def admin_set_chat_mode(chat_id: str) -> ResponseReturnValue:
        denied = require_operator()
        if denied:
            return denied

        data = request.get_json(silent=True) or {}
        mode = str(data.get("mode", ""))

        try:
            set_chat_mode(chat_id, mode)
        except ChatError as exc:
            return jsonify(status="error", detail=str(exc)), 400

        return jsonify(status="ok")

    return app


app = create_app()

if __name__ == "__main__":
    config = load_config()
    app.run(host=config.host, port=config.port, debug=config.debug)
