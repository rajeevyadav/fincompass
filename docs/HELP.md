# FinCompass - Quick Help

FinCompass has two screen modes:

- **Guided** - the default. Use this if you simply want to research, train a governed model, forecast, and check Live conditions.
- **Research** - exposes recipes, configuration JSON, model comparison, experiment lineage, and adaptive maintenance controls.

## The three things FinCompass keeps separate

1. **Analyze** - a 0 to 10 evidence score. It is not a return probability.
2. **Forecast** - the probability of one exact forward event from a validated frozen model.
3. **Live** - a bounded adaptive update around that frozen forecast. If the adaptive gate is not ready, the frozen forecast remains in control.

## Fastest safe path to a forecast

Open **Forecast** in Guided Mode:

1. Select **Update data & train recommended model**.
2. FinCompass updates the required local history and trains only from the retained local store.
3. Inspect the locked-test result.
4. If the candidate passed and is live eligible, select **Activate**.
5. Enter a ticker and select **Run forecast**.

A rejected candidate stays rejected. FinCompass never auto-activates the newest model.

## Reading a forecast

- **Probability** - chance of the exact event in the model manifest. It is not expected return.
- **Model uncertainty range** - how uncertain the probability is.
- **Brier skill** - improvement over a probability baseline on locked data. Positive is better; negative is worse.
- **ROC AUC** - ranking quality. About 0.5 is coin-flip ranking.
- **Calibration error** - how closely stated probabilities match observed frequencies. Lower is better.

## Live conditions

Live offers three governed profiles:

- **Conservative** - lowest responsiveness.
- **Balanced** - default.
- **Responsive** - faster reaction within its own limits.

Use **Compare all conditions** to see all three against the same observed information. This is sensitivity analysis, not three simulated market futures. The comparison does not queue learning observations.

A normal manual Live refresh automatically checks matured outcomes first. The adaptive model can learn only after the original forecast horizon has completed.

## Why Live may not move

The adaptive candidate is applied only when the gate permits it. A stale, warming, degraded, or drifting state contributes zero applied shift and FinCompass falls back to the frozen anchor.

## Updating models

Anchor update cycle:

1. update local history;
2. retrain the recipe;
3. inspect validation;
4. explicitly activate the new candidate if it passed.

Adaptive update cycle:

1. make a live observation;
2. wait for the exact target horizon to mature;
3. resolve the outcome;
4. update the adaptive posterior and performance gate.

## Fresh installation

The package includes a small real historical research-only bootstrap corpus so the complete offline Model Lab pipeline can be exercised without a network connection. It is not live eligible and is not evidence of market skill.

## Research Mode

Research Mode exposes:

- all declared Model Lab recipes;
- profile overrides;
- validated-model comparison;
- experiment metrics and lineage;
- forecast and adaptive JSON configuration;
- explicit active-model deactivation;
- manual matured-label maintenance.

The full manual is available from **User Manual** in the footer.
