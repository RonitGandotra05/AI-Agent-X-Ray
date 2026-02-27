"""
LangChain integration for X-Ray SDK.

Auto-captures chain/agent steps via LangChain's callback system.
No manual wrapping needed — just pass the handler to your chain.

Usage:
    from xray_sdk import XRayClient
    from xray_sdk.integrations.langchain import XRayCallbackHandler

    handler = XRayCallbackHandler(pipeline_name="my_chain")
    chain.invoke({"input": "hello"}, config={"callbacks": [handler]})

    client = XRayClient("http://localhost:5000")
    result = handler.send(client)
    print(result["analysis"])
"""

import time
import logging
from typing import Any, Dict, List, Optional, Union

from ..run import XRayRun
from ..step import XRayStep

logger = logging.getLogger(__name__)

# Try importing LangChain — fail gracefully if not installed
try:
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.outputs import LLMResult
    _HAS_LANGCHAIN = True
except ImportError:
    try:
        from langchain.callbacks.base import BaseCallbackHandler
        from langchain.schema import LLMResult
        _HAS_LANGCHAIN = True
    except ImportError:
        _HAS_LANGCHAIN = False
        BaseCallbackHandler = object  # Fallback so the class definition works


class XRayCallbackHandler(BaseCallbackHandler):
    """
    LangChain callback handler that auto-captures chain execution steps.
    
    Captures:
    - LLM calls (model, prompt, response, token usage)
    - Tool calls (tool name, input, output)
    - Chain start/end with inputs/outputs
    - Retriever queries and results
    
    Args:
        pipeline_name: Name for this pipeline run
        description: What this chain/agent does
        metadata: Additional metadata for the run
        sample_size: Max items to keep when summarizing large outputs
    """
    
    def __init__(
        self,
        pipeline_name: str = "langchain_pipeline",
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        sample_size: int = 100,
    ):
        if not _HAS_LANGCHAIN:
            raise ImportError(
                "LangChain is not installed. Install it with:\n"
                "  pip install langchain-core\n"
                "  # or: pip install langchain"
            )
        super().__init__()
        self.run = XRayRun(
            pipeline_name=pipeline_name,
            description=description,
            metadata=metadata or {},
            sample_size=sample_size,
        )
        self._step_order = 0
        self._active_steps: Dict[str, Dict[str, Any]] = {}  # run_id -> step info

    # ── LLM callbacks ──────────────────────────────────────────────

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        model_name = serialized.get("id", ["unknown"])[-1] if isinstance(serialized.get("id"), list) else "llm"
        step_id = str(run_id) if run_id else f"llm_{self._step_order}"
        self._active_steps[step_id] = {
            "name": f"llm:{model_name}",
            "description": f"LLM call to {model_name}",
            "inputs": {"prompts": prompts[:3]},  # Cap to avoid huge payloads
            "start_time": time.time(),
        }

    def on_llm_end(self, response: "LLMResult", *, run_id: Any = None, **kwargs: Any) -> None:
        step_id = str(run_id) if run_id else None
        step_info = self._active_steps.pop(step_id, None)
        if step_info is None:
            return
        
        self._step_order += 1
        
        # Extract response text and token usage
        outputs: Dict[str, Any] = {}
        if response.generations:
            outputs["response"] = response.generations[0][0].text[:2000]  # Truncate
        if hasattr(response, "llm_output") and response.llm_output:
            token_usage = response.llm_output.get("token_usage", {})
            if token_usage:
                outputs["token_usage"] = token_usage

        self.run.add_step(XRayStep(
            name=step_info["name"],
            order=self._step_order,
            description=step_info.get("description", ""),
            inputs=step_info.get("inputs", {}),
            outputs=outputs,
            metrics={"duration_ms": int((time.time() - step_info["start_time"]) * 1000)},
        ))

    def on_llm_error(self, error: BaseException, *, run_id: Any = None, **kwargs: Any) -> None:
        step_id = str(run_id) if run_id else None
        step_info = self._active_steps.pop(step_id, None)
        if step_info is None:
            return
        self._step_order += 1
        self.run.add_step(XRayStep(
            name=step_info["name"],
            order=self._step_order,
            description=step_info.get("description", ""),
            inputs=step_info.get("inputs", {}),
            outputs={"error": str(error)[:1000]},
        ))

    # ── Tool callbacks ─────────────────────────────────────────────

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        tool_name = serialized.get("name", "unknown_tool")
        step_id = str(run_id) if run_id else f"tool_{self._step_order}"
        self._active_steps[step_id] = {
            "name": f"tool:{tool_name}",
            "description": f"Tool call to {tool_name}",
            "inputs": {"input": input_str[:2000]},
            "start_time": time.time(),
        }

    def on_tool_end(self, output: str, *, run_id: Any = None, **kwargs: Any) -> None:
        step_id = str(run_id) if run_id else None
        step_info = self._active_steps.pop(step_id, None)
        if step_info is None:
            return
        self._step_order += 1
        self.run.add_step(XRayStep(
            name=step_info["name"],
            order=self._step_order,
            description=step_info.get("description", ""),
            inputs=step_info.get("inputs", {}),
            outputs={"output": str(output)[:2000]},
            metrics={"duration_ms": int((time.time() - step_info["start_time"]) * 1000)},
        ))

    def on_tool_error(self, error: BaseException, *, run_id: Any = None, **kwargs: Any) -> None:
        step_id = str(run_id) if run_id else None
        step_info = self._active_steps.pop(step_id, None)
        if step_info is None:
            return
        self._step_order += 1
        self.run.add_step(XRayStep(
            name=step_info["name"],
            order=self._step_order,
            description=step_info.get("description", ""),
            inputs=step_info.get("inputs", {}),
            outputs={"error": str(error)[:1000]},
        ))

    # ── Chain callbacks ────────────────────────────────────────────

    def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        chain_name = serialized.get("id", ["chain"])[-1] if isinstance(serialized.get("id"), list) else "chain"
        step_id = str(run_id) if run_id else f"chain_{self._step_order}"
        self._active_steps[step_id] = {
            "name": f"chain:{chain_name}",
            "description": f"Chain execution: {chain_name}",
            "inputs": inputs,
            "start_time": time.time(),
        }

    def on_chain_end(self, outputs: Dict[str, Any], *, run_id: Any = None, **kwargs: Any) -> None:
        step_id = str(run_id) if run_id else None
        step_info = self._active_steps.pop(step_id, None)
        if step_info is None:
            return
        self._step_order += 1
        self.run.add_step(XRayStep(
            name=step_info["name"],
            order=self._step_order,
            description=step_info.get("description", ""),
            inputs=step_info.get("inputs", {}),
            outputs=outputs if isinstance(outputs, dict) else {"output": str(outputs)[:2000]},
            metrics={"duration_ms": int((time.time() - step_info["start_time"]) * 1000)},
        ))

    def on_chain_error(self, error: BaseException, *, run_id: Any = None, **kwargs: Any) -> None:
        step_id = str(run_id) if run_id else None
        step_info = self._active_steps.pop(step_id, None)
        if step_info is None:
            return
        self._step_order += 1
        self.run.add_step(XRayStep(
            name=step_info["name"],
            order=self._step_order,
            description=step_info.get("description", ""),
            inputs=step_info.get("inputs", {}),
            outputs={"error": str(error)[:1000]},
        ))

    # ── Retriever callbacks ────────────────────────────────────────

    def on_retriever_start(
        self,
        serialized: Dict[str, Any],
        query: str,
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        step_id = str(run_id) if run_id else f"retriever_{self._step_order}"
        self._active_steps[step_id] = {
            "name": "retriever",
            "description": "Document retrieval step",
            "inputs": {"query": query[:2000]},
            "start_time": time.time(),
        }

    def on_retriever_end(self, documents: List[Any], *, run_id: Any = None, **kwargs: Any) -> None:
        step_id = str(run_id) if run_id else None
        step_info = self._active_steps.pop(step_id, None)
        if step_info is None:
            return
        self._step_order += 1
        # Summarize documents to avoid huge payloads
        doc_summaries = []
        for doc in documents[:10]:  # Max 10 docs
            content = getattr(doc, "page_content", str(doc))
            doc_summaries.append(content[:500])
        self.run.add_step(XRayStep(
            name="retriever",
            order=self._step_order,
            description="Document retrieval step",
            inputs=step_info.get("inputs", {}),
            outputs={"documents_count": len(documents), "documents_sample": doc_summaries},
            metrics={"duration_ms": int((time.time() - step_info["start_time"]) * 1000)},
        ))

    # ── Send results ───────────────────────────────────────────────

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
            return {"error": "No steps were captured. Did the chain run?"}
        return client.send(self.run, analyze=analyze)

    def get_run(self) -> XRayRun:
        """Return the captured XRayRun for manual inspection."""
        return self.run

    def reset(self) -> None:
        """Reset to capture a new run with the same config."""
        self.run.steps.clear()
        self._step_order = 0
        self._active_steps.clear()
