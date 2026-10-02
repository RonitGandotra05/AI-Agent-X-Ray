# AI Agent X-Ray

**Record a multi-step AI pipeline and inspect where its data went wrong.**

X-Ray is a small Python SDK (`xray-sdk`) and an optional self-hosted Flask API. You
record each step's inputs, outputs, intent, rejection reasons, and metrics. The
API stores the run and can ask an LLM to identify contradictions and suggest fixes.
It works with ordinary Python functions, agents, and application workflows.

The SDK has one direct dependency: Requests. Recording and sampling data make no
LLM calls. Analysis happens on the API server, with your chosen provider.

## Installation

Requires Python 3.9 or later.

```bash
python -m pip install xray-sdk
```

The import name is `xray_sdk`. This README describes the 0.2.0 source and release.
For development or to use this checkout before its release, run `pip install .`.

## Quick start

Start an API as described below, then record and send a run:

```python
from xray_sdk import XRayClient, XRayRun, XRayStep

run = XRayRun("search", description="Find phone cases matching the query.")
run.add_step(XRayStep(
    "keywords", 1,
    inputs={"query": "phone case"},
    outputs={"keywords": ["laptop sleeve"]},
    description="Generate relevant search keywords.",
))

with XRayClient("http://localhost:5000") as client:
    result = client.send(run)
    print(result)
```

`send()` defaults to analysis. To record without spending LLM tokens, use
`client.send(run, analyze=False)`. No provider credentials are needed for storage.

A successful ingestion returns `success`, `run_id`, `status`, and `analysis`.
`success=True` acknowledges storage; inspect `status` and
`analysis["analysis_status"]` to determine whether analysis completed.

## Run the API locally

```bash
python -m pip install 'xray-sdk[server,openai]'
export LLM_PROVIDER=openai
export OPENAI_API_KEY=your-provider-key
export XRAY_API_KEY=your-xray-key
python -m xray_api.app
```

The development server listens on `127.0.0.1:5000` and uses SQLite. Configure the
same `XRAY_API_KEY` in your application, or pass `api_key` to `XRayClient`.
The local server loads `.env` when started with `python -m xray_api.app`.
The SDK reads the process environment and does not load `.env` automatically.

For deployment:

```bash
python -m pip install 'xray-sdk[server,openai,postgres]'
export DATABASE_URL=postgresql://user:password@host/database
# Also set XRAY_API_KEY and your provider configuration.
gunicorn --timeout 300 xray_api.wsgi:app
```

The service uses one shared API key. Without a configured key it is open for local
development. Use HTTPS and a key when exposing it remotely. Tables are created on
startup; existing tables need no schema migration for 0.2.0.

## How it works

1. `XRayRun` collects snapshots of `XRayStep` records without changing your objects.
2. Oversized JSON fields are sampled locally, with explicit omission markers.
3. `XRayClient` sends one JSON payload. Transient failures can be saved to disk.
4. The API validates and persists the run, then optionally analyzes it.
5. Small runs use one LLM request. Larger runs use bounded windows with one
   overlapping step to retain adjacent transitions.

Analysis is a diagnostic aid based on supplied evidence. It does not inspect
source code, execute your pipeline, prove correctness, or recover omitted data.
Give runs and steps short descriptions, retain relevant identifiers and explicit
counts, and provide representative examples of suspicious results.

## Common usage

### Store now, analyze later

```python
with XRayClient() as client:  # XRAY_API_URL, or http://localhost:5000
    stored = client.send(run, analyze=False)
    if stored.get("success"):
        run_id = stored["run_id"]
        result = client.analyze_run(run_id)
        print(result["analysis"])
```

`analyze_run()` explicitly runs analysis again. It is not automatically retried,
because a repeated request could incur another LLM charge.

### Background and asyncio

```python
with XRayClient() as client:
    future = client.send_async(run, analyze=False)
    # Perform other work.
    result = future.result(timeout=30)
```

`send_async()` retains its `concurrent.futures.Future` return type. For asyncio,
use `result = await client.asend(run, analyze=False)`. HTTP runs in a bounded
worker pool, so the event loop remains free; this is not a native async transport.
Canceling an await does not cancel a request already executing.

`send_background(run, callback=...)` is also available. `flush(timeout=...)` waits
for current background sends and returns whether they finished. Use a context
manager or `close()` to drain workers and release connections. Finish foreground
calls and active streams before closing the client.

### Offline replay

```python
with XRayClient(spool_dir=".xray_spool") as client:
    path = client.spool(run, analyze=False)
    replay = client.flush_spool()
    print(replay["flushed"], replay["failed"])
```

