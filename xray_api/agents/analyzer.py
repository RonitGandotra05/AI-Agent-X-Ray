"""
XRayAnalyzer - AI agent for analyzing pipeline runs
Uses sliding-window analysis to stay under token limits.
Supports multiple LLM providers via adapters.
"""

import os
import json
import logging
from typing import Dict, Any, List
from .llm_adapters import get_adapter, LLMAdapter
from xray_shared.summarize import Summarizer


class XRayAnalyzer:
    """
    Analyzes pipeline runs to identify faulty steps using LLM.
    Uses a sliding-window approach (2 steps at a time) to fit within token context limits.
    
    Supports multiple LLM providers via LLM_PROVIDER env var:
    - cerebras (default)
    - openai
    - anthropic  
    - ollama (local)
    """
    
    WINDOW_SIZE = 2  # Analyze 2 steps at a time
    _system_prompt_cache = None  # Cache system prompt across windows
    
    def __init__(self, provider: str = None):
        """
        Initialize the analyzer with LLM adapter.
        
        Args:
            provider: LLM provider name (cerebras, openai, anthropic, ollama).
                      Defaults to LLM_PROVIDER env var, then 'cerebras'.
        """
        self.log_thinking = os.getenv('XRAY_LOG_THINKING', 'true').lower() in ('1', 'true', 'yes')
        
        # Get the appropriate LLM adapter
        self.adapter: LLMAdapter = get_adapter(provider)
        
        # Shared summarizer for server-side safety net
        self.summarizer = Summarizer()
        
        # Cache the system prompt once (it's the same for every window)
        if XRayAnalyzer._system_prompt_cache is None:
            XRayAnalyzer._system_prompt_cache = self._get_system_prompt()
        self._cached_system_prompt = XRayAnalyzer._system_prompt_cache

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
            for noisy_logger in ("openai", "httpx", "httpcore", "werkzeug", "anthropic"):
                logging.getLogger(noisy_logger).setLevel(logging.WARNING)
            self.logger.info(f"[analyzer] Using LLM provider: {self.adapter.provider_name} ({self.adapter.model_name})")
    
    def analyze_run(self, run_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze a pipeline run using sliding-window approach with cross-window context.
        
        Each window receives a summary of the previous window's findings,
        enabling detection of multi-step issues. Collects ALL faults instead
        of stopping at the first one.
        
        Args:
            run_data: Dictionary containing pipeline run with steps
            
        Returns:
            Analysis result with faulty step identification and severity
        """
        steps = run_data.get('steps', [])
        if not steps:
            return {"error": "No steps to analyze"}

        run_data = self._summarize_run_data(run_data)
        sorted_steps = sorted(run_data.get('steps', []), key=lambda s: s.get('step_order', 0))

        window_results = []
        prev_context = None  # Cross-window context
        
        if len(sorted_steps) <= self.WINDOW_SIZE:
            result = self._analyze_window(sorted_steps, 0, run_data, prev_context)
            window_results.append(result)
        else:
            for i in range(len(sorted_steps) - 1):
                window = sorted_steps[i:i + self.WINDOW_SIZE]
                result = self._analyze_window(window, i, run_data, prev_context)
                window_results.append(result)
                # Build context for next window (1-line summary)
                if result.get('faulty_step'):
                    prev_context = f"Previous window found {result.get('severity','error')} in step '{result['faulty_step']}': {result.get('reason','')[:100]}"
                else:
                    prev_context = f"Previous window ({sorted_steps[i].get('step_name')} → {sorted_steps[i+1].get('step_name')}): OK"

        return self._combine_window_results(window_results, sorted_steps)

    def analyze_run_streaming(self, run_data: Dict[str, Any]):
        """
        Streaming version of analyze_run - yields results as each window completes.
        
        Yields:
            Dict with window analysis result for each transition
        """
        steps = run_data.get('steps', [])
        if not steps:
            yield {"event": "error", "data": {"error": "No steps to analyze"}}
            return

        run_data = self._summarize_run_data(run_data)
        sorted_steps = sorted(run_data.get('steps', []), key=lambda s: s.get('step_order', 0))
        
        total_windows = max(1, len(sorted_steps) - 1) if len(sorted_steps) > self.WINDOW_SIZE else 1
        window_results = []

        prev_context = None

        if len(sorted_steps) <= self.WINDOW_SIZE:
            result = self._analyze_window(sorted_steps, 0, run_data, prev_context)
            window_results.append(result)
            yield {
                "event": "window",
                "data": {
                    "window": 1,
                    "total_windows": 1,
                    "steps_analyzed": [s.get('step_name') for s in sorted_steps],
                    "result": result
                }
            }
        else:
            for i in range(len(sorted_steps) - 1):
                window = sorted_steps[i:i + self.WINDOW_SIZE]
                result = self._analyze_window(window, i, run_data, prev_context)
                window_results.append(result)
                
                yield {
                    "event": "window",
                    "data": {
                        "window": i + 1,
                        "total_windows": total_windows,
                        "steps_analyzed": [s.get('step_name') for s in window],
                        "result": result
                    }
                }
                
                # Build context for next window
                if result.get('faulty_step'):
                    prev_context = f"Previous window found {result.get('severity','error')} in step '{result['faulty_step']}': {result.get('reason','')[:100]}"
                else:
                    prev_context = f"Previous window ({sorted_steps[i].get('step_name')} → {sorted_steps[i+1].get('step_name')}): OK"

        # Yield final combined result
        final_result = self._combine_window_results(window_results, sorted_steps)
        yield {
            "event": "complete",
            "data": final_result
        }

    def _summarize_run_data(self, run_data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply server-side summarization to keep prompts bounded.
        
        Skips summarization if the SDK already processed the data
        (indicated by _sdk_summarized flag), avoiding redundant work.
        """
        # If SDK already summarized, skip the expensive re-processing
        if run_data.get("_sdk_summarized"):
            self.logger.debug("[analyzer] skipping server-side summarization (SDK already processed)")
            return run_data
        
        summarized = dict(run_data)
        summarized_steps = []
        for step in run_data.get("steps", []):
            summarized_step = dict(step)
            summarized_step["inputs"] = self.summarizer.ensure_within_budget(step.get("inputs"))
            summarized_step["outputs"] = self.summarizer.ensure_within_budget(step.get("outputs"))
            summarized_steps.append(summarized_step)
        summarized["steps"] = summarized_steps
        return summarized

    def _analyze_window(self, window_steps: List[Dict], window_index: int, run_data: Dict, prev_context: str = None) -> Dict[str, Any]:
        """Analyze a window of 2 steps, with optional cross-window context."""
        prompt = self._build_window_prompt(window_steps, window_index, run_data, prev_context)
        if self.log_thinking:
            self.logger.info("[analyzer] window_prompt window=%s size=%s", window_index + 1, len(prompt))
        
        try:
            messages = [
                {"role": "system", "content": self._cached_system_prompt},
                {"role": "user", "content": prompt}
            ]
            
            result_text, token_usage = self.adapter.chat_completion_with_usage(
                messages=messages,
                temperature=0.1,
                max_tokens=1000
            )
            
            if self.log_thinking:
                self.logger.info("[analyzer] window_raw_response chars=%s tokens=%s", len(result_text or ""), token_usage)
            parsed = self._parse_analysis_response(result_text)
            parsed["_token_usage"] = token_usage
            if self.log_thinking:
                self.logger.info("[analyzer] window_parsed=%s", parsed)
            return parsed
            
        except Exception as e:
            return {"error": str(e), "faulty_step": None, "_token_usage": {}}
    
    def _get_system_prompt(self) -> str:
        """System prompt for window analysis with severity levels."""
        return """You are analyzing a WINDOW of 2 consecutive steps from a pipeline.

## Understanding the Pipeline & Steps
Use the **pipeline description** to understand what TYPE of pipeline this is (data processing, AI/ML, document, automation, etc.).
Use each **step description** to understand what each step does.

## Check Data Flow
1. Does Step 2's input match Step 1's output?
2. Are there semantic mismatches given what each step is supposed to do?
3. Did anything get lost or corrupted in the transition?
4. Does the output format match what the next step type expects?

## Context from Previous Windows
If provided, use the "Previous context" to understand what was already analyzed. This helps detect multi-step issues that span several transitions.

## IMPORTANT: Config vs Data Flow
Many inputs are config parameters (min_rating, max_price, limit) from settings, NOT from the previous step — these are normal.
Data often flows implicitly (shared state, databases). Focus on whether outputs make sense for the step's purpose.

**Only flag as faulty if:**
- Outputs contain wrong/corrupted data
- Clear semantic mismatch (e.g., laptop items in phone case filter)
- Outputs contradict config (e.g., items with rating 4.1 when min_rating is 4.5)

Respond in valid JSON:
{
    "faulty_step": "step_name or null",
    "faulty_step_order": step_number or null,
    "reason": "What went wrong",
    "severity": "ok|warning|error|critical",
    "suggestion": "How to fix it or null"
}

Severity levels:
- **ok**: Transition is correct
- **warning**: Minor concern but data flows correctly (e.g., unusual elimination rate)
- **error**: Clear data flow or semantic problem
- **critical**: Data corruption, total mismatch, or pipeline-breaking issue"""

    def _build_window_prompt(self, steps: List[Dict], window_index: int, run_data: Dict, prev_context: str = None) -> str:
        """Build prompt for a 2-step window with optional cross-window context."""
        pipeline_name = run_data.get('pipeline_name', 'unknown')
        pipeline_description = run_data.get('pipeline_description') or run_data.get('description') or 'No description provided'
        
        parts = [
            f"## Pipeline: {pipeline_name}",
            f"**Purpose:** {pipeline_description}",
        ]
        
        # Cross-window context (keeps LLM informed about prior analysis)
        if prev_context:
            parts.append(f"**Previous context:** {prev_context}")
        
        parts.append(f"## Window {window_index + 1}: Steps {steps[0].get('step_order')} → {steps[-1].get('step_order')}")
        
        for step in steps:
            parts.append(f"### Step {step.get('step_order', '?')}: {step.get('step_name', 'unknown')}")
            step_description = step.get('step_description') or step.get('description')
            if step_description:
                parts.append(f"**Intent:** {step_description}")
            # Compact JSON — no indent, minimal separators (~35-40% fewer tokens)
            inputs = step.get('inputs', {})
            outputs = step.get('outputs', {})
            if inputs:
                parts.append(f"**Inputs:** {json.dumps(inputs, separators=(',',':'), default=str)}")
            if outputs:
                parts.append(f"**Outputs:** {json.dumps(outputs, separators=(',',':'), default=str)}")
            
            # Only include reasons and metrics if non-empty (skip {} noise)
            reasons = step.get('reasons')
            if reasons:
                parts.append(f"**Reasons:** {json.dumps(reasons, separators=(',',':'), default=str)}")
            
            metrics = step.get('metrics')
            if metrics:
                parts.append(f"**Metrics:** {json.dumps(metrics, separators=(',',':'), default=str)}")
        
        parts.append("Analyze the transition between these steps. Consider the pipeline type and step purposes when evaluating data flow.")
        return "\n".join(parts)
    
    def _combine_window_results(
        self,
        window_results: List[Dict],
        all_steps: List[Dict],
    ) -> Dict[str, Any]:
        """Combine results from all windows, collecting every issue found."""
        # Aggregate token usage across all windows
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        all_issues = []
        
        for result in window_results:
            usage = result.pop("_token_usage", {})
            for key in total_usage:
                total_usage[key] += usage.get(key, 0)
            
            if result.get('faulty_step'):
                all_issues.append({
                    "faulty_step": result['faulty_step'],
                    "faulty_step_order": result.get('faulty_step_order'),
                    "reason": result.get('reason', ''),
                    "severity": result.get('severity', 'error'),
                    "suggestion": result.get('suggestion'),
                })
        
        if all_issues:
            # Primary issue is the most severe
            severity_rank = {'critical': 4, 'error': 3, 'warning': 2, 'ok': 1}
            all_issues.sort(key=lambda x: severity_rank.get(x.get('severity', 'error'), 3), reverse=True)
            primary = all_issues[0]
            
            return {
                "faulty_step": primary['faulty_step'],
                "faulty_step_order": primary.get('faulty_step_order'),
                "reason": primary.get('reason', ''),
                "severity": primary.get('severity', 'error'),
                "suggestion": primary.get('suggestion', ''),
                "analysis_method": "sliding_window",
                "windows_analyzed": len(window_results),
                "token_usage": total_usage,
                "all_issues": all_issues if len(all_issues) > 1 else None,
            }
        
        # No issues found
        return {
            "faulty_step": None,
            "faulty_step_order": None,
            "reason": "All step transitions appear correct",
            "severity": "ok",
            "suggestion": None,
            "analysis_method": "sliding_window",
            "windows_analyzed": len(window_results),
            "token_usage": total_usage,
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
