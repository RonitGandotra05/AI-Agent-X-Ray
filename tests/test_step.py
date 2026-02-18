"""Tests for XRayStep dataclass."""

from xray_sdk.step import XRayStep


class TestXRayStep:
    """Unit tests for the XRayStep dataclass."""

    def test_create_minimal(self):
        """Step can be created with just name and order."""
        step = XRayStep(name="search", order=1)
        assert step.name == "search"
        assert step.order == 1
        assert step.inputs == {}
        assert step.outputs == {}
        assert step.description == ""
        assert step.reasons == {}
        assert step.metrics == {}

    def test_create_full(self):
        """Step can be created with all fields."""
        step = XRayStep(
            name="filter",
            order=3,
            inputs={"candidates_count": 100},
            outputs={"filtered_count": 5},
            description="Filter by rating",
            reasons={"dropped": [{"id": 1, "reason": "low"}]},
            metrics={"elimination_rate": 0.95},
        )
        assert step.name == "filter"
        assert step.outputs["filtered_count"] == 5
        assert step.metrics["elimination_rate"] == 0.95

    def test_to_dict(self):
        """to_dict returns all fields as a plain dictionary."""
        step = XRayStep(name="rank", order=2, inputs={"k": 10}, outputs={"top": [1, 2]})
        d = step.to_dict()
        assert d["name"] == "rank"
        assert d["order"] == 2
        assert d["inputs"] == {"k": 10}
        assert d["outputs"] == {"top": [1, 2]}
        assert d["description"] == ""

    def test_repr(self):
        step = XRayStep(name="embed", order=4)
        assert "embed" in repr(step)
        assert "4" in repr(step)
