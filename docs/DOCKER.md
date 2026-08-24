# FinCompass 1.0 — Docker Deployment

## Build and run

```bash
docker build -t fincompass:1.0 .
docker run --rm -p 8000:8000 --env-file .env fincompass:1.0
```

For persistent cache, audit, realtime event history, delayed-label state and adaptive runtime state, mount `/app/data` to durable storage. Application code and bundled model/adaptive artifacts are intentionally not runtime-writable in the supplied image.

Example:

```bash
docker run --rm \
  -p 8000:8000 \
  --env-file .env \
  -v fincompass-data:/app/data \
  fincompass:1.0
```

## Forecast and adaptive artifacts

The image ships the deterministic `fixture_only` frozen anchor and `fixture_only` adaptive regression artifact so registry, validation and fail-closed behavior can be inspected. Neither is eligible for a live market claim.

To deploy a real validated anchor, build it before the image build or mount a **trusted, read-only** model directory under a deployment design you control. Never load an untrusted serialized `.joblib` model.

Adaptive runtime state belongs in the writable data volume. A production operator should preserve that state, event history and pending labels across restarts.

## Optional source configuration

Set only the credentials/identifiers you need in `.env`:

```text
FMP_API_KEY=
ALPHA_VANTAGE_KEY=
FRED_API_KEY=
SEC_USER_AGENT=FinCompass research your-email@example.com
FINCOMPASS_EVENT_INGEST_TOKEN=
```

`FINCOMPASS_EVENT_INGEST_TOKEN` enables the authenticated operator event-ingest endpoint. Treat it as a secret. External event payloads are context-only by default and are not exposed verbatim through public Live responses.

## Multiple workers / hosts

SQLite/WAL can coordinate processes that genuinely share one database file. For separate hosts/containers, use the Redis rate-limit backend:

```text
RATE_LIMIT_BACKEND=redis
REDIS_URL=redis://...
```

and install `requirements-scale.txt` in the image. Multi-host deployment also needs a deliberate shared-state design for cache, event history, delayed labels and adaptive state; independent SQLite files are not a coherent distributed online-learning system.

## Reverse proxy and TLS

Terminate TLS at the hosting/proxy layer, redirect HTTP to HTTPS, and configure trusted forwarded-header boundaries correctly. Do not trust arbitrary client-supplied forwarding headers.

The supplied application CSP is self-only and the application does not require a runtime frontend CDN.

## Health and operational status

- `/api/v1/health` — application/provider/registry health compatibility endpoint.
- `/api/v1/realtime/status` — aggregate realtime/adaptive status without exposing ticker-scoped provider keys.
- `/api/v1/forecast/status` — frozen-anchor registry status.

Provider health is last-observed operational state, not an SLA guarantee.

## Release verification before image build

```bash
pip install -r requirements-dev.txt
python tools/verify_release.py
```

Build the image only from a clean tree that passes the verifier and whose `RELEASE_MANIFEST.sha256` matches the distributed source package.
