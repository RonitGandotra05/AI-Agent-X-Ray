"""
XRayRun - Represents a complete pipeline execution with multiple steps
"""

from typing import List, Dict, Any, Optional
from .step import XRayStep
from xray_shared.summarize import Summarizer
from xray_shared.validation import json_snapshot, name_string

class XRayRun:
    """
    A complete run of a pipeline, containing multiple steps.
    
    Automatically summarizes large inputs/outputs to prevent token limit issues.
    """
    
    def __init__(
        self,
        pipeline_name: str,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        sample_size: Optional[int] = None,
        *,
        max_payload_size: int = Summarizer.DEFAULT_MAX_PAYLOAD_SIZE,
    ):
        """
        Initialize a new run.
        
        Args:
            pipeline_name: Name of the pipeline (e.g., "competitor_selection")
            description: Optional description of what this pipeline does (helps AI analysis)
            metadata: Optional metadata about this run (e.g., {"product_id": "123"})
            sample_size: Optional override for summarization sample size
            max_payload_size: Maximum JSON characters per captured data field
        """
        self.pipeline_name = name_string(pipeline_name, "pipeline_name")
        if description is not None and not isinstance(description, str):
            raise ValueError("description must be a string or None")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be a dictionary or None")
        self.description = description or ""
        self.metadata = json_snapshot(metadata or {}, "metadata")
        self.summarizer = Summarizer(
            sample_size=sample_size if sample_size is not None else Summarizer.DEFAULT_SAMPLE_SIZE,
            max_payload_size=max_payload_size,
        )
        self.steps: List[XRayStep] = []
    
    def add_step(self, step: XRayStep) -> None:
        """
        Add a step to this run. Auto-summarizes large outputs.
        
        Args:
            step: The XRayStep to add
        """
        if not isinstance(step, XRayStep):
            raise TypeError("step must be an XRayStep")
        if len(self.steps) >= 50:
            raise ValueError("Too many steps (max 50)")
        if any(existing.order == step.order for existing in self.steps):
            raise ValueError(f"Duplicate step order: {step.order}")
        snapshot = step.to_dict()
        for name in ("inputs", "outputs", "reasons", "metrics"):
            snapshot[name] = self.summarizer.ensure_within_budget(snapshot[name])
        self.steps.append(XRayStep(**snapshot))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert run to dictionary for JSON serialization"""
        name_string(self.pipeline_name, "pipeline_name")
        if not self.steps:
            raise ValueError("At least one step is required")
        if len(self.steps) > 50 or len({s.order for s in self.steps}) != len(self.steps):
            raise ValueError("Runs require at most 50 steps with unique orders")
        steps = []
        for step in self.steps:
            snapshot = step.to_dict()
            for name in ("inputs", "outputs", "reasons", "metrics"):
                snapshot[name] = self.summarizer.ensure_within_budget(snapshot[name])
            steps.append(snapshot)
        if not isinstance(self.description, str) or not isinstance(self.metadata, dict):
            raise ValueError("description must be a string and metadata must be a dictionary")
        return {
            "pipeline_name": self.pipeline_name,
            "pipeline_description": self.description,
            "metadata": self.summarizer.ensure_within_budget(json_snapshot(self.metadata, "metadata")),
            "steps": steps,
            "_sdk_summarized": True,  # Legacy hint; server still enforces its own bounds.
        }
    
    def __repr__(self) -> str:
        return f"XRayRun(pipeline='{self.pipeline_name}', steps={len(self.steps)})"
