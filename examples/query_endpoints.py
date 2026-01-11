"""Scenario: call GET endpoints via SDK helpers."""

import os
from xray_sdk import XRayClient


def main() -> None:
    client = XRayClient("http://localhost:5000", api_key=os.getenv("XRAY_API_KEY"))

    pipelines = client.list_pipelines()
    print({"pipelines": pipelines})

    runs = client.list_runs(limit=5)
    print({"runs": runs})

    run_id = None
    for item in runs.get("runs", []):
        run_id = item.get("id")
        if run_id:
            break

    if not run_id:
        print({"error": "no runs found"})
        return

    run_detail = client.get_run(run_id)
    print({"run_detail": run_detail})

    analysis = client.get_analysis(run_id)
    print({"analysis": analysis})

    steps = client.search_steps(limit=5)
    print({"steps": steps})


if __name__ == "__main__":
    main()