Spool files preserve analysis options and a request UUID. The API acknowledges a
replayed UUID without creating another run or repeating analysis; a different
payload with the same UUID returns HTTP 409. Each intentional `send()` creates a
new run. Legacy API versions ignore UUIDs, so replay deduplication requires 0.2.0
of the server. Old spool files are upgraded before transmission.

Files are written atomically with owner-only permissions and deleted only after
acknowledgement. They contain captured data; redact sensitive content before
recording it. A flush processes files oldest first and retains invalid or failed
files for inspection. Use one client/process per spool directory when flushing.

### Query and stream

```python
with XRayClient() as client:
    runs = client.list_runs(pipeline="search", limit=20, offset=0)
    if runs["runs"]:
        run_id = runs["runs"][0]["id"]
        detail = client.get_run(run_id)
        for event in client.stream_analysis(run_id):
            print(event["event"], event["data"])
```

Streams emit `window`, then `complete`, or `error` on an execution failure. A
complete event can contain a failed or partial analysis: inspect its
`analysis_status`. Close a stream iterator if stopping early. Streaming invokes
new analysis and saves its completed result.

### Optional integrations

For LangChain, install `xray-sdk[langchain]` and pass an
`XRayCallbackHandler(pipeline_name="agent")` from
`xray_sdk.integrations.langchain` through `config={"callbacks": [handler]}`.
Call `handler.send(client)` afterwards. The callback captures chat/text model,
tool, chain, and retriever events. Nested/concurrent callbacks are ordered by
completion and include parent IDs; they do not describe a strict sequential data
flow. Captured non-JSON framework objects use bounded text representations.

`XRayCrewMonitor` from `xray_sdk.integrations.crewai` can wrap writable
`execute_sync` methods on an existing crew's tasks. Use `monitor.attach(crew)`
before execution and `monitor.detach()` afterwards. This is a best-effort sync
integration; it does not capture every internal tool or asynchronous task and
may be incompatible with frameworks that prohibit instance method assignment.
Manual `XRayStep` capture is the most portable integration.

## Configuration

Explicit client arguments override environment defaults.

| Client option | Default | Meaning |
| --- | --- | --- |
| `api_url` | `XRAY_API_URL`, then `http://localhost:5000` | HTTP(S) API base URL |
| `api_key` | `XRAY_API_KEY` | Shared API key; empty string disables environment fallback |
| `timeout` | `180` | Requests connect/read timeout in seconds, or `(connect, read)` pair |
| `retries` | `3` | Total attempts, including the first |
| `retry_delay` / `max_retry_delay` | `1.0` / `30.0` | Exponential delay and ceiling; respects bounded `Retry-After` |
| `spool_dir` | `.xray_spool` | Local offline directory |
| `raise_on_error` | `False` | Raise typed send errors instead of returning an error dictionary |
| `max_workers` / `max_pending` | `4` / `64` | Background workers and total pending sends |

`XRayRun(..., sample_size=100, max_payload_size=80000)` controls local sampling.
The size limit applies separately to metadata and each step's inputs, outputs,
reasons, and metrics. Small fields pass through unchanged. Lower sample limits
apply only when a field exceeds its character budget. Steps require nonempty
names, unique positive integer orders, and finite JSON data. A run supports up to
50 steps. Inputs/outputs accept JSON values (`None` is captured as `{}` for compatibility);
reasons/metrics/metadata are dicts.

| Server environment | Default | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///xray.db` | SQLite or PostgreSQL connection; bare `postgres://` and `postgresql://` URLs use the packaged psycopg2 driver |
| `XRAY_API_KEY` | unset | API authentication; `/health` remains public |
| `XRAY_CORS_ORIGINS` | unset | Comma-separated browser origins allowed access |
| `LLM_PROVIDER` | `cerebras` | `openai`, `cerebras`, `groq`, `openrouter`, `anthropic`, or `ollama` |
| `XRAY_MAX_PROMPT_CHARS` | `32000` | Total system/user message character cap; minimum 4000 |
| `XRAY_LLM_TIMEOUT` | `20` | Provider request timeout in seconds |
| `XRAY_LLM_MAX_RETRIES` | `0` | Provider SDK retries; maximum 5 |
| `XRAY_LLM_JSON_MODE` | `true` | JSON mode for compatible providers; disable for incompatible models |

