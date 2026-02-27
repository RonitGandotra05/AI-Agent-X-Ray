"""
X-Ray SDK - Lightweight debugging for multi-step AI pipelines
"""

from .step import XRayStep
from .run import XRayRun
from .client import XRayClient

__all__ = ["XRayStep", "XRayRun", "XRayClient"]
__version__ = "0.2.0"


# Lazy imports for optional integrations (don't require langchain/crewai)
def __getattr__(name):
    if name == "XRayCallbackHandler":
        from .integrations.langchain import XRayCallbackHandler
        return XRayCallbackHandler
    if name == "XRayCrewMonitor":
        from .integrations.crewai import XRayCrewMonitor
        return XRayCrewMonitor
    raise AttributeError(f"module 'xray_sdk' has no attribute {name!r}")

