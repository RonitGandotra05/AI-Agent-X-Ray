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
run = XRayRun("my_pipeline", metadata={"context": "test"})

# Add steps (after your pipeline executes)
run.add_step(XRayStep(
    name="keyword_generation",
    order=1,
    inputs={"title": "Phone Case"},
    outputs={"keywords": ["phone case", "iphone"]}
))

run.add_step(XRayStep(
    name="search",
    order=2,
    inputs={"keywords": ["phone case", "iphone"]},
    outputs={"candidates_count": 100}
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

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ingest` | POST | Submit run for analysis |
| `/health` | GET | Health check |

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
- **Auto-summarization**: Large outputs (>50K chars) automatically sampled to 30 random items
- **Spool fallback**: If API is down, saves to `.xray_spool/` for later submission
- **AI-powered analysis**: Uses Cerebras LLM with a 2-step sliding window only (even for small runs) to identify semantic mismatches and faulty steps
