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

### Analysis Strategy

The analyzer uses a **sliding-window** approach:
- Analyzes **2 consecutive steps at a time**
- Each LLM call stays within the **65K token context limit**
- Examines data flow between steps to detect mismatches
- Stops early when a faulty step is identified
- Step descriptions are included in prompts to guide intent

---

## Data Model

### Entities

| Entity | Purpose | Key Fields |
|--------|---------|------------|
| **Pipeline** | Workflow type (e.g., "competitor_selection") | `id`, `name`, `description`, `created_at` |
| **Run** | Single execution of a pipeline | `id`, `pipeline_id`, `status`, `run_metadata`, `analysis_result`, `created_at` |
| **Step** | Individual step in a run | `id`, `run_id`, `step_name`, `step_order`, `step_description`, `inputs`, `outputs`, `created_at` |

### Run Status Values

| Status | Description |
|--------|-------------|
| `pending` | Initial state |
| `received` | Data received, analysis not yet started |
| `stored` | Data stored, analysis skipped (`analyze=false`) |
| `analyzed` | AI analysis completed successfully |
| `analysis_failed` | AI analysis failed (error stored in `analysis_result`) |

### Why This Structure?

- **Flexible JSONB**: `inputs` and `outputs` accept any structure, making it domain-agnostic
- **Step ordering**: Essential for tracing data flow and causality
- **Analysis result stored**: Enables querying historical analyses without re-running

---

## API Specification

### Base URL

```
http://localhost:5000
```

### Health Check

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Returns `{"status": "healthy"}` |

---

### Ingest Endpoints

#### POST `/api/ingest`

Receive pipeline run data, store it, and optionally trigger AI analysis.

**Request Body:**
```json
{
  "pipeline_name": "competitor_selection",
  "metadata": {"product_id": "123", "user_id": "456"},
  "steps": [
    {
      "name": "keyword_gen",
      "order": 1,
      "description": "Generate keywords from the product title",
      "inputs": {"title": "Wireless Bluetooth Headphones"},
      "outputs": {"keywords": ["wireless", "bluetooth", "headphones"]}
    },
    {
      "name": "search",
      "order": 2,
      "description": "Search inventory using the keywords",
      "inputs": {"keywords": ["wireless", "bluetooth", "headphones"]},
      "outputs": {"candidates": [...], "candidates_count": 500}
    },
    {
      "name": "filter",
      "order": 3,
      "description": "Filter candidates by rating",
      "inputs": {"candidates_count": 500, "min_rating": 4.0},
      "outputs": {"filtered_count": 50}
    }
  ],
  "analyze": true
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `pipeline_name` | string | ✅ | - | Name of the pipeline |
| `metadata` | object | ❌ | `{}` | Arbitrary metadata about this run |
| `steps` | array | ✅ | - | List of step objects |
| `steps[].name` | string | ✅ | - | Step identifier |
| `steps[].order` | integer | ✅ | - | Step sequence number (1, 2, 3, ...) |
| `steps[].description` | string | ❌ | `null` | One-line summary of step intent |
| `steps[].inputs` | object | ❌ | `{}` | What was fed to this step |
| `steps[].outputs` | object | ❌ | `{}` | What this step produced |
| `analyze` | boolean | ❌ | `true` | Whether to trigger AI analysis |

**Response (201 Created):**
```json
{
  "success": true,
  "run_id": "2de68150-8c39-453e-a54c-8b8d18437fa1",
  "status": "analyzed",
  "analysis": {
    "faulty_step": "filter",
    "faulty_step_order": 3,
    "reason": "Step 3 expects candidates but Step 2 only passed count",
    "suggestion": "",
    "analysis_method": "sliding_window",
    "windows_analyzed": 2
  }
}
```

---

### Query Endpoints

#### GET `/api/pipelines`

List all registered pipelines.

**Response:**
```json
{
  "pipelines": [
    {"id": "uuid", "name": "competitor_selection", "description": null, "created_at": "2026-01-09T10:00:00"}
  ]
}
```

---

#### GET `/api/runs`

List pipeline runs with optional filters.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `pipeline` | string | Filter by pipeline name |
| `status` | string | Filter by status |
| `limit` | integer | Max results (default: 50) |

**Response:**
```json
{
  "runs": [
    {
      "id": "uuid",
      "pipeline_id": "uuid",
      "pipeline_name": "competitor_selection",
      "status": "analyzed",
      "metadata": {"product_id": "123"},
      "analysis_result": {...},
      "created_at": "2026-01-09T10:00:00"
    }
  ]
}
```

---

#### GET `/api/runs/<run_id>`

Get a single run with all its steps.

**Response:**
```json
{
  "id": "uuid",
  "pipeline_id": "uuid",
  "pipeline_name": "competitor_selection",
  "status": "analyzed",
  "metadata": {...},
  "analysis_result": {...},
  "created_at": "2026-01-09T10:00:00",
  "steps": [
    {
      "id": "uuid",
      "run_id": "uuid",
      "step_name": "keyword_gen",
      "step_order": 1,
      "step_description": "Generate keywords from the product title",
      "inputs": {...},
      "outputs": {...},
      "created_at": "2026-01-09T10:00:00"
    }
  ]
}
```

---

#### GET `/api/runs/<run_id>/analysis`

Get only the analysis result for a run.

**Response:**
```json
{
  "run_id": "uuid",
  "status": "analyzed",
  "analysis": {
    "faulty_step": "filter",
    "faulty_step_order": 3,
    "reason": "...",
    "suggestion": "...",
    "analysis_method": "sliding_window",
    "windows_analyzed": 2
  }
}
```

---

#### POST `/api/analyze/<run_id>`

Trigger (re-)analysis for an existing run.

**Response:**
```json
{
  "success": true,
  "run_id": "uuid",
  "analysis": {...}
}
```

---

#### GET `/api/search/steps`

Search steps across all runs.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `step_name` | string | Filter by step name (partial match) |
| `pipeline` | string | Filter by pipeline name |
| `limit` | integer | Max results (default: 50) |

**Response:**
```json
{
  "steps": [
    {
      "id": "uuid",
      "run_id": "uuid",
      "step_name": "filter",
      "step_order": 3,
      "step_description": "Filter candidates by rating",
      "inputs": {...},
      "outputs": {...},
      "created_at": "2026-01-09T10:00:00"
    }
  ]
}
```

---

## SDK Usage

### Installation

```bash
pip install flask flask-sqlalchemy flask-cors psycopg2-binary openai python-dotenv requests
```

### Minimal Example

```python
from xray_sdk import XRayClient, XRayRun, XRayStep

