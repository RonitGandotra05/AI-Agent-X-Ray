"""Client workflows: retry, durable replay, background lifecycle and SSE."""

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from xray_sdk import XRayClient, XRayRun, XRayStep
from xray_sdk.errors import XRayError, XRayHTTPError, XRayResponseError, XRayTransportError


def response(status=201, body=None, *, headers=None, lines=None):
    result = Mock(spec=requests.Response)
    result.status_code = status
    result.headers = headers or {}
    result.json.return_value = body if body is not None else {"success": True, "run_id": "run-1", "analysis": None}
    result.iter_lines.return_value = iter(lines or [])
    return result


@pytest.fixture
def run():
    result = XRayRun("pipeline")
    result.add_step(XRayStep("search", 1, inputs={"query": "hello"}, outputs={"items": [1, 2]}))
    return result


@pytest.fixture
def transport(monkeypatch):
    session = Mock(spec=requests.Session)
    session.request.return_value = response()
    factory = Mock(return_value=session)
    monkeypatch.setattr("xray_sdk.client.requests.Session", factory)
    return session, factory


@pytest.mark.parametrize("options", [
    {"api_url": ""}, {"api_url": "ftp://localhost"}, {"api_url": "http://user:password@localhost"},
    {"api_url": "http://localhost?key=value"}, {"api_url": "http://localhost:invalid"},
    {"timeout": 0}, {"timeout": float("nan")}, {"timeout": (1, 0)}, {"timeout": (1,)},
    {"retries": 0}, {"retries": True}, {"retry_delay": -1}, {"max_retry_delay": float("inf")},
    {"max_pending": 0}, {"max_workers": 0}, {"api_key": "bad\nkey"}, {"raise_on_error": "yes"},
])
def test_invalid_configuration(options):
    with pytest.raises(ValueError):
        XRayClient(**options)


def test_environment_defaults_and_lazy_resources(monkeypatch, transport):
    session, factory = transport
    monkeypatch.setenv("XRAY_API_URL", "https://example.test/xray/")
    monkeypatch.setenv("XRAY_API_KEY", "test-key")
    with XRayClient() as client:
        assert client.api_url == "https://example.test/xray"
        assert client._executor is None
        factory.assert_not_called()
        client.list_pipelines()
        client.list_runs(limit=4, offset=2)
        assert factory.call_count == 1
        assert session.request.call_args.kwargs["headers"]["X-API-Key"] == "test-key"
        assert session.request.call_args.kwargs["params"] == {"limit": 4, "offset": 2}
    session.close.assert_called_once()


def test_send_validates_empty_run_and_analyze(transport):
    with XRayClient() as client:
        with pytest.raises(ValueError, match="[Aa]t least one"):
            client.send(XRayRun("empty"))
        with pytest.raises(ValueError, match="analyze"):
            client.send(XRayRun("empty"), analyze="false")
    transport[0].request.assert_not_called()


def test_success_and_same_payload_for_transient_retries(transport, run, tmp_path, monkeypatch):
    session, _ = transport
    failed = response(429, {"error": "busy"}, headers={"Retry-After": "300"})
    session.request.side_effect = [requests.ConnectionError("offline"), failed, response()]
    sleep = Mock()
    monkeypatch.setattr("xray_sdk.client.time.sleep", sleep)
    with XRayClient(retry_delay=0, max_retry_delay=0.01, spool_dir=str(tmp_path)) as client:
        assert client.send(run, analyze=False)["run_id"] == "run-1"
    payloads = [call.kwargs["json"] for call in session.request.call_args_list]
    assert len({payload["request_id"] for payload in payloads}) == 1
    assert all(payload["analyze"] is False for payload in payloads)
    assert sleep.call_args_list[-1].args == (0.01,)
    assert not list(tmp_path.iterdir())
    failed.close.assert_called_once()


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422, 302])
def test_permanent_errors_never_retry_or_spool(status, transport, run, tmp_path):
    session, _ = transport
    session.request.return_value = response(status, {"error": "invalid request"})
    with XRayClient(retry_delay=0, spool_dir=str(tmp_path)) as client:
        result = client.send(run)
        assert result["status_code"] == status
        assert "spooled" not in result
    assert session.request.call_count == 1
    assert not list(tmp_path.iterdir())


