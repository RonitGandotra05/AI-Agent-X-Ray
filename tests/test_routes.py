"""Tests for API routes using Flask test client."""

import json
import pytest
from xray_api.app import create_app
from xray_api.models import db


@pytest.fixture
def app():
    """Create a test app with in-memory SQLite database."""
    app = create_app()
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['TESTING'] = True
    app.config['XRAY_API_KEY'] = None  # Disable auth for tests
    
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


class TestHealthEndpoint:
    def test_health(self, client):
        response = client.get('/health')
        assert response.status_code == 200
        assert response.get_json()["status"] == "healthy"


class TestIngestEndpoint:
    def _make_payload(self, **overrides):
        payload = {
            "pipeline_name": "test_pipeline",
            "description": "test pipeline desc",
            "steps": [
                {"name": "step1", "order": 1, "inputs": {"a": 1}, "outputs": {"b": 2}},
                {"name": "step2", "order": 2, "inputs": {"b": 2}, "outputs": {"c": 3}},
            ],
            "analyze": False,  # Skip LLM calls in tests
        }
        payload.update(overrides)
        return payload

    def test_ingest_success(self, client):
        resp = client.post('/api/ingest', json=self._make_payload())
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["success"] is True
        assert data["run_id"] is not None
        assert data["status"] == "stored"

    def test_ingest_no_json(self, client):
        resp = client.post('/api/ingest', content_type='application/json', data='')
        assert resp.status_code == 400

    def test_ingest_no_pipeline_name(self, client):
        resp = client.post('/api/ingest', json={"steps": [{"name": "s", "order": 1}]})
        assert resp.status_code == 400
        assert "pipeline_name" in resp.get_json()["error"]

    def test_ingest_no_steps(self, client):
        resp = client.post('/api/ingest', json={"pipeline_name": "p", "steps": []})
        assert resp.status_code == 400

    def test_ingest_invalid_step_name(self, client):
        resp = client.post('/api/ingest', json=self._make_payload(
            steps=[{"name": "", "order": 1}]
        ))
        assert resp.status_code == 400
        assert "name" in resp.get_json()["error"]

    def test_ingest_invalid_step_order(self, client):
        resp = client.post('/api/ingest', json=self._make_payload(
            steps=[{"name": "s1", "order": "not_int"}]
        ))
        assert resp.status_code == 400
        assert "order" in resp.get_json()["error"]

    def test_ingest_too_many_steps(self, client):
        steps = [{"name": f"s{i}", "order": i} for i in range(51)]
        resp = client.post('/api/ingest', json=self._make_payload(steps=steps))
        assert resp.status_code == 400
        assert "Too many" in resp.get_json()["error"]


class TestQueryEndpoints:
    def _ingest_run(self, client):
        """Helper to ingest a test run."""
        payload = {
            "pipeline_name": "query_test",
            "steps": [
                {"name": "step_a", "order": 1, "inputs": {}, "outputs": {}},
                {"name": "step_b", "order": 2, "inputs": {}, "outputs": {}},
            ],
            "analyze": False,
        }
        resp = client.post('/api/ingest', json=payload)
        return resp.get_json()["run_id"]

    def test_list_pipelines(self, client):
        self._ingest_run(client)
        resp = client.get('/api/pipelines')
        assert resp.status_code == 200
        pipelines = resp.get_json()["pipelines"]
        assert len(pipelines) >= 1
        assert any(p["name"] == "query_test" for p in pipelines)

    def test_list_runs(self, client):
        self._ingest_run(client)
        resp = client.get('/api/runs')
        assert resp.status_code == 200
        assert len(resp.get_json()["runs"]) >= 1

    def test_list_runs_filter_pipeline(self, client):
        self._ingest_run(client)
        resp = client.get('/api/runs?pipeline=query_test')
        assert resp.status_code == 200
        runs = resp.get_json()["runs"]
        assert len(runs) >= 1

    def test_list_runs_filter_nonexistent(self, client):
        resp = client.get('/api/runs?pipeline=nonexistent')
        assert resp.status_code == 200
        assert resp.get_json()["runs"] == []

    def test_get_run(self, client):
        run_id = self._ingest_run(client)
        resp = client.get(f'/api/runs/{run_id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == run_id
        assert len(data["steps"]) == 2

    def test_get_run_not_found(self, client):
        resp = client.get('/api/runs/nonexistent-id')
        assert resp.status_code == 404

    def test_get_analysis(self, client):
        run_id = self._ingest_run(client)
        resp = client.get(f'/api/runs/{run_id}/analysis')
        assert resp.status_code == 200

    def test_search_steps(self, client):
        self._ingest_run(client)
        resp = client.get('/api/search/steps?step_name=step_a')
        assert resp.status_code == 200
        steps = resp.get_json()["steps"]
        assert len(steps) >= 1
        assert all("step_a" in s["step_name"] for s in steps)
