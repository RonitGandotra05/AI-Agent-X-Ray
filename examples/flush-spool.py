"""Flush all spooled runs to the API."""

from dotenv import load_dotenv

import os
from xray_sdk import XRayClient

load_dotenv()

client = XRayClient("https://ai-agent-x-ray.onrender.com", api_key=os.getenv("XRAY_API_KEY"))
result = client.flush_spool()
print(result)
