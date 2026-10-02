"""Tests for XRayRun class."""

from xray_sdk.step import XRayStep
from xray_sdk.run import XRayRun
import json
import pytest


class TestXRayRun:
    """Unit tests for XRayRun."""

    def test_create_minimal(self):
        run = XRayRun(pipeline_name="test_pipeline")
        assert run.pipeline_name == "test_pipeline"
        assert run.description == ""
        assert run.metadata == {}
        assert run.steps == []

    def test_create_with_all_params(self):
        run = XRayRun(
            pipeline_name="my_pipe",
            description="A test pipeline",
            metadata={"env": "staging"},
            sample_size=50,
        )
        assert run.description == "A test pipeline"
        assert run.metadata["env"] == "staging"
        assert run.summarizer.sample_size == 50

    def test_add_step(self):
        run = XRayRun(pipeline_name="p")
        step = XRayStep(name="s1", order=1, inputs={"x": 1}, outputs={"y": 2})
        run.add_step(step)
        assert len(run.steps) == 1
        assert run.steps[0].name == "s1"

    def test_add_multiple_steps(self):
        run = XRayRun(pipeline_name="p")
        run.add_step(XRayStep(name="a", order=1))
        run.add_step(XRayStep(name="b", order=2))
        run.add_step(XRayStep(name="c", order=3))
        assert len(run.steps) == 3

    def test_to_dict(self):
        run = XRayRun(pipeline_name="demo", description="test", metadata={"k": "v"})
        run.add_step(XRayStep(name="s1", order=1, inputs={"a": 1}, outputs={"b": 2}))
        d = run.to_dict()
        
        assert d["pipeline_name"] == "demo"
        assert d["pipeline_description"] == "test"
        assert d["metadata"] == {"k": "v"}
        assert len(d["steps"]) == 1
        assert d["steps"][0]["name"] == "s1"

    def test_repr(self):
        run = XRayRun(pipeline_name="p")
        run.add_step(XRayStep(name="s", order=1))
        r = repr(run)
        assert "p" in r
        assert "1" in r

    def test_large_outputs_get_summarized(self):
        """Outputs exceeding MAX_PAYLOAD_SIZE should be summarized."""
        run = XRayRun(pipeline_name="p", sample_size=10)
        
        # Create a step with a very large output (~200K chars)
        big_list = [{"id": i, "data": "x" * 500} for i in range(400)]
        step = XRayStep(name="big", order=1, outputs={"items": big_list})
        run.add_step(step)
        
        # After summarization, the output should be smaller
        import json
        output_size = len(json.dumps(run.steps[0].outputs, default=str))
        assert output_size <= 80000

    def test_none_inputs_become_empty_dict(self):
        """None inputs/outputs should be normalized to {}."""
        run = XRayRun(pipeline_name="p")
        step = XRayStep(name="s", order=1)
        step.inputs = None
        step.outputs = None
        run.add_step(step)
        assert run.steps[0].inputs == {}
        assert run.steps[0].outputs == {}

    def test_capture_detaches_caller_data(self):
        source = {"x": [1]}
        step = XRayStep("s", 1, inputs=source)
        run = XRayRun("p", metadata=source)
        run.add_step(step)
        source["x"].append(2)
        step.outputs = {"later": True}
        assert run.steps[0].inputs == {"x": [1]}
        assert run.steps[0].outputs == {}
        assert run.metadata == {"x": [1]}

    def test_large_capture_does_not_modify_original_step(self):
        step = XRayStep("s", 1, outputs={"items": list(range(100000))})
        run = XRayRun("p")
        run.add_step(step)
        assert len(step.outputs["items"]) == 100000
        assert len(run.steps[0].outputs["items"]) <= 100

    def test_all_json_fields_obey_payload_budget(self):
        large = {"items": ["x" * 1000] * 100}
        run = XRayRun("p", metadata=large, max_payload_size=1000)
        run.add_step(XRayStep("s", 1, inputs=large, outputs=large, reasons=large, metrics=large))
        payload = run.to_dict()
        assert len(json.dumps(payload["metadata"])) <= 1000
        for field in ("inputs", "outputs", "reasons", "metrics"):
            assert len(json.dumps(payload["steps"][0][field])) <= 1000

    @pytest.mark.parametrize("kwargs", [{"pipeline_name": ""}, {"pipeline_name": 1}, {"pipeline_name": "p", "sample_size": 0}, {"pipeline_name": "p", "metadata": []}])
    def test_invalid_configuration(self, kwargs):
        with pytest.raises(ValueError):
            XRayRun(**kwargs)

    def test_duplicate_order_and_empty_run_fail_clearly(self):
        run = XRayRun("p")
        with pytest.raises(ValueError, match="At least one"):
            run.to_dict()
        run.add_step(XRayStep("s", 1))
        with pytest.raises(ValueError, match="Duplicate"):
            run.add_step(XRayStep("another", 1))

    @pytest.mark.parametrize("data", [{1: "x"}, {"x": float("nan")}, {"x": object()}, {"x": "\ud800"}, {"\ud800": "x"}])
    def test_invalid_json_is_rejected(self, data):
        run = XRayRun("p")
        with pytest.raises(ValueError):
            run.add_step(XRayStep("s", 1, inputs=data))

    def test_circular_data_is_rejected(self):
        data = []
        data.append(data)
        with pytest.raises(ValueError, match="circular"):
            XRayRun("p").add_step(XRayStep("s", 1, inputs=data))

    def test_deep_data_is_rejected(self):
        data = "x"
        for _ in range(70):
            data = [data]
        with pytest.raises(ValueError, match="nesting"):
            XRayRun("p").add_step(XRayStep("s", 1, inputs=data))
