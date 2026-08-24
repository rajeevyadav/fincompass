# FinCompass 1.0 — Market Data Contract

A model can earn `validated_market` only when the dataset is both statistically acceptable and the market-data controls are substantiated. This document defines the expected evidence.

## Required controls

The dataset manifest must declare all four controls `true` **and** provide a non-empty `data_quality.evidence` record for each:

1. `point_in_time_features` — how each historical feature's public availability date was reconstructed; revisions/amendments policy included.
2. `survivorship_control` — source/process showing historical universe membership rather than only today's survivors.
3. `delistings_included` — reconciliation showing delisted securities and terminal/delisting returns are represented where applicable.
4. `corporate_action_adjusted` — source/audit demonstrating splits, dividends and other relevant corporate actions are consistently handled for stock and benchmark series.

The application can verify that evidence records exist; it cannot independently prove an external vendor/source is truthful. Independent data review remains part of release governance.

## Minimum row contract

Each sample must contain:

- `date` — observation/as-of date;
- `ticker` — identifier valid for that observation period;
- `target_end_date` — date at which the forward event is resolved;
- `target_outperform` — binary target;
- backward-looking feature columns only.

Forward-return columns may be retained for audit, but `forecasting.features.feature_columns()` excludes them from model features.

## Temporal rules

- no feature may use information published after `date`;
- train targets must resolve before validation begins;
- validation targets must resolve before test begins;
- the configured embargo is applied before downstream partitions;
- internal validation stages are separated by target-horizon purge + configured embargo;
- bootstrap resampling preserves same-date cross-sectional clusters and uses consecutive date blocks to represent serial dependence from overlapping targets;
- the locked test is not used for feature selection, hyperparameter tuning, calibration or ensemble weighting.

## Recommended external evidence package

For a market-grade release, retain alongside the FinCompass manifest:

- universe-membership source/version and extraction date;
- delisting reconciliation report;
- corporate-action/price-adjustment methodology;
- symbol-change / merger mapping;
- fundamental filing/revision availability audit;
- data-vendor terms/licensing review;
- code commit/release identifier;
- generated dataset audit (`tools/audit_forecast_dataset.py`);
- train/validation/test hashes;
- model manifest and artifact hash;
- locked-test predictions and validation report.


## Realtime extension

The historical market-data contract governs the frozen anchor. The adaptive Live layer has an additional timestamp/freshness and matured-label contract in `datasets/REALTIME_EVENT_CONTRACT.md`. A strong historical anchor does not automatically validate a realtime event family; new event sources and adaptive learning behavior require their own prequential evidence and provenance controls.
