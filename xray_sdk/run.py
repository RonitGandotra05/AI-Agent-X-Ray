"""
XRayRun - Represents a complete pipeline execution with multiple steps
"""

import logging
from typing import List, Dict, Any, Optional
from .step import XRayStep
from xray_shared.summarize import Summarizer

logger = logging.getLogger(__name__)


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
    ):
        """
        Initialize a new run.
        
        Args:
            pipeline_name: Name of the pipeline (e.g., "competitor_selection")
            description: Optional description of what this pipeline does (helps AI analysis)
            metadata: Optional metadata about this run (e.g., {"product_id": "123"})
            sample_size: Optional override for summarization sample size
        """
        self.pipeline_name = pipeline_name
        self.description = description or ""
        self.metadata = metadata or {}
        self.summarizer = Summarizer(
            sample_size=max(1, sample_size) if sample_size is not None else Summarizer.DEFAULT_SAMPLE_SIZE
        )
        self.steps: List[XRayStep] = []
    
    def add_step(self, step: XRayStep) -> None:
        """
        Add a step to this run. Auto-summarizes large outputs.
        
        Args:
            step: The XRayStep to add
        """
        step.inputs = self.summarizer.ensure_within_budget(step.inputs)
        step.outputs = self.summarizer.ensure_within_budget(step.outputs)
        
        self.steps.append(step)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert run to dictionary for JSON serialization"""
        return {
            "pipeline_name": self.pipeline_name,
            "pipeline_description": self.description,
            "metadata": self.metadata,
            "steps": [step.to_dict() for step in self.steps],
            "_sdk_summarized": True,  # Signal to API: don't re-summarize
        }
    
    def __repr__(self) -> str:
        return f"XRayRun(pipeline='{self.pipeline_name}', steps={len(self.steps)})"

