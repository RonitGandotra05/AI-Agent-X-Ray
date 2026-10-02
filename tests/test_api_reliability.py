"""User workflows and failures against an isolated API database."""

import json
import uuid

import pytest
from xray_api.app import create_app
from xray_api.models import db, Run


class Analyzer:
    def __init__(self, status="complete", failure=False):
        self.calls = []
        self.status = status
        self.failure = failure

    def analyze_run(self, data):
        self.calls.append(data)
        if self.failure:
            raise RuntimeError("secret-provider-key")
        return {"analysis_status": self.status, "severity": "ok" if self.status == "complete" else "unknown",
                "faulty_step": None}

    def analyze_run_streaming(self, data):
        result = self.analyze_run(data)
        yield {"event": "window", "data": {"window": 1}}
        yield {"event": "complete", "data": result}


@pytest.fixture
def app():
    return create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                       "XRAY_API_KEY": None, "XRAY_ANALYZER": Analyzer()})


@pytest.fixture
def client(app):
    return app.test_client()


def payload(**overrides):
    data = {"pipeline_name": "example", "pipeline_description": "Process original evidence",
            "metadata": {"owner": "demo"}, "steps": [{"name": "read", "order": 1, "outputs": {"x": 1}},
                                                         {"name": "write", "order": 2, "inputs": {"x": 1}}],
            "analyze": False}
    data.update(overrides)
    return data


def test_factory_uses_database_overrides_before_initialization(app):
    with app.app_context():
        assert db.engine.url.database == ":memory:"


@pytest.mark.parametrize("invalid", [[], [1], "text", 1, None])
def test_ingestion_requires_json_object(client, invalid):
    response = client.post("/api/ingest", data=json.dumps(invalid), content_type="application/json")
    assert response.status_code == 400


@pytest.mark.parametrize("changes", [
    {"pipeline_name": 1}, {"pipeline_name": " "}, {"pipeline_name": "x" * 256},
    {"pipeline_description": 0}, {"metadata": []}, {"analyze": "false"},
    {"steps": {}}, {"steps": [1]}, {"steps": [{"name": "read", "order": True}]},
    {"steps": [{"name": "read", "order": -1}]},
    {"steps": [{"name": "read", "order": 1}, {"name": "write", "order": 1}]},
    {"steps": [{"name": "read", "order": 1, "description": False}]},
    {"steps": [{"name": "read", "order": 1, "metrics": []}]},
    {"steps": [{"name": "read", "order": 1, "outputs": float("nan")}]},
    {"request_id": "invalid"}, {"request_id": True},
])
def test_invalid_ingestion_is_clear_and_stores_nothing(app, client, changes):
    response = client.post("/api/ingest", json=payload(**changes))
    assert response.status_code == 400
    assert response.is_json
    with app.app_context():
        assert Run.query.count() == 0


def test_repeated_step_names_and_legacy_zero_order_are_supported(client):
    response = client.post("/api/ingest", json=payload(steps=[{"name": "tool", "order": 0},
                                                            {"name": "tool", "order": 1}]))
    assert response.status_code == 201


def test_idempotent_replay_acknowledges_existing_run_without_reanalysis(app, client):
    data = payload(request_id=str(uuid.uuid4()), analyze=True)
    first = client.post("/api/ingest", json=data)
    second = client.post("/api/ingest", json=dict(data, _sdk_summarized=True))
    assert first.status_code == second.status_code == 201
    assert first.get_json() == second.get_json()
    assert len(app.config["XRAY_ANALYZER"].calls) == 1
    with app.app_context():
        assert Run.query.count() == 1


def test_request_id_conflict_is_not_overwritten(client):
    request_id = str(uuid.uuid4())
    assert client.post("/api/ingest", json=payload(request_id=request_id)).status_code == 201
    response = client.post("/api/ingest", json=payload(request_id=request_id, metadata={"owner": "other"}))
    assert response.status_code == 409
    assert client.get(f"/api/runs/{request_id}").get_json()["metadata"] == {"owner": "demo"}


def test_pipeline_description_is_snapshotted_per_run_and_internal_metadata_hidden(client):
    first = client.post("/api/ingest", json=payload()).get_json()["run_id"]
    client.post("/api/ingest", json=payload(pipeline_description="New purpose"))
    result = client.get(f"/api/runs/{first}").get_json()
    assert result["pipeline_description"] == "Process original evidence"
    assert result["metadata"] == {"owner": "demo"}
    assert "_xray_storage" not in json.dumps(result)


@pytest.mark.parametrize("route", ["/api/runs", "/api/pipelines", "/api/search/steps"])
@pytest.mark.parametrize("query", ["limit=-1", "limit=0", "limit=201", "limit=oops", "offset=-1", "offset=oops"])
def test_invalid_pagination_is_rejected(client, route, query):
    assert client.get(f"{route}?{query}").status_code == 400


