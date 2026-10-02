"""Small route helpers; analyzer lifetime belongs to each Flask app."""

from flask import current_app, request
from werkzeug.exceptions import BadRequest

from ..agents.analyzer import XRayAnalyzer


def get_analyzer() -> XRayAnalyzer:
    configured = current_app.config.get("XRAY_ANALYZER")
    if configured is not None:
        return configured
    with current_app.extensions["xray_analyzer_lock"]:
        if "xray_analyzer" not in current_app.extensions:
            current_app.extensions["xray_analyzer"] = XRayAnalyzer()
        return current_app.extensions["xray_analyzer"]


def pagination():
    values = {}
    for key, default in (("limit", 50), ("offset", 0)):
        raw = request.args.get(key, str(default))
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise BadRequest(f"{key} must be an integer") from exc
        if value < 0 or (key == "limit" and not 1 <= value <= 200):
            raise BadRequest(f"{key} must be {'between 1 and 200' if key == 'limit' else 'non-negative'}")
        values[key] = value
    return values["limit"], values["offset"]


def analysis_status(result):
    status = result.get("analysis_status", "complete")
    return "analyzed" if status == "complete" else "analysis_partial" if status == "partial" else "analysis_failed"


def acknowledgement(run):
    return {"success": True, "run_id": run.id, "status": run.status, "analysis": run.analysis_result}
