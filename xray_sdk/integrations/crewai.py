"""Best-effort instrumentation of CrewAI synchronous task execution.

This adapter wraps writable ``execute_sync`` methods. It captures task results
and failures, not individual tool calls or CrewAI asynchronous task execution.
Use ``detach`` after the crew invocation to restore the original methods.
"""

import functools
import json
import logging
import threading
import time
from typing import Any, Dict, Optional

from ..run import XRayRun
from ..step import XRayStep

logger = logging.getLogger(__name__)


class XRayCrewMonitor:
    """Record synchronous task calls without a CrewAI runtime dependency."""

    def __init__(
        self, pipeline_name: str = "crewai_pipeline", description: str = "",
        metadata: Optional[Dict[str, Any]] = None, sample_size: int = 100,
    ):
        self._config = dict(pipeline_name=pipeline_name, description=description, metadata=metadata, sample_size=sample_size)
        self.run = XRayRun(**self._config)
        self._step_order = 0
        self._crew = None
        self._wrapped = []
        self._lock = threading.RLock()

    def attach(self, crew: Any) -> "XRayCrewMonitor":
        """Wrap supported tasks once; unsupported tasks are logged and skipped."""
        if self._crew is crew:
            return self
        self.detach()
        self._crew = crew
        tasks = getattr(crew, "tasks", None)
        if tasks is None:
            logger.warning("X-Ray CrewAI monitor found no tasks")
            return self
        for task in tasks:
            original = getattr(task, "execute_sync", None)
            if not callable(original):
                logger.warning("X-Ray CrewAI monitor skipped a task without execute_sync")
                continue
            if getattr(task, "async_execution", False):
                logger.warning("X-Ray CrewAI monitor does not capture asynchronous tasks")
                continue
            wrapper = self._wrapper(original, task)
            try:
                setattr(task, "execute_sync", wrapper)
            except (AttributeError, TypeError, ValueError):
                logger.warning("X-Ray CrewAI task method is not writable; use manual steps for this task")
            else:
                self._wrapped.append((task, original, wrapper))
        return self

    def _wrapper(self, original: Any, task: Any) -> Any:
        @functools.wraps(original)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            started = time.monotonic()
            agent = getattr(task, "agent", None)
            role = str(getattr(agent, "role", "unknown_agent"))
            description = str(getattr(task, "description", "") or "")
            inputs = {
                "task_description": description, "agent": role,
                "expected_output": str(getattr(task, "expected_output", "") or ""),
            }
            context = getattr(task, "context", None)
            if isinstance(context, (list, tuple)):
                inputs["context_from"] = [str(getattr(item, "description", "") or "") for item in context[:5]]
                inputs["context_count"] = len(context)
            try:
                result = original(*args, **kwargs)
            except BaseException as exc:
                self._capture(role, inputs, {"error": str(exc)}, started)
                raise
            self._capture(role, inputs, {"result": str(result) if result is not None else ""}, started)
            return result
        return wrapped

    def _capture(self, role: str, inputs: Dict[str, Any], outputs: Dict[str, Any], started: float) -> None:
        try:
            self.add_step(
                name=f"agent:{role}", inputs=inputs, outputs=outputs,
                description=f"CrewAI task executed by {role}",
                metrics={"duration_ms": int((time.monotonic() - started) * 1000)},
            )
        except Exception:
            logger.warning("X-Ray could not capture a CrewAI task", exc_info=True)

    def detach(self) -> None:
        """Restore methods still owned by this monitor without overwriting other wrappers."""
        for task, original, wrapper in self._wrapped:
            if getattr(task, "execute_sync", None) is wrapper:
                try:
                    setattr(task, "execute_sync", original)
                except (AttributeError, TypeError, ValueError):
                    logger.warning("X-Ray could not restore a CrewAI task method")
        self._wrapped.clear()
        self._crew = None

    def add_step(
        self, name: str, inputs: Dict[str, Any], outputs: Dict[str, Any],
        description: str = "", **kwargs: Any,
    ) -> None:
        with self._lock:
            self._step_order += 1
            self.run.add_step(XRayStep(
                name=name, order=self._step_order, description=description,
                inputs=json.loads(json.dumps(inputs, default=str)),
                outputs=json.loads(json.dumps(outputs, default=str)), **kwargs,
            ))

    def send(self, client: Any, analyze: bool = True) -> Dict[str, Any]:
        if not self.run.steps:
            return {"error": "No steps were captured. Did the crew run?"}
        return client.send(self.run, analyze=analyze)

    def get_run(self) -> XRayRun:
        return self.run

    def reset(self) -> None:
        with self._lock:
            self.run = XRayRun(**self._config)
            self._step_order = 0
