"""Scenario: call GET endpoints via SDK helpers."""

from xray_sdk import XRayClient

def main() -> None:
    client = XRayClient()

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
        client.close()
        return

    run_detail = client.get_run(run_id)
    print({"run_detail": run_detail})

    analysis = client.get_analysis(run_id)
    print({"analysis": analysis})

    steps = client.search_steps(limit=5)
    print({"steps": steps})

    client.close()

if __name__ == "__main__":
    main()
