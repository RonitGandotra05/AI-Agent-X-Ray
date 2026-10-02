# Architecture

X-Ray exports recorded pipeline evidence to a separate diagnostic service.
The separation is appropriate for small Python applications and agents: capture
requires neither a provider key nor a framework dependency, while storage and
LLM calls stay on the service.

## Components

- `xray_sdk`: validated run/step snapshots, HTTP transport, bounded background
  sends, durable local replay, optional framework callbacks.
- `xray_shared`: dependency-free JSON validation and deterministic sampling.
- `xray_api`: Flask routes and SQLAlchemy persistence; SQLite locally or
  PostgreSQL through an optional extra.
- `xray_api.agents`: bounded prompt packing, strict result validation and
  aggregation; small provider adapters with explicit timeout/retry settings.

The base wheel includes the server source for convenient self-hosting, but imports
only SDK/shared code. Flask, provider SDKs and integrations remain optional.

## Capture and delivery

A step is an explicit record of observed inputs/outputs and intended behavior.
Adding it captures an independent JSON snapshot and bounds oversized fields.
Transport captures another snapshot before background submission so later edits
do not change an in-flight send. Sampling never calls a model.

Requests sessions belong to individual threads. A worker pool is created only on
first background use; a semaphore bounds queued/running work. Future-based
`send_async` remains compatible. `asend` adapts a Future to asyncio. Closing a
client drains workers and releases sessions.

Each send snapshot has a UUID. Retry attempts and spool replay preserve that ID.
The server uses the existing Run primary key and a fingerprint of normalized
input to reject conflicting replay and acknowledge matching replay. A run is
committed before analysis so a lost response cannot cause another run/model call
on retry. A replay received while analysis is running may acknowledge status
`received`; query later for its outcome. This is at-most-once ingestion-triggered
analysis, not an automatic job-recovery system.

Spool writes use temporary files, fsync and atomic rename. A file is removed only
after an acknowledged object response. A process-local flush lock protects a
single client. Cross-process ownership/leases are intentionally not implemented.

## Persistence and compatibility

Pipeline, Run and Step tables retain the existing schema. New runs store an
internal versioned JSON metadata envelope holding user metadata, immutable run
purpose and fingerprint; public responses return user metadata. Older rows with
plain metadata remain readable and use the current pipeline description because
the previous implementation did not preserve historical descriptions.

The service applies configuration before initializing database extensions.
Analyzer clients are initialized lazily under an app-scoped lock and may be
injected for testing. No process-global mutable analyzer singleton is required.

## Analysis

Small runs fit into one prompt, which exposes non-adjacent dependencies and avoids
repeated instructions/evidence. If a run exceeds the character budget, the
analyzer packs overlapping windows. A transition remains visible in at least one
window. Only evidence that cannot fit is sampled further, with explicit loss
markers. Context, descriptions, reasons and metrics share the prompt cap.

Sync and streaming analysis use the same generator. Provider responses are
validated as objects with known severities and real step references; refusal,
truncation and malformed output fail explicitly. Completed streams persist their
result before emitting `complete`. Database access remains within Flask context.

Aggregation preserves issues and real usage without mutating window responses.
`analysis_status` distinguishes complete, partial and failed coverage. No finding
in incomplete coverage is `unknown`; completed no-finding results say only that
no issue was observed in the supplied evidence.

## Deliberate limits

The API is a single-key service with synchronous model calls. It has no tenant
isolation, durable analysis job queue, distributed trace engine or repository
index. Large runs can occupy a web worker for multiple provider timeouts. Store
without analysis on latency-sensitive paths and explicitly analyze later. Repeated
explicit analysis/streams can incur new provider charges.

Sampling can miss defects in omitted records; adjacent windows do not prove
arbitrary distant dependencies. Character bounds are not model token counts.
Choose an appropriate model/context limit and measure on representative data.

Add durable jobs, migrations or a standards-based trace exporter only when a
concrete deployment requires them. They are not needed for the core SDK workflow.
