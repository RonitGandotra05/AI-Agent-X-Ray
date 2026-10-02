"""Flush all spooled runs to the API."""

from xray_sdk import XRayClient

client = XRayClient()
result = client.flush_spool()
print(result)
client.close()
