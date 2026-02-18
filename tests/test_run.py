"""Tests for XRayRun class."""

from xray_sdk.step import XRayStep
from xray_sdk.run import XRayRun


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
