"""Optional framework integrations, imported only when requested."""

__all__ = ["XRayCallbackHandler", "XRayCrewMonitor"]


def __getattr__(name):
    if name == "XRayCallbackHandler":
        from .langchain import XRayCallbackHandler
        return XRayCallbackHandler
    if name == "XRayCrewMonitor":
        from .crewai import XRayCrewMonitor
        return XRayCrewMonitor
    raise AttributeError(f"module 'xray_sdk.integrations' has no attribute {name!r}")
