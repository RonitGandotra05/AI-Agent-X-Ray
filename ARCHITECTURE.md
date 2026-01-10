# X-Ray SDK and API Architecture

A lightweight debugging system for multi-step AI pipelines that captures execution data and uses AI to identify faulty steps.

---

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

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Language** | Python 3.9+ | Core language for SDK and API |
| **Web Framework** | Flask | REST API server |
| **Database** | PostgreSQL (or SQLite) | Stores pipelines, runs, and steps |
| **ORM** | SQLAlchemy + Flask-SQLAlchemy | Database models and queries |
| **LLM Provider** | Cerebras API | AI-powered analysis (gpt-oss-120b) |

---

## SDK Usage Flow

This section explains how to use the SDK from start to finish.

### Step 1: Create a Pipeline Run

Use `XRayRun` to create a container for your pipeline execution:

```python
from xray_sdk import XRayRun

run = XRayRun(
    pipeline_name="competitor_selection",           # Required
    description="E-commerce pipeline for finding competitors",  # Optional
    metadata={"product_id": "ASIN123", "user": "test"},         # Optional
    sample_size=100                                  # Optional (default: 100)
)
```

#### XRayRun Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `pipeline_name` | str | ✅ | - | Identifier for the pipeline type |
| `description` | str | ❌ | `""` | Describes what the pipeline does (helps AI understand context) |
| `metadata` | dict | ❌ | `{}` | Arbitrary metadata about this run |
| `sample_size` | int | ❌ | `100` | Max items to keep when summarizing large lists |

---

### Step 2: Add Steps After Each Execution

After each step in your pipeline runs, call `run.add_step()` to capture its data:

```python
from xray_sdk import XRayStep

# After your keyword generation step runs:
run.add_step(XRayStep(
    name="keyword_generation",
    order=1,
    description="LLM step - generates search keywords from product title",
    inputs={"product_title": "iPhone 15 Case", "category": "Phone Accessories"},
    outputs={"keywords": ["iphone case", "phone case", "protective case"]},
    reasons={},      # Optional: why items were dropped
    metrics={}       # Optional: step-level metrics
))

# After your search step runs:
run.add_step(XRayStep(
    name="search",
    order=2,
    description="API call - searches catalog using keywords",
    inputs={"keywords": ["iphone case", "phone case"]},
    outputs={"candidates": [...], "candidates_count": 500}
))

# After your filter step runs:
run.add_step(XRayStep(
    name="filter",
    order=3,
    description="Filters candidates by rating and price",
    inputs={"min_rating": 4.5, "max_price": 50},
    outputs={"filtered_count": 45},
    reasons={"dropped_items": [{"id": "B001", "reason": "rating too low"}]},
    metrics={"elimination_rate": 0.91}
))
```

#### XRayStep Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | str | ✅ | - | Step identifier (e.g., "filter", "search") |
| `order` | int | ✅ | - | Step sequence number (1, 2, 3, ...) |
| `description` | str | ❌ | `""` | What this step does (helps AI understand intent) |
| `inputs` | dict | ❌ | `{}` | Data fed into this step |
| `outputs` | dict | ❌ | `{}` | Data produced by this step |
| `reasons` | dict | ❌ | `{}` | Why items were dropped/rejected |
| `metrics` | dict | ❌ | `{}` | Step-level performance metrics |

> **Note:** Large `inputs` and `outputs` (>80K chars) are automatically summarized using head/tail sampling to fit within the LLM's 65K token context window.

---

### Step 3: Send for Analysis

Use `XRayClient` to send the run to the API:

```python
from xray_sdk import XRayClient

client = XRayClient("http://localhost:5000")
result = client.send(run)

print(result["analysis"])
# {
#   "faulty_step": "keyword_generation",
#   "faulty_step_order": 1,
#   "reason": "Generated irrelevant keyword 'laptop cover' causing wrong results",
#   "analysis_method": "sliding_window",
#   "windows_analyzed": 2
# }
```

---

## SDK Methods → API Endpoints

| SDK Method | HTTP Call | Description |
|------------|-----------|-------------|
| `client.send(run)` | `POST /api/ingest` | Send run data, trigger analysis |
| `client.send(run, analyze=False)` | `POST /api/ingest` | Store only, skip analysis |
| `client.spool(run)` | *(local file)* | Save to `.xray_spool/` for later |
| `client.flush_spool()` | `POST /api/ingest` | Send newest spooled run |
| `client.list_pipelines()` | `GET /api/pipelines` | List all pipelines |
| `client.list_runs(...)` | `GET /api/runs` | List runs with filters |
| `client.get_run(run_id)` | `GET /api/runs/<id>` | Get run with all steps |
| `client.get_analysis(run_id)` | `GET /api/runs/<id>/analysis` | Get analysis only |
| `client.search_steps(...)` | `GET /api/search/steps` | Search steps across runs |

