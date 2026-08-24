# FinCompass 1.0 — Security

FinCompass is a public, no-auth, read-mostly research application. Its security goal is to minimize attack surface, protect optional provider credentials, avoid becoming an abuse relay, and prevent untrusted artifacts from being treated as validated models.

## Implemented controls

- strict ticker input validation and Pydantic request validation;
- shared sliding-window rate limiting (SQLite default; optional Redis);
- request correlation IDs and privacy-minimized rotating audit identifiers;
- strict self-only CSP for the bundled app, plus standard browser security headers;
- no application CDN/runtime third-party script dependency;
- no accounts, passwords, uploads, brokerage credentials, advertising, or telemetry;
- API keys and SEC identification settings read from environment variables;
- provider requests avoid credential-bearing URLs in logged exceptions;
- evidence-score cache tied to engine version and normalized-data schema version;
- forecast model manifests contain model SHA-256 hashes and dataset hashes;
- live forecasting accepts only `validated_research` or `validated_market` registry tiers;
- synthetic and rejected models are blocked from live forecast execution;
- CSV formula-injection neutralization;
- container runs as a non-root user, with application/model files root-owned and runtime writes limited to `/app/data`.

FastAPI-generated `/docs` and `/redoc` may require narrowly relaxed CSP behavior for their documentation assets. The application UI itself remains self-contained.

## Model artifact trust boundary

FinCompass uses `joblib` for locally generated scikit-learn model artifacts. Python/joblib serialization is **not a safe format for untrusted input**. SHA-256 in the adjacent manifest verifies integrity against that manifest; it is not a cryptographic signature proving who created the artifact.

Therefore:

- do not expose model upload endpoints;
- do not load downloaded/third-party `.joblib` files unless they are independently trusted;
- keep `models/` read-only to the runtime service in production;
- if third-party model distribution is added later, add signed manifests or another authenticated artifact-distribution mechanism.

## Deployment responsibilities

Operators remain responsible for TLS termination, HTTP-to-HTTPS redirect, proxy-header trust boundaries, `.env` permissions, dependency patching, durable `data/` storage, Redis when rate limits span hosts, and normal WAF/hosting controls at scale.

## Reporting a vulnerability

Do not publish exploitable details before maintainers can assess them. Report the affected version, reproduction, impact, and mitigation through the repository's private security-reporting mechanism when available.

This document is a self-assessment, not a penetration-test report or security certification.

## v1 event-ingest and adaptive-state security

- External event ingestion is disabled unless `FINCOMPASS_EVENT_INGEST_TOKEN` is explicitly configured.
- The bearer token is compared in constant time and is not placed in URLs.
- Operator-supplied events are `context_only` by default and cannot change probabilities without a separately validated feature contract.
- Realtime events are bounded in payload size and normalized before persistence.
- Event IDs are deterministic/deduplicated to limit replay duplication.
- Adaptive runtime state is stored under the mutable data boundary; bundled registry artifacts are hash verified.
- Adaptive live influence is fail-closed: missing/invalid base model, stale market context, warming state or degradation leads to zero adaptive shift.
- Realtime, adaptive-maintenance and ingest endpoints have dedicated rate-limit groups.

Do not expose the ingest token in frontend JavaScript or commit it to source control. For internet deployments, terminate TLS at a reviewed reverse proxy and keep the application/data volumes least-privilege.

## v1 realtime privacy / feed isolation

- Market and SEC provider-check state is ticker/benchmark scoped internally, but public status responses expose only aggregate source health; raw ticker-scoped status keys are not returned.
- Authenticated external/operator events are `context_only` by default. Their raw payloads are retained locally but redacted from unauthenticated Live/event API responses to avoid accidental redistribution of licensed or proprietary feed content.
- Pending labels and runtime adaptive states are bound to the exact adaptive settings fingerprint; one profile cannot consume another profile's learning state.
- Provider verification age is distinct from immutable event age. If SEC/macro verification exceeds the configured safety limit, that source's adaptive feature contribution is forced to zero until a successful check resumes.
