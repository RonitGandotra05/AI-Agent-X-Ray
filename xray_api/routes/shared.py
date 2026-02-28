"""
Shared XRayAnalyzer singleton — avoids recreating the LLM client per request.
"""

from ..agents.analyzer import XRayAnalyzer

_analyzer_instance = None


def get_analyzer() -> XRayAnalyzer:
    """Return the shared XRayAnalyzer instance (created on first call)."""
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = XRayAnalyzer()
    return _analyzer_instance
