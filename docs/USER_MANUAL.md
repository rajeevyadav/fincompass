---
title: "FinCompass User Manual"
subtitle: "Guided operation and research extension guide"
date: "August 2026"
toc: true
toc-depth: 3
geometry: margin=0.75in
fontsize: 10pt
---

## What FinCompass is

FinCompass is a local-first research application for studying stocks and testing probabilistic forecasting models. It separates three things that are easy to confuse:

1. **Evidence score** - a 0 to 10 research score based on available company and market evidence.
2. **Forecast probability** - the estimated chance of one precisely defined future event, produced only by a model that passed its recorded validation gates.
3. **Live adaptive probability** - a bounded update around a frozen validated forecast when fresh information arrives. If the live layer is not ready or its data are stale, FinCompass falls back to the frozen forecast.

FinCompass is educational research support. It is not financial advice, a trading signal, or a guarantee of future returns.

---

# Part I - Guided Mode

Guided Mode is the default. You do not need to know signal processing, machine learning, Bayesian statistics, or model calibration to use it.

## 1. Start the application

### Windows

Run `run.bat`, or use the packaged executable if you built one.

### macOS / Linux

Run:

```bash
./run.sh
```

Then open the local address shown by the application. By default FinCompass runs on your own computer.

## 2. Choose Guided or Research mode

At the top of the screen you will see **Mode**.

- **Guided** - recommended for normal use. It shows the safest next action and hides low-level model settings.
- **Research** - exposes model recipes, validation overrides, configuration JSON, experiment lineage, model comparison, and adaptive maintenance controls.

You can switch modes at any time. Switching the screen mode does not change a trained model or its validation status.

---

# 3. Analyze a company

Open **Analyze** and enter a ticker such as `AAPL`.

FinCompass reports a 0 to 10 evidence score built from five research pillars:

| Pillar | Plain-language meaning |
| --- | --- |
| Quality | How strong the company's business and operating evidence looks |
| Financial Durability | Whether the company appears financially resilient |
| Safety | Evidence related to balance-sheet and operating risk |
| Valuation | Whether valuation evidence looks favorable or demanding |
| Cycle | Evidence related to market and economic conditions |

The score is **not** a probability that the stock will rise.

### Read these three items first

- **Evidence score** - overall research assessment.
- **Evidence coverage** - how much of the desired data was actually available.
- **Uncertainty interval** - how uncertain the evidence score is.

A high score with weak data coverage should not be treated as strong evidence.

---

# 4. Use the Screener

Open **Screener**.

1. Choose a minimum evidence score if desired.
2. Choose a sector or leave all sectors selected.
3. Choose a minimum evidence level.
4. Select **Load results**.
5. Use **Refresh source data** if the local snapshot is empty or stale.

The screener ranks research evidence. It does not silently rank stocks by forecast probability.

---

# 5. Compare companies and use the Watchlist

**Compare** lets you place several companies side by side.

**Watchlist** stores tickers locally in your browser. There is no account or cloud sync required for the watchlist.

These tools remain evidence-score workflows. They do not change any forecast model.

---

# 6. Create a forecast model

Open **Forecast**.

Guided Mode presents a three-step workflow:

1. **Update** - obtain or refresh the local history needed by the recommended recipe.
2. **Train** - build, calibrate, and evaluate the candidate.
3. **Activate** - only a candidate that passes the locked-test gates can be made the active forecast model.

Select **Update data & train recommended model**.

If the required local data are already available, the button changes to **Train recommended model**.

## What happens during training

FinCompass does not download data inside the trainer. Data acquisition and model training are separate operations.

The trainer:

1. reads retained local history;
2. builds the dataset for the recipe;
3. separates training, validation, and locked-test periods chronologically;
4. trains the component models;
5. calibrates their probabilities;
6. combines them using validation data;
7. performs final calibration;
8. evaluates the untouched locked-test data;
9. records every gate result;
10. saves a model only when the required gates pass.

A failed candidate remains in experiment history with its failed gates. FinCompass does not lower the thresholds to force a pass.

## Why activation is separate

A passing candidate does **not** become active automatically.

This protects you from accidentally replacing the current model merely because a newer experiment exists.

When a candidate is eligible, select **Activate** in its experiment entry.

You can later activate a different validated model. In Research Mode you can also deactivate the active model explicitly.

---

# 7. Run a forecast

After a validated model is active:

1. Open **Forecast**.
2. Enter a ticker.
3. Leave **Forecast model** on **Active model (default)**, or select another validated model.
4. Select **Run forecast**.

The forecast shows the estimated probability of the exact event recorded in the model.

Example:

> 63% probability of outperforming SPY over 126 trading days by more than the model's recorded hurdle.

This does **not** mean a 63% return.

## Important forecast numbers

### Probability

The estimated chance of the exact event in the model contract.

### Model uncertainty range

A wider range means the probability is less certain.

### Brier skill

A probability-forecast quality measure relative to a baseline.

- 0% = no improvement over the baseline.
- Positive = better than the baseline on the locked test.
- Negative = worse than the baseline.

### ROC AUC

A ranking measure.