def test_strict_error_preserves_http_compatibility(transport, run):
    transport[0].request.return_value = response(401, {"error": "invalid key"})
    with XRayClient(raise_on_error=True) as client:
        with pytest.raises(XRayHTTPError) as caught:
            client.send(run)
    assert isinstance(caught.value, requests.HTTPError)
    assert caught.value.status_code == 401


@pytest.mark.parametrize("body", [{}, [], {"success": False, "error": "not accepted"}, {"success": True, "run_id": 7}])
def test_invalid_success_response_never_retried_or_spooled(body, transport, run, tmp_path):
    transport[0].request.return_value = response(body=body)
    with XRayClient(spool_dir=str(tmp_path)) as client:
        assert "error" in client.send(run)
    assert transport[0].request.call_count == 1
    assert not list(tmp_path.iterdir())


def test_non_json_success_never_retried(transport, run):
    transport[0].request.return_value.json.side_effect = ValueError("HTML")
    with XRayClient(raise_on_error=True) as client:
        with pytest.raises(XRayResponseError, match="invalid JSON"):
            client.send(run)
    assert transport[0].request.call_count == 1


def test_spool_preserves_analysis_and_id_then_flushes(transport, run, tmp_path):
    session, _ = transport
    session.request.side_effect = requests.Timeout("slow")
    with XRayClient(retries=2, retry_delay=0, spool_dir=str(tmp_path)) as client:
        result = client.send(run, analyze=False)
        assert result["spooled"] is True
        assert result["retries_attempted"] == 2
        path = Path(result["spool_path"])
        payload = json.loads(path.read_text())
        assert payload["analyze"] is False
        assert payload["request_id"] == session.request.call_args.kwargs["json"]["request_id"]
        session.request.side_effect = None
        session.request.return_value = response()
        assert client.flush_spool()["flushed"] == 1
        assert session.request.call_args.kwargs["json"] == payload
        assert not path.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_strict_transient_error_spools_then_raises(transport, run, tmp_path):
    transport[0].request.side_effect = requests.ConnectionError("offline")
    with XRayClient(retries=1, spool_dir=str(tmp_path), raise_on_error=True) as client:
        with pytest.raises(XRayTransportError) as caught:
            client.send(run)
        assert Path(caught.value.spool_path).is_file()


def test_safe_filenames_and_failed_flush_retained(transport, tmp_path):
    run = XRayRun("../unsafe/pipeline")
    run.add_step(XRayStep("step", 1))
    session, _ = transport
    with XRayClient(retries=1, spool_dir=str(tmp_path)) as client:
        path = client.spool(run, analyze=False)
        assert path.parent == tmp_path
        session.request.return_value = response(body={})
        result = client.flush_spool()
        assert result["failed"] == 1
        assert path.exists()
        assert json.loads(path.read_text())["analyze"] is False


def test_old_and_corrupt_spool_files_keep_stable_retry_id(transport, run, tmp_path):
    old_path = tmp_path / "old.json"
    old_path.write_text(json.dumps(run.to_dict()))
    (tmp_path / "broken.json").write_text("not JSON")
    transport[0].request.side_effect = requests.ConnectionError("offline")
    with XRayClient(retries=1, spool_dir=str(tmp_path)) as client:
        assert client.flush_spool()["failed"] == 2
        first_id = json.loads(old_path.read_text())["request_id"]
        assert client.flush_spool()["failed"] == 2
        assert json.loads(old_path.read_text())["request_id"] == first_id
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_spool_failure_is_reported_without_false_success(transport, run, tmp_path, monkeypatch):
    transport[0].request.side_effect = requests.ConnectionError("offline")
    with XRayClient(retries=1, spool_dir=str(tmp_path)) as client:
        monkeypatch.setattr(client, "_spool_payload", Mock(side_effect=OSError("disk full")))
        result = client.send(run)
        assert result["spooled"] is False
        assert "disk full" in result["error"]


