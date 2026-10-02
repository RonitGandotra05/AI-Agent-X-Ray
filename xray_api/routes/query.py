"""Retrieve recorded runs and explicitly request analysis."""

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.orm import joinedload
from ..models import db, Pipeline, Run, Step
from .shared import analysis_status, get_analyzer, pagination

query_bp = Blueprint("query", __name__)


def _page(query, key, serialize):
    limit, offset = pagination()
    return jsonify({key: [serialize(row) for row in query.offset(offset).limit(limit).all()],
                    "total": query.count(), "limit": limit, "offset": offset})


@query_bp.get("/api/pipelines")
def list_pipelines():
    return _page(Pipeline.query.order_by(Pipeline.created_at.desc(), Pipeline.id), "pipelines", lambda p: p.to_dict())


@query_bp.get("/api/runs")
def list_runs():
    query = Run.query.join(Pipeline).options(joinedload(Run.pipeline))
    if request.args.get("pipeline"):
        query = query.filter(Pipeline.name == request.args["pipeline"])
    if request.args.get("status"):
        query = query.filter(Run.status == request.args["status"])
    return _page(query.order_by(Run.created_at.desc(), Run.id), "runs", lambda r: r.to_dict())


@query_bp.get("/api/runs/<run_id>")
def get_run(run_id):
    run = db.session.get(Run, run_id)
    if run is None:
        return jsonify({"error": "Run not found"}), 404
    return jsonify(run.to_dict(include_steps=True))


@query_bp.get("/api/runs/<run_id>/analysis")
def get_analysis(run_id):
    run = db.session.get(Run, run_id)
    if run is None:
        return jsonify({"error": "Run not found"}), 404
    return jsonify({"run_id": run.id, "status": run.status, "analysis": run.analysis_result})


@query_bp.post("/api/analyze/<run_id>")
def trigger_analysis(run_id):
    run = db.session.get(Run, run_id)
    if run is None:
        return jsonify({"error": "Run not found"}), 404
    try:
        result = get_analyzer().analyze_run(run.to_dict(include_steps=True))
        run.analysis_result = result
        run.status = analysis_status(result)
        db.session.commit()
        return jsonify({"success": True, "run_id": run.id, "status": run.status, "analysis": result})
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning("Run analysis failed (%s)", type(exc).__name__)
        run.analysis_result = {"analysis_status": "failed", "severity": "unknown", "error": "Analysis unavailable",
                               "error_type": type(exc).__name__}
        run.status = "analysis_failed"
        db.session.commit()
        return jsonify({"error": "Analysis unavailable", "run_id": run.id, "status": run.status}), 502


@query_bp.get("/api/search/steps")
def search_steps():
    query = Step.query.join(Run).join(Pipeline)
    if request.args.get("step_name"):
        safe = request.args["step_name"].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.filter(Step.step_name.ilike(f"%{safe}%", escape="\\"))
    if request.args.get("pipeline"):
        query = query.filter(Pipeline.name == request.args["pipeline"])
    return _page(query.order_by(Step.created_at.desc(), Step.id), "steps", lambda s: s.to_dict())