- 0.5 is roughly coin-flip ranking.
- 1.0 is perfect ranking.

AUC does not measure probability calibration by itself.

### Calibration error

How closely stated probabilities match observed frequencies. Lower is better.

---

# 8. Use Live

The **Live** workspace starts from a validated frozen forecast model called the **anchor**.

Fresh market, filing, and macroeconomic context can produce an **adaptive candidate** around that anchor. The adaptive layer cannot make an invalid anchor live.

When you manually refresh Live, FinCompass first performs bounded maintenance on any outcomes that have matured. A model can learn from an observation only after the original forecast horizon has completed.

## The three Live conditions

FinCompass provides three governed adaptive profiles:

| Condition | Use | Interpretation |
| --- | --- | --- |
| Conservative | Lowest responsiveness | Prefers smaller/slower adaptive influence |
| Balanced | Default | Middle ground between stability and responsiveness |
| Responsive | Faster reaction | Allows greater responsiveness within its own validation and safety limits |

Choose one profile and select **Refresh selected condition**.

Or select **Compare all conditions**.

The comparison uses the **same observed live information** for all three profiles. It changes only the adaptive settings. It is therefore a sensitivity comparison, not a simulation of three different future market scenarios.

The comparison does not queue learning observations and cannot manufacture adaptive evidence.

## What Live can display

- frozen anchor probability;
- adaptive candidate probability;
- applied live probability;
- gate state;
- source freshness;
- top adaptive contributions;
- recent event chronology;
- pending observation status;
- adaptive state lineage.

## Why candidate and applied probability may be different

A fresh event may change the candidate immediately, but the candidate is applied only when the adaptive gate permits it.

If the gate is:

- warming;
- stale;
- degraded; or
- in drift alert,

FinCompass applies zero adaptive shift and retains the frozen anchor.

---

# 9. Updating data and models

FinCompass keeps research market history in a durable local store.

On an update it requests only the missing tail plus a short overlap window. Existing history is not erased and downloaded again unnecessarily.

If overlapping provider data change, the new value is revision-journaled instead of silently replacing the historical record without evidence.

Raw provider frames and SHA-256 hashes are retained locally for auditability.

## Anchor model update cycle

A normal anchor-model update is:

1. update local market data;
2. train the chosen recipe again;
3. inspect the new locked-test result;
4. activate the new model only if it passes and you intentionally choose it.

The old active model remains active until that explicit activation.

## Adaptive model update cycle

The adaptive residual learns differently:

1. a live observation is made;
2. its original target is stored as pending;
3. the full target horizon passes;
4. the exact outcome is resolved;
5. the adaptive posterior and performance history update;
6. the adaptive gate is recomputed.

This prevents the model from learning from a future outcome before that outcome exists.

---

# 10. What happens on a fresh installation

The package includes a small **real historical research-only bootstrap corpus** so the complete offline training pipeline can be exercised without a network connection.

That bootstrap dataset is intentionally **not live eligible**. Its purpose is to verify that FinCompass can:

- load local real historical data;
- build a dataset;
- train and calibrate a model;
- run the locked-test validation;
- record a rejected or passing result honestly;
- survive restart and retain the evidence.

A clean installation does not pretend that this bootstrap corpus proves live market skill.

For live-eligible research, update the broader local market history and train a live-eligible recipe. The model must still pass its validation gates.

---

# Part II - Research Mode

Research Mode is for users who want to inspect or extend the model rather than simply operate the validated workflow.

# 11. Model Lab recipes

Model Lab recipes define:

- target universe;
- benchmark;
- forecast horizon;
- validation profile;
- feature contract;
- whether the recipe is allowed to produce a live-eligible anchor.

Current recipe families include:

- Core US equity;
- Nasdaq growth;
- global equity proxies including Russell, Canada, Japan, China/Hong Kong, and emerging markets;
- cross-asset regime research using equity, bond, and commodity proxies;
- the bundled real-data bootstrap acceptance recipe.

A recipe being available does not imply that it will pass validation.

---

# 12. Model selection and comparison

Research Mode exposes **Compare validated models**.

The comparison shows each model's:

- model ID;
- validation tier;
- forecast horizon;
- benchmark;
- probability for the selected ticker;
- Brier skill;
- ROC AUC.

Do not rank two models solely by probability if their target definitions differ. A six-month SPY-relative event and a twelve-month QQQ-relative event are different questions.

---

# 13. Forecast configuration

Advanced forecast configuration includes:

- horizon;
- benchmark;
- excess-return hurdle;
- split fractions;
- outer embargo;
- Bayesian prior strength;
- enabled component models;
- calibration method;
- bootstrap settings;
- validation thresholds;
- walk-forward settings;
- abstention settings.

Unknown fields and invalid types are rejected by the configuration validator.

Target-defining changes require rebuilding the dataset and retraining. Editing browser settings does not mutate an already validated artifact.

---

# 14. Temporal validation design

FinCompass uses chronological train, validation, and test partitions.

At the **outer** train-to-validation and validation-to-test boundaries:

- rows whose forward target crosses the next partition boundary are purged;
- the configured outer embargo is applied.

Inside the validation partition, three chronological roles are used:

