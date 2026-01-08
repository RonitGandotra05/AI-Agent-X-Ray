from xray_sdk import XRayClient

client = XRayClient("http://localhost:5000")
result = client.flush_spool()
print(result)
