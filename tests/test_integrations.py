"""Framework callback contracts without installing heavy framework dependencies."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from xray_sdk.integrations.crewai import XRayCrewMonitor
from xray_sdk.integrations import langchain


@pytest.fixture
def handler(monkeypatch):
    # Exercise callback logic independently of the optional base-handler dependency.
    if langchain.BaseCallbackHandler is object:
        monkeypatch.setattr(langchain, "BaseCallbackHandler", type("InstalledHandler", (), {}))
    return langchain.XRayCallbackHandler("chain")


def test_langchain_missing_dependency_error(monkeypatch):
    monkeypatch.setattr(langchain, "BaseCallbackHandler", object)
    with pytest.raises(ImportError, match="xray-sdk\\[langchain\\]"):
        langchain.XRayCallbackHandler()


def test_chat_model_and_modern_usage_metadata(handler):
    handler.on_chat_model_start(None, [[SimpleNamespace(type="human", content="hello")]], run_id="llm", parent_run_id="chain")
    generation = SimpleNamespace(text="answer", message=SimpleNamespace(usage_metadata={"input_tokens": 4, "output_tokens": 2}))
    handler.on_llm_end(SimpleNamespace(generations=[[generation]], llm_output=None), run_id="llm")
    step = handler.run.steps[0]
    assert step.inputs["messages"][0][0] == {"role": "human", "content": "hello"}
    assert step.outputs["response"] == "answer"
    assert step.outputs["token_usage"]["input_tokens"] == 4
    assert step.metrics["parent_run_id"] == "chain"
    assert step.metrics["duration_ms"] >= 0


def test_nullable_serialized_anonymous_callbacks_and_empty_generations(handler):
    handler.on_chain_start(None, {"input": "hi"})
    handler.on_llm_start({"id": []}, ["prompt"])
    handler.on_llm_end(SimpleNamespace(generations=[[]], llm_output={}))
    handler.on_chain_end({"output": "ok"})
    assert [step.order for step in handler.run.steps] == [1, 2]
    assert len(handler._active_steps) == 0


def test_retriever_errors_and_counts(handler):
    handler.on_retriever_start(None, "query", run_id="retrieval")
    handler.on_retriever_error(RuntimeError("offline"), run_id="retrieval")
    assert handler.run.steps[0].outputs["error"] == "offline"
    handler.on_retriever_start(None, "query", run_id="retrieval-2")
    docs = [SimpleNamespace(page_content=f"document {i}") for i in range(20)]
    handler.on_retriever_end(docs, run_id="retrieval-2")
    assert handler.run.steps[1].outputs["documents_count"] == 20
    assert len(handler.run.steps[1].outputs["documents_sample"]) == 10


def test_concurrent_callbacks_use_unique_completion_order(handler):
    def callback(index):
        handler.on_tool_start({"name": "search"}, str(index), run_id=f"tool-{index}")
        handler.on_tool_end(str(index), run_id=f"tool-{index}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(callback, range(40)))
    assert sorted(step.order for step in handler.run.steps) == list(range(1, 41))
    assert len({step.metrics["run_id"] for step in handler.run.steps}) == 40
    assert not handler._active_steps


def test_callback_invalid_json_is_best_effort(handler, caplog):
    handler.on_chain_start(None, {"input": float("nan")}, run_id="bad")
    handler.on_chain_end({"result": "ok"}, run_id="bad")
    assert not handler.run.steps
    assert "could not capture" in caplog.text


def test_callback_send_and_reset_preserve_old_run(handler):
    handler.on_tool_start(None, "hello", run_id="tool")
    handler.on_tool_end("result", run_id="tool")
    old_run = handler.get_run()
    client = Mock()
    handler.send(client, analyze=False)
    client.send.assert_called_once_with(old_run, analyze=False)
    handler.reset()
    assert not handler.run.steps
    assert len(old_run.steps) == 1


def task(execute=None, **kwargs):
    return SimpleNamespace(agent=SimpleNamespace(role="researcher"), description="Find an answer",
                           expected_output=None, context=None, execute_sync=execute or (lambda: "answer"), **kwargs)


def test_crew_attach_detach_is_idempotent_and_restores_method():
    item = task()
    original = item.execute_sync
    crew = SimpleNamespace(tasks=[item])
    monitor = XRayCrewMonitor("crew")
    monitor.attach(crew).attach(crew)
    assert item.execute_sync() == "answer"
    assert len(monitor.run.steps) == 1
    monitor.detach()
    assert item.execute_sync is original
    monitor.detach()
    assert monitor.run.steps[0].inputs["expected_output"] == ""


def test_crew_application_errors_preserved_and_capture_failure_safe(monkeypatch):
    error = RuntimeError("application failed")
    def failure():
        raise error
    item = task(failure)
    monitor = XRayCrewMonitor()
    monitor.attach(SimpleNamespace(tasks=[item]))
    with pytest.raises(RuntimeError) as caught:
        item.execute_sync()
    assert caught.value is error
    assert monitor.run.steps[0].outputs["error"] == "application failed"
    monkeypatch.setattr(monitor, "add_step", Mock(side_effect=ValueError("capture failed")))
    with pytest.raises(RuntimeError) as caught:
        item.execute_sync()
    assert caught.value is error
    monitor.detach()


def test_crew_unsupported_tasks_and_foreign_wrapper_are_preserved(caplog):
    item = task(async_execution=True)
    original = item.execute_sync
    monitor = XRayCrewMonitor()
    monitor.attach(SimpleNamespace(tasks=[item, SimpleNamespace()]))
    assert item.execute_sync is original
    assert "asynchronous" in caplog.text
    second = task()
    monitor.attach(SimpleNamespace(tasks=[second]))
    foreign = lambda: "other instrumentation"
    second.execute_sync = foreign
    monitor.detach()
    assert second.execute_sync is foreign


def test_crew_reset_preserves_snapshot():
    monitor = XRayCrewMonitor()
    monitor.add_step("manual", {"x": 1}, {"y": 2})
    old = monitor.get_run()
    monitor.reset()
    assert len(old.steps) == 1
    assert monitor.get_run().steps == []
