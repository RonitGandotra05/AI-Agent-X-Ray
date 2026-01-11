"""Scenario: happy-path flow with config inputs, reasons, metrics."""

import os
from xray_sdk import XRayClient, XRayRun, XRayStep


def main() -> None:
    run = XRayRun("scenario_basic_ok", metadata={"case": "ok"}, sample_size=20)
    run.add_step(XRayStep(
        name="keyword_generation",
        order=1,
        inputs={"product_title": "Premium Phone Case for iPhone 15"},
        outputs={"keywords": ["phone case", "iphone 15 case", "protective case"]},
        description="Generate search keywords from the product title."
    ))
    run.add_step(XRayStep(
        name="search",
        order=2,
        inputs={"keywords": ["phone case", "iphone 15 case", "protective case"]},
        outputs={"candidates_count": 3, "candidates": ["B001", "B002", "B003"]},
        description="Search the catalog for items matching the keywords.",
        metrics={"candidates_returned": 3}
    ))
    run.add_step(XRayStep(
        name="filter",
        order=3,
        inputs={"candidates": ["B001", "B002", "B003"], "filters": {"min_rating": 4.0}},
        outputs={"filtered_count": 2, "filtered_sample": ["B001", "B003"]},
        description="Filter candidates by rating.",
        reasons={"dropped_items": [{"id": "B002", "reason": "rating too low"}]},
        metrics={"elimination_rate": 0.33}
    ))

    client = XRayClient("http://localhost:5000", api_key=os.getenv("XRAY_API_KEY"))
    result = client.send(run)
    print(result)


if __name__ == "__main__":
    main()
