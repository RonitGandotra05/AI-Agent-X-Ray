"""
XRayClient - Sends run data to the X-Ray API for analysis
"""

import os
import json
import time
import logging
import requests
from pathlib import Path
from typing import Dict, Any, Optional
from .run import XRayRun

logger = logging.getLogger(__name__)


class XRayClient:
    """
    Client for sending pipeline runs to the X-Ray API.
    
    Features:
    - Sends run data to API for AI-powered analysis
    - Retries with exponential backoff on transient failures
    - Spools to local file if API is unavailable after retries
    - Supports API key authentication
    """
    
    DEFAULT_SPOOL_DIR = ".xray_spool"
    
    def __init__(
        self,
        api_url: str,
        api_key: Optional[str] = None,
        timeout: int = 180,
        retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """
        Initialize the X-Ray client.
        
        Args:
            api_url: Base URL of the X-Ray API (e.g., "http://localhost:5000")
            api_key: Optional API key for authentication
            timeout: Request timeout in seconds (default: 180 for LLM analysis)
            retries: Number of retry attempts before spooling (default: 3)
            retry_delay: Initial delay between retries in seconds, doubles each attempt (default: 1.0)
        """
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.retries = retries
        self.retry_delay = retry_delay
    
    def _headers(self) -> Dict[str, str]:
        """Build headers for API requests."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers
    
    def send(self, run: XRayRun, analyze: bool = True) -> Dict[str, Any]:
        """
        Send a run to the X-Ray API with retry logic.
        
        Retries on connection/timeout errors with exponential backoff.
        Spools locally only after all retries are exhausted.
        4xx errors (bad request, auth) fail immediately — retrying won't help.
        
        Args:
            run: The XRayRun to send
            analyze: Whether to trigger AI analysis (default: True)
            
        Returns:
            API response with run_id and analysis result (if requested)
        """
        payload = run.to_dict()
        payload["analyze"] = analyze
        
        last_error = None
        delay = self.retry_delay
        
        for attempt in range(1, self.retries + 1):
            try:
                response = requests.post(
                    f"{self.api_url}/api/ingest",
                    json=payload,
                    headers=self._headers(),
                    timeout=self.timeout
                )
                response.raise_for_status()
                return response.json()
            except requests.exceptions.HTTPError as e:
                # Don't retry 4xx — it's a client error, retrying won't fix it
                if e.response is not None and 400 <= e.response.status_code < 500:
                    return {"error": str(e), "status_code": e.response.status_code}
                last_error = e
            except requests.exceptions.RequestException as e:
                last_error = e
            
            if attempt < self.retries:
                logger.warning("[xray] send failed (attempt %d/%d), retrying in %.1fs: %s", attempt, self.retries, delay, last_error)
                time.sleep(delay)
                delay *= 2  # Exponential backoff
        
        # All retries exhausted — spool locally
        logger.warning("[xray] all %d retries failed, spooling locally: %s", self.retries, last_error)
        spool_path = self.spool(run)
        return {
            "error": str(last_error),
            "spooled": True,
            "spool_path": str(spool_path),
            "retries_attempted": self.retries
        }
    
    def spool(self, run: XRayRun, spool_dir: Optional[str] = None) -> Path:
        """
        Save run data to local file for later submission.
        
        Args:
            run: The XRayRun to spool
            spool_dir: Directory to save files (default: .xray_spool)
            
        Returns:
            Path to the spooled file
        """
        spool_dir = Path(spool_dir or self.DEFAULT_SPOOL_DIR)
        spool_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate filename with timestamp
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{run.pipeline_name}_{timestamp}.json"
        filepath = spool_dir / filename
        
        with open(filepath, "w") as f:
            json.dump(run.to_dict(), f, indent=2, default=str)
        
        return filepath

    def list_pipelines(self) -> Dict[str, Any]:
        """List all pipelines."""
        response = requests.get(f"{self.api_url}/api/pipelines", headers=self._headers(), timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def list_runs(
        self,
        pipeline: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """List runs with optional filters."""
        params = {"limit": limit}
        if pipeline:
            params["pipeline"] = pipeline
        if status:
            params["status"] = status
        response = requests.get(f"{self.api_url}/api/runs", params=params, headers=self._headers(), timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_run(self, run_id: str) -> Dict[str, Any]:
        """Get a single run with all its steps."""
        response = requests.get(f"{self.api_url}/api/runs/{run_id}", headers=self._headers(), timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_analysis(self, run_id: str) -> Dict[str, Any]:
        """Get analysis result for a run."""
        response = requests.get(f"{self.api_url}/api/runs/{run_id}/analysis", headers=self._headers(), timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def search_steps(
        self,
        step_name: Optional[str] = None,
        pipeline: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Search steps across runs."""
        params = {"limit": limit}
        if step_name:
            params["step_name"] = step_name
        if pipeline:
            params["pipeline"] = pipeline
        response = requests.get(f"{self.api_url}/api/search/steps", params=params, headers=self._headers(), timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def stream_analysis(self, run_id: str):
        """
        Stream analysis results via Server-Sent Events.
        
        Yields window results as they complete instead of waiting for full analysis.
        
        Args:
            run_id: The run ID to analyze
            
        Yields:
            Dict with event type and data for each window/completion
        """
        import json
        
        response = requests.get(
            f"{self.api_url}/api/analyze/{run_id}/stream",
            headers=self._headers(),
            stream=True,
            timeout=self.timeout
        )
        response.raise_for_status()
        
        event_type = None
        data_buffer = []
        
        for line in response.iter_lines(decode_unicode=True):
            if line is None:
                continue
            line = line.strip()
            
            if line.startswith('event:'):
                event_type = line[6:].strip()
            elif line.startswith('data:'):
                data_buffer.append(line[5:].strip())
            elif line == '' and event_type and data_buffer:
                # Empty line signals end of event
                data_str = ''.join(data_buffer)
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    data = {"raw": data_str}
                
                yield {"event": event_type, "data": data}
                
                event_type = None
                data_buffer = []
    
    def flush_spool(self, spool_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Send the newest spooled run to the API and delete all spooled files.
        
        Args:
            spool_dir: Directory containing spooled files
            
        Returns:
            Summary of flush results
        """
        spool_dir = Path(spool_dir or self.DEFAULT_SPOOL_DIR)
        if not spool_dir.exists():
            return {"flushed": 0, "failed": 0}

        files = list(spool_dir.glob("*.json"))
        if not files:
            return {"flushed": 0, "failed": 0}

        newest = max(files, key=lambda p: p.stat().st_mtime)
        results = {"flushed": 0, "failed": 0, "errors": [], "sent_file": str(newest)}

        try:
            with open(newest) as f:
                data = json.load(f)

            response = requests.post(
                f"{self.api_url}/api/ingest",
                json=data,
                headers=self._headers(),
                timeout=self.timeout
            )
            response.raise_for_status()
            response_json = response.json()
            results["flushed"] = 1
            results["response"] = response_json

            # Delete all spooled files after successful send of newest.
            for filepath in files:
                filepath.unlink()
        except Exception as e:
            results["failed"] = 1
            results["errors"].append({"file": str(newest), "error": str(e)})

        return results
