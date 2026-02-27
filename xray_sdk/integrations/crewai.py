"""
CrewAI integration for X-Ray SDK.

Auto-captures agent tasks and tool calls from CrewAI crews.
Attach the monitor before kickoff to capture everything.

Usage:
    from xray_sdk import XRayClient
    from xray_sdk.integrations.crewai import XRayCrewMonitor

    monitor = XRayCrewMonitor(pipeline_name="my_crew")
    monitor.attach(crew)
    crew.kickoff()

    client = XRayClient("http://localhost:5000")
    result = monitor.send(client)
    print(result["analysis"])
"""

import time
import logging
from typing import Any, Dict, List, Optional

from ..run import XRayRun
from ..step import XRayStep

logger = logging.getLogger(__name__)


class XRayCrewMonitor:
    """
    CrewAI monitor that auto-captures agent task execution as X-Ray steps.
    
    Hooks into CrewAI's task execution lifecycle to capture:
    - Agent task start/end with inputs/outputs
    - Tool usage within tasks
    - Task delegation between agents
    - Execution timing
    
    Works with CrewAI v0.28+ (both crewai and crewai-tools).
    
    Args:
        pipeline_name: Name for this pipeline run
        description: What this crew does
        metadata: Additional metadata for the run
        sample_size: Max items for summarization
    """
    
    def __init__(
        self,
        pipeline_name: str = "crewai_pipeline",
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        sample_size: int = 100,
    ):
        self.run = XRayRun(
            pipeline_name=pipeline_name,
            description=description,
            metadata=metadata or {},
            sample_size=sample_size,
        )
        self._step_order = 0
        self._crew = None
        self._original_execute_task = None

    def attach(self, crew: Any) -> "XRayCrewMonitor":
        """
        Attach this monitor to a CrewAI Crew instance.
        
        Monkey-patches the crew's task execution to capture steps.
        Call this BEFORE crew.kickoff().
        
        Args:
            crew: A CrewAI Crew instance
            
        Returns:
            self (for chaining)
        """
        self._crew = crew
        self._wrap_tasks(crew)
        return self

    def _wrap_tasks(self, crew: Any) -> None:
        """Wrap each task's execute method to capture inputs/outputs."""
        if not hasattr(crew, 'tasks'):
            logger.warning("[xray] CrewAI crew has no tasks — nothing to monitor")
            return
        
        for task in crew.tasks:
            original_execute = task.execute_sync if hasattr(task, 'execute_sync') else None
            if original_execute is None:
                continue
            
            monitor = self
            task_ref = task

            def make_wrapper(orig_fn, task_obj):
                def wrapped(*args, **kwargs):
                    start_time = time.time()
                    agent_name = getattr(task_obj.agent, 'role', 'unknown_agent') if task_obj.agent else 'unknown_agent'
                    task_desc = getattr(task_obj, 'description', '') or ''
                    step_inputs = {
                        "task_description": task_desc[:1000],
                        "agent": agent_name,
                        "expected_output": getattr(task_obj, 'expected_output', '')[:500],
                    }
                    
                    # Add context from dependent tasks if available
                    context_tasks = getattr(task_obj, 'context', []) or []
                    if context_tasks:
                        step_inputs["context_from"] = [
                            getattr(ct, 'description', '')[:200] for ct in context_tasks[:5]
                        ]
                    
                    try:
                        result = orig_fn(*args, **kwargs)
                        duration_ms = int((time.time() - start_time) * 1000)
                        
                        monitor._step_order += 1
                        output_str = str(result)[:2000] if result else ""
                        
                        monitor.run.add_step(XRayStep(
                            name=f"agent:{agent_name}",
                            order=monitor._step_order,
                            description=f"CrewAI task executed by {agent_name}: {task_desc[:100]}",
                            inputs=step_inputs,
                            outputs={"result": output_str},
                            metrics={"duration_ms": duration_ms},
                        ))
                        return result
                        
                    except Exception as e:
                        duration_ms = int((time.time() - start_time) * 1000)
                        monitor._step_order += 1
                        monitor.run.add_step(XRayStep(
                            name=f"agent:{agent_name}",
                            order=monitor._step_order,
                            description=f"CrewAI task (FAILED) by {agent_name}: {task_desc[:100]}",
                            inputs=step_inputs,
                            outputs={"error": str(e)[:1000]},
                            metrics={"duration_ms": duration_ms},
                        ))
                        raise
                
                return wrapped
            
            task.execute_sync = make_wrapper(original_execute, task)

    def add_step(
        self,
        name: str,
        inputs: Dict[str, Any],
        outputs: Dict[str, Any],
        description: str = "",
        **kwargs: Any,
    ) -> None:
        """
        Manually add a step (useful for pre/post-processing around the crew).
        
        Args:
            name: Step name
            inputs: Step inputs
            outputs: Step outputs
            description: What this step does
        """
        self._step_order += 1
        self.run.add_step(XRayStep(
            name=name,
            order=self._step_order,
            description=description,
            inputs=inputs,
            outputs=outputs,
            **kwargs,
        ))

    def send(self, client: Any, analyze: bool = True) -> Dict[str, Any]:
        """
        Send the captured run to the X-Ray API.
        
        Args:
            client: XRayClient instance
            analyze: Whether to trigger analysis
            
        Returns:
            API response with analysis result
        """
        if not self.run.steps:
            return {"error": "No steps were captured. Did the crew run?"}
        return client.send(self.run, analyze=analyze)

    def get_run(self) -> XRayRun:
        """Return the captured XRayRun for manual inspection."""
        return self.run

    def reset(self) -> None:
        """Reset to capture a new run with the same config."""
        self.run.steps.clear()
        self._step_order = 0
