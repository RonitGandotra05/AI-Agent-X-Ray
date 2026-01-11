"""Scenario: intentional mismatch (wrong keywords → wrong candidates)."""

import os
from xray_sdk import XRayClient, XRayRun, XRayStep


def main() -> None:
    run = XRayRun("scenario_mismatch", metadata={"case": "mismatch"}, sample_size=20)
    run.add_step(XRayStep(
        name="keyword_generation",
        order=1,
        inputs={"product_title": "Premium Phone Case for iPhone 15"},
        outputs={"keywords": ["phone case", "iphone 15 case"]},
        description="Generate search keywords from the product title."
    ))
    run.add_step(XRayStep(
        name="search",
        order=2,
        inputs={"keywords": ["laptop sleeve", "laptop cover"]},
        outputs={"candidates_count": 2, "candidates": ["L001", "L002"]},
        description="Search using the keywords provided."
    ))
    run.add_step(XRayStep(
        name="rank",
        order=3,
        inputs={"candidates": ["L001", "L002"], "criteria": {"category": "phone case"}},
        outputs={"selected": ["L002"]},
        description="Rank candidates by relevance to the target category."
    ))

    client = XRayClient("http://localhost:5000", api_key=os.getenv("XRAY_API_KEY"))
    result = client.send(run)
    print(result)


if __name__ == "__main__":
    main()
