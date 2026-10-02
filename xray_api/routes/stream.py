"""SSE events from explicit analysis, with persisted completion and failure status."""

import json
from flask import Blueprint, Response, current_app, jsonify, stream_with_context
from ..models import db, Run
from .shared import analysis_status, get_analyzer

stream_bp = Blueprint("stream", __name__)


def _event(kind, data):
    return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


@stream_bp.get("/api/analyze/<run_id>/stream")
def stream_analysis(run_id):
    run = db.session.get(Run, run_id)
    if run is None:
        return jsonify({"error": "Run not found"}), 404
    # Materialize relationships before entering the generator.
    run_data = run.to_dict(include_steps=True)

    @stream_with_context
    def generate():
        try:
            analyzer = get_analyzer()
            for event in analyzer.analyze_run_streaming(run_data):
                if event.get("event") == "complete":
                    stored_run = db.session.get(Run, run_id)
                    stored_run.analysis_result = event["data"]
                    stored_run.status = analysis_status(event["data"])
                    db.session.commit()
                yield _event(event.get("event", "message"), event.get("data", {}))
        except GeneratorExit:
            # A client disconnect does not create a successful analysis.
            db.session.rollback()
            raise
        except Exception as exc:
            db.session.rollback()
            current_app.logger.warning("Stream analysis failed (%s)", type(exc).__name__)
            stored_run = db.session.get(Run, run_id)
            stored_run.status = "analysis_failed"
            stored_run.analysis_result = {"analysis_status": "failed", "severity": "unknown", "error": "Analysis unavailable",
                                          "error_type": type(exc).__name__}
            db.session.commit()
            yield _event("error", {"error": "Analysis unavailable", "error_type": type(exc).__name__})

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
