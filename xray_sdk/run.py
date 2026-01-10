"""
XRayRun - Represents a complete pipeline execution with multiple steps
"""

import json
from typing import List, Dict, Any, Optional
from .step import XRayStep


class XRayRun:
    """
    A complete run of a pipeline, containing multiple steps.
    
    Automatically summarizes large inputs/outputs to prevent token limit issues.
    """
    
    MAX_PAYLOAD_SIZE = 80000  # chars per step side (~20K tokens) - 2 steps = ~40K tokens, safely under 65K limit
    SAMPLE_SIZE = 100         # initial sample size per large list
    MIN_SAMPLE_SIZE = 10      # floor for aggressive trimming when still oversized
    STRING_TRUNCATE = 2000    # truncate very long strings to this many chars
    
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
        if sample_size is None:
            self.sample_size = self.SAMPLE_SIZE
        else:
            self.sample_size = max(1, sample_size)
        self.steps: List[XRayStep] = []
    
    def add_step(self, step: XRayStep) -> None:
        """
        Add a step to this run. Auto-summarizes large outputs.
        
        Args:
            step: The XRayStep to add
        """
        step.inputs = self._ensure_within_budget(step.inputs)
        step.outputs = self._ensure_within_budget(step.outputs)
        
        self.steps.append(step)

    def _ensure_within_budget(self, data: Any) -> Any:
        """Summarize data if it exceeds MAX_PAYLOAD_SIZE."""
        if data is None:
            return {}
        try:
            size = len(json.dumps(data, default=str))
        except Exception:
            size = self.MAX_PAYLOAD_SIZE + 1  # force summarization if not serializable
        if size <= self.MAX_PAYLOAD_SIZE:
            return data
        # Log summarization
        print(f"   [SDK] Summarizing large payload: {size} chars -> MAX {self.MAX_PAYLOAD_SIZE} chars")
        summarized = self._summarize_with_budget(data)
        new_size = len(json.dumps(summarized, default=str))
        print(f"   [SDK] Summarization complete: {size} -> {new_size} chars")
        return summarized

    def _summarize_with_budget(self, data: Any) -> Any:
        """Iteratively summarize until payload fits under MAX_PAYLOAD_SIZE."""
        sample_size = self.sample_size
        summarized = data
        while True:
            summarized = self._summarize_once(summarized, sample_size)
            size = len(json.dumps(summarized, default=str))
            if size <= self.MAX_PAYLOAD_SIZE or sample_size <= self.MIN_SAMPLE_SIZE:
                return summarized
            sample_size = max(self.MIN_SAMPLE_SIZE, sample_size // 2)
    
    def _summarize_once(self, data: Any, sample_size: int) -> Any:
        """One-pass summarization with recursion and string truncation."""
        if isinstance(data, dict):
            summarized = {}
            for key, value in data.items():
                if isinstance(value, list):
                    summarized_list, total_count = self._summarize_list(value, sample_size)
                    summarized[key] = summarized_list
                    if total_count is not None:
                        summarized[f"{key}_total_count"] = total_count
                else:
                    summarized[key] = self._summarize_once(value, sample_size)
            return summarized
        if isinstance(data, list):
            summarized_list, _ = self._summarize_list(data, sample_size)
            return summarized_list
        if isinstance(data, str) and len(data) > self.STRING_TRUNCATE:
            overflow = len(data) - self.STRING_TRUNCATE
            return f"{data[:self.STRING_TRUNCATE]}...[truncated {overflow} chars]"
        return data
    
    def _summarize_list(self, items: List[Any], sample_size: int):
        """Summarize a list: sample if large, recurse into elements."""
        total_count = None
        if len(items) > sample_size:
            total_count = len(items)
            head_count = sample_size // 2
            tail_count = sample_size - head_count
            items = items[:head_count] + items[-tail_count:]
        return [self._summarize_once(item, sample_size) for item in items], total_count
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert run to dictionary for JSON serialization"""
        return {
            "pipeline_name": self.pipeline_name,
            "pipeline_description": self.description,
            "metadata": self.metadata,
            "steps": [step.to_dict() for step in self.steps]
        }
    
    def __repr__(self) -> str:
        return f"XRayRun(pipeline='{self.pipeline_name}', steps={len(self.steps)})"
