# X-Ray SDK and API

A lightweight debugging system for multi-step AI pipelines that captures execution data and uses AI to identify faulty steps.

## Quick Start

### 1. Install Dependencies

```bash
pip3 install flask flask-sqlalchemy flask-cors psycopg2-binary openai python-dotenv requests
```

### 2. Configure Environment

Create a `.env` file:
```env
DATABASE_URL=postgresql://user:pass@host/dbname
CEREBRAS_API_KEY=your-api-key
CEREBRAS_BASE_URL=https://api.cerebras.ai/v1
CEREBRAS_MODEL=llama3.1-8b
```

### 3. Initialize Database

```bash
python3 -c "
from dotenv import load_dotenv
load_dotenv()
from xray_api.app import create_app
from xray_api.models import db

app = create_app()
with app.app_context():
    db.create_all()
    print('Database tables created!')
"
```

### 4. Start the API Server

```bash
python3 -m xray_api.app
```

### 5. Run Example

```bash
python3 examples/amazon_competitor.py
```

## Install SDK from PyPI

```bash
python3 -m pip install xray-sdk
```

Configure environment:
```bash
export XRAY_API_URL=https://ai-agent-x-ray.onrender.com
export XRAY_API_KEY=your-xray-api-key
```

Basic usage:
```python
import os
from xray_sdk import XRayClient, XRayRun, XRayStep

client = XRayClient(
    os.getenv("XRAY_API_URL", "https://ai-agent-x-ray.onrender.com"),
    api_key=os.getenv("XRAY_API_KEY"),
)

run = XRayRun("my_pipeline", metadata={"context": "test"}, sample_size=50)
run.add_step(XRayStep(
    name="keyword_generation",
    order=1,
    inputs={"title": "Phone Case"},
    outputs={"keywords": ["phone case", "iphone"]},
    description="Generate search keywords from the title."
))

result = client.send(run)
print(result.get("analysis"))
```

## SDK Usage

```python
from xray_sdk import XRayClient, XRayRun, XRayStep

# Create a run
run = XRayRun("my_pipeline", metadata={"context": "test"}, sample_size=50)

# Add steps (after your pipeline executes)
run.add_step(XRayStep(
    name="keyword_generation",
    order=1,
    inputs={"title": "Phone Case"},
    outputs={"keywords": ["phone case", "iphone"]},
    description="Generate search keywords from the title."# explain what this step does
))

run.add_step(XRayStep(
    name="search",
    order=2,
    inputs={"keywords": ["phone case", "iphone"]},
    outputs={"candidates_count": 100},
    description="Search the catalog for items matching the keywords."
))

run.add_step(XRayStep(
    name="filter",
    order=3,
    inputs={"candidates_count": 100},
    outputs={"filtered_count": 5},
    description="Filter candidates by rating.",
    reasons={"dropped_items": [{"id": 123, "reason": "low rating"}]},
    metrics={"elimination_rate": 0.95}
))

# Send for analysis
client = XRayClient("http://localhost:5000")
result = client.send(run)

print(result["analysis"])
# {
#   "faulty_step": "keyword_generation",
#   "reason": "...",
#   "suggestion": "..."
# }
```

## SDK Client Methods

| Method | Description |
|--------|-------------|
| `send(run, analyze=True)` | Send run to API; spools locally if unavailable |
| `spool(run)` | Manually save run to `.xray_spool/` |
| `flush_spool()` | Send newest spooled run and delete all spool files |
| `list_pipelines()` | List all pipelines |
| `list_runs(pipeline, status, limit)` | List runs with filters |
| `get_run(run_id)` | Get run with all steps |
| `get_analysis(run_id)` | Get analysis result only |
| `search_steps(step_name, pipeline, limit)` | Search steps across runs |

## API Endpoints

POST
- `/api/ingest`: Store a run and, by default, trigger analysis (`analyze=false` to skip)
- `/api/analyze/<id>`: Re-trigger analysis for an existing run

GET
- `/api/runs`: List runs (filter by pipeline/status)
- `/api/runs/<id>`: Get a run with all steps
- `/api/runs/<id>/analysis`: Get analysis only for a run
- `/api/pipelines`: List pipelines
- `/api/search/steps`: Search steps by name/pipeline
- `/health`: Health check

## Project Structure

```
├── xray_sdk/          # Python SDK
│   ├── step.py        # XRayStep dataclass
│   ├── run.py         # XRayRun with auto-summarization
│   └── client.py      # HTTP client with spool fallback
├── xray_api/          # Flask API
│   ├── app.py         # Flask entry point
│   ├── models.py      # Database models
│   ├── routes/        # API endpoints
│   └── agents/        # Cerebras AI analyzer
├── examples/          # Example scripts
├── ARCHITECTURE.md    # Detailed architecture doc
└── requirements.txt   # Dependencies
```

## Features

- **End-of-pipeline integration**: Add steps as your pipeline runs, send at the end
- **Deterministic summarization**: Large outputs are summarized with head/tail sampling for reproducible debugging
- **Spool fallback**: If API is down, saves to `.xray_spool/` for later submission
- **Step intent hints**: Optional one-line descriptions per step improve semantic analysis
- **Server-side safety net**: The API summarizes oversized inputs/outputs if a client skips SDK summarization
- **AI-powered analysis**: Uses Cerebras LLM with a 2-step sliding window when needed to identify semantic mismatches and faulty steps

## Approach

The system is designed around these key principles:
1. **Minimal Integration Burden**: The SDK requires only wrapping each step's inputs/outputs after execution. Users can enrich this data with optional descriptions for both the pipeline and individual steps, making the system extensible and allowing the AI to understand the intent behind any domain-specific logic without requiring code changes.

2. **Sliding Window Analysis**: Instead of sending entire pipelines to the LLM (which can exceed token limits), we analyze 2 consecutive steps at a time. This keeps prompts under 65K tokens while still detecting data flow issues between adjacent steps.

3. **Semantic Context via Descriptions**: Pipeline and step descriptions tell the LLM what *type* of pipeline (e-commerce, document processing, etc.) and what each step *should* do. This helps detect semantic mismatches beyond just structural data flow.

4. **Deterministic Summarization**: Large outputs (500+ items) are summarized using head/tail sampling (first N + last N items). This is deterministic and preserves edge cases that often reveal bugs.

5. **Graceful Degradation**: If the API is unavailable, runs are spooled locally and can be flushed later with `client.flush_spool()`.

## Known Limitations

- **No cross-window context**: When analyzing step 3→4, the LLM doesn't see steps 1→2. Issues that span multiple transitions may be missed, if they are not detected somehow at previous step.

- **Single LLM provider**: Currently only supports Cerebras API. Other providers require code changes.

- **Summarization loses detail**: Very large payloads are aggressively trimmed. Some bugs may be hidden in truncated data.

## Future Improvements

- **Docker image**: Pre-built container for one-command local setup - developers just run `docker compose up` instead of installing packages, databases, etc.
- **Local LLM support**: Run lightweight local models (e.g., Ollama, llama.cpp) to eliminate third-party API dependency and reduce costs
- **Multi-LLM support**: Add OpenAI, Anthropic, and other cloud providers via configurable adapters
- **Pipeline-level summary**: Generate a one-pass summary of the entire pipeline before window analysis
- **Streaming results**: Return partial analysis as each window completes
- **Web dashboard**: Visual timeline of pipeline runs with highlighted faulty steps
- **Comparison mode**: Compare two runs of the same pipeline to spot regressions
