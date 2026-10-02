# Repository audit and 0.2.0 changes

Reviewed on 2 October 2026. Baseline: repository commit `27732d9`; public PyPI
release `xray-sdk==0.1.5`. The untracked technical DOCX was read as background and
left unchanged. No application source or user data is sent to an LLM by this audit.

## Original purpose and architectural decision

The project captures inputs, outputs, descriptions, reasons and metrics for a
multi-step Python workflow. A Requests-based SDK submits those observations to a
Flask/SQLAlchemy service, which persists the run and diagnoses it using adjacent
LLM windows. Optional LangChain callbacks and CrewAI method wrappers capture
framework activity. Six provider adapters support remote or local analysis.

This separation fits a lightweight post-run diagnostic tool. The three primary
SDK types (`XRayRun`, `XRayStep`, `XRayClient`) are understandable and remain the
public entry points. A distributed tracing framework, vector store, agent
framework, plugin system, dependency-injection container or task broker would add
cost without solving the discovered defects. The service remains optional.

## Problems found and addressed

| Area | Original problem | Change |
| --- | --- | --- |
| Installation | Wheel excluded mandatory `xray_shared` and integration subpackages | Explicit package discovery, clean wheel/sdist smoke tests |
| Version | Metadata 0.1.5 and runtime 0.2.0 disagreed; published wheel runtime also stale | Single version source at 0.2.0, equality check |
| Diagnostics | Network/parse failures became “all transitions correct” | Failed/partial coverage, unknown severity, strict provider/step/schema checks |
| Intent | Run serialization lost pipeline purpose and later updates changed historical meaning | Per-run purpose snapshot in existing JSON storage |
| Prompts | N-1 calls even for tiny runs; repeated instructions and middle steps | Full small run in one call; packed overlapping windows when required |
| Budget | Sampling floor could still exceed budget; original list counts could change on repeated passes | Hard serialized bound, resample original data, original counts and loss markers |
| Evidence | Only inputs/outputs bounded; reasons, metrics, context could explode | Bound every relevant field and the complete system/user prompt |
| SDK flag | Client flag could bypass server bounds, and was lost during persistence anyway | Informational compatibility hint; server bounds always enforced |
| Capture | `add_step` changed caller's objects; background sends read mutable state | Validated independent snapshots at capture/submission |
| Validation | Arrays/non-object steps, booleans as integers, invalid field types, NaN, excessive nesting and malformed Unicode | Clear local exceptions/API 400, shared JSON validation, isolated regression tests |
| Delivery | Retried ingest could create duplicate runs and paid analyses | Stable request UUID and stored payload fingerprint through retries/replay |
| Offline | Filename used pipeline name; replay dropped `analyze=False`; no atomic write | Safe random filenames, fsync/atomic replacement, retained options, verified acknowledgement |
| Responses | Malformed successful JSON retried; arbitrary objects accepted as delivery | Separate parsing from retry, require success/run ID, retain unacknowledged spool files |
| Background | Eager executor, unbounded queue, no cleanup, callback exceptions and races | Lazy bounded pool, flush/close/context manager, safe worker shutdown and callback diagnostics |
| Async | “Async” meant a Future with no awaitable convenience | Preserve Future API; add `asend` using existing workers |
| HTTP | Fresh connection per call, no retry on rate limits, divergent error behavior | Thread-local sessions, capped backoff/Retry-After, typed errors, consistent transport |
| Paid operations | Automatic retry can repeat explicit/streamed analysis | Single initiation attempt for both; ingestion remains idempotent |
| Streaming | Generator used database outside Flask context; completion not stored; dropped/malformed SSE accepted | Context-safe generator, persisted results, strict terminal-event parsing and close |
| Queries | Unknown pipeline step search returned other pipelines; unbounded/invalid pages; loaded all run IDs | Direct database joins, literal wildcard escaping, validated bounded pagination |
| App | Overrides after extension setup did not isolate test DB; global singleton/logging state; default public CORS | Config-first factory, app-local analyzer, opt-in origins, host logging preserved |
| Providers | Four duplicate transports, eager OpenAI dependency, retired model defaults, unbounded calls, ignored Anthropic temperature | Shared small compatible adapter, lazy dependencies, current configurable defaults, timeout/retry/finish/refusal checks |
| Integrations | Missing chat/retriever failures, nullable callback errors, no concurrency/parent identity, CrewAI no detach | Callback lock/identity/completion capture, reversible best-effort sync CrewAI support |
| Documentation | Stale claims of verification, token guarantees and integrations; hosted URL/default model hardcoded | Rewritten README/architecture/contribution guides and portable examples |

## Research and adopted patterns

