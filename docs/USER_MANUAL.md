# FinCompass User Manual

**Version 2.0**

FinCompass is a local-first financial research and probabilistic forecasting environment. The primary workflow is: choose a security and horizon, let FinCompass resolve the market/benchmark/data/model, update data when needed, use the best scientifically applicable Forecast, and start Live only when the evidence tier permits it.

## Evidence tiers

- **Invalid** — a hard data, temporal, numerical, or applicability condition failed. No Forecast.
- **Bayesian baseline / Limited evidence** — the regularized Bayesian probability model is hard-valid and calibrated, but stronger out-of-sample predictive skill has not been demonstrated. Forecast allowed; adaptive Live not allowed.
- **Validated research** — the configured locked-test research gates pass. Forecast and Live eligibility subject to normal activation and Live controls.
- **Validated market** — the statistical gate plus stronger point-in-time and historical-universe controls pass.

A 54% Forecast does not mean a 54% return or 54% accuracy.

## Data and model updates

Normal market updates fetch only the missing tail plus an overlap window. Corrections are journaled. A price-basis mismatch triggers a controlled symbol rebuild instead of mixing raw and adjusted histories. Retraining uses the complete accumulated valid corpus and only labels whose future endpoint has matured.

## Version 2.0 analytics

The deterministic analytics kernel includes performance, risk, technical indicators, valuation, fixed-income math, option pricing/Greeks, financial ratios, and portfolio calculations. Analytics availability does not automatically make a metric a Forecast feature.

For the complete progressive guide, including formulas and research details, see `docs/v2/FinCompass-User-Guide-v2.0.pdf`.
