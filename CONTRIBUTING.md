# Contributing

Use Python 3.9 or later and keep base SDK dependencies minimal.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[server,openai,anthropic,langchain,dev]'
python -m pytest
python -m build
python -m twine check --strict dist/*
```

Tests isolate databases and substitute deterministic providers. Actual localhost
HTTP tests cover SDK integration, background/asyncio sends, replay and streaming.
No external keys are required. Do not point tests at an existing database.

Changes should preserve public imports, positional arguments, and legacy server
response fields. Add regression tests for observable failures and user workflows;
avoid tests that only repeat the implementation. Update README examples whenever
public behavior changes. Keep diagnostics honest about incomplete evidence and
unknown token usage.

The package version lives in `xray_sdk/_version.py`; build metadata reads it
without importing optional dependencies. Before releasing, build a wheel from
its source distribution, install both artifacts in clean environments, and run
`scripts/smoke_installed.py` with Python's `-I` flag. Add `--server` after installing
the server extra. CI covers Python 3.9–3.14.

Provider implementations extend `LLMAdapter` and return text plus optional real
usage. OpenAI-compatible providers share `openai_compatible.py`; preserve small
provider classes for existing imports. Validate finish/refusal/empty responses,
apply explicit timeout/retry settings, and import optional dependencies lazily.
Register new providers in `llm_adapters/__init__.py` and document configuration.

Use descriptive commits scoped to meaningful changes. Do not publish a release
without project-owner authorization and configured PyPI credentials. Proprietary
metadata is retained; changing the license requires an explicit owner decision.
