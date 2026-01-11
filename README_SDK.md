# X-Ray SDK (PyPI)

Install:
```bash
python3 -m pip install xray-sdk
```

Configure env (example):
```bash
export XRAY_API_URL=https://ai-agent-x-ray.onrender.com
export XRAY_API_KEY=your-xray-api-key
```
Or create a `.env` with those keys and the examples will load it via `load_dotenv()`.

Basic use:
```python
import os
from xray_sdk import XRayClient, XRayRun, XRayStep

client = XRayClient(
    os.getenv("XRAY_API_URL", "https://ai-agent-x-ray.onrender.com"),
    api_key=os.getenv("XRAY_API_KEY"),
)

run = XRayRun(
    pipeline_name="my_pipeline",
    description="Demo pipeline for keyword generation and search.",
    metadata={"ctx": "demo"},
    sample_size=20,
)

run.add_step(XRayStep(
    name="stage1",
    order=1,
    description="Generate search keywords from the user query.",
    inputs={
        "query": "phone case",
        "filters": {"min_rating": 4.0},
        "llm_prompt": "Generate 5 search keywords for the product query.",
    },
    outputs={
        "keywords": ["phone case", "iphone 15 case"],
        "candidates_count": 3,
    },
    reasons={
        "dropped_items": [
            {"id": "B002", "reason": "too expensive"},
        ]
    },
    metrics={
        "latency_ms": 120,
        "elimination_rate": 0.33,
        "model": "gpt-4o-mini",
        "temperature": 0.2,
        "prompt_tokens": 42,
    },
))

result = client.send(run)
print(result)
```

Client methods:
- `send(run, analyze=True)` → POST `/api/ingest`
- `spool(run, spool_dir=".xray_spool")` → save locally if API unavailable
- `flush_spool(spool_dir=".xray_spool")` → replay newest spooled run
- `list_pipelines()` → GET `/api/pipelines`
- `list_runs(pipeline=None, status=None, limit=50)` → GET `/api/runs`
- `get_run(run_id)` → GET `/api/runs/<id>`
- `get_analysis(run_id)` → GET `/api/runs/<id>/analysis`
- `search_steps(step_name=None, pipeline=None, limit=50)` → GET `/api/search/steps`