Set the selected provider's `*_API_KEY` and optionally `*_MODEL`.
OpenAI-compatible providers require the `openai` extra; Anthropic requires
`anthropic`; Ollama needs only `server`. See [.env.example](https://github.com/RonitGandotra05/AI-Agent-X-Ray/blob/main/.env.example) for model
and endpoint settings. Model availability changes; override defaults as needed.

The API limits requests to 10 MiB and query pages to 200 records.
`create_app(config)` supports configuration before database initialization,
including `XRAY_CREATE_TABLES=False` and an injected `XRAY_ANALYZER` for tests.

## API reference

| Interface | Result |
| --- | --- |
| `XRayStep(name, order, inputs, outputs, description, reasons, metrics)` | One recorded step; `to_dict()` returns a validated snapshot |
| `XRayRun(pipeline_name, description=None, metadata=None, sample_size=None, *, max_payload_size=80000)` | Run container; `add_step(step)`, `to_dict()` |
| `XRayClient(...).send(run, analyze=True)` | Ingestion result or compatible error dict |
| `send_async()` / `asend()` / `send_background()` | Future / awaitable / callback-based background send |
| `flush(timeout=None)` / `close()` | Drain current futures / shut down client |
| `spool(run, spool_dir=None, *, analyze=True)` / `flush_spool()` | File path / replay counts and errors |
| `list_pipelines()`, `list_runs()`, `search_steps()` | Paginated results with `total`, `limit`, `offset` |
| `get_run(run_id)` / `get_analysis(run_id)` | Stored run and steps / saved analysis |
| `analyze_run(run_id)` / `stream_analysis(run_id)` | Explicit new analysis / SSE iterator |

REST routes retain `/api/ingest`, `/api/pipelines`, `/api/runs`,
`/api/runs/<id>`, `/api/runs/<id>/analysis`, `/api/search/steps`,
`POST /api/analyze/<id>`, and `GET /api/analyze/<id>/stream`.
Stored steps retain `step_name`, `step_order`, and `step_description` fields.

## Errors and reliability

By default `send()` returns an `error` dict on transport, HTTP, or response
failure. Exhausted transient failures include `spooled` and `spool_path` if the
local save succeeds. Authentication/validation errors and malformed successful
responses are not retried or spooled. Transient connection/timeouts, 408, 429,
and 5xx are retried for ingestion and read-only queries within the configured
attempt limit. Explicit and streaming analysis initiation each use one attempt
to avoid repeating paid work.

Query, explicit analysis, and streaming methods raise typed `XRayError`
subclasses. Set `raise_on_error=True` for the same behavior on sends:

```python
from xray_sdk import XRayError

try:
    with XRayClient(raise_on_error=True) as client:
        result = client.send(run)
except XRayError as error:
    print(error, error.spool_path)
```

Public exceptions are `XRayHTTPError` (`status_code`), `XRayTransportError`,
and `XRayResponseError`, all derived from `XRayError`. Invalid local arguments
raise `ValueError` or `TypeError`. A full background queue raises `XRayError`.
Provider failures, refusals, truncated or malformed results are reported as
`analysis_status="failed"` or `"partial"`; no observed fault in a failed analysis
has severity `unknown`, never `ok`.

## Performance and token efficiency

Recording makes no model calls. HTTP sessions reuse connections per thread.
Sampling is deterministic and records original counts and `_xray_summary`
omissions; it can reduce below the requested sample size to enforce a hard JSON
character limit. Server bounds apply even if a client claims prior sampling.

Analysis sends compact JSON, omits database IDs/timestamps and empty fields,
uses one call for small runs, and passes only bounded prior findings between
large windows. Token usage comes from provider responses when available;
unavailable usage is identified separately. Character limits are not exact token
limits: choose a suitable model and lower the cap for a smaller context window.
A Python string cache does not reduce API tokens. Provider prompt caching is
provider-dependent and cached token counts are retained when exposed.

See [AUDIT.md](https://github.com/RonitGandotra05/AI-Agent-X-Ray/blob/main/AUDIT.md) for measured fixtures, research, compatibility changes,
and remaining deployment limits.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[server,openai,anthropic,langchain,dev]'
python -m pytest
python -m build
python -m twine check --strict dist/*
```

Tests include real localhost HTTP workflows with stub providers; no paid model
calls or external service credentials are required. CI covers Python 3.9–3.14,
wheels built from source distributions, and clean base/server installations.
Run `python -I scripts/smoke_installed.py --server` in a clean environment after
installing a wheel with its `server` extra. Build artifacts are under `dist/`.

The project retains its existing proprietary package metadata. No open-source
license grant is supplied. Publishing requires the project owner's PyPI access;
normal builds and CI do not publish releases.
