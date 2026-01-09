"""Scenario: large outputs to exercise summarization + config inputs."""

from xray_sdk import XRayClient, XRayRun, XRayStep


def main() -> None:
    run = XRayRun("scenario_large_payload", metadata={"case": "large_payload"}, sample_size=20)
    candidates = [
        {"id": f"B{i:04d}", "title": f"Phone Case {i}", "rating": 4.0 + (i % 10) / 10}
        for i in range(1, 201)
    ]

    run.add_step(XRayStep(
        name="search",
        order=1,
        inputs={"keywords": ["phone case", "iphone 15 case"]},
        outputs={"candidates": candidates},
        description="Search the catalog and return candidate items."
    ))
    run.add_step(XRayStep(
        name="filter",
        order=2,
        inputs={"min_rating": 4.5},
        outputs={"filtered_count": 120, "filtered_sample": ["B0001", "B0002"]},
        description="Filter candidates by minimum rating.",
        metrics={"elimination_rate": 0.4}
    ))

    client = XRayClient("http://localhost:5000")
    result = client.send(run)
    print(result)


if __name__ == "__main__":
    main()
