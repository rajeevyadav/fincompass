# FinCompass — Probabilistic Forecasting Design

## Objective

Forecasting is implemented as a **separate empirical model**, not as a reinterpretation of the 0–10 evidence score.

The default event is:

`R_stock(t, t+252) - R_SPY(t, t+252) > 0`

where the return basis is whatever price series the dataset records. Corporate-action adjustment must be explicitly verified in the dataset manifest before `validated_market` can be assigned.

## Model Lab data and experiment lifecycle

Model Lab is offline-first. `services/research_store.py` keeps market history in a dedicated user-writable SQLite database; `services/research_data.py` owns acquisition; and `services/model_builder.py` consumes only that local store. Training never falls back to an implicit network call.

The source package contains a small real historical GOOG/MSFT acceptance corpus. Its `bootstrap-real-1m` recipe is explicitly research-only and cannot be activated for live forecasts. It proves first-run data loading and the full training/validation evidence path, but it is **not** evidence of current market skill and may correctly be rejected by the statistical gates.

Current cross-asset recipes cover US broad market and Nasdaq, Russell/small-cap proxies, Canada/TSX, Japan, China/Hong Kong, emerging markets, Treasury/credit proxies, and commodity proxies. A refresh requests only an overlap window and missing tail, journals provider corrections, and retains raw frames plus hashes. Recipe readiness reports the available benchmark and target series before training.

Experiment states are retained as `training`, `candidate`, `validated`, `rejected`, `failed`, or `interrupted`. A stale interrupted build can be reclaimed without deleting research data or prior evidence. A validated live-eligible candidate is still inert until explicit activation; forecasts never select the newest artifact implicitly.

### Guided and Research operation

The same validation engine is exposed through two UI layers. **Guided mode** is the default and recommends a stable starting recipe, tells the user whether required local data are ready, performs the bounded data refresh when needed, starts training, and then requires explicit activation of an eligible passing candidate. **Research mode** exposes the full recipe list, profile overrides, experiment lineage, raw metrics, validated-model comparison, and explicit deactivate/maintenance controls. Neither mode changes the statistical gates.

Model comparison is descriptive: models with different horizons, benchmarks, hurdles or event definitions are not ranked as if their probabilities were interchangeable.

## Why this architecture

A probability is only meaningful if three layers are separated:

1. **discrimination** — does the model rank higher-risk/higher-opportunity cases differently?;
2. **calibration** — do 70% forecasts occur about 70% of the time for the defined event?;
3. **validation** — were both measured on data the model/calibrator did not fit?

The design therefore uses train data for base-model fitting; an outer purged train/validation/locked-test split with the configured business-day embargo; three chronological validation roles for component calibration, ensemble weighting, and final ensemble calibration separated by strict forward-target purging; and a locked test for final acceptance. The outer embargo is not reapplied inside each validation role.

## Base models

### Bayesian logistic regression

Advantages:

- interpretable standardized coefficients;
- explicit Gaussian prior regularization;
- posterior covariance via Laplace approximation;
- coefficient uncertainty can be propagated to probability uncertainty;
- stable baseline for walk-forward tests.

### Histogram gradient boosting

Advantages:

- non-linear relationships;
- interactions without manually enumerating them;
- efficient for medium-size tabular data.

### Random forest

Advantages:

- structurally different inductive bias;
- robust non-linear partitioning;
- helps expose inter-model disagreement.

## Calibration

Calibration never uses the locked test. The first validation stage calibrates each component; the third validation stage calibrates the weighted ensemble. At each internal validation boundary, upstream observations are retained only when `target_end_date` is strictly before the next fitting stage. This prevents unresolved forward labels from crossing roles without duplicating the outer split embargo. `sigmoid` is the default. `isotonic` is available when the calibration sample is sufficiently large and the user accepts greater overfit risk.

A model with a high AUC but poor Brier/log-loss/calibration performance can fail the activation gate.

## Ensemble weighting

Weights are learned only from the dedicated middle validation/stacking stage using Brier loss with non-negativity and sum-to-one constraints. A regularization term discourages extreme all-in allocations when models have similar validation loss.

## Dependence-aware metric uncertainty

Locked-test uncertainty is estimated with a **moving date-block + cross-sectional cluster bootstrap**. The resampling unit is a block of consecutive observation dates; all securities on a sampled date travel together. This preserves same-date cross-sectional dependence and materially better reflects serial dependence created when a 252-trading-day target is sampled more frequently than every 252 days.

With `bootstrap_block_dates = 0`, the block length is selected conservatively as `ceil(horizon_trading_days / sample_step_trading_days)`. For the strict 252/21 default this is 12 observation dates.

## Uncertainty

FinCompass deliberately avoids calling every interval a Bayesian credible interval. The Bayesian component has a coefficient-posterior interval; the displayed ensemble uncertainty range also includes inter-model dispersion. It is therefore labeled **model uncertainty range**.

## Abstention

A model can abstain when the calibrated probability lies inside a configurable band around 0.5, or optionally when the model-uncertainty range crosses 0.5. Abstention is a feature, not a failure: it avoids converting small probability differences into false conviction.

## Extending the feature set

New features are permitted only when their historical availability can be reconstructed without look-ahead. Every new feature should document:

- source;
- observation/period date;
- public availability date;
- revision policy;
- missingness behavior;
- units and normalization;
- sector applicability.

Current fundamentals scraped today must never be copied backward across historical dates.

## Freeware path to stronger models

The architecture is intentionally open to future additions such as:

- hierarchical sector-specific Bayesian priors;
- dynamic coefficient models / regime-dependent priors;
- Bayesian model averaging;
- monotonic gradient boosting where economic direction is defensible;
- conformal risk sets for abstention/coverage;
- survival/hazard targets;
- multi-horizon models;
- expected-excess-return regression alongside classification;
- explicit transaction-cost-aware decision analysis.

Any additional complexity must improve locked-test calibration/skill and preserve point-in-time provenance; complexity alone is not evidence of quality.

## Relationship to realtime adaptation

The Live layer does **not replace** this validated forecasting pipeline. The empirically validated forecast remains the anchor `p0`. A separately governed sequential Bayesian residual may add a bounded log-odds correction only after its own prequential gate passes.

Fresh events can alter current feature/context state before their future target is known. They cannot update model parameters until that target matures. This preserves the distinction between inference and learning.

A `fixture_only` adaptive artifact is blocked exactly as a `fixture_only` anchor model is blocked. See `REALTIME.md` and `VALIDATION_PROTOCOL.md`.
