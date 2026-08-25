# FinCompass — Developer Guide

## Environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

Run:

```bash
uvicorn api:app --host 127.0.0.1 --port 8000 --reload
```

## Verification

```bash
pytest -q
python tools/verify_release.py
node --check static/app.js
```

## Statistical development rule

Do not tune against the locked test. Use train + validation + walk-forward development evidence. Once locked-test results are inspected, material tuning requires a new untouched future test period before a fresh final validation claim.

## Adding a forecast feature

1. Define the source and unit.
2. Define the public `available_date`.
3. Implement historical reconstruction using only data available on/before each sample date.
4. Add a leakage regression test.
5. Update `MODEL_CARD.md` and `FORECASTING.md`.
6. Rebuild the dataset.
7. Retrain; never reuse a model artifact built from a different feature schema.

## Changing the target

Any change to horizon, benchmark, hurdle or sample step creates a different forecasting problem. Rebuild and retrain.

## Forecast configuration

Use `forecasting/config.py` and `settings_from_dict`. Unknown fields are intentionally rejected.

Browser-exported JSON:

```bash
python tools/train_forecast.py datasets/market \
  --profile strict \
  --settings-json fincompass-forecast-settings.json \
  --name default
```

## Building data

Synthetic regression fixture:

```bash
python tools/generate_validation_fixtures.py --output datasets/fixtures
python tools/audit_forecast_dataset.py datasets/fixtures --output datasets/fixtures/dataset_audit.json
python tools/train_forecast.py datasets/fixtures --profile strict --name fixture-reference
```

Real research dataset:

```bash
export SEC_USER_AGENT="FinCompass research your-email@example.com"
export SEC_CACHE_MAX_AGE_HOURS=24
export SEC_MAX_REQUESTS_PER_SECOND=8
python tools/build_market_dataset.py --with-sec
python tools/audit_forecast_dataset.py datasets/market --output datasets/market/dataset_audit.json
```

The default builder uses today's curated universe and therefore does not claim survivorship control.

## Model Lab offline-first workflow

Rebuild the bundled research-only starter corpus deterministically:

```bash
python tools/build_builtin_seed.py
```

The builder verifies retained source hashes, recreates `datasets/market-seed/market_seed.db`, checkpoints SQLite WAL state, verifies database integrity, and writes `SEED_MANIFEST.json` plus its SHA-256 sidecar. Do not replace the bundled source originals without updating their provenance/license metadata and tests.

At runtime, Model Lab copies/merges the seed into the user-writable research database. Use **Update local data** to extend the broader catalogue; the updater requests only the overlap and missing tail and retains raw response frames. `STOOQ_API_KEY` is an optional fallback credential and is never written to provenance URLs.

A training build consumes local data only. Check `/api/v4/model-lab/recipes` readiness before launching a recipe, retain rejected/failed/interrupted experiment evidence, and never activate a candidate implicitly.

## Model registry

Artifacts live under `models/`.

Never hand-edit a manifest to raise the validation tier. The tier is computed from statistical gates plus dataset quality flags/evidence. Model IDs are bound to the serialized artifact SHA-256; dataset manifests and CSVs are hash-verified. Treat any hash mismatch as invalidation, not as a repairable warning.

## API compatibility

- Evidence consumers: `/api/v1/*`.
- Forecast consumers: `/api/v1/*` (`/api/v1/*` forecast aliases are compatibility-only).

Do not place a forward-event probability under an evidence-score field name or vice versa.

## Versioning

Bump:

- `APP_VERSION` for application releases;
- `SCORING_ENGINE_VERSION` for evidence methodology changes;
- `DATA_SCHEMA_VERSION` for normalized fundamental schema changes;
- `FORECAST_ENGINE_VERSION` for forecast anchor model architecture/serialization changes;
- `REALTIME_ENGINE_VERSION` for adaptive statistical semantics;
- `EVENT_SCHEMA_VERSION` for normalized event-contract changes;
- `ADAPTIVE_STATE_VERSION` for adaptive state-serialization changes.

Update `VERSION`, `CHANGELOG.md`, model card and release audit in the same change.

## Adaptive development workflow

Generate and backtest the deterministic streaming fixture:

```bash
python tools/generate_realtime_fixtures.py --output datasets/realtime-fixtures
python tools/backtest_adaptive_stream.py datasets/realtime-fixtures --profile balanced --name balanced-adaptive
```

Run the full release gate:

```bash
python tools/verify_release.py
```

Key modules:

- `realtime/events.py` — normalized immutable event contract;
- `realtime/store.py` — append-only events, source health, pending labels and runtime states;
- `realtime/providers.py` — built-in source adapters;
- `realtime/adaptive.py` — Bayesian residual, prequential metrics and drift gate;
- `realtime/registry.py` — immutable validated adaptive artifacts;
- `services/realtime_service.py` — orchestration and matured-label lifecycle.

Never call `state.update(...)` from a request merely because a fresh observation arrived. Only the matured-label path may reveal a target and update parameters. Preserve the queued adaptive settings fingerprint/contract and benchmark lineage through maturity; a later UI profile must not reinterpret an older pending prediction.

For online performance, treat time—not row count—as the primary validation axis. The reference gate retains the most recent configured observation dates, includes all rows on those dates, and date-balances Brier/log-loss. Avoid changes that turn cross-sectional ticker count into apparent temporal sample size.
