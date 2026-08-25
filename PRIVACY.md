# FinCompass — Privacy Notice

FinCompass is designed to collect as little user data as practical.

## Browser-local data

The bundled UI may use browser `localStorage` (with an in-memory fallback) for:

- educational-use consent state;
- watchlist ticker symbols;
- runtime display preferences;
- the user's draft/exportable forecast-training settings JSON.

These values are not synchronized to a FinCompass account because FinCompass has no accounts.

## Server-side data

The server caches public market/fundamental data, evidence scores, price history, macro context, screener jobs, SEC response cache when configured, and rate-limit state. Training datasets and locally generated model artifacts exist only when the operator explicitly creates them.

The rate limiter temporarily keys traffic by client IP and endpoint group. The audit log stores timestamp, request ID, method, path, status and, by default, a daily rotating one-way hash of the client IP. `AUDIT_IP_MODE=raw` enables raw addresses and `AUDIT_IP_MODE=none` suppresses that identifier.

## What FinCompass does not collect by design

The bundled application has no user profile, email/name collection, advertising identifier, analytics pixel, brokerage connection, payment information, portfolio upload, cloud watchlist sync, or model-upload feature.

## Provider credentials and SEC identification

FMP, Alpha Vantage and FRED keys are optional environment variables and are not intentionally returned to the browser. `SEC_USER_AGENT` is sent to SEC endpoints when the optional historical CompanyFacts builder is used; operators should supply the identification/contact string appropriate for their use. CompanyFacts responses are cached locally under `data/sec_cache/` according to `SEC_CACHE_MAX_AGE_HOURS`; no SEC API key is required.

## Third-party data providers

When the server or dataset builder retrieves public data, those providers may observe the server's network address and request metadata and are governed by their own policies.

## v1 realtime data

The Live workspace does not require an account. Local server-side operational state may contain ticker symbols, provider timestamps, normalized public-market/filing/macro values, model state, pending forecast labels and source-health records. It is intended to contain no personal profile data.

If an operator enables `/api/v1/events/ingest`, the operator is responsible for ensuring the supplied event payload is authorized for processing/storage and does not include unnecessary personal or confidential data. The reference implementation treats external payloads as research context, not a user profiling channel.

## v1 shared-deployment privacy

Ticker/benchmark-specific provider health is stored locally for cadence control, but public health/status endpoints return aggregate source state rather than the raw ticker-scoped keys. This avoids exposing another user's recent research symbols on a shared deployment.

Authenticated operator-supplied event payloads may be stored locally. Their payload content is redacted from unauthenticated realtime/event responses by default; only event metadata and a redaction marker are exposed publicly. Operators remain responsible for ensuring that any externally ingested data may lawfully be stored and processed.
