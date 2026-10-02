"""Optional LangChain callbacks for completed chain, model, tool and retrieval calls."""

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional

from ..run import XRayRun
from ..step import XRayStep

logger = logging.getLogger(__name__)

try:
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError:
    try:
        from langchain.callbacks.base import BaseCallbackHandler
    except ImportError:
        BaseCallbackHandler = object


class XRayCallbackHandler(BaseCallbackHandler):
    """Capture callbacks without network I/O in the application execution path.

    Steps follow completion order; run and parent IDs preserve callback identity.
    A handler represents one invocation. Call ``reset`` between invocations and
    ``send`` explicitly when ready. Capturing is best effort: an invalid callback
    payload is logged and does not replace the application's result or exception.
    """

    def __init__(
        self, pipeline_name: str = "langchain_pipeline", description: str = "",
        metadata: Optional[Dict[str, Any]] = None, sample_size: int = 100,
    ):
        if BaseCallbackHandler is object:
            raise ImportError("Install the LangChain integration with: pip install 'xray-sdk[langchain]'")
        super().__init__()
        self._config = dict(pipeline_name=pipeline_name, description=description, metadata=metadata, sample_size=sample_size)
        self.run = XRayRun(**self._config)
        self._step_order = 0
        self._active_steps: Dict[str, Dict[str, Any]] = {}
        self._anonymous: Dict[str, List[str]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _name(serialized: Any, fallback: str) -> str:
        if not isinstance(serialized, dict):
            return fallback
        if serialized.get("name"):
            return str(serialized["name"])
        identifier = serialized.get("id")
        return str(identifier[-1]) if isinstance(identifier, list) and identifier else fallback

    def _start(self, kind: str, name: str, inputs: Any, run_id: Any, parent_run_id: Any = None) -> None:
        with self._lock:
            step_id = str(run_id) if run_id is not None else f"{kind}_{time.monotonic_ns()}"
            if run_id is None:
                self._anonymous.setdefault(kind, []).append(step_id)
            try:
                snapshot = json.loads(json.dumps(inputs, default=str))
            except (TypeError, ValueError, RecursionError):
                snapshot = {"capture_error": "Input could not be converted to JSON"}
            self._active_steps[step_id] = {
                "name": name, "inputs": snapshot, "start_time": time.monotonic(),
                "run_id": str(run_id) if run_id is not None else None,
                "parent_run_id": str(parent_run_id) if parent_run_id is not None else None,
            }

    def _finish(self, kind: str, outputs: Any, run_id: Any) -> None:
        with self._lock:
            if run_id is None:
                stack = self._anonymous.get(kind, [])
                step_id = stack.pop() if stack else None
            else:
                step_id = str(run_id)
            info = self._active_steps.pop(step_id, None)
            if info is None:
                return
            metrics = {"duration_ms": int((time.monotonic() - info["start_time"]) * 1000)}
            metrics.update({key: info[key] for key in ("run_id", "parent_run_id") if info[key] is not None})
            try:
                output_data = outputs if isinstance(outputs, dict) else {"output": outputs}
                snapshot = json.loads(json.dumps(output_data, default=str))
                self._step_order += 1
                self.run.add_step(XRayStep(
                    name=info["name"], order=self._step_order,
                    description=f"LangChain {kind} call", inputs=info["inputs"],
                    outputs=snapshot, metrics=metrics,
                ))
            except (TypeError, ValueError, RecursionError):
                logger.warning("X-Ray could not capture a LangChain %s callback", kind, exc_info=True)

    def on_llm_start(self, serialized: Any, prompts: List[str], *, run_id: Any = None, **kwargs: Any) -> None:
        self._start("llm", f"llm:{self._name(serialized, 'llm')}",
                    {"prompts": prompts[:3], "prompts_count": len(prompts)}, run_id, kwargs.get("parent_run_id"))

    def on_chat_model_start(self, serialized: Any, messages: List[List[Any]], *, run_id: Any = None, **kwargs: Any) -> None:
        samples = [[{"role": getattr(message, "type", "message"), "content": getattr(message, "content", str(message))}
                    for message in batch] for batch in messages[:3]]
        self._start("llm", f"llm:{self._name(serialized, 'chat_model')}",
                    {"messages": samples, "batches_count": len(messages)}, run_id, kwargs.get("parent_run_id"))

    def on_llm_end(self, response: Any, *, run_id: Any = None, **kwargs: Any) -> None:
        outputs: Dict[str, Any] = {}
        generations = getattr(response, "generations", None) or []
        if generations and generations[0]:
            generation = generations[0][0]
            outputs["response"] = getattr(generation, "text", str(generation))
            usage = getattr(getattr(generation, "message", None), "usage_metadata", None)
            if usage:
                outputs["token_usage"] = usage
        llm_output = getattr(response, "llm_output", None)
        if isinstance(llm_output, dict) and llm_output.get("token_usage"):
            outputs["token_usage"] = llm_output["token_usage"]
        self._finish("llm", outputs, run_id)

    def on_llm_error(self, error: BaseException, *, run_id: Any = None, **kwargs: Any) -> None:
        self._finish("llm", {"error": str(error)}, run_id)

    def on_tool_start(self, serialized: Any, input_str: str, *, run_id: Any = None, **kwargs: Any) -> None:
        self._start("tool", f"tool:{self._name(serialized, 'unknown_tool')}",
                    {"input": input_str}, run_id, kwargs.get("parent_run_id"))

    def on_tool_end(self, output: Any, *, run_id: Any = None, **kwargs: Any) -> None:
        self._finish("tool", {"output": output}, run_id)

    def on_tool_error(self, error: BaseException, *, run_id: Any = None, **kwargs: Any) -> None:
        self._finish("tool", {"error": str(error)}, run_id)

    def on_chain_start(self, serialized: Any, inputs: Any, *, run_id: Any = None, **kwargs: Any) -> None:
        self._start("chain", f"chain:{self._name(serialized, 'chain')}",
                    inputs if isinstance(inputs, dict) else {"input": inputs}, run_id, kwargs.get("parent_run_id"))

    def on_chain_end(self, outputs: Any, *, run_id: Any = None, **kwargs: Any) -> None:
        self._finish("chain", outputs, run_id)

    def on_chain_error(self, error: BaseException, *, run_id: Any = None, **kwargs: Any) -> None:
        self._finish("chain", {"error": str(error)}, run_id)

    def on_retriever_start(self, serialized: Any, query: str, *, run_id: Any = None, **kwargs: Any) -> None:
        self._start("retriever", "retriever", {"query": query}, run_id, kwargs.get("parent_run_id"))

    def on_retriever_end(self, documents: List[Any], *, run_id: Any = None, **kwargs: Any) -> None:
        samples = [getattr(doc, "page_content", str(doc)) for doc in documents[:10]]
        self._finish("retriever", {"documents_count": len(documents), "documents_sample": samples}, run_id)

    def on_retriever_error(self, error: BaseException, *, run_id: Any = None, **kwargs: Any) -> None:
        self._finish("retriever", {"error": str(error)}, run_id)

    def send(self, client: Any, analyze: bool = True) -> Dict[str, Any]:
        if not self.run.steps:
            return {"error": "No steps were captured. Did the chain run?"}
        return client.send(self.run, analyze=analyze)

    def get_run(self) -> XRayRun:
        return self.run

    def reset(self) -> None:
        """Begin another invocation; do not call while callbacks are still active."""
        with self._lock:
            self.run = XRayRun(**self._config)
            self._step_order = 0
            self._active_steps.clear()
            self._anonymous.clear()
