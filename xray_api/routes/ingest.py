"""Validated ingestion with idempotent retry acknowledgements."""

import hashlib
import json
import uuid

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import BadRequest, Conflict

from ..models import db, Pipeline, Run, Step
from xray_shared.validation import json_snapshot
from .shared import acknowledgement, analysis_status, get_analyzer

ingest_bp = Blueprint("ingest", __name__)


def _text(value, field, *, required=False, max_length=None):
    if not isinstance(value, str) or (required and not value.strip()):
        raise BadRequest(f"{field} must be {'a non-empty' if required else 'a'} string")
    if max_length is not None and len(value) > max_length:
        raise BadRequest(f"{field} must have at most {max_length} characters")
    return value


def _validated_payload(data):
    if not isinstance(data, dict):
        raise BadRequest("Request JSON must be an object")
    name = _text(data.get("pipeline_name"), "pipeline_name", required=True, max_length=255)
    description_value = data.get("pipeline_description", data.get("description", ""))
    description = _text("" if description_value is None else description_value, "pipeline_description")
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        raise BadRequest("metadata must be an object")
    analyze = data.get("analyze", True)
    if type(analyze) is not bool:
        raise BadRequest("analyze must be a boolean")
    source = data.get("steps")
    if not isinstance(source, list) or not source:
        raise BadRequest("At least one step is required in a steps array")
    if len(source) > 50:
        raise BadRequest("Too many steps (max 50)")
    steps = []
    orders = set()
    for index, step in enumerate(source):
        if not isinstance(step, dict):
            raise BadRequest(f"Step {index + 1} must be an object")
        order = step.get("order")
        if type(order) is not int or order < 0 or order in orders:
            raise BadRequest(f"Step {index + 1}: order must be a unique non-negative integer")
        orders.add(order)
        step_description = step.get("description", "")
        normalized = {"name": _text(step.get("name"), f"Step {index + 1}: name", required=True, max_length=255),
                      "order": order, "description": _text("" if step_description is None else step_description, f"Step {index + 1}: description")}
        for key in ("inputs", "outputs", "reasons", "metrics"):
            value = step.get(key, {})
            if key in ("reasons", "metrics") and not isinstance(value, dict):
                raise BadRequest(f"Step {index + 1}: {key} must be an object")
            normalized[key] = value
        steps.append(normalized)
    payload = {"pipeline_name": name, "pipeline_description": description,
               "metadata": metadata, "analyze": analyze, "steps": sorted(steps, key=lambda s: s["order"])}
    try:
        payload = json_snapshot(payload, "payload")
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise BadRequest("Payload must contain finite JSON values") from exc
    request_id = data.get("request_id")
    if request_id is None:
        request_id = str(uuid.uuid4())
    else:
        try:
            if not isinstance(request_id, str):
                raise ValueError()
            request_id = str(uuid.UUID(request_id))
        except (ValueError, AttributeError) as exc:
            raise BadRequest("request_id must be a UUID string") from exc
    return payload, request_id, hashlib.sha256(encoded.encode()).hexdigest()


def _existing_acknowledgement(run, fingerprint):
    if run.storage_data().get("fingerprint") != fingerprint:
        raise Conflict("request_id is already used for a different payload")
    return jsonify(acknowledgement(run)), 201


@ingest_bp.post("/api/ingest")
def ingest_run():
    try:
        data = request.get_json()
    except RecursionError as exc:
        raise BadRequest("Payload exceeds the maximum nesting depth (64)") from exc
    payload, request_id, fingerprint = _validated_payload(data)
    existing = db.session.get(Run, request_id)
    if existing is not None:
        return _existing_acknowledgement(existing, fingerprint)
    # A pipeline or run may be inserted concurrently. Retry only the local transaction,
    # never the provider request, and let the unique primary key identify a replay.
    for attempt in range(2):
        try:
            pipeline = Pipeline.query.filter_by(name=payload["pipeline_name"]).first()
            if pipeline is None:
                pipeline = Pipeline(name=payload["pipeline_name"], description=payload["pipeline_description"])
                db.session.add(pipeline)
                db.session.flush()
            elif payload["pipeline_description"]:
                pipeline.description = payload["pipeline_description"]
            run = Run(id=request_id, pipeline_id=pipeline.id, status="received" if payload["analyze"] else "stored",
                      run_metadata={"_xray_storage": {"version": 1, "metadata": payload["metadata"],
                                    "pipeline_description": payload["pipeline_description"], "fingerprint": fingerprint}})
            db.session.add(run)
            for step in payload["steps"]:
                db.session.add(Step(run_id=request_id, step_name=step["name"], step_order=step["order"],
                                    step_description=step["description"], inputs=step["inputs"], outputs=step["outputs"],
                                    reasons=step["reasons"], metrics=step["metrics"]))
            db.session.commit()
            break
        except IntegrityError:
            db.session.rollback()
            existing = db.session.get(Run, request_id)
            if existing is not None:
                return _existing_acknowledgement(existing, fingerprint)
            if attempt:
                raise
    if payload["analyze"]:
        try:
            run.analysis_result = get_analyzer().analyze_run(run.to_dict(include_steps=True))
            run.status = analysis_status(run.analysis_result)
        except Exception as exc:
            current_app.logger.warning("Run analysis failed (%s)", type(exc).__name__)
            run.status = "analysis_failed"
            run.analysis_result = {"analysis_status": "failed", "severity": "unknown", "error": "Analysis unavailable",
                                   "error_type": type(exc).__name__}
        db.session.commit()
    return jsonify(acknowledgement(run)), 201
