"""
XRayAnalyzer - AI agent for analyzing pipeline runs using Cerebras API
Uses sliding window approach (2 steps at a time) to stay under token limits.
"""

import os
import json
from typing import Dict, Any, List
from openai import OpenAI


class XRayAnalyzer:
    """
    Analyzes pipeline runs to identify faulty steps using Cerebras LLM.
    Uses sliding window of 2 steps to fit within 65K token context limit.
    """
    
    WINDOW_SIZE = 2  # Analyze 2 steps at a time
    
    def __init__(self):
        """Initialize the analyzer with Cerebras API configuration"""
        self.api_key = os.getenv('CEREBRAS_API_KEY')
        self.base_url = os.getenv('CEREBRAS_BASE_URL', 'https://api.cerebras.ai/v1')
        self.model = os.getenv('CEREBRAS_MODEL', 'llama-3.3-70b')
        
        if not self.api_key:
            raise ValueError("CEREBRAS_API_KEY environment variable not set")
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
    
    def analyze_run(self, run_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze a pipeline run using sliding window approach.
        
        Analyzes 2 steps at a time to stay under 65K token limit:
        - Each step can have up to 20K chars (~5K tokens)
        - 2 steps = ~40K tokens + overhead = safely under 65K
        
        Args:
            run_data: Dictionary containing pipeline run with steps
            
        Returns:
            Analysis result with faulty step identification
        """
        steps = run_data.get('steps', [])
        if not steps:
            return {"error": "No steps to analyze"}
        
        # Sort steps by order
        sorted_steps = sorted(steps, key=lambda s: s.get('step_order', 0))
        
        # If only 1-2 steps, analyze directly
        if len(sorted_steps) <= self.WINDOW_SIZE:
            return self._analyze_steps(sorted_steps, run_data)
        
        # Sliding window analysis
        window_results = []
        for i in range(len(sorted_steps) - 1):
            window = sorted_steps[i:i + self.WINDOW_SIZE]
            result = self._analyze_window(window, i, run_data)
            window_results.append(result)
            
            # If we found a faulty step, stop early
            if result.get('faulty_step'):
                break
        
        # Combine results
        return self._combine_window_results(window_results, sorted_steps)
    
    def _analyze_window(self, window_steps: List[Dict], window_index: int, run_data: Dict) -> Dict[str, Any]:
        """Analyze a window of 2 steps"""
        prompt = self._build_window_prompt(window_steps, window_index, run_data)
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._get_window_system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=1000
            )
            
            result_text = response.choices[0].message.content
            return self._parse_analysis_response(result_text)
            
        except Exception as e:
            return {"error": str(e), "faulty_step": None}
    
    def _analyze_steps(self, steps: List[Dict], run_data: Dict) -> Dict[str, Any]:
        """Analyze all steps when total is <= WINDOW_SIZE"""
        prompt = self._build_analysis_prompt(steps, run_data)
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=1000
            )
            
            result_text = response.choices[0].message.content
            return self._parse_analysis_response(result_text)
            
        except Exception as e:
            return {"error": str(e), "faulty_step": None, "reason": "Analysis failed"}
    
    def _get_system_prompt(self) -> str:
        """System prompt for full analysis"""
        return """You are an expert debugging assistant that analyzes multi-step AI pipeline executions.

Your task is to trace through each step and identify where things went wrong.

For each step, examine:
1. Does the output logically follow from the input?
2. Are there semantic mismatches (e.g., phone case input producing laptop-related output)?
3. Was too much or too little data filtered?
4. Does the step's reasoning (if provided in outputs) make sense?

Respond in valid JSON:
{
    "faulty_step": "step_name or null if no issues",
    "faulty_step_order": step_number or null,
    "reason": "Clear explanation of what went wrong",
    "suggestion": "How to fix the issue",
    "all_steps_analysis": [
        {"step": "step_name", "status": "ok|warning|error", "note": "brief note"}
    ]
}"""

    def _get_window_system_prompt(self) -> str:
        """System prompt for window analysis (2 steps)"""
        return """You are analyzing a WINDOW of 2 consecutive steps from a pipeline.

Check if the data flows correctly between these two steps:
1. Does Step 2's input match Step 1's output?
2. Are there semantic mismatches?
3. Did anything get lost or corrupted in the transition?

Respond in valid JSON:
{
    "faulty_step": "step_name or null if transition looks OK",
    "faulty_step_order": step_number or null,
    "reason": "What went wrong between these steps",
    "transition_status": "ok|warning|error"
}"""

    def _build_window_prompt(self, steps: List[Dict], window_index: int, run_data: Dict) -> str:
        """Build prompt for a 2-step window"""
        pipeline_name = run_data.get('pipeline_name', 'unknown')
        
        parts = [
            f"## Pipeline: {pipeline_name}",
            f"## Window {window_index + 1}: Steps {steps[0].get('step_order')} → {steps[-1].get('step_order')}",
            ""
        ]
        
        for step in steps:
            parts.append(f"### Step {step.get('step_order', '?')}: {step.get('step_name', 'unknown')}")
            parts.append(f"**Inputs:** {json.dumps(step.get('inputs', {}), indent=2, default=str)}")
            parts.append(f"**Outputs:** {json.dumps(step.get('outputs', {}), indent=2, default=str)}")
            parts.append("")
        
        parts.append("Analyze the transition between these steps. Is the data flow correct?")
        return "\n".join(parts)
    
    def _build_analysis_prompt(self, steps: List[Dict], run_data: Dict) -> str:
        """Build prompt for full analysis"""
        pipeline_name = run_data.get('pipeline_name', 'unknown')
        metadata = run_data.get('metadata', {})
        
        parts = [
            f"## Pipeline: {pipeline_name}",
            f"## Metadata: {json.dumps(metadata)}",
            "",
            "## Steps Executed:",
            ""
        ]
        
        for step in steps:
            parts.append(f"### Step {step.get('step_order', '?')}: {step.get('step_name', 'unknown')}")
            parts.append(f"**Inputs:** {json.dumps(step.get('inputs', {}), indent=2, default=str)}")
            parts.append(f"**Outputs:** {json.dumps(step.get('outputs', {}), indent=2, default=str)}")
            parts.append("")
        
        parts.append("---")
        parts.append("Identify the FIRST step where something went wrong (if any).")
        return "\n".join(parts)
    
    def _combine_window_results(self, window_results: List[Dict], all_steps: List[Dict]) -> Dict[str, Any]:
        """Combine results from multiple window analyses"""
        # Find first faulty step
        for result in window_results:
            if result.get('faulty_step'):
                return {
                    "faulty_step": result['faulty_step'],
                    "faulty_step_order": result.get('faulty_step_order'),
                    "reason": result.get('reason', ''),
                    "suggestion": result.get('suggestion', ''),
                    "analysis_method": "sliding_window",
                    "windows_analyzed": len(window_results)
                }
        
        # No issues found
        return {
            "faulty_step": None,
            "faulty_step_order": None,
            "reason": "All step transitions appear correct",
            "suggestion": None,
            "analysis_method": "sliding_window",
            "windows_analyzed": len(window_results),
            "all_steps_analysis": [
                {"step": s.get('step_name'), "status": "ok", "note": "Transition verified"}
                for s in all_steps
            ]
        }
    
    def _parse_analysis_response(self, response_text: str) -> Dict[str, Any]:
        """Parse the LLM response into structured analysis result"""
        try:
            text = response_text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            
            return json.loads(text.strip())
        except json.JSONDecodeError:
            return {
                "faulty_step": None,
                "faulty_step_order": None,
                "reason": response_text,
                "suggestion": "Unable to parse structured response",
                "raw_response": response_text
            }