def test_unknown_pipeline_search_is_empty(client):
    client.post("/api/ingest", json=payload())
    result = client.get("/api/search/steps?pipeline=missing&limit=3&offset=2").get_json()
    assert result == {"steps": [], "total": 0, "limit": 3, "offset": 2}


def test_search_treats_wildcards_as_literal(client):
    client.post("/api/ingest", json=payload(steps=[{"name": "read%_\\data", "order": 1}]))
    assert client.get("/api/search/steps?step_name=%25_").get_json()["total"] == 1
    assert client.get("/api/search/steps?step_name=%25_missing").get_json()["total"] == 0


@pytest.mark.parametrize("status,expected", [("complete", "analyzed"), ("partial", "analysis_partial"), ("failed", "analysis_failed")])
def test_analysis_status_is_persisted(app, client, status, expected):
    app.config["XRAY_ANALYZER"] = Analyzer(status=status)
    result = client.post("/api/ingest", json=payload(analyze=True)).get_json()
    assert result["status"] == expected
    assert client.get(f"/api/runs/{result['run_id']}/analysis").get_json()["analysis"]["analysis_status"] == status


def test_provider_failure_stores_run_without_leaking_details(app, client):
    app.config["XRAY_ANALYZER"] = Analyzer(failure=True)
    response = client.post("/api/ingest", json=payload(analyze=True))
    assert response.status_code == 201
    data = response.get_json()
    assert data["status"] == "analysis_failed"
    assert "secret-provider-key" not in response.get_data(as_text=True)
    assert client.post(f"/api/analyze/{data['run_id']}").status_code == 502


def test_stream_materializes_context_and_persists_result(app, client):
    run_id = client.post("/api/ingest", json=payload()).get_json()["run_id"]
    response = client.get(f"/api/analyze/{run_id}/stream")
    content = response.get_data(as_text=True)
    assert response.mimetype == "text/event-stream"
    assert "event: window" in content and "event: complete" in content
    assert "event: error" not in content
    assert client.get(f"/api/runs/{run_id}/analysis").get_json()["status"] == "analyzed"


def test_stream_failure_is_explicit_and_persisted(app, client):
    run_id = client.post("/api/ingest", json=payload()).get_json()["run_id"]
    app.config["XRAY_ANALYZER"] = Analyzer(failure=True)
    content = client.get(f"/api/analyze/{run_id}/stream").get_data(as_text=True)
    assert "event: error" in content and "secret-provider-key" not in content
    assert client.get(f"/api/runs/{run_id}/analysis").get_json()["status"] == "analysis_failed"
    assert client.get("/api/analyze/missing/stream").status_code == 404


def test_auth_and_opt_in_cors(client, app):
    app.config["XRAY_API_KEY"] = "secret"
    app.config["XRAY_CORS_ORIGINS"] = ["https://example.test"]
    assert client.get("/health").status_code == 200
    assert client.get("/api/runs").status_code == 401
    response = client.get("/api/runs", headers={"X-API-Key": "secret", "Origin": "https://example.test"})
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "https://example.test"
    response = client.get("/api/runs", headers={"X-API-Key": "secret", "Origin": "https://other.test"})
    assert "Access-Control-Allow-Origin" not in response.headers


def test_request_size_limit_returns_json(client, app):
    app.config["MAX_CONTENT_LENGTH"] = 100
    response = client.post("/api/ingest", json=payload())
    assert response.status_code == 413
    assert response.get_json()["max_bytes"] == 100


def test_deep_json_is_rejected_before_storage(app, client):
    value = {}
    for _ in range(80):
        value = {"nested": value}
    response = client.post("/api/ingest", json=payload(steps=[{"name": "deep", "order": 1, "outputs": value}]))
    assert response.status_code == 400
    with app.app_context():
        assert Run.query.count() == 0


def test_json_parser_recursion_failure_is_a_bad_request(client):
    raw = '{"pipeline_name":"deep","steps":[{"name":"s","order":1,"outputs":' + '[' * 3000 + '1' + ']' * 3000 + '}],"analyze":false}'
    response = client.post("/api/ingest", data=raw, content_type="application/json")
    assert response.status_code == 400


def test_legacy_reserved_looking_metadata_is_preserved(app):
    from xray_api.models import Pipeline
    with app.app_context():
        pipeline = Pipeline(name="legacy")
        db.session.add(pipeline)
        db.session.flush()
        metadata = {"_xray_storage": {"version": 1, "metadata": {"old": "user data"}}}
        run = Run(pipeline_id=pipeline.id, run_metadata=metadata)
        db.session.add(run)
        db.session.commit()
        assert run.to_dict()["metadata"] == metadata


@pytest.mark.parametrize("outputs", [r'"\ud800"', r'{"\ud800":"value"}'])
def test_invalid_unicode_is_a_bad_request_not_a_transient_server_failure(client, outputs):
    raw = '{"pipeline_name":"unicode","steps":[{"name":"s","order":1,"outputs":' + outputs + '}],"analyze":false}'
    response = client.post("/api/ingest", data=raw, content_type="application/json")
    assert response.status_code == 400
