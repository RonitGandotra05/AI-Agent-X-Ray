"""
XRayClient - Sends run data to the X-Ray API for analysis
"""

import os
import json
import requests
from pathlib import Path
from typing import Dict, Any, Optional
from .run import XRayRun


class XRayClient:
    """
    Client for sending pipeline runs to the X-Ray API.
    
    Features:
    - Sends run data to API for AI-powered analysis
    - Spools to local file if API is unavailable
    - Supports API key authentication
    """
    
    DEFAULT_SPOOL_DIR = ".xray_spool"
    
    def __init__(self, api_url: str, api_key: Optional[str] = None, timeout: int = 180):
        """
        Initialize the X-Ray client.
        
        Args:
            api_url: Base URL of the X-Ray API (e.g., "http://localhost:5000")
            api_key: Optional API key for authentication (required if server has XRAY_API_KEY set)
            timeout: Request timeout in seconds (default: 180 for LLM analysis)
        """
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
    
    def _headers(self) -> Dict[str, str]:
        """Build headers for API requests."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers
    
    def send(self, run: XRayRun, analyze: bool = True) -> Dict[str, Any]:
        """
        Send a run to the X-Ray API for storage and optional analysis.
        
        Args:
            run: The XRayRun to send
            analyze: Whether to trigger AI analysis (default: True)
            
        Returns:
            API response with run_id and analysis result (if requested)
            
        Raises:
            requests.exceptions.RequestException: If API call fails
        """
        payload = run.to_dict()
        payload["analyze"] = analyze
        
        try:
            response = requests.post(
                f"{self.api_url}/api/ingest",
                json=payload,
                headers=self._headers(),
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            # Spool locally if API unavailable
            spool_path = self.spool(run)
            return {
                "error": str(e),
                "spooled": True,
                "spool_path": str(spool_path)
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
