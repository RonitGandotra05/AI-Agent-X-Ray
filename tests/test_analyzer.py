"""Provider-independent analysis correctness, coverage and bounded-prompt tests."""

import json
import logging

import pytest
from xray_api.agents.analyzer import XRayAnalyzer


def ok():
    return {"faulty_step": None, "faulty_step_order": None, "reason": "No contradiction observed",
            "severity": "ok", "suggestion": None, "all_issues": []}


class Adapter:
    def __init__(self, response=None):
        self.calls = []
        self.response = ok() if response is None else response

    def chat_completion_with_usage(self, **kwargs):
        self.calls.append(kwargs)
        response = self.response(len(self.calls), kwargs) if callable(self.response) else self.response
        if isinstance(response, Exception):
            raise response
        return (response if isinstance(response, str) else json.dumps(response)), {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


def run(count=4, size=0):
    return {"pipeline_name": "pipeline", "pipeline_description": "Pass data between recorded steps",
            "steps": [{"step_name": f"step{i}", "step_order": i + 1,
                       "inputs": {"value": "x" * size}, "outputs": {"value": "x" * size}} for i in range(count)]}


def test_small_run_uses_one_call_and_keeps_all_steps():
    adapter = Adapter()
    result = XRayAnalyzer(adapter=adapter).analyze_run(run())
    assert result["analysis_status"] == "complete" and result["severity"] == "ok"
    assert result["analysis_method"] == "full_run" and len(adapter.calls) == 1
    assert len(json.loads(adapter.calls[0]["messages"][1]["content"])["steps"]) == 4
    assert result["token_usage"]["total_tokens"] == 15
    assert "verified" not in result["reason"]


def test_stream_and_sync_results_are_identical():
    analyzer = XRayAnalyzer(adapter=Adapter())
    sync = analyzer.analyze_run(run())
    events = list(analyzer.analyze_run_streaming(run()))
    assert events[-1] == {"event": "complete", "data": sync}


@pytest.mark.parametrize("response", [RuntimeError("secret"), "not json", "[]", "null", "{}",
    {"severity": "ok", "reason": "looks fine"},
    dict(ok(), suggestion=[]), dict(ok(), severity="unsupported"),
    {"faulty_step": "missing", "faulty_step_order": 1, "severity": "error", "reason": "bad"},
    {"faulty_step": "step0", "faulty_step_order": True, "severity": "error", "reason": "bad"},
    dict(ok(), all_issues="bad"), dict(ok(), all_issues=[1]),
])
def test_failed_or_invalid_analysis_never_reports_ok(response):
    result = XRayAnalyzer(adapter=Adapter(response)).analyze_run(run())
    assert result["analysis_status"] == "failed"
    assert result["severity"] == "unknown"
    assert result["errors"] and "secret" not in json.dumps(result)


def test_collects_multiple_issues_and_selects_most_severe():
    response = {"all_issues": [
        {"faulty_step": "step0", "faulty_step_order": 1, "reason": "minor", "severity": "warning"},
        {"faulty_step": "step2", "faulty_step_order": 3, "reason": "corrupt", "severity": "critical"}]}
    result = XRayAnalyzer(adapter=Adapter(response)).analyze_run(run())
    assert result["faulty_step"] == "step2"
    assert len(result["all_issues"]) == 2


def test_repeated_names_are_identified_by_order():
    data = run(2)
    for step in data["steps"]:
        step["step_name"] = "tool"
    response = {"faulty_step": "tool", "faulty_step_order": 2, "reason": "bad", "severity": "error"}
    assert XRayAnalyzer(adapter=Adapter(response)).analyze_run(data)["faulty_step_order"] == 2
    response["faulty_step_order"] = None
    assert XRayAnalyzer(adapter=Adapter(response)).analyze_run(data)["severity"] == "unknown"


def test_large_run_packs_overlap_windows_and_bounds_every_field():
    adapter = Adapter()
    analyzer = XRayAnalyzer(adapter=adapter, max_prompt_chars=6000)
    data = run(8, 1500)
    data["pipeline_description"] = "purpose" * 2000
    data["metadata"] = {"details": "meta" * 3000}
    for step in data["steps"]:
        step["reasons"] = {"reason": "r" * 10000}
        step["metrics"] = {"details": "m" * 10000}
        step["step_description"] = "description" * 2000
    result = analyzer.analyze_run(data)
    assert result["analysis_status"] == "complete"
    assert len(adapter.calls) > 1
    covered_pairs = set()
    for call in adapter.calls:
        assert sum(len(message["content"]) for message in call["messages"]) <= 6000
        steps = json.loads(call["messages"][1]["content"])["steps"]
        orders = [step["step_order"] for step in steps]
        covered_pairs.update(zip(orders, orders[1:]))
    assert covered_pairs == set(zip(range(1, 8), range(2, 9)))
    assert data["steps"][0]["reasons"]["reason"] == "r" * 10000  # Input remains untouched.


def test_packing_preserves_original_pair_evidence_that_fits():
    adapter = Adapter()
    analyzer = XRayAnalyzer(adapter=adapter, max_prompt_chars=6000)
    data = run(8, 700)
    analyzer.analyze_run(data)
    assert len(adapter.calls) > 1
    for call in adapter.calls:
        for step in json.loads(call["messages"][1]["content"])["steps"]:
            assert step["inputs"]["value"] == "x" * 700
            assert "evidence" not in step


def test_partial_failure_retains_faults_but_marks_analysis_partial():
    def response(index, kwargs):
        if index == 2:
            return RuntimeError("network down")
        steps = json.loads(kwargs["messages"][1]["content"])["steps"]
        return {"faulty_step": steps[0]["step_name"], "faulty_step_order": steps[0]["step_order"],
                "reason": "Concrete mismatch", "severity": "error"}
    result = XRayAnalyzer(adapter=Adapter(response), max_prompt_chars=6000).analyze_run(run(8, 700))
    assert result["analysis_status"] == "partial" and result["severity"] == "error"
    assert result["errors"] and result["all_issues"]


@pytest.mark.parametrize("data", [{}, {"steps": []}, {"steps": [1]}, {"steps": [{"name": "x", "order": True}]}])
def test_invalid_input_raises_predictably(data):
    with pytest.raises(ValueError):
        XRayAnalyzer(adapter=Adapter()).analyze_run(data)


def test_analyzer_does_not_change_host_logging_configuration():
    root = logging.getLogger()
    previous = root.level
    XRayAnalyzer(adapter=Adapter())
    assert root.level == previous


def test_capture_order_prompt_does_not_claim_concurrent_spans_are_dependencies():
    adapter = Adapter()
    data = run(3)
    for index, step in enumerate(data["steps"]):
        step["metrics"] = {"run_id": f"child-{index}", "parent_run_id": "parent"}
    XRayAnalyzer(adapter=adapter).analyze_run(data)
    prompt = adapter.calls[0]["messages"][0]["content"]
    assert "order alone does not establish data dependencies" in prompt
    supplied = json.loads(adapter.calls[0]["messages"][1]["content"])
    assert supplied["steps"][1]["metrics"]["parent_run_id"] == "parent"


def test_malformed_primary_fault_is_rejected_even_with_valid_issue_array():
    issue = {"faulty_step": "step0", "faulty_step_order": 1, "reason": "bad", "severity": "error"}
    result = XRayAnalyzer(adapter=Adapter({"faulty_step": 0, "all_issues": [issue]})).analyze_run(run())
    assert result["analysis_status"] == "failed" and result["severity"] == "unknown"


def test_unavailable_usage_is_distinct_from_zero_cost():
    class NoUsageAdapter(Adapter):
        def chat_completion_with_usage(self, **kwargs):
            text, _ = super().chat_completion_with_usage(**kwargs)
            return text, {}
    result = XRayAnalyzer(adapter=NoUsageAdapter()).analyze_run(run())
    assert result["token_usage_available"] is False
    assert result["token_usage_complete"] is False
    assert result["token_usage_windows_reported"] == 0
