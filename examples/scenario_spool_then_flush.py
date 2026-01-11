"""Scenario: force spooling (bad port) then flush to real API."""

import os
from xray_sdk import XRayClient, XRayRun, XRayStep


def main() -> None:
    run = XRayRun("scenario_spool_then_flush", metadata={"case": "spool"}, sample_size=20)
    run.add_step(XRayStep(
        name="stage1",
        order=1,
        inputs={"q": "phone case"},
        outputs={"keywords": ["phone case", "iphone 15 case"]},
        description="Generate keywords from the query."
    ))

    # Intentionally point to a bad port to force spooling.
    bad_client = XRayClient("http://localhost:5999", api_key=os.getenv("XRAY_API_KEY"), timeout=2)
    bad_result = bad_client.send(run)
    print({"spool_attempt": bad_result})

    # Then flush using the real API once it is up.
    good_client = XRayClient("http://localhost:5000", api_key=os.getenv("XRAY_API_KEY"))
    flush_result = good_client.flush_spool()
    print({"flush_result": flush_result})


if __name__ == "__main__":
    main()