---

## Fallback Behavior (Offline Mode)

When the API is unavailable, the SDK gracefully degrades:

```
┌─────────────────────────────────────────────────────────────────────┐
│                     client.send(run)                                │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ API Available?  │
                    └─────────────────┘
                      │           │
                     YES          NO
                      │           │
                      ▼           ▼
              ┌───────────┐  ┌────────────────────────┐
              │ POST to   │  │ Save to .xray_spool/   │
              │ /api/ingest│  │ pipeline_timestamp.json│
              └───────────┘  └────────────────────────┘
                      │           │
                      ▼           ▼
              ┌───────────┐  ┌────────────────────────┐
              │ Return    │  │ Return:                │
              │ analysis  │  │ {spooled: true,        │
              │ result    │  │  spool_path: "..."}    │
              └───────────┘  └────────────────────────┘
```

**To flush spooled data later:**
```python
result = client.flush_spool()
# Sends the newest spooled run and deletes all spool files
```

---

## Data Model

### Entities

| Entity | Purpose | Key Fields |
|--------|---------|------------|
| **Pipeline** | Workflow type (e.g., "competitor_selection") | `id`, `name`, `description`, `created_at` |
| **Run** | Single execution of a pipeline | `id`, `pipeline_id`, `status`, `run_metadata`, `analysis_result`, `created_at` |
| **Step** | Individual step in a run | `id`, `run_id`, `step_name`, `step_order`, `step_description`, `inputs`, `outputs`, `reasons`, `metrics`, `created_at` |

### Run Status Values

| Status | Description |
|--------|-------------|
| `received` | Data received, analysis starting |
| `stored` | Data stored, analysis skipped (`analyze=false`) |
| `analyzed` | AI analysis completed successfully |
| `analysis_failed` | AI analysis failed (error in `analysis_result`) |

---

## Analysis Approach

### Sliding Window Strategy

The analyzer uses a **sliding-window** approach to stay within the LLM's 65K token context limit:

```
Pipeline: Step1 → Step2 → Step3 → Step4

Window 1: [Step1, Step2] → LLM analyzes transition
Window 2: [Step2, Step3] → LLM analyzes transition
Window 3: [Step3, Step4] → LLM analyzes transition
```

- Analyzes **2 consecutive steps at a time**
- Stops early when a faulty step is identified
- Each step can have up to **80K chars** (~20K tokens)
- 2 steps + overhead = ~45K tokens, safely under 65K limit

### Summarization

When data exceeds 80K chars, it's automatically summarized:

```python
# Original: 3000 candidates (~1.6M chars)
# After summarization: 50 head + 50 tail items (~27K chars)

outputs = {
    "candidates": [first 50 items, ..., last 50 items],
    "candidates_total_count": 3000
}
```

Both SDK and API apply summarization as a safety net.

---

## API Endpoints Reference

### Ingest

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/ingest` | Store run and optionally trigger analysis |
| POST | `/api/analyze/<run_id>` | Re-trigger analysis for existing run |

### Query

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/pipelines` | List all pipelines |
| GET | `/api/runs` | List runs (filter by `pipeline`, `status`, `limit`) |
| GET | `/api/runs/<id>` | Get run with all steps |
| GET | `/api/runs/<id>/analysis` | Get analysis result only |
| GET | `/api/search/steps` | Search steps (filter by `step_name`, `pipeline`, `limit`) |
| GET | `/health` | Health check |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///xray.db` | PostgreSQL or SQLite connection |
| `CEREBRAS_API_KEY` | - | **Required.** Cerebras API key |
| `CEREBRAS_BASE_URL` | `https://api.cerebras.ai/v1` | Cerebras API endpoint |
| `CEREBRAS_MODEL` | `llama-3.3-70b` | Model for analysis |
| `XRAY_LOG_THINKING` | `true` | Log analyzer debug output |

---

## Project Structure

```
├── xray_sdk/              # Python SDK
│   ├── __init__.py        # Exports XRayStep, XRayRun, XRayClient
│   ├── step.py            # XRayStep dataclass
│   ├── run.py             # XRayRun with auto-summarization
│   └── client.py          # HTTP client with spool fallback
│
├── xray_api/              # Flask API
│   ├── app.py             # Flask entry point & /health endpoint
│   ├── models.py          # SQLAlchemy models (Pipeline, Run, Step)
│   ├── routes/
│   │   ├── ingest.py      # POST /api/ingest
│   │   └── query.py       # GET/POST query endpoints
│   └── agents/
│       └── analyzer.py    # Cerebras AI sliding-window analysis
│
├── examples/              # Example scripts
├── requirements.txt       # Dependencies
├── ARCHITECTURE.md        # This file
└── README.md              # Quick start guide
```
