# FinCompass 1.0 — Forecast Validation Protocol

## Purpose

Use this protocol before a model is presented as an empirical forward-event probability model.

## 1. Freeze the target

Record:

- benchmark;
- horizon trading days;
- excess-return hurdle;
- adjusted-price definition;
- sample frequency.

Changing any of these creates a different model problem.

## 2. Verify data provenance

For every feature, verify the value was publicly available on or before the sample date.

For SEC features, `available_date` must be the filing date. Never use fiscal period end as the availability date.

For a `validated_market` claim, independently verify:

- point-in-time constituent universe;
- delisted securities;
- corporate-action-adjusted prices;
- symbol changes / mergers;
- no future sector/classification leakage.

## 3. Verify partition integrity

Confirm:

- chronological train -> validation -> test ordering;
- no target end date from train reaches validation;
- no target end date from validation reaches test;
- configured embargo is applied;
- locked test is never used to fit model parameters, calibrators, weights or feature selection.

## 4. Development validation

Use walk-forward development folds. Review:

- Brier skill by fold;
- ROC AUC by fold;
- event rate by fold;
- calibration behavior by regime/time period;
- coefficient/sign stability for the Bayesian component;
- component disagreement.

A single excellent fold does not establish robustness.

## 5. Calibration

Partition validation into three chronological stages: (1) component calibration, (2) ensemble stacking/weight fitting, and (3) final ensemble calibration. At each internal boundary, purge upstream rows whose `target_end_date` reaches the downstream stage and apply the configured embargo. Do not reuse one validation observation across these roles, and never use the locked test for any of them.

Review reliability/calibration plots outside the core package if desired. Quantitatively record:

- ECE;
- calibration slope;
- calibration intercept;
- Brier score;
- log loss.

## 6. Locked test

Run the locked test once the development configuration is frozen. Record all configured gates, not only metrics that look favorable.

Default strict gates are documented in `MODEL_CARD.md` and the generated model manifest.

For Brier/log-loss skill, the reference event-rate baseline must be estimated from the **pre-test development data only** (train + validation), never from the locked test.

## 7. Moving date-block + cross-sectional cluster bootstrap

Resample **blocks of consecutive observation dates**, carrying all securities from each sampled date together. This avoids pretending either same-date cross-sectional outcomes or adjacent overlapping-horizon outcomes are independent. With `bootstrap_block_dates = 0`, use `ceil(horizon_trading_days / sample_step_trading_days)` as the automatic block length.

Review interval estimates for:

- Brier skill;
- log-loss skill;
- AUC;
- ECE;
- calibration slope.

The strict activation profile also gates on bootstrap interval bounds, not only point estimates, and requires minimum locked-test temporal breadth. Record the bootstrap method, block length, draw count and interval level in the validation report.

## 8. Tier assignment

Do not manually override the tier upward.

- synthetic -> `fixture_only`;
- gate failure -> `rejected`;
- real + gates pass -> at least `validated_research`;
- `validated_market` only if all market-grade data-quality flags are true **and** each has a non-empty evidence record as defined in `datasets/MARKET_DATA_CONTRACT.md`.

## 9. Locked-test contamination rule

If developers inspect the locked test and then materially tune:

- feature set;
- hyperparameters;
- target;
- calibration method;
- gate thresholds;
- ensemble components/weights;

then the existing test should be considered part of development. Establish a new untouched future test period.

## 10. Reporting

Retain:

- dataset manifest;
- train/validation/test hashes;
- settings JSON;
- model manifest;
- validation report;
- locked-test prediction file;
- code version / commit hash when available.

## v1 adaptive-stream validation protocol

### A. Software/statistical regression fixture

1. Generate the deterministic adaptive fixture with `tools/generate_realtime_fixtures.py`.
2. Verify `fixture_manifest.sha256` and all CSV hashes.
3. Warm the sequential Bayesian state on `warmup.csv` in chronological order.
4. Freeze the warm-start state for evaluation.
5. Process `locked_test.csv` strictly in **predict-before-update** order: score the observation, record anchor/adaptive losses, then reveal the target and update the evaluation copy.
6. Require the configured adaptive gate to pass at the end of the locked stream.
7. Register the warm-start artifact as `fixture_only`, never as a live model.

The bundled reference stream has 1,200 warmup observations and 600 locked observations. The final locked-stream gate must also satisfy the configured minimum matured-label count, unique observation-date count, elapsed observation span, date-balanced Brier/log-loss non-inferiority, date-balanced ECE and no-drift conditions. The rolling evaluation window is defined in observation dates rather than rows. It is synthetic and cannot establish market skill.

The warm-start state and locked evaluation copy must be distinguished: the shipped warm-start artifact may remain warming/fixture-only while the evaluation copy adapts across the locked stream. A passing locked synthetic stream never upgrades the artifact beyond `fixture_only`.

Pending labels used in real validation must preserve the exact adaptive settings fingerprint/contract that generated the prediction. A matured outcome may update only that state lineage. Market event reconstruction must also preserve the exact benchmark used to construct relative features.

### B. Real adaptive-market validation

Before `validated_research`, a historical event stream must document event source time/effective time and no-lookahead reconstruction. Before `validated_market`, additionally document survivorship/delisting control and corporate-action-adjusted prices with evidence records.

Pre-register the event feature contract, base anchor model, target, update cadence, forgetting/process-noise settings, activation thresholds and locked event-test period before viewing final results. Material changes after viewing a locked result require a new untouched test period.

Report anchor and adaptive Brier/log loss, uplift, calibration/ECE, unique-date/span breadth, time/regime slices, activation/degradation history, drift alerts, provider-outage/staleness scenarios and abstention/fallback frequency. Brier/log-loss and ECE evaluation should be date-balanced when multiple securities share an observation date. Incremental adaptive skill must be measured against the **same frozen anchor**, not against an unrelated baseline.

Validate event-age decay and provider-verification staleness separately: an old but valid event and a provider outage are different conditions. Historical SEC/macro reconstruction must use information/vintages actually available at each observation time. External/news/NLP feeds require a separately documented source-time/effective-time and rights contract before predictive use.


## Realtime target-resolution invariant

For delayed online labels, the processing job must resolve the event at the exact configured H-th common stock/benchmark trading session after `observation_date`. The job-run date is not the target endpoint. If the H-th common session is not yet observable as of processing, the label remains pending. This invariant prevents scheduler delay, weekends, holidays, or outages from changing the target definition after prediction time.