- [Requests sessions and streaming](https://requests.readthedocs.io/en/latest/user/advanced/)
  support connection reuse and explicit response/client cleanup.
- [urllib3 retry semantics](https://urllib3.readthedocs.io/en/stable/reference/urllib3.util.html)
  inform transient-status selection, Retry-After and bounded backoff. A single
  small retry loop preserves the existing durable-send result contract.
- [OpenTelemetry SDK lifecycle](https://opentelemetry.io/docs/specs/otel/trace/sdk/),
  [Langfuse's Python client](https://github.com/langfuse/langfuse-python/blob/main/langfuse/_client/client.py),
  and [LangSmith's client](https://reference.langchain.com/python/langsmith/client/Client)
  demonstrate explicit lifecycle and bounded export patterns. Their broader
  tracing machinery is not imported into this SDK.
- [LangChain callback definitions](https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/callbacks/base.py)
  establish nullable serialized context, chat callbacks and failure callbacks.
- [Flask streaming](https://flask.palletsprojects.com/en/stable/patterns/streaming/)
  requires retained request context; [Flask-SQLAlchemy configuration](https://flask-sqlalchemy.palletsprojects.com/en/stable/config/)
  must precede extension initialization.
- [OpenAI structured output guidance](https://developers.openai.com/api/docs/guides/structured-outputs)
  supports checking structured responses. Portable JSON mode plus local semantic
  validation is used because providers do not share one strict-schema capability.
- [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
  describes provider-side prefix caching. A Python string cache does not reduce
  submitted tokens. Instructions stay stable; no cache-hit or billing saving is
  promised. Available cached-token usage is retained.
- [Cerebras model lifecycle](https://inference-docs.cerebras.ai/support/deprecation),
  [completion parameters](https://inference-docs.cerebras.ai/api-reference/chat-completions),
  [Anthropic model lifecycle](https://platform.claude.com/docs/en/about-claude/model-deprecations)
  and [stop reasons](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons)
  informed supported defaults and refusal/truncation checks. Models remain
  environment-configurable; live availability can change.
- [OpenAI 1.55.3](https://github.com/openai/openai-python/releases/tag/v1.55.3)
  and [Anthropic 0.40.0](https://github.com/anthropics/anthropic-sdk-python/releases/tag/v0.40.0)
  fix compatibility with HTTPX 0.28. Optional minimum versions include these
  fixes without pinning a transitive HTTP client.
- [PyPA version guidance](https://packaging.python.org/en/latest/guides/single-sourcing-package-version/),
  [project metadata](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/),
  [setuptools discovery](https://setuptools.pypa.io/en/stable/userguide/package_discovery.html)
  and [typed-package distribution](https://typing.python.org/en/latest/spec/distributing.html)
  informed the version source, extras, complete package discovery and `py.typed`.

## Public API and compatibility

Existing imports, constructors' positional arguments, route paths and original
stored step field names remain. `send` still defaults to returning dictionaries;
`send_async` still returns a concurrent Future. Existing spool files are supported.
The API still accepts zero-based raw step orders; the SDK requires positive orders.

Additions: environment URL/key defaults; keyword-only client lifecycle/queue/spool
options; `asend`, `flush`, `close`, context-manager use, `analyze_run`, pagination
`offset`, `XRayError`/HTTP/transport/response exceptions; `max_payload_size` on runs;
CrewAI `detach`; analysis coverage/errors and usage-availability fields.

Intentional behavioral changes:

- Invalid names, orders, duplicate orders, non-finite/non-JSON/deep/invalid-Unicode
  data, empty serialization/sends and nonpositive settings now fail explicitly.
- Capturing no longer mutates the supplied step or keeps live references to it.
- Pagination is capped at 200. An unknown stream run is HTTP 404 instead of an
  HTTP 200 error event. Malformed/truncated streams raise typed errors.
- Failed analysis is not healthy. `all_issues` is consistently an array; the
  misleading `all_steps_analysis` “verified” output was removed.
- The WSGI factory reads the process environment; `.env` loading is explicit in
  the development module command. Root logging and browser CORS are not enabled
  implicitly.
- New replay deduplication requires the updated server. A replay while analysis
  is running can acknowledge `received`; it does not launch a second analysis.

No database schema migration is required. New storage uses an internal versioned
metadata envelope; old rows stay readable. Historical purpose from old rows cannot
be recovered because it was not stored. Proprietary metadata is preserved; this
work does not invent or grant a license.

## Measured efficiency

Run `python -m scripts.benchmark_prompts` in the installed development environment.
It uses deterministic stub responses and the same ten-stage input as baseline
`27732d9`. The original baseline omits previous-window text, making it conservative.

| Fixture | Before | After |
| --- | --- | --- |
| Ten short stages: model requests | 9 | 1 |
| Total system + user prompt characters | 19,327 | 2,508 (87.0% less) |
| 400 records with 500-character values, sample size 10: serialized JSON characters | 209,901 unsampled | 5,384 sampled (original count 400 retained) |

These are character/request measurements, not billed-token, latency, or semantic
accuracy benchmarks. The sampling example verifies a bounded payload reduction;
sampling existed previously, so it is not claimed as a new comparative saving.
Connection reuse, lazy resources and fewer model requests reduce avoidable work.
Validated copies intentionally add local capture work to prevent mutation/races.
No tokenization dependency or auxiliary model calls were added.

Usage is aggregated from provider responses. `token_usage_available`,
`token_usage_complete`, and `token_usage_windows_reported` distinguish missing
usage from zero. Usage cannot include failed provider calls that return no counters
or hidden provider retry charges.

## Validation

- Baseline suite: 35 passing tests, with no meaningful HTTP-client/provider/SSE
  coverage. Test fixtures were moved to config-first isolated databases.
- Final suite: 233 passing tests. Added client, integration, analyzer, provider,
  validation, replay/failure and actual localhost HTTP workflow coverage.
- Full suites run locally on Python 3.9.6, 3.11.14, 3.12.12, 3.13.12 and 3.14.2.
  CI also includes Python 3.10, unavailable on this host. Apple Python 3.9 emits an
  urllib3 warning about its old LibreSSL build; newer local runtimes are clean.
- Actual workflows include sync storage/query/analysis, Future sends, asyncio,
  offline replay after acknowledged transmission, persisted SSE, auth and invalid
  configuration. Providers are deterministic stubs; no paid requests were made.
- Source distribution and wheel build through isolated PEP 517 environments;
  wheel is built from the source distribution. Strict Twine metadata/README
  validation passes. Clean base/server/real-LangChain installation checks and
  dependency checks pass. Version equality and optional-import behavior checked.
- `git diff --check` and Python source compilation pass. The clean installed smoke
  uses `-I` to prevent the repository checkout from masking missing wheel files.

## Changed files

Core changes are in `xray_sdk/{__init__,client,run,step,errors,_version}.py`,
`xray_sdk/integrations/*.py`, `xray_sdk/py.typed`,
`xray_shared/{summarize,validation}.py`, `xray_api/{app,models}.py`,
`xray_api/routes/{ingest,query,shared,stream}.py`, and provider/analyzer modules.

Tests: expanded `test_run.py`, `test_step.py`, `test_summarize.py`, isolated
`test_routes.py`; added `test_client.py`, `test_integrations.py`,
`test_analyzer.py`, `test_api_reliability.py`, `test_llm_adapters.py`, and
`test_workflows.py`.

Packaging/operations: `pyproject.toml`, `MANIFEST.in`, `requirements.txt`,
`.gitignore`, `.github/workflows/tests.yml`, `render.yaml`,
`scripts/smoke_installed.py`, and `scripts/benchmark_prompts.py`.

Documentation/examples: complete rewrite of `README.md`, compact redirect in
`README_SDK.md`, updated `ARCHITECTURE.md`, `CONTRIBUTING.md`, `.env.example`,
this report, and all eight example scripts.

Dependency changes: base Requests requirement retained. Removed mandatory
Flask-CORS and provider/database requirements from the SDK installation; server,
OpenAI-compatible/Anthropic providers, PostgreSQL, LangChain and development tools
are optional extras. Shared provider code removes duplicated implementations;
no new mandatory runtime dependency was added.

## Remaining limits and focused future work

This is a validated small diagnostic SDK, not a correctness proof or multi-tenant
observability platform. Sampling can hide defects; completion order does not imply
causality; LLMs can make wrong judgments even with complete input. A labeled real
pipeline evaluation set and live provider contract checks are the most useful
next accuracy work.

Analysis remains synchronous and occupies a web worker. An interrupted service can
leave a run `received`; explicit reanalysis is the recovery path. Cross-process
spool ownership, automatic job recovery, cancellation of in-flight HTTP and strict
per-model tokenization are not implemented. Use storage-only sends on critical
paths, set suitable timeouts/context limits and close streams/resources explicitly.

PostgreSQL integration is packaged but tested here through SQLite; high-concurrency
PostgreSQL load/migration exercises and live provider billing are not claimed.
CrewAI wrappers depend on writable synchronous task methods; no blanket framework
version guarantee is made. LangChain real callback smoke is included.

The existing project has proprietary metadata without license terms. The owner
should clarify permitted use before broader distribution. Release upload requires
configured owner credentials; normal builds/CI never publish.
