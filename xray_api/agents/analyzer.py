"""
XRayAnalyzer - AI agent for analyzing pipeline runs using Cerebras API
Uses sliding-window analysis to stay under token limits.
"""

import os
import json
import logging
from typing import Dict, Any, List
from openai import OpenAI


class XRayAnalyzer:
    """
    Analyzes pipeline runs to identify faulty steps using Cerebras LLM.
    Uses a sliding-window approach (2 steps at a time) to fit within 65K token context limit.
    """
    
    WINDOW_SIZE = 2  # Analyze 2 steps at a time
    MAX_PAYLOAD_SIZE = 80000  # chars per step side (~20K tokens) - 2 steps = ~40K tokens, safely under 65K limit
    SAMPLE_SIZE = 100
    MIN_SAMPLE_SIZE = 10
    STRING_TRUNCATE = 2000
    
    def __init__(self):
        """Initialize the analyzer with Cerebras API configuration"""
        self.api_key = os.getenv('CEREBRAS_API_KEY')
        self.base_url = os.getenv('CEREBRAS_BASE_URL', 'https://api.cerebras.ai/v1')
        self.model = os.getenv('CEREBRAS_MODEL', 'llama-3.3-70b')
        self.log_thinking = os.getenv('XRAY_LOG_THINKING', 'true').lower() in ('1', 'true', 'yes')
        
        if not self.api_key:
            raise ValueError("CEREBRAS_API_KEY environment variable not set")
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

        self.logger = logging.getLogger(__name__)
        if not self.logger.handlers:
            logging.basicConfig(level=logging.DEBUG if self.log_thinking else logging.INFO)
        if self.log_thinking:
            root_logger = logging.getLogger()
            root_logger.setLevel(logging.DEBUG)
            for handler in root_logger.handlers:
                handler.setLevel(logging.DEBUG)
            self.logger.setLevel(logging.DEBUG)
            # Keep analyzer output concise by muting noisy HTTP client debug logs.
            for noisy_logger in ("openai", "httpx", "httpcore", "werkzeug"):
                logging.getLogger(noisy_logger).setLevel(logging.WARNING)
    
    def analyze_run(self, run_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze a pipeline run using sliding-window approach.
        
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

        run_data = self._summarize_run_data(run_data)
        sorted_steps = sorted(run_data.get('steps', []), key=lambda s: s.get('step_order', 0))

        window_results = []
        # Always use sliding windows (even for <= WINDOW_SIZE) to keep a single analysis mode
        if len(sorted_steps) <= self.WINDOW_SIZE:
            result = self._analyze_window(sorted_steps, 0, run_data)
            window_results.append(result)
        else:
            for i in range(len(sorted_steps) - 1):
                window = sorted_steps[i:i + self.WINDOW_SIZE]
                result = self._analyze_window(window, i, run_data)
                window_results.append(result)
                if result.get('faulty_step'):
                    break

        return self._combine_window_results(window_results, sorted_steps)

    def _summarize_run_data(self, run_data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply server-side summarization to keep prompts bounded."""
        summarized = dict(run_data)
        summarized_steps = []
        for step in run_data.get("steps", []):
            summarized_step = dict(step)
            summarized_step["inputs"] = self._ensure_within_budget(step.get("inputs"))
            summarized_step["outputs"] = self._ensure_within_budget(step.get("outputs"))
            summarized_steps.append(summarized_step)
        summarized["steps"] = summarized_steps
        return summarized

    def _ensure_within_budget(self, data: Any) -> Any:
        if data is None:
            return {}
        try:
            size = len(json.dumps(data, default=str))
        except Exception:
            size = self.MAX_PAYLOAD_SIZE + 1
        if size <= self.MAX_PAYLOAD_SIZE:
            return data
        # Log that summarization is happening
        self.logger.info(f"[analyzer] Summarizing large payload: {size} chars -> MAX {self.MAX_PAYLOAD_SIZE} chars")
        summarized = self._summarize_with_budget(data)
        new_size = len(json.dumps(summarized, default=str))
        self.logger.info(f"[analyzer] Summarization complete: {size} -> {new_size} chars")
        return summarized

    def _summarize_with_budget(self, data: Any) -> Any:
        sample_size = self.SAMPLE_SIZE
        summarized = data
        while True:
            summarized = self._summarize_once(summarized, sample_size)
            size = len(json.dumps(summarized, default=str))
            if size <= self.MAX_PAYLOAD_SIZE or sample_size <= self.MIN_SAMPLE_SIZE:
                return summarized
            sample_size = max(self.MIN_SAMPLE_SIZE, sample_size // 2)

    def _summarize_once(self, data: Any, sample_size: int) -> Any:
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
        total_count = None
        if len(items) > sample_size:
            total_count = len(items)
            head_count = sample_size // 2
            tail_count = sample_size - head_count
            items = items[:head_count] + items[-tail_count:]
        return [self._summarize_once(item, sample_size) for item in items], total_count

    def _analyze_window(self, window_steps: List[Dict], window_index: int, run_data: Dict) -> Dict[str, Any]:
        """Analyze a window of 2 steps"""
        prompt = self._build_window_prompt(window_steps, window_index, run_data)
        if self.log_thinking:
            self.logger.info("[analyzer] window_prompt window=%s size=%s", window_index + 1, len(prompt))
        
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
            if self.log_thinking:
                self.logger.info("[analyzer] window_raw_response chars=%s", len(result_text or ""))
            parsed = self._parse_analysis_response(result_text)
            if self.log_thinking:
                self.logger.info("[analyzer] window_parsed=%s", parsed)
            return parsed
            
        except Exception as e:
            return {"error": str(e), "faulty_step": None}
    
    def _get_system_prompt(self) -> str:
        """System prompt for window analysis (2 steps)"""
        return """You are analyzing a WINDOW of 2 consecutive steps from a pipeline.

## Understanding the Pipeline & Steps
First, use the **pipeline description** to understand what TYPE of pipeline this is:
- Is it a data processing pipeline? (ETL, data transformation)
- Is it an AI/ML pipeline? (inference, embeddings, classification)
- Is it a document pipeline? (parsing, extraction, summarization)
- Is it an automation pipeline? (scraping, API calls, integrations)

Then, use each **step description** to understand what TYPE of step it is:
- Data retrieval steps (fetching from DB, API, files)
- Transformation steps (parsing, filtering, mapping)
- AI/LLM steps (generation, embedding, classification)
- Output steps (writing, sending, storing)

## Check Data Flow
With the pipeline type and step types in mind, check if data flows correctly:
1. Does Step 2's input match Step 1's output?
2. Are there semantic mismatches given what each step is supposed to do?
3. Did anything get lost or corrupted in the transition?
4. Does the output format match what the next step type expects?

## Use Available Context
- **Reasons**: If present, shows why items were dropped/rejected - useful for understanding filtering logic
- **Metrics**: If present, shows step performance (e.g., elimination_rate) - useful for spotting anomalies

## IMPORTANT: Config Inputs vs Data Flow Inputs
Many step inputs are **configuration parameters** (filters, thresholds, limits, options) that come from settings, NOT from the previous step. Examples:
- `min_rating`, `max_price`, `limit`, `threshold`, `filter_by`, `sort_order`
- These are expected and normal - do NOT flag them as "missing data flow"

Also, data often flows **implicitly** between steps (via shared state, databases, or function chaining) without being explicitly declared in inputs. If a step has only config inputs, assume the data flows implicitly and focus on whether the **outputs make sense** given the step's purpose.

**Only flag as faulty if:**
- Outputs contain wrong/corrupted data that doesn't match the step's purpose
- There's a clear semantic mismatch (e.g., laptop items in a phone case filter)
- The outputs contradict the config (e.g., items with rating 4.1 when min_rating was 4.5)

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
        pipeline_description = run_data.get('pipeline_description') or run_data.get('description') or 'No description provided'
        
        parts = [
            f"## Pipeline: {pipeline_name}",
            f"**Pipeline Description (use this to understand the pipeline type):** {pipeline_description}",
            "",
            f"## Window {window_index + 1}: Steps {steps[0].get('step_order')} → {steps[-1].get('step_order')}",
            ""
        ]
        
        for step in steps:
            parts.append(f"### Step {step.get('step_order', '?')}: {step.get('step_name', 'unknown')}")
            step_description = step.get('step_description') or step.get('description')
            if step_description:
                parts.append(f"**Step Type/Purpose (use this to understand what this step does):** {step_description}")
            else:
                parts.append("**Step Type/Purpose:** Not provided - infer from step name and data")
            parts.append(f"**Inputs:** {json.dumps(step.get('inputs', {}), indent=2, default=str)}")
            parts.append(f"**Outputs:** {json.dumps(step.get('outputs', {}), indent=2, default=str)}")
            
            # Include reasons if present (explains why items were dropped/rejected)
            reasons = step.get('reasons', {})
            if reasons:
                parts.append(f"**Reasons (items dropped/rejected):** {json.dumps(reasons, indent=2, default=str)}")
            
            # Include metrics if present (step-level performance data)
            metrics = step.get('metrics', {})
            if metrics:
                parts.append(f"**Metrics:** {json.dumps(metrics, indent=2, default=str)}")
            
            parts.append("")
        
        parts.append("Analyze the transition between these steps. Consider the pipeline type and step purposes when evaluating data flow.")
        return "\n".join(parts)
    
    def _combine_window_results(
        self,
        window_results: List[Dict],
        all_steps: List[Dict],
    ) -> Dict[str, Any]:
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
