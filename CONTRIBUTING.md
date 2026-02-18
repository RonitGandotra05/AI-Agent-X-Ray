# Contributing to X-Ray

## Development Setup

```bash
# Clone and set up virtual environment
git clone https://github.com/RonitGandotra05/AI-Agent-X-Ray.git
cd AI-Agent-X-Ray
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install pytest

# Copy env template and fill in your keys
cp .env.example .env

# Start the API (SQLite for local dev)
python3 -m xray_api.app
```

## Running Tests

```bash
python -m pytest          # all tests
python -m pytest tests/test_routes.py  # just API tests
python -m pytest -k "summarize"        # tests matching a keyword
```

## Adding a New LLM Adapter

1. Create `xray_api/agents/llm_adapters/your_provider.py`
2. Extend `LLMAdapter` base class from `base.py`
3. Implement `chat_completion()`, `provider_name`, and `model_name`
4. Register it in `llm_adapters/__init__.py` (import + add to `adapters` dict in `get_adapter`)
5. Add corresponding env vars (API key, model name) to `.env.example`

**Template:**
```python
import os
from typing import List, Dict
from .base import LLMAdapter

class YourAdapter(LLMAdapter):
    def __init__(self):
        self.api_key = os.getenv('YOUR_API_KEY')
        self._model = os.getenv('YOUR_MODEL', 'default-model')
        if not self.api_key:
            raise ValueError("YOUR_API_KEY not set")
        # Initialize your client here

    def chat_completion(self, messages: List[Dict[str, str]], temperature=0.1, max_tokens=1000) -> str:
        # Call your LLM and return the response text
        pass

    @property
    def provider_name(self) -> str:
        return "your_provider"

    @property
    def model_name(self) -> str:
        return self._model
```

## Project Layout

| Directory | Purpose |
|-----------|---------|
| `xray_sdk/` | Python SDK published to PyPI |
| `xray_api/` | Flask API server |
| `xray_shared/` | Shared utilities (summarization) used by both SDK and API |
| `tests/` | Test suite (pytest) |
| `examples/` | Example pipeline scripts |

## Commit Messages

Keep commit messages human-readable and descriptive. Avoid conventional commit prefixes like `feat:` or `fix:`. Examples:
- `add streaming analysis via server-sent events`
- `clean up deps, fix sql injection in search`
- `extract shared summarization, fix deprecated datetime`
