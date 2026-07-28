"""Точка входа Flask-приложения."""

from __future__ import annotations

from flask import Flask, jsonify
from flask.typing import ResponseReturnValue

from config import load_config


def create_app() -> Flask:
    """Собрать и сконфигурировать Flask-приложение."""
    config = load_config()

    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.secret_key

    @app.get("/health")
    def health() -> ResponseReturnValue:
        return jsonify(status="ok")

    return app


app = create_app()

if __name__ == "__main__":
    config = load_config()
    app.run(host=config.host, port=config.port, debug=config.debug)
