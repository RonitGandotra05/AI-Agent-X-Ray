"""Small HTTP client with durable replay and explicit background lifecycle."""

import asyncio
import json
import logging
import math
import os
import tempfile
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional, Tuple, Union
from urllib.parse import quote, urlsplit

import requests

from .errors import XRayError, XRayHTTPError, XRayResponseError, XRayTransportError
from .run import XRayRun

logger = logging.getLogger(__name__)
Timeout = Union[float, Tuple[float, float]]


class XRayClient:
    """Export runs to X-Ray. ``retries`` is the total number of attempts.

    ``send`` preserves the original result-dictionary interface. Use
    ``raise_on_error=True`` to raise typed errors instead. Background sends
    return concurrent futures; ``asend`` provides an asyncio awaitable without
    another HTTP dependency. Close the client or use it as a context manager.
    """

    DEFAULT_SPOOL_DIR = ".xray_spool"
    _TRANSIENT_STATUSES = {408, 429, 500, 502, 503, 504}

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Timeout = 180,
        retries: int = 3,
        retry_delay: float = 1.0,
        *,
        spool_dir: Optional[str] = None,
        raise_on_error: bool = False,
        max_pending: int = 64,
        max_workers: int = 4,
        max_retry_delay: float = 30.0,
    ):
        api_url = api_url if api_url is not None else os.getenv("XRAY_API_URL", "http://localhost:5000")
        if not isinstance(api_url, str):
            raise ValueError("api_url must be an HTTP or HTTPS URL")
        parsed = urlsplit(api_url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or
                parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("api_url must be an HTTP or HTTPS URL without credentials, query or fragment")
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("api_url has an invalid port") from exc
        api_key = api_key if api_key is not None else os.getenv("XRAY_API_KEY")
        if api_key is not None and (not isinstance(api_key, str) or "\n" in api_key or "\r" in api_key):
            raise ValueError("api_key must be a string without newlines")
        for name, value in (("retries", retries), ("max_pending", max_pending), ("max_workers", max_workers)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        timeout_values = timeout if isinstance(timeout, tuple) else (timeout,)
        if isinstance(timeout, tuple) and len(timeout) != 2:
            raise ValueError("timeout must be seconds or a (connect, read) pair")
        for value in timeout_values:
            self._validate_number("timeout", value, positive=True)
        self._validate_number("retry_delay", retry_delay)
        self._validate_number("max_retry_delay", max_retry_delay)
        if not isinstance(raise_on_error, bool):
            raise ValueError("raise_on_error must be a boolean")
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.retries = retries
        self.retry_delay = retry_delay
        self.spool_dir = Path(spool_dir if spool_dir is not None else self.DEFAULT_SPOOL_DIR)
        self.raise_on_error = raise_on_error
        self.max_retry_delay = max_retry_delay
        self._max_workers = max_workers
        self._executor: Optional[ThreadPoolExecutor] = None
        self._local = threading.local()
        self._sessions = []
        self._pending = set()
        self._slots = threading.BoundedSemaphore(max_pending)
        self._lock = threading.RLock()
        self._lifecycle = threading.Condition(self._lock)
        self._active_calls = 0
        self._flush_lock = threading.Lock()
        self._closing = False
        self._closed = False

    @staticmethod
    def _validate_number(name: str, value: Any, positive: bool = False) -> None:
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                not math.isfinite(value) or (value <= 0 if positive else value < 0)):
            raise ValueError(f"{name} must be a finite {'positive' if positive else 'non-negative'} number")

    def _check_open(self) -> None:
        if self._closing or self._closed:
            raise XRayError("This XRayClient is closed; create a new client")

    @contextmanager
    def _operation(self):
        # Already queued workers may finish during close; new public calls cannot.
        with self._lifecycle:
            if self._closed:
                raise XRayError("This XRayClient is closed; create a new client")
            self._active_calls += 1
        try:
            yield
        finally:
            with self._lifecycle:
                self._active_calls -= 1
                self._lifecycle.notify_all()

    def _session(self) -> requests.Session:
        # Sessions contain mutable cookies/state, so each caller thread owns one.
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            self._local.session = session
            with self._lock:
                self._sessions.append(session)
        return session

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def _delay(self, attempt: int, response: Optional[requests.Response]) -> float:
        delay = min(self.max_retry_delay, self.retry_delay * (2 ** min(attempt - 1, 30)))
        retry_after = response.headers.get("Retry-After", "")[:256] if response is not None else None
        if retry_after:
            try:
                seconds = float(retry_after)
            except (TypeError, ValueError):
                try:
                    date = parsedate_to_datetime(retry_after)
                    if date.tzinfo is None:
                        date = date.replace(tzinfo=timezone.utc)
                    seconds = (date - datetime.now(timezone.utc)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    seconds = delay
            if math.isfinite(seconds):
                delay = min(self.max_retry_delay, max(delay, seconds, 0.0))
        return delay

    def _request(self, method: str, path: str, *, attempts: Optional[int] = None, **kwargs: Any) -> requests.Response:
        """Retry only transient transport/status failures, never response parsing."""
        attempts = self.retries if attempts is None else attempts
        for attempt in range(1, attempts + 1):
            response = None
            try:
                response = self._session().request(
                    method, f"{self.api_url}{path}", headers=self._headers(),
                    timeout=self.timeout, allow_redirects=False, **kwargs,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                error = XRayTransportError(f"X-Ray request failed after {attempt} attempt(s): {str(exc)[:1000]}")
            except requests.RequestException as exc:
                raise XRayTransportError(f"X-Ray request failed: {str(exc)[:1000]}") from exc
            else:
                if 200 <= response.status_code < 300:
                    return response
                message = f"X-Ray returned HTTP {response.status_code}"
                try:
                    body = response.json()
                    if isinstance(body, dict) and isinstance(body.get("error"), str):
                        message += f": {body['error'][:1000]}"
                except ValueError:
                    pass
                error = XRayHTTPError(message, response)
                if response.status_code not in self._TRANSIENT_STATUSES and not 500 <= response.status_code < 600:
                    response.close()
                    raise error
            delay = self._delay(attempt, response)
            if response is not None:
                response.close()
            if attempt == attempts:
                raise error
            logger.warning("X-Ray request failed (attempt %d/%d); retrying in %.2fs", attempt, attempts, delay)
            time.sleep(delay)
        raise AssertionError("unreachable")

    @staticmethod
    def _object_response(response: requests.Response) -> Dict[str, Any]:
        try:
            try:
                result = response.json()
            except ValueError as exc:
                raise XRayResponseError("X-Ray returned invalid JSON; the request was not retried") from exc
            if not isinstance(result, dict):
                raise XRayResponseError("X-Ray returned JSON that is not an object; the request was not retried")
            if result.get("success") is False:
                raise XRayResponseError(f"X-Ray did not accept the request: {result.get('error', 'unknown error')}")
            return result
        finally:
            response.close()

    @staticmethod
    def _payload(run: XRayRun, analyze: bool) -> Dict[str, Any]:
        if not isinstance(run, XRayRun):
            raise TypeError("run must be an XRayRun")
        if not isinstance(analyze, bool):
            raise ValueError("analyze must be a boolean")
        payload = run.to_dict()
        if not payload.get("steps"):
            raise ValueError("A run must contain at least one step before sending")
        payload["analyze"] = analyze
        payload["request_id"] = str(uuid.uuid4())
        # Snapshot before background submission; reject NaN and unsupported values.
        try:
            return json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValueError("Run data must contain finite JSON-serializable values") from exc

    def _send_payload(self, payload: Dict[str, Any], *, spool_on_failure: bool = True) -> Dict[str, Any]:
        with self._operation():
            return self._send_with_replay(payload, spool_on_failure=spool_on_failure)

    def _send_with_replay(self, payload: Dict[str, Any], *, spool_on_failure: bool) -> Dict[str, Any]:
        try:
            response = self._object_response(self._request("POST", "/api/ingest", json=payload))
            self._acknowledged(response)
            return response
        except XRayError as exc:
            result: Dict[str, Any] = {"error": str(exc)}
            if isinstance(exc, XRayHTTPError):
                result["status_code"] = exc.status_code
            transient = isinstance(exc, XRayTransportError) or (
                isinstance(exc, XRayHTTPError) and (exc.status_code in self._TRANSIENT_STATUSES or exc.status_code >= 500)
            )
            if transient and spool_on_failure:
                try:
                    path = self._spool_payload(payload)
                except OSError as spool_error:
                    error = XRayError(f"{exc}; local spool failed: {spool_error}")
                    if self.raise_on_error:
                        raise error from spool_error
                    result["error"] = str(error)
                    result["spooled"] = False
                else:
                    exc.spool_path = str(path)
                    result.update(spooled=True, spool_path=str(path), retries_attempted=self.retries)
            if self.raise_on_error:
                raise
            return result

    def send(self, run: XRayRun, analyze: bool = True) -> Dict[str, Any]:
        """Send a snapshot; transient failures are saved for ``flush_spool``."""
        self._check_open()
        return self._send_payload(self._payload(run, analyze))

    def send_async(self, run: XRayRun, analyze: bool = True) -> Future:
        """Return a background Future; raise clearly when the bounded queue is full."""
        payload = self._payload(run, analyze)
        with self._lock:
            self._check_open()
            if not self._slots.acquire(blocking=False):
                raise XRayError("X-Ray background queue is full; wait for a Future or call send()")
            try:
                if self._executor is None:
                    self._executor = ThreadPoolExecutor(max_workers=self._max_workers, thread_name_prefix="xray")
                future = self._executor.submit(self._background_send, payload)
                self._pending.add(future)
                future.add_done_callback(self._completed)
                return future
            except BaseException:
                self._slots.release()
                raise

    def _background_send(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._local.worker = True
        return self._send_payload(payload)

    def _completed(self, future: Future) -> None:
        with self._lock:
            self._pending.discard(future)
        self._slots.release()

    async def asend(self, run: XRayRun, analyze: bool = True) -> Dict[str, Any]:
        """Await a background send without blocking the asyncio event loop."""
        return await asyncio.wrap_future(self.send_async(run, analyze))

    def send_background(
        self, run: XRayRun, analyze: bool = True,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        """Send in the background; log unexpected worker/callback failures."""
        if callback is not None and not callable(callback):
            raise ValueError("callback must be callable")
        future = self.send_async(run, analyze)

        def completed(result: Future) -> None:
            try:
                value = result.result()
                if callback is not None:
                    callback(value)
                elif value.get("error"):
                    logger.warning("X-Ray background send failed: %s", value["error"])
            except Exception:
                logger.exception("X-Ray background send or callback failed")

        future.add_done_callback(completed)

    def flush(self, timeout: Optional[float] = None) -> bool:
        """Wait for currently queued sends; return False if the timeout expires."""
        if timeout is not None:
            self._validate_number("timeout", timeout)
        with self._lock:
            pending = tuple(self._pending)
        return not wait(pending, timeout=timeout).not_done

    def close(self) -> None:
        """Drain sends and release sessions; callback workers defer cleanup safely.

        A callback-worker call initiates cleanup in a separate thread so it cannot
        join itself. Normal calls wait for queued and active synchronous requests.
        Close active streaming iterators before closing the client.
        """
        with self._lock:
            if self._closed:
                return
            if self._closing:
                if not getattr(self._local, "worker", False):
                    while not self._closed:
                        self._lifecycle.wait()
                return
            self._closing = True
            executor = self._executor
        if getattr(self._local, "worker", False):
            threading.Thread(target=self._finish_close, args=(executor,), name="xray-close", daemon=True).start()
        else:
            self._finish_close(executor)

    def _finish_close(self, executor: Optional[ThreadPoolExecutor]) -> None:
        if executor is not None:
            executor.shutdown(wait=True)
        with self._lifecycle:
            while self._active_calls:
                self._lifecycle.wait()
            for session in self._sessions:
                session.close()
            self._sessions.clear()
            self._closed = True
            self._lifecycle.notify_all()

    def __enter__(self) -> "XRayClient":
        self._check_open()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _spool_payload(self, payload: Dict[str, Any], spool_dir: Optional[str] = None) -> Path:
        directory = Path(spool_dir) if spool_dir is not None else self.spool_dir
        directory.mkdir(parents=True, exist_ok=True)
        filepath = directory / f"{time.time_ns()}_{uuid.uuid4().hex}.json"
        self._replace_spool_file(filepath, payload)
        return filepath

    def spool(self, run: XRayRun, spool_dir: Optional[str] = None, *, analyze: bool = True) -> Path:
        """Atomically save a snapshot for replay; files contain captured run data."""
        self._check_open()
        return self._spool_payload(self._payload(run, analyze), spool_dir)

    def flush_spool(self, spool_dir: Optional[str] = None) -> Dict[str, Any]:
        """Replay all files oldest first; delete only acknowledged sends."""
        self._check_open()
        with self._operation():
            return self._flush_spool(spool_dir)

    @staticmethod
    def _acknowledged(response: Dict[str, Any]) -> None:
        if response.get("success") is not True or not isinstance(response.get("run_id"), str) or not response["run_id"]:
            raise XRayResponseError("X-Ray ingestion was not acknowledged; the request was not retried")

    def _flush_spool(self, spool_dir: Optional[str]) -> Dict[str, Any]:
        directory = Path(spool_dir) if spool_dir is not None else self.spool_dir
        results: Dict[str, Any] = {"flushed": 0, "failed": 0, "errors": [], "total_files": 0}
        with self._flush_lock:
            files = sorted(directory.glob("*.json"), key=lambda path: path.stat().st_mtime)
            results["total_files"] = len(files)
            for filepath in files:
                try:
                    with filepath.open(encoding="utf-8") as file:
                        data = json.load(file)
                    if not isinstance(data, dict) or not isinstance(data.get("steps"), list) or not data["steps"]:
                        raise ValueError("Spool file must contain a run object with steps")
                    if "request_id" not in data:
                        # Upgrade old files before network I/O, so later replays reuse the ID.
                        data["request_id"] = str(uuid.uuid4())
                        self._replace_spool_file(filepath, data)
                    response = self._object_response(self._request("POST", "/api/ingest", json=data))
                    self._acknowledged(response)
                    filepath.unlink()
                    results["flushed"] += 1
                except (OSError, ValueError, XRayError) as exc:
                    results["failed"] += 1
                    results["errors"].append({"file": str(filepath), "error": str(exc)})
                    logger.warning("X-Ray spool replay failed for %s: %s", filepath.name, exc)
        return results

    @staticmethod
    def _replace_spool_file(filepath: Path, payload: Dict[str, Any]) -> None:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=filepath.parent, suffix=".tmp", delete=False) as file:
                temporary = Path(file.name)
                json.dump(payload, file, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, filepath)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _get(self, path: str, **params: Any) -> Dict[str, Any]:
        self._check_open()
        with self._operation():
            return self._object_response(self._request("GET", path, params=params or None))

    @staticmethod
    def _pagination(limit: int, offset: int = 0) -> Dict[str, int]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("limit must be an integer between 1 and 200")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        return {"limit": limit, "offset": offset}

    @staticmethod
    def _run_id(run_id: str) -> str:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id must be a non-empty string")
        return quote(run_id, safe="")

    def list_pipelines(self, *, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """List pipelines with pagination."""
        return self._get("/api/pipelines", **self._pagination(limit, offset))

    def list_runs(
        self, pipeline: Optional[str] = None, status: Optional[str] = None,
        limit: int = 50, *, offset: int = 0,
    ) -> Dict[str, Any]:
        """List runs with optional filters and pagination."""
        return self._get("/api/runs", **self._pagination(limit, offset), **{
            key: value for key, value in (("pipeline", pipeline), ("status", status)) if value is not None
        })

    def get_run(self, run_id: str) -> Dict[str, Any]:
        return self._get(f"/api/runs/{self._run_id(run_id)}")

    def get_analysis(self, run_id: str) -> Dict[str, Any]:
        return self._get(f"/api/runs/{self._run_id(run_id)}/analysis")

    def analyze_run(self, run_id: str) -> Dict[str, Any]:
        """Explicitly analyze a run previously stored with analyze=False."""
        self._check_open()
        with self._operation():
            return self._object_response(self._request("POST", f"/api/analyze/{self._run_id(run_id)}", attempts=1))

    def search_steps(
        self, step_name: Optional[str] = None, pipeline: Optional[str] = None,
        limit: int = 50, *, offset: int = 0,
    ) -> Dict[str, Any]:
        return self._get("/api/search/steps", **self._pagination(limit, offset), **{
            key: value for key, value in (("step_name", step_name), ("pipeline", pipeline)) if value is not None
        })

    def stream_analysis(self, run_id: str) -> Iterator[Dict[str, Any]]:
        """Yield parsed SSE events; closing the iterator releases its connection."""
        self._check_open()
        with self._operation():
            yield from self._stream_analysis(run_id)

    def _stream_analysis(self, run_id: str) -> Iterator[Dict[str, Any]]:
        # This GET starts a new analysis; automatic retries could charge twice.
        response = self._request("GET", f"/api/analyze/{self._run_id(run_id)}/stream", stream=True, attempts=1)
        event_type = "message"
        data_buffer = []
        terminal_event = False
        try:
            response.encoding = "utf-8"
            for line in response.iter_lines(decode_unicode=True):
                if line is None:
                    continue
                if isinstance(line, bytes):
                    line = line.decode("utf-8")
                if not line:
                    if data_buffer:
                        try:
                            data = json.loads("\n".join(data_buffer))
                        except ValueError as exc:
                            raise XRayResponseError("X-Ray returned invalid JSON in an SSE event") from exc
                        terminal_event = terminal_event or event_type in {"complete", "error"}
                        yield {"event": event_type, "data": data}
                    event_type, data_buffer = "message", []
                elif line.startswith("event:"):
                    event_type = line[6:].lstrip(" ")
                elif line.startswith("data:"):
                    data_buffer.append(line[5:].lstrip(" "))
            if data_buffer:
                raise XRayResponseError("X-Ray analysis stream ended before the final event separator")
            if not terminal_event:
                raise XRayResponseError("X-Ray analysis stream ended without a complete or error event")
        except requests.RequestException as exc:
            raise XRayTransportError(f"X-Ray analysis stream was interrupted: {exc}") from exc
        finally:
            response.close()
