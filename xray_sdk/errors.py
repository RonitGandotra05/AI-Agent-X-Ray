"""Predictable errors raised by the X-Ray client."""

from typing import Optional

import requests


class XRayError(Exception):
    """Base client error; failed sends may also expose ``spool_path``."""

    spool_path: Optional[str] = None


class XRayHTTPError(XRayError, requests.HTTPError):
    """The server returned an unsuccessful HTTP status."""

    def __init__(self, message: str, response: requests.Response):
        super().__init__(message)
        self.response = response
        self.status_code = response.status_code


class XRayTransportError(XRayError, requests.RequestException):
    """A connection or timeout failure exhausted the request attempts."""


class XRayResponseError(XRayError):
    """A successful HTTP response contained invalid JSON or an invalid object."""
