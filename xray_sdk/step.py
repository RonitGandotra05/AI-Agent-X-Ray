"""
XRayStep - Represents a single step in a pipeline execution
"""

from dataclasses import dataclass, field
from typing import Dict, Any
from xray_shared.validation import json_snapshot, name_string, positive_int


@dataclass
class XRayStep:
    """
    A single step in a pipeline execution.
    
    Attributes:
        name: Step identifier (e.g., "keyword_generation", "filter", "rank")
        order: Step sequence number (1, 2, 3, ...)
        inputs: What was fed to this step (any JSON-serializable dict)
        outputs: What this step produced (any JSON-serializable dict)
        description: Optional one-line summary of the step's intent
        reasons: Optional dict for rejections or drops
        metrics: Optional dict for step-level metrics
    """
    name: str
    order: int
    inputs: Any = field(default_factory=dict)
    outputs: Any = field(default_factory=dict)
    description: str = ""
    reasons: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        name_string(self.name, "name")
        positive_int(self.order, "order")
        if not isinstance(self.description, str):
            raise ValueError("description must be a string")
        for name in ("reasons", "metrics"):
            if not isinstance(getattr(self, name), dict):
                raise ValueError(f"{name} must be a dictionary")

    def to_dict(self) -> Dict[str, Any]:
        """Return a validated JSON snapshot, independent of caller state."""
        self._validate()
        return json_snapshot({
            "name": self.name, "order": self.order,
            "inputs": self.inputs if self.inputs is not None else {},
            "outputs": self.outputs if self.outputs is not None else {},
            "description": self.description, "reasons": self.reasons,
            "metrics": self.metrics,
        }, "step")
    
    def __repr__(self) -> str:
        return f"XRayStep(name='{self.name}', order={self.order})"
