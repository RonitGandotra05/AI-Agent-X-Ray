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
