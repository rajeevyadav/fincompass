# Third-Party Notices - FinCompass v2.0

FinCompass remains MIT licensed. The v2.0 source package includes native implementations of standard published mathematical formulas. No code from the repositories below is vendored in this package unless a future file-specific notice explicitly says otherwise.

## FinanceToolkit

- Project: FinanceToolkit
- Repository: https://github.com/JerBouma/FinanceToolkit
- License: MIT
- Use in FinCompass v2.0: architectural/formula reference and independent cross-check target only; no FinanceToolkit runtime dependency and no FinanceToolkit source vendored in this package.

## Bayesian / market-model research references reviewed during v2.0 design

- `luisdamiano/gsoc17-hhmm` - CC-BY-SA 4.0 project; used as a conceptual reference for regime-state/HMM research and simulation-based validation. No code or restricted market data copied.
- `sydney-machine-learning/Bayesianneuralnet_stockmarket` - no repository license identified during review; concepts only, no code copied.
- `AaryanAnand10/Inference-learning` - MIT; reviewed as a general Bayesian-inference example, no code copied.
- `0xpranjal/Stock-Prediction-using-different-models` - MIT; reviewed for the simple-model-vs-complex-model benchmarking principle, no code copied.
- `shaunak-batra/BasketTradingBO` - no repository license identified during review; concepts only, no code copied.

## Data rights

Model artifacts and raw market data are different assets. The public/source package must not redistribute market datasets unless the relevant upstream data terms permit redistribution. Bundled model artifacts therefore retain their provenance and evidence manifests while raw training rows are not included merely because a model artifact is distributable.
