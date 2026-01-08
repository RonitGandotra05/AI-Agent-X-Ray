"""
XRayStep - Represents a single step in a pipeline execution
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, Any


@dataclass
class XRayStep:
    """
    A single step in a pipeline execution.
    
    Attributes:
        name: Step identifier (e.g., "keyword_generation", "filter", "rank")
        order: Step sequence number (1, 2, 3, ...)
        inputs: What was fed to this step (any JSON-serializable dict)
        outputs: What this step produced (any JSON-serializable dict)
    """
    name: str
    order: int
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert step to dictionary for JSON serialization"""
        return asdict(self)
    
    def __repr__(self) -> str:
        return f"XRayStep(name='{self.name}', order={self.order})"
