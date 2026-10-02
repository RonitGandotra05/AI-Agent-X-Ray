"""Flask application factory for the optional self-hosted X-Ray API."""

import hmac
import os
from threading import Lock
from typing import Any, Mapping, Optional

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from .models import db
from .routes.ingest import ingest_bp
from .routes.query import query_bp
from .routes.stream import stream_bp


def create_app(config: Optional[Mapping[str, Any]] = None) -> Flask:
    """Apply config before initialization; tests may inject XRAY_ANALYZER."""
    app = Flask(__name__)
    database_url = os.getenv("DATABASE_URL", "sqlite:///xray.db")
    if database_url.startswith("postgres://"):
        database_url = "postgresql://" + database_url[len("postgres://"):]
    app.config.update(SQLALCHEMY_DATABASE_URI=database_url,
                      SQLALCHEMY_TRACK_MODIFICATIONS=False,
                      SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
                      XRAY_API_KEY=os.getenv("XRAY_API_KEY"),
                      XRAY_CORS_ORIGINS=os.getenv("XRAY_CORS_ORIGINS", ""),
                      MAX_CONTENT_LENGTH=10 * 1024 * 1024,
                      XRAY_CREATE_TABLES=True)
    if config:
        app.config.update(config)
    if app.config["XRAY_API_KEY"] is not None and not isinstance(app.config["XRAY_API_KEY"], str):
        raise ValueError("XRAY_API_KEY must be a string or None")
    if not isinstance(app.config["XRAY_CORS_ORIGINS"], (str, list, tuple)):
        raise ValueError("XRAY_CORS_ORIGINS must be a comma-separated string or a list")
    app.json.sort_keys = False
    db.init_app(app)
    app.extensions["xray_analyzer_lock"] = Lock()

    @app.before_request
    def check_api_key():
        if request.path == "/health" or request.method == "OPTIONS":
            return None
        expected = app.config["XRAY_API_KEY"]
        if expected and not hmac.compare_digest(request.headers.get("X-API-Key", "").encode(), str(expected).encode()):
            return jsonify({"error": "Invalid or missing API key"}), 401
        return None

    @app.after_request
    def configured_cors(response):
        origins = app.config["XRAY_CORS_ORIGINS"]
        if isinstance(origins, str):
            origins = [origin.strip() for origin in origins.split(",") if origin.strip()]
        origin = request.headers.get("Origin")
        if origin and origin in origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers.add("Vary", "Origin")
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

    app.register_blueprint(ingest_bp)
    app.register_blueprint(query_bp)
    app.register_blueprint(stream_bp)

    @app.errorhandler(HTTPException)
    def http_error(error):
        body = {"error": error.description, "type": error.name}
        if error.code == 413:
            body["max_bytes"] = app.config["MAX_CONTENT_LENGTH"]
        return jsonify(body), error.code

    @app.errorhandler(Exception)
    def unexpected_error(error):
        db.session.rollback()
        app.logger.error("API request failed (%s)", type(error).__name__)
        return jsonify({"error": "Internal server error"}), 500

    @app.get("/health")
    def health():
        return {"status": "healthy"}

    if app.config["XRAY_CREATE_TABLES"]:
        with app.app_context():
            db.create_all()
    return app


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    create_app().run(host="127.0.0.1", port=5000)
