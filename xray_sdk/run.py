"""
XRayRun - Represents a complete pipeline execution with multiple steps
"""

import json
import random
from typing import List, Dict, Any, Optional
from .step import XRayStep


class XRayRun:
    """
    A complete run of a pipeline, containing multiple steps.
    
    Automatically summarizes large outputs to prevent token limit issues.
    """
    
    MAX_OUTPUT_SIZE = 20000  # chars per step (~5K tokens) - keeps total under 65K token limit
    SAMPLE_SIZE = 100        # number of items to keep in random sample
    
    def __init__(self, pipeline_name: str, metadata: Optional[Dict[str, Any]] = None):
        """
        Initialize a new run.
        
        Args:
            pipeline_name: Name of the pipeline (e.g., "competitor_selection")
            metadata: Optional metadata about this run (e.g., {"product_id": "123"})
        """
        self.pipeline_name = pipeline_name
        self.metadata = metadata or {}
        self.steps: List[XRayStep] = []
    
    def add_step(self, step: XRayStep) -> None:
        """
        Add a step to this run. Auto-summarizes large outputs.
        
        Args:
            step: The XRayStep to add
        """
        # Auto-summarize if outputs too large
        output_str = json.dumps(step.outputs, default=str)
        if len(output_str) > self.MAX_OUTPUT_SIZE:
            step.outputs = self._summarize(step.outputs)
        
        self.steps.append(step)
    
    def _summarize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Structural summarization - keeps random 30 items from large lists.
        
        Args:
            data: The data dict to summarize
            
        Returns:
            Summarized data with large lists reduced to random samples
        """
        summarized = {}
        for key, value in data.items():
            if isinstance(value, list) and len(value) > self.SAMPLE_SIZE:
                # Random sample of 30 items + total count
                summarized[key] = random.sample(value, self.SAMPLE_SIZE)
                summarized[f"{key}_total_count"] = len(value)
            else:
                summarized[key] = value
        return summarized
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert run to dictionary for JSON serialization"""
        return {
            "pipeline_name": self.pipeline_name,
            "metadata": self.metadata,
            "steps": [step.to_dict() for step in self.steps]
        }
    
    def __repr__(self) -> str:
        return f"XRayRun(pipeline='{self.pipeline_name}', steps={len(self.steps)})"