1. component calibration;
2. ensemble stacking;
3. final ensemble calibration.

Those internal boundaries use strict forward-target purging. They do **not** reapply the full outer embargo a second time. Reapplying a one-year outer embargo inside a much smaller validation partition can erase entire stages and was explicitly corrected in the Model Lab implementation.

The locked test remains untouched by model fitting, calibration, ensemble weighting, and threshold selection.

---

# 15. Validation tiers

FinCompass distinguishes the quality of evidence behind an artifact.

### `fixture_only`

Synthetic or deterministic regression evidence. Useful for testing software and statistical invariants. Never live eligible.

### `rejected`

The candidate completed evaluation but failed one or more required gates.

### `validated_research`

The statistical gate passed, but the dataset does not claim the complete data-governance controls required for stronger market-validation claims.

### `validated_market`

Reserved for a candidate whose dataset and protocol satisfy the stronger market data-quality contract as well as the statistical gates.

---

# 16. Adaptive research settings

The three standard profiles are declarative configurations. Research Mode also exposes their validated JSON representation.

Adaptive settings include:

- market, filing, and macro staleness limits;
- event half-lives;
- residual prior strength;
- process noise;
- forgetting behavior;
- maximum log-odds shift;
- online evaluation window;
- minimum matured observations;
- minimum unique observation dates;
- minimum elapsed time span;
- calibration limits;
- proper-score non-inferiority gates;
- drift controls.

Changing learning semantics creates a new settings fingerprint and a separate state lineage. FinCompass does not reinterpret an old posterior under new assumptions.

---

# 17. Data provenance and local persistence

The research store records:

- instrument catalogue metadata;
- price rows;
- provider/fetch ledger;
- raw source snapshots;
- SHA-256 hashes;
- correction/revision journal;
- experiments;
- model lineage;
- explicit activation state.

SQLite transactions protect committed rows from partial refreshes. Temporary files are atomically replaced only after successful writes.

If a refresh is interrupted, already committed rows remain. The next refresh resumes from the latest retained date plus its overlap window.

If a model build is interrupted, the stale build slot can be reclaimed and the old experiment is marked **interrupted** instead of being left indefinitely as **training**.

---

# 18. Extending FinCompass for academic research

The codebase is deliberately split so a researcher can evolve one layer without silently changing another.

## Main extension points

### `forecasting/recipes.py`

Add or revise declared research universes and target contracts.

### `forecasting/features.py`

Extend the frozen-anchor feature contract. Any feature change creates a new modeling contract and requires complete revalidation.

### `forecasting/model.py`

Add model families or alternative probabilistic ensembles. New models should preserve chronological fitting, separated calibration, locked testing, and gate reporting.

### `forecasting/split.py`

Temporal separation logic. Changes here are high risk and require regression tests specifically for leakage and stage feasibility.

### `realtime/features.py`

Add adaptive event features. New information sources require timestamp semantics, freshness logic, and separate validation.

### `realtime/adaptive.py`

Research alternative bounded online update rules or drift diagnostics.

### `services/research_store.py`

Extend local provenance, additional datasets, or point-in-time research tables.

## Good research directions

The project roadmap includes:

- hierarchical sector/regime priors;
- explicit latent-state regime probabilities;
- multi-horizon anchor models;
- conformal abstention under distribution shift;
- Bayesian change-point diagnostics;
- expected excess-return and downside models;
- historically reconstructed event streams;
- vintage-aware macro data;
- point-in-time historical universe membership;
- delisting-aware market datasets.

These are research extensions, not claims already established by the bundled application.

---

# 19. Troubleshooting

## "No active validated forecast model is available"

This means there is no explicitly active model whose artifact and manifest pass the registry checks.

Go to **Forecast**:

1. update local data;
2. train a live-eligible recipe;
3. inspect the experiment;
4. activate it only if it passed.

## "Needs local data before training"

The recipe is missing its benchmark or required target history. Use the Guided update button or **Update local data**.

## A model was rejected

That is not a software failure by itself. Open the experiment and inspect **Failed gates**.

Do not lower gates merely to obtain an active model. Change the research hypothesis, data quality, model design, or pre-registered protocol and run a new experiment.

## Live stays on the anchor

Check:

- whether the anchor is valid;
- whether market verification is fresh;
- whether the adaptive gate is still warming;
- whether there are enough matured independent observation dates;
- whether a drift alert is active.

Failing closed to the anchor is intentional.

## Data update was interrupted

Restart the update. Retained committed rows are not discarded. FinCompass resumes incrementally from the local tail.

## Model build was interrupted

Start a new build. The stale build slot is reclaimable, and the old experiment is marked interrupted with its evidence retained.

---

# 20. A one-page mental model

If you remember only six rules, remember these:

1. **Analyze is a research score, not a return forecast.**
2. **Forecast asks one precise future-event question.**
3. **A candidate must pass before it can be activated.**
4. **Newer does not mean active; activation is explicit.**
5. **Live can react now but learns only after the outcome matures.**
6. **If freshness or validation is weak, FinCompass falls back instead of pretending confidence.**

That is the core operating philosophy of FinCompass.
