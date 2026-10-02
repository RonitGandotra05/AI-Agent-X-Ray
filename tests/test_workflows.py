"""Exercise actual SDK HTTP, background, asyncio, replay and analysis workflows."""

import asyncio
import json
import threading

import pytest
from werkzeug.serving import make_server

from xray_api.app import create_app
from xray_api.agents.analyzer import XRayAnalyzer
from xray_sdk import XRayClient, XRayRun, XRayStep


class RecordedAdapter:
    provider_name = "test"
    model_name = "test-model"

    def __init__(self):
        self.calls = 0
        self.messages = []

    def chat_completion_with_usage(self, messages, **kwargs):
        self.calls += 1
        self.messages.append(messages)
        return json.dumps({
            "faulty_step": None, "faulty_step_order": None,
            "reason": "No contradiction in the supplied evidence", "severity": "ok",
            "suggestion": None, "all_issues": [],
        }), {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70}


@pytest.fixture
def service():
    adapter = RecordedAdapter()
    app = create_app({
        "TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "XRAY_API_KEY": "workflow-key", "XRAY_ANALYZER": XRayAnalyzer(adapter=adapter),
    })
    server = make_server("127.0.0.1", 0, app, threaded=True)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", adapter
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()


def trace(name="workflow"):
    run = XRayRun(name, description="Multiply an integer by two.", metadata={"case": "test"})
    run.add_step(XRayStep("read", 1, outputs={"n": 2}))
    run.add_step(XRayStep("multiply", 2, inputs={"n": 2}, outputs={"n": 4}))
    return run


def test_real_sync_store_query_and_explicit_analysis(service, tmp_path):
    url, adapter = service
    with XRayClient(url, "workflow-key", spool_dir=str(tmp_path)) as client:
        response = client.send(trace(), analyze=False)
        assert response["status"] == "stored"
        assert adapter.calls == 0
        run_id = response["run_id"]
        assert client.get_run(run_id)["metadata"] == {"case": "test"}
        assert client.list_runs(pipeline="workflow")["total"] == 1
        analysis = client.analyze_run(run_id)["analysis"]
        assert analysis["analysis_status"] == "complete"
        assert analysis["token_usage"]["total_tokens"] == 70
        assert "Multiply an integer" in adapter.messages[0][1]["content"]
        assert client.get_analysis(run_id)["analysis"] == analysis
        assert client.search_steps(pipeline="missing")["steps"] == []


def test_real_background_and_asyncio_sends(service, tmp_path):
    url, adapter = service
    with XRayClient(url, "workflow-key", spool_dir=str(tmp_path)) as client:
        future = client.send_async(trace("future"), analyze=False)
        assert future.result(timeout=10)["status"] == "stored"
        response = asyncio.run(client.asend(trace("asyncio"), analyze=False))
        assert response["status"] == "stored"
        assert client.flush(timeout=10)
        assert client.list_runs()["total"] == 2
        assert adapter.calls == 0


def test_real_spool_replay_preserves_options_and_request_id(service, tmp_path):
    url, adapter = service
    with XRayClient(url, "workflow-key", spool_dir=str(tmp_path)) as client:
        path = client.spool(trace(), analyze=False)
        saved = json.loads(path.read_text())
        assert saved["analyze"] is False
        assert client.flush_spool()["flushed"] == 1
        assert not path.exists()
        assert adapter.calls == 0
        # Simulate a crash after acknowledgement but before local unlink.
        path.write_text(json.dumps(saved))
        assert client.flush_spool()["flushed"] == 1
        assert client.list_runs()["total"] == 1
        assert client.get_run(saved["request_id"])["status"] == "stored"


def test_real_stream_completes_and_persists_result(service, tmp_path):
    url, adapter = service
    with XRayClient(url, "workflow-key", spool_dir=str(tmp_path)) as client:
        run_id = client.send(trace(), analyze=False)["run_id"]
        events = list(client.stream_analysis(run_id))
        assert [event["event"] for event in events] == ["window", "complete"]
        assert events[-1]["data"]["analysis_status"] == "complete"
        assert client.get_analysis(run_id)["status"] == "analyzed"
        assert adapter.calls == 1


def test_small_run_analysis_has_one_bounded_call():
    adapter = RecordedAdapter()
    analyzer = XRayAnalyzer(adapter=adapter)
    run = XRayRun("ten_steps", description="Pass a value through each stage.")
    for order in range(1, 11):
        run.add_step(XRayStep(f"step_{order}", order, inputs={"v": order - 1}, outputs={"v": order}))
    result = analyzer.analyze_run(run.to_dict())
    assert result["analysis_method"] == "full_run"
    assert adapter.calls == 1
    assert sum(len(message["content"]) for message in adapter.messages[0]) <= analyzer.max_prompt_chars
