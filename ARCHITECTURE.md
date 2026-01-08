# X-Ray SDK and API Architecture

A lightweight debugging system for multi-step AI pipelines that captures execution data and uses AI to identify faulty steps.

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DEVELOPER'S CODE                             │
│   Step 1 → Step 2 → Step 3 → Step 4 → client.send(run)             │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   │ HTTP POST /api/ingest
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          X-RAY API                                   │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │ Flask Routes │───▶│  PostgreSQL  │───▶│ Cerebras AI Analyzer │  │
│  └──────────────┘    └──────────────┘    └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
                        Analysis Result:
                        {faulty_step, reason, suggestion}
```

  **Analysis strategy:** The analyzer always runs in a sliding window of 2 steps. Even when a run has only 1–2 steps, it still uses the same windowed path (single window in that case). There is no full-run mode.

## Data Model

### Entities

| Entity | Purpose | Key Fields |
|--------|---------|------------|
| **Pipeline** | Workflow type (e.g., "competitor_selection") | `id`, `name`, `description` |
| **Run** | Single execution of a pipeline | `id`, `pipeline_id`, `status`, `metadata`, `analysis_result` |
| **Step** | Individual step in a run | `id`, `run_id`, `step_name`, `step_order`, `inputs`, `outputs` |

### Why This Structure?

- **Flexible JSONB**: `inputs` and `outputs` accept any structure, making it domain-agnostic
- **Step ordering**: Essential for tracing data flow and causality
- **Analysis result stored**: Enables querying historical analyses without re-running

### Alternatives Considered

| Alternative | Why Rejected |
|-------------|--------------|
| Separate tables per pipeline type | Not extensible; requires schema changes for each new pipeline |
| Storing all steps as array in Run | Harder to query individual steps across runs |
| Typed step schemas | Too rigid; prevents SDK from being truly general-purpose |

---

## API Specification

### Ingest Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ingest` | POST | Receive run data, store, trigger analysis |

**Request:**
```json
{
  "pipeline_name": "competitor_selection",
  "metadata": {"product_id": "123"},
  "steps": [
    {"name": "keyword_gen", "order": 1, "inputs": {...}, "outputs": {...}},
    {"name": "search", "order": 2, "inputs": {...}, "outputs": {...}}
  ],
  "analyze": true
}
```

**Response:**
```json
{
  "success": true,
  "run_id": "uuid",
  "status": "analyzed",
  "analysis": {
    "faulty_step": "keyword_gen",
    "faulty_step_order": 1,
    "reason": "Generated unrelated keywords",
    "suggestion": "Constrain to product category"
  }
}
```


## Performance & Scale

### Large Data Handling

For steps with 5000 candidates:

| Approach | Trade-off |
|----------|-----------|
| **Full capture** | Complete but expensive |
| **Random sample (30 items)** | Loses detail but fits in context |
| **Summary stats** | Counts + sample + distribution |

**Our solution:** SDK auto-summarizes if output > 20K chars (to stay under Cerebras 65K token limit):
```python
# Original: 5000 candidates
# Stored: 100 random samples + total count
outputs = {
    "candidates": [100 random items],
    "candidates_total_count": 5000
}
```

**Decision maker:** The developer controls what gets captured. SDK provides auto-summarization as guardrail.

---

## Developer Experience

### Minimal Instrumentation

```python
from xray_sdk import XRayClient, XRayRun, XRayStep

run = XRayRun("my_pipeline")
run.add_step(XRayStep("step1", 1, inputs={...}, outputs={...}))

client = XRayClient("http://localhost:5000")
result = client.send(run)
```

### Full Instrumentation

Add to each step:
- Detailed inputs/outputs
- Reasoning (if LLM step)
- Metrics (latency, counts) in outputs

### Backend Unavailable

SDK automatically spools to `.xray_spool/` directory. Later:
```python
client.flush_spool()  # Sends all spooled runs
```

---

## Real-World Application

In a previous project, I built a **product recommendation system** with 5 stages:
1. User profile analysis
2. Candidate retrieval
3. Feature extraction
4. ML scoring
5. Reranking

Debugging was painful—when recommendations were wrong, we logged everything but couldn't trace *why* the model preferred item A over B. X-Ray would have:
- Captured scoring inputs/outputs at each stage
- Identified if the user profile was wrong, or candidates were bad, or reranking flipped good results

---

## What's Next for Production

1. **Async analysis:** Queue analysis jobs for long-running pipelines
2. **Retention policies:** Auto-delete old runs after N days
3. **Streaming ingest:** For real-time pipelines, stream steps individually
4. **Dashboard:** Visual timeline of steps with status indicators
5. **Alerting:** Notify when faulty steps exceed threshold
6. **Sampling strategies:** More sophisticated than random 30 (stratified, by category, etc.)

---

## Project Structure

```
xray_sdk/
├── __init__.py      # Exports XRayStep, XRayRun, XRayClient
├── step.py          # Step dataclass
├── run.py           # Run with auto-summarization
└── client.py        # HTTP client with spool fallback

xray_api/
├── app.py           # Flask entry point
├── models.py        # SQLAlchemy models
├── routes/
│   ├── ingest.py    # POST /api/ingest
└── agents/
    └── analyzer.py  # Cerebras AI analysis
```
