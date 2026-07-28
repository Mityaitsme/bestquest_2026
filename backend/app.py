"""Точка входа Flask-приложения."""

from __future__ import annotations

from flask import Flask, jsonify
from flask.typing import ResponseReturnValue

from config import load_config
from supabase_client import get_supabase_client


def create_app() -> Flask:
    """Собрать и сконфигурировать Flask-приложение."""
    config = load_config()

    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.secret_key

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

    return app


app = create_app()

if __name__ == "__main__":
    config = load_config()
    app.run(host=config.host, port=config.port, debug=config.debug)
