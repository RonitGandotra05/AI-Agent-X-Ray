"""Flush all spooled runs to the API."""

import os
from xray_sdk import XRayClient

client = XRayClient("http://localhost:5000", api_key=os.getenv("XRAY_API_KEY"))
result = client.flush_spool()
print(result)
