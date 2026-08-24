# FinCompass 1.0 — Settings and Configuration

## Two settings classes

### Runtime/browser preferences

Stored in browser `localStorage` with an in-memory fallback:

- chart period;
- default screener evidence filter;
- probability display as percent or decimal;
- preferred validated forecast model.

These do not change a model.

### Forecast-training settings

These settings define dataset construction, model fitting or validation. They must be recorded in the model manifest.

## Validation profiles

### strict

Default release profile. Highest minimum sample/class counts and narrowest calibration tolerances.

### standard

Useful for smaller real research datasets while retaining positive skill/calibration requirements.

### exploratory

Permits smaller samples and wider validation tolerances. Intended for R&D; a result should not be promoted beyond the validation tier actually assigned by the model registry.

## Target-defining settings

Changing any of these requires rebuilding the dataset and retraining:

- `horizon_trading_days`
- `benchmark`
- `excess_return_threshold`
- `sample_step_trading_days`

## Split settings

- `train_fraction`
- `validation_fraction`
- `test_fraction`
- `embargo_trading_days`

Fractions must sum to 1.

## Model settings

- `bayesian_prior_sigma`
- `use_hist_gradient_boosting`
- `use_random_forest`
- `calibration_method`
- `random_seed`

## Uncertainty/presentation settings

- `posterior_draws`
- `prediction_credible_level`
- `abstain_probability_band`
- `abstain_if_interval_crosses_half`

## Validation gate settings

- `walk_forward_splits`
- `bootstrap_draws`
- `bootstrap_block_dates` (`0` = auto `ceil(horizon_trading_days / sample_step_trading_days)`)
- `min_test_samples`
- `min_class_count`
- `min_test_dates`
- `min_test_span_days`
- `min_auc`
- `min_brier_skill`
- `min_log_loss_skill`
- `max_ece`
- `min_bootstrap_brier_skill_low`
- `min_bootstrap_log_loss_skill_low`
- `min_bootstrap_auc_low`
- `max_bootstrap_ece_high`
- `min_calibration_slope`
- `max_calibration_slope`
- `min_positive_walk_forward_fraction`

## Browser workflow

Open **Settings** -> choose a profile -> edit the advanced JSON -> **Validate configuration** -> **Export JSON**.

Use the exported file with:

```bash
python tools/train_forecast.py datasets/market \
  --profile strict \
  --settings-json fincompass-forecast-settings.json \
  --name my-model
```

The backend validates field names and ranges. Unknown fields are rejected rather than silently ignored.

Equivalent machine-readable presets ship in `config/forecast-strict.json`, `config/forecast-standard.json`, and `config/forecast-exploratory.json`.
## Reproducibility rule

Every training run freezes the complete validated settings object into the model manifest. Target/split/model/gate changes therefore remain attributable. Target-defining settings require dataset rebuild + retraining; calibration/model/gate changes require retraining and a fresh locked-test evaluation under the contamination rules in `VALIDATION_PROTOCOL.md`.


## v1 adaptive settings

Pre-generated adaptive profiles are shipped in:

- `config/realtime-balanced.json`
- `config/realtime-responsive.json`
- `config/realtime-conservative.json`

The Settings workspace exposes the complete typed JSON contract and validates it through `/api/v1/realtime/settings/validate`.

Configurable groups include:

- provider refresh cadence and maximum staleness;
- event half-life and local retention;
- snapshot spacing/pending-label limits;
- Bayesian residual prior strength;
- forgetting factor and process noise;
- minimum matured outcomes, unique observation dates, elapsed observation span and observation-date evaluation window;
- Brier/log-loss non-inferiority thresholds;
- maximum ECE;
- EWMA drift allowance, smoothing, control multiplier and minimum samples;
- adaptive probability clipping and maximum logit shift;
- adaptive activation and online-learning switches.

Runtime cadence/freshness controls affect acquisition immediately. Learning-semantic settings (prior, forgetting/process noise, activation/gate controls and related fields) are fingerprinted into the adaptive state lineage. Pending labels carry the exact originating settings contract; switching profile cannot reinterpret another profile's matured outcome. Changing adaptive-learning semantics therefore creates a distinct state lineage. A validated historical anchor model is never silently retrained by changing these settings.

`online_eval_window` is measured in **observation dates**, not rows. All rows on the retained dates are evaluated, with equal-date weighting for Brier/log-loss. This prevents ticker breadth or repeated intraday refreshes from being mistaken for temporal validation breadth.
