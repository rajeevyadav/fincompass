# FinCompass Forecast Datasets

## `fixtures/`

Deterministic synthetic regression data shipped with the repository.

Purpose:

- test dataset hashing;
- test chronological splitting;
- test model fitting;
- test calibration;
- test validation gates;
- test model registry blocking of synthetic models;
- provide reproducible example outputs.

The fixture is **not market data** and cannot be used as evidence of investment performance.

## `realtime-fixtures/`

Deterministic synthetic event-stream data for the adaptive layer.

It contains:

- `warmup.csv` — sequential warmup observations;
- `locked_test.csv` — untouched streaming regression sequence;
- `fixture_manifest.json` and SHA-256 sidecar;
- `adaptive_stream_manifest.json`;
- `adaptive_validation_report.json`.

The stream exercises predict-before-update ordering, settings lineage, temporal-breadth gating, date-balanced online metrics, bounded adaptive updates and drift controls. It is marked **synthetic / fixture_only** and is never market-performance evidence.

See [`REALTIME_EVENT_CONTRACT.md`](REALTIME_EVENT_CONTRACT.md) and the top-level `REALTIME.md`.

## `market/`

Not shipped by default. Create it with `tools/build_market_dataset.py` in an environment with network access.

A dataset bundle contains:

- `train.csv`
- `validation.csv`
- `test.csv`
- `dataset_manifest.json`
- `dataset_manifest.sha256`

Audit/training additionally create:

- `dataset_audit.json`
- `locked_test_predictions.csv`
- `validation_report.json`

Audit a bundle before training with:

```bash
python tools/audit_forecast_dataset.py datasets/market --output datasets/market/dataset_audit.json
```

For the stronger `validated_market` data-quality contract, see [`MARKET_DATA_CONTRACT.md`](MARKET_DATA_CONTRACT.md).

## Manifest integrity

Every CSV is hashed with SHA-256, and `dataset_manifest.sha256` binds the manifest itself. `tools/train_forecast.py` verifies the bundle before training. Editing a CSV or manifest after bundle creation causes validation/training to fail rather than silently invalidating reproducibility.

The registered model manifest also records the dataset split, provenance, manifest-content SHA-256 and each CSV hash. The model ID is the first 16 hexadecimal characters of the serialized model artifact SHA-256.
