# FinCompass — How to Use It

FinCompass deliberately separates three different questions so that a research score, a validated forward forecast and a live adaptive adjustment are never presented as the same thing.

## Analyze — evidence score

**Analyze** returns the 0–10 Bayesian evidence score. It is a structured research assessment, not a future-return probability.

Review:

- overall score and label;
- evidence coverage and confidence;
- 90% model interval;
- Quality, Financial Durability, Safety, Valuation and Cycle pillars;
- data completeness and source state;
- score-threshold posterior ranges;
- metric-level evidence and caveats.

## Forecast — frozen validated anchor

**Forecast** is the long-horizon probabilistic workspace. A forecast appears only when the local model registry contains a real model with `validated_research` or `validated_market` status.

The forecast card shows:

- the exact binary event definition;
- horizon, benchmark and excess-return hurdle;
- calibrated event probability;
- model-uncertainty interval;
- validation tier;
- locked-test metrics;
- component-model probabilities;
- abstention state when applicable;
- model ID and as-of information.

The bundled anchor artifact is `fixture_only`, so a clean FinCompass download correctly refuses to present it as a live market forecast.

## Live — new information and governed adaptation

**Live** is separate from Forecast. It collects timestamped market, SEC-filing and macro context and evaluates a bounded adaptive residual around the frozen anchor.

The workspace shows:

- anchor probability and adaptive candidate probability;
- whether the adaptive correction is actually permitted to apply;
- freshness / staleness and source-health state;
- top feature-level log-odds contributions;
- recent event chronology;
- adaptive state ID, settings lineage and gate status;
- matured-label count, independent observation-date breadth and elapsed span;
- Brier/log-loss comparison, calibration error and drift state.

Important operating rule: **fresh evidence may change the candidate probability immediately, but model parameters learn only after the corresponding forward outcome has matured.** If the adaptive gate is warming, stale or degraded, FinCompass falls back to the validated anchor.

The built-in public providers are best-effort / near-real-time, not exchange-grade market feeds.

## Process matured outcomes

The **Process matured** action checks unresolved live observations whose configured forecast horizon has completed. Only then can they become online-learning observations.

FinCompass binds each pending observation to:

- ticker;
- base model;
- benchmark / target contract;
- adaptive settings fingerprint;
- observation date and as-of information.

Changing adaptive profiles therefore creates a separate state lineage rather than reinterpreting old observations under new assumptions.

## Settings

There are two advanced configuration families:

1. **Forecast settings** — horizon, benchmark, hurdle, split design, priors, component models, calibration, bootstrap and validation thresholds. Target-defining changes require dataset reconstruction and retraining.
2. **Realtime settings** — provider cadence/staleness, event half-life, Bayesian residual prior, forgetting/process noise, maximum logit shift, online evaluation breadth, calibration/non-inferiority limits and drift controls.

Use the configuration validators before export. Unknown fields and invalid types are rejected. Runtime settings do not silently mutate an already-validated frozen model.

## Screener

The screener remains evidence-score based. It does not silently rank securities by a forecast probability or an adaptive candidate.

## Watchlist / Compare

These are local research workflows. Browser-local state is used where available, with graceful fallback if browser storage is disabled.

## Building a validated frozen anchor

1. Configure `SEC_USER_AGENT` if using SEC features.
2. Build a point-in-time historical dataset with `tools/build_market_dataset.py`.
3. Inspect `dataset_manifest.json`, hashes and provenance evidence.
4. Run `tools/audit_forecast_dataset.py` before training.
5. Freeze settings and train with `tools/train_forecast.py`.
6. Inspect validation report, locked-test predictions, dependence-aware bootstrap bounds and purged walk-forward folds.
7. Install only an artifact whose documented tier supports your intended use.

## Building adaptive evidence

A real adaptive layer needs time. It should accumulate live predictions first, resolve labels only when their horizons mature, and demonstrate prequential non-inferiority / improvement across independent dates and sufficient elapsed time. The bundled streaming fixture proves the software and statistics pipeline only; it is not market evidence.


## Reading the numbers (plain-language glossary)

Hover over any dotted-underline label in the app to see this explanation inline.

- **Evidence score (0-10)** - a structured research assessment across Quality,
  Financial Durability, Safety, Valuation and Cycle. It is **not** a prediction
  of future return.
- **Probability (forecast)** - the model's estimated chance of the exact event
  in its manifest (e.g. "beats the benchmark over 252 trading days"). 65% means
  a 65% chance of that event, **not** a 65% return.
- **Brier skill** - how much better the model's probabilities are than a naive
  baseline, on unseen "locked" test data. 0% = no better than the baseline;
  higher is better. Negative = worse than the baseline.
- **ROC AUC** - how well the model ranks outperformers above underperformers.
  0.5 = a coin flip; 1.0 = perfect ranking; below 0.5 = worse than random.
- **Calibration error (ECE)** - how closely stated probabilities match what
  actually happens. Lower is better; 5% means predictions are off by about
  5 percentage points on average.
- **Model uncertainty range** - the plausible range for a probability, combining
  statistical uncertainty with disagreement between the component models. A wide
  range means low confidence.
- **Frozen anchor vs. adaptive candidate** - the anchor is the validated,
  locked probability; the candidate is a provisional value that reacts to fresh
  news. The candidate is only **applied** if the adaptive gate passes.
- **Gate: warming / stale / degraded** - the adaptive adjustment is only used
  when it has proven itself; otherwise the app falls back to the frozen anchor
  and the gate shows why.
- **Validation tier** - `fixture_only` (synthetic demo, never live), then
  `validated_research`, then `validated_market` (real, survivorship-controlled).
  A forecast is only activated at `validated_research` or higher.

## Validation tiers

Frozen anchor:

- `fixture_only` — software/statistical fixture only;
- `rejected` — failed validation;
- `validated_research` — real historical statistical validation passed, but dataset limitations remain;
- `validated_market` — statistical gates plus documented market-data controls.

Adaptive artifact:

- `fixture_only` — synthetic online-learning regression only;
- non-live states remain blocked from applying to public market forecasts;
- a live-eligible adaptive state must be linked to a live-eligible frozen anchor and satisfy the prequential gate under its exact settings lineage.

## Interpreting probability

A 65% event probability does not mean 65% expected return. It means the model estimates a 65% probability of the exact binary event encoded in its manifest.

The adaptive layer is a bounded correction to that event probability, not an independent guarantee. Tail risk, regime change, data errors, revisions, costs, taxes, liquidity, capacity and portfolio-level risk remain outside or only partially represented by the model.

See `FORECASTING.md`, `REALTIME.md`, `MODEL_CARD.md` and `VALIDATION_PROTOCOL.md` for the governed methodology.