def test_query_validation_and_single_attempt_analysis(transport):
    session, _ = transport
    with XRayClient(retries=3, retry_delay=0) as client:
        for limit in (0, 201, True):
            with pytest.raises(ValueError):
                client.list_runs(limit=limit)
        with pytest.raises(ValueError):
            client.search_steps(offset=-1)
        with pytest.raises(ValueError):
            client.get_run("")
        session.request.side_effect = requests.Timeout("slow")
        with pytest.raises(XRayTransportError):
            client.analyze_run("run-1")
        assert session.request.call_count == 1


def test_bounded_background_snapshot_flush_and_close(transport, run):
    session, _ = transport
    entered = threading.Event()
    release = threading.Event()

    def request(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return response()

    session.request.side_effect = request
    client = XRayClient(max_pending=1)
    try:
        future = client.send_async(run)
        assert entered.wait(2)
        run.steps[0].outputs["items"].append(999)
        with pytest.raises(XRayError, match="queue is full"):
            client.send_async(run)
        assert client.flush(timeout=0) is False
        release.set()
        assert future.result(timeout=3)["success"] is True
        assert client.flush(timeout=2) is True
        assert session.request.call_args.kwargs["json"]["steps"][0]["outputs"]["items"] == [1, 2]
    finally:
        release.set()
        client.close()
    client.close()
    with pytest.raises(XRayError, match="closed"):
        client.send(run)


def test_asyncio_workflow(transport, run):
    with XRayClient() as client:
        result = asyncio.run(client.asend(run, analyze=False))
        assert result["success"] is True
        assert transport[0].request.call_args.kwargs["json"]["analyze"] is False


def test_callback_can_close_client_from_worker(transport, run):
    session, _ = transport
    entered = threading.Event()
    release = threading.Event()
    closed = threading.Event()
    session.close.side_effect = closed.set

    def request(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return response()

    session.request.side_effect = request
    client = XRayClient()
    client.send_background(run, callback=lambda result: client.close())
    assert entered.wait(2)
    release.set()
    assert closed.wait(3)
    assert client._closed


def test_close_waits_for_active_sync_request(transport, run):
    session, _ = transport
    entered, release, closing = threading.Event(), threading.Event(), threading.Event()

    def request(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return response()

    session.request.side_effect = request
    client = XRayClient()
    with ThreadPoolExecutor(max_workers=2) as executor:
        send = executor.submit(client.send, run)
        assert entered.wait(2)
        close = executor.submit(lambda: (closing.set(), client.close()))
        assert closing.wait(2)
        session.close.assert_not_called()
        release.set()
        assert send.result(timeout=3)["success"]
        close.result(timeout=3)
    session.close.assert_called_once()


def test_stream_multiline_json_terminal_and_cleanup(transport):
    stream = response(lines=[": comment", "event: window", 'data: {"index":', "data: 1}", "",
                             "event: complete", 'data: {"ok": true}', ""])
    transport[0].request.return_value = stream
    with XRayClient() as client:
        assert list(client.stream_analysis("run-1")) == [
            {"event": "window", "data": {"index": 1}}, {"event": "complete", "data": {"ok": True}},
        ]
    stream.close.assert_called_once()


def test_stream_initiation_is_not_retried(transport):
    transport[0].request.side_effect = requests.Timeout("slow")
    with XRayClient(retries=3, retry_delay=0) as client:
        with pytest.raises(XRayTransportError):
            list(client.stream_analysis("run-1"))
    assert transport[0].request.call_count == 1


@pytest.mark.parametrize("lines", [[], ["event: window", "data: {}", ""], ["event: complete", "data: {}"],
                                    ["event: complete", "data: invalid", ""]])
def test_partial_streams_fail_clearly(lines, transport):
    stream = response(lines=lines)
    transport[0].request.return_value = stream
    with XRayClient() as client:
        with pytest.raises(XRayResponseError):
            list(client.stream_analysis("run-1"))
    stream.close.assert_called_once()


def test_stream_iterator_close_releases_connection(transport):
    stream = response(lines=["event: window", "data: {}", "", "event: complete", "data: {}", ""])
    transport[0].request.return_value = stream
    with XRayClient() as client:
        iterator = client.stream_analysis("run-1")
        assert next(iterator)["event"] == "window"
        iterator.close()
    stream.close.assert_called_once()