# Create a run
run = XRayRun("my_pipeline", metadata={"user": "test"})

# Add steps after your pipeline executes
run.add_step(XRayStep(
    name="step1",
    order=1,
    inputs={"query": "wireless headphones"},
    outputs={"results": [...]},
    description="Search for products"
))

run.add_step(XRayStep(
    name="step2",
    order=2,
    inputs={"results": [...]},
    outputs={"filtered": [...]},
    description="Filter by rating"
))

# Send for analysis
client = XRayClient("http://localhost:5000")
result = client.send(run)

print(result["analysis"])
```

### XRayStep Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | ✅ | Step identifier |
| `order` | int | ✅ | Step sequence number |
| `inputs` | dict | ❌ | Input data |
| `outputs` | dict | ❌ | Output data |
| `description` | string | ❌ | One-line intent summary |
| `reasons` | dict | ❌ | Optional rejection/drop reasons |
| `metrics` | dict | ❌ | Optional step-level metrics |

### XRayRun Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `pipeline_name` | - | Required. Pipeline identifier |
| `metadata` | `{}` | Arbitrary run metadata |
| `sample_size` | `100` | Override for summarization sample size |

### XRayClient Methods

| Method | Description |
|--------|-------------|
| `send(run, analyze=True)` | Send run to API; spools locally if unavailable |
| `spool(run)` | Manually save run to `.xray_spool/` |
| `flush_spool()` | Send newest spooled run and delete all spool files |
| `list_pipelines()` | List all pipelines |
| `list_runs(pipeline, status, limit)` | List runs with filters |
| `get_run(run_id)` | Get run with steps |
| `get_analysis(run_id)` | Get analysis only |
| `search_steps(step_name, pipeline, limit)` | Search steps |

---

## Performance & Scale

### Large Data Handling

The SDK auto-summarizes if output > **20K chars** to stay under the Cerebras 65K token limit.

| Approach | Trade-off |
|----------|-----------|
| **Full capture** | Complete but expensive |
| **Deterministic sample (head/tail)** | Loses detail but fits in context |

**Summarization example:**
```python
# Original: 5000 candidates
# Stored: deterministic head/tail sample + total count
outputs = {
    "candidates": [50 head items + 50 tail items],
    "candidates_total_count": 5000
}
```

Both SDK and API apply summarization as a safety net.

---

## Environment Variables

### API Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///xray.db` | PostgreSQL or SQLite connection string |
| `CEREBRAS_API_KEY` | - | **Required.** Cerebras API key |
| `CEREBRAS_BASE_URL` | `https://api.cerebras.ai/v1` | Cerebras API base URL |
| `CEREBRAS_MODEL` | `llama-3.3-70b` | Model to use for analysis |
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
│   │   ├── __init__.py
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

---

## What's Next for Production

1. **Async analysis:** Queue analysis jobs for long-running pipelines
2. **Retention policies:** Auto-delete old runs after N days
3. **Streaming ingest:** For real-time pipelines, stream steps individually
4. **Dashboard:** Visual timeline of steps with status indicators
5. **Alerting:** Notify when faulty steps exceed threshold
6. **Sampling strategies:** More sophisticated than simple head/tail (stratified, by category, etc.)
