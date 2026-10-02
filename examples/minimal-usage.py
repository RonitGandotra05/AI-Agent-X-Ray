"""Record a step without provider credentials; configure XRAY_API_URL as needed."""

from xray_sdk import XRayClient, XRayRun, XRayStep


def main():
    run = XRayRun("example", description="Multiply a value by two.")
    run.add_step(XRayStep("multiply", 1, inputs={"value": 2}, outputs={"value": 4}))
    with XRayClient() as client:
        result = client.send(run, analyze=False)
        if result.get("spooled"):
            print("Saved offline:", result["spool_path"])
        elif result.get("error"):
            print("Delivery failed:", result["error"])
        else:
            print("Stored run:", result["run_id"])


if __name__ == "__main__":
    main()
