<p align="center">
  <img src="assets/banner.svg" alt="FinCompass — free systematic stock research" width="100%">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-58dbc9" alt="MIT license">
  <img src="https://img.shields.io/badge/tests-release%20verified-5fe09b" alt="release verified">
  <img src="https://img.shields.io/badge/python-3.11%2B-2a86d6" alt="python 3.11+">
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-9fb0c5" alt="cross platform">
  <img src="https://img.shields.io/badge/accounts-none-5fe09b" alt="no accounts">
</p>

# FinCompass

**Free, self-hostable systematic stock research** — a FastAPI + vanilla-JavaScript workbench with three
deliberately separated analytical layers. No accounts, no subscriptions, no advertising, no analytics, no paid
frontend libraries, no proprietary cloud backend.

1. **Evidence engine** — a transparent 0–10 Bayesian research score across Quality, Financial Durability, Safety, Valuation and Cycle, with per-pillar uncertainty.
2. **Forecast architecture** — validity-tiered Bayesian reference models plus stronger validated models. A hard-valid baseline can remain available as Limited evidence; stronger validation tiers remain unchanged and preferred.
3. **Adaptive live layer** — timestamped market/filing/macro context plus a bounded sequential Bayesian residual that may adjust the anchor only after a separate prequential activation gate passes.

> **Educational research support, not financial advice.** The evidence score is not a return forecast. A forecast
> probability, when available, applies only to the exact event definition, horizon, benchmark, hurdle, dataset and
> model manifest that produced it. No probability is a guarantee.

---

## Get started in one click

FinCompass is designed so an end user **never needs the command line**.

| Platform | How |
|---|---|
| **Windows (installer)** | Run the generated FinCompass Setup executable → launch from the Start menu. Windowed app, no console. |
| **Windows (portable)** | Double-click **`run.bat`** — it creates the environment and opens the app. |
| **macOS / Linux** | Run `./run.sh`. |

The app opens at `http://127.0.0.1:8000/`. Local data (watchlist, settings, any models you build) lives in a
writable per-user directory and survives upgrades.

📘 **New here? Read the [User Manual (PDF)](docs/FinCompass-User-Manual.pdf)** for a guided walkthrough of every workspace. It's also linked in the app footer.

FinCompass opens in **Guided mode**. For a supported ticker, the intended path is **ticker -> automatic market/benchmark resolution -> update missing local data -> strongest applicable model -> Forecast -> Start Live**. The user does not need to understand model IDs, feature contracts, locked tests, or training recipes. **Research mode** exposes model experiments, evidence tiers, regime alternatives, quantitative analytics, lineage, and validation diagnostics.

Everything operational is an **in-app button**, including:

- **Refresh universe** — repopulate the screener from free public data.
- **Update local data** — incrementally extend the durable Model Lab corpus; only the overlap and missing tail are requested, and raw provider frames are retained with hashes.
- **Update / research models** — normal Guided Forecast uses pooled model families. Model Lab remains available for research and retraining. Hard-invalid models remain unavailable; hard-valid Bayesian references can remain forecast-eligible as **Limited evidence** instead of disappearing merely because the stronger research gate is not met.

<details>
<summary><strong>Run from source (developers)</strong></summary>

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn api:app --host 127.0.0.1 --port 8000
```

Build the desktop executable and installer:

```bash
build_exe.bat            # -> dist\FinCompass.exe  (windowed, release-stamped)
build_installer.bat      # -> versioned Setup executable (needs Inno Setup)
```
</details>

---

## Version 2.0 model ladder

FinCompass v2.0 packages a conservative model ladder instead of forcing every user through a bespoke training exercise:

1. unconditional reference;
2. regularized Bayesian reference (6/12/24/36-month US-equity artifacts);
3. experimental 3-state regime-aware Bayesian reference (Research alternative);
4. enhanced nonlinear/ensemble model;
5. governed adaptive Live residual for eligible validated anchors.

The bundled 12-month enhanced model remains `validated_research` on its declared historical research corpus and is preferred over weaker exact-domain baselines. Regime-aware models are shipped for transparent research comparison but are not automatically preferred because their current locked-test evidence does not consistently improve the simpler architecture.

The v2.0 source also includes provider-independent statement normalization, a versioned formula registry, 25+ financial ratios, performance/risk/technical analytics, DCF arithmetic, fixed-income math, options pricing/Greeks, and portfolio calculations. Analytics are kept separate from Forecast features unless explicitly registered and validated.

## Current release highlights

- **Offline-first Model Lab.** A durable SQLite research corpus, incremental overlap refresh, raw-frame SHA-256 provenance, declarative cross-asset recipes, experiment history, explicit activation, and a bundled real historical acceptance corpus let a fresh install exercise training without network access. Training and acquisition are separate operations.
- **Guided and Research workflows.** Guided mode provides a safe update -> train -> inspect -> activate -> forecast path and plain-language Live condition comparison. Research mode exposes recipe selection, advanced configuration, lineage, model comparison, and maintenance controls without weakening the same validation gates.
- **Validated in-app forecast builds.** Background training is SQLite-tracked and writes evidence bundles to a writable user directory. Passing candidates remain inactive until explicitly activated; rejected and interrupted runs stay inspectable.
- **Windowed desktop app + Windows installer.** No console window; a small control window with Open/Quit and
  graceful shutdown. Version-stamped `.exe` with copyright, plus an Inno Setup installer.
- **Investor Posture indicators.** Three mechanically-derived, model-free research signals —
  New-Position Priority, Accumulation Signal, Re-Underwrite Trigger — shown below the pillar boxes. Research
  signals, not buy/sell recommendations; no combined verdict, no personalization.

See [`CHANGELOG.md`](CHANGELOG.md) for the full history.

---

## The three layers

### 1. Evidence engine

A transparent 0–10 Bayesian research score across five pillars — **Quality, Financial Durability, Safety,
Valuation, Cycle** — each with an evidence-coverage measure and a 90% credible interval. Missing evidence shrinks
the posterior toward neutral and widens uncertainty rather than silently guessing.

### 2. Forecast anchor

A calibrated forward-event probability model, kept strictly separate from the evidence score.

- Bayesian logistic regression (Laplace posterior) + histogram gradient boosting + regularized random forest.
- Purged chronological train / validation / locked-test partitions with the configured embargo on the outer split; the three internal validation roles are chronologically disjoint and use strict forward-target purging without reapplying the outer embargo.
- Locked-test Brier/skill, log-loss/skill, ROC AUC, average precision, ECE and calibration slope/intercept, temporal-breadth gates and clustered-bootstrap bound gates.
- Abstention near a configurable neutral band; model registry with hash verification and validation tiers.

**Validation / evidence tiers**

| Tier | Meaning | Guided Forecast | Adaptive Live |
|---|---|---:|---:|
| `invalid` / `rejected` | Hard validity failure or unusable candidate | No | No |
| `bayesian_baseline` | Hard-valid calibrated Bayesian estimate; stronger skill not established | Yes, **Limited evidence** | No adaptive control |
| `validated_research` | Strong configured locked-test research gate passed | Yes | Eligible after explicit activation |
| `validated_market` | Research gate plus stronger point-in-time / historical-universe controls | Yes | Eligible after explicit activation |

The stronger research/market thresholds are not weakened. The baseline tier changes how a weak-but-valid Bayesian estimate is communicated, not what counts as validated research.

The app refuses to promote a synthetic fixture or a failed model into the live Forecast workspace.

### Model Lab: offline-first training lifecycle

Model Lab separates data acquisition, training, validation, and activation:

1. A fresh install bootstraps a small **real historical, research-only** GOOG/MSFT corpus from `datasets/market-seed/`. It exists to prove the offline training path and is never live-eligible.
2. **Update local data** requests only the configured overlap and missing tail for the cross-asset catalogue. Provider frames and SHA-256 provenance are retained locally; broad provider data are not redistributed in the source package.
3. Recipe readiness is computed before training. The UI shows the local benchmark/target coverage and disables recipes that cannot yet be trained.
4. Training consumes only the durable local store, freezes a dataset evidence bundle, calibrates, runs the locked test, and records the experiment.
5. Rejected and interrupted experiments remain in history. A passing live-eligible candidate is still inactive until explicit activation writes the active-model pointer.
6. Forecasting loads only the explicitly selected/active validated artifact and verifies its hash. There is no newest-model-wins fallback.

The bundled acceptance corpus can legitimately produce a **rejected** statistical candidate; that does not make the training pipeline a failure and its gates are never weakened to force a pass.

**Point-in-time data.** The SEC CompanyFacts path makes a fundamental feature available on its **filing date**, not
the fiscal period end — preventing a common form of backtest look-ahead leakage. The bundled public-data builder
stays conservative: today's curated universe plus free price-provider fallbacks can earn `validated_research`, but
not `validated_market`.

### 3. Adaptive live layer

Source-cadence market, SEC filing and FRED macro context with explicit timestamps, freshness and staleness, plus a
bounded sequential Bayesian log-odds residual over the validated anchor.

- Strict **matured-label-only** updates; unresolved observations never train themselves.
- Prequential predict-before-update monitoring and anchor-relative EWMA drift detection.
- Activation requires matured-label count, observation-date/span breadth, date-balanced non-inferiority, date-balanced calibration error, and no active drift alert — otherwise it falls back to the frozen anchor.
- Append-only local event store, privacy-safe aggregate source-health telemetry, versioned adaptive state.

Built-in free market polling is **near-real-time / best-effort**, not exchange-grade streaming. See [`REALTIME.md`](REALTIME.md).

---

## Three probabilities you must not conflate

| Concept | Example | Means |
|---|---|---|
| **Evidence-score posterior** | `P(score ≥ 8)` | Posterior mass above an evidence-score threshold. Not about returns. |
| **Anchor forward-event probability** | `63%` | Validated model's probability for the *exact event in its manifest* (e.g. outperform SPY by >0% over 252 trading days). |
| **Adaptive applied probability** | anchor ± residual | Anchor adjusted by the bounded residual **only** when its separate gate is active; otherwise the frozen anchor. |

None of these means a target price, an expected return, a chance of profit on every path, or a recommendation.

---

## API

Stable surface under `/api/v1/*`; forecasting/adaptive also under versioned namespaces. Swagger/OpenAPI at `/docs`.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/health` | App, engines, provider health, registry status |
| GET | `/api/v1/analyze/{ticker}` | Five-pillar evidence analysis (incl. Investor Posture) |
| GET | `/api/v1/screener` | Cached evidence universe |
| GET | `/api/v1/history/{ticker}` | Price-history context |
| GET | `/api/v4/forecast/status` | Validated anchor registry / activation status |
| GET | `/api/v4/model-lab/data` | Durable local corpus audit / provenance |
| POST | `/api/v4/model-lab/data/refresh` | Incrementally update the local research corpus |
| GET | `/api/v4/model-lab/recipes` | Cross-asset recipes plus local-data readiness |
| GET | `/api/v4/model-lab/experiments` | Candidate/rejection/interruption history |
| GET | `/api/v4/forecast/{ticker}` | Forward-event probability from a validated anchor |
| POST | `/api/v4/forecast/build` | Start an in-app model build (background job) |
| GET | `/api/v4/forecast/build/status` | In-app build progress |
| GET | `/api/v4/realtime/{ticker}` | Freshness-aware anchor + adaptive live snapshot |
| POST | `/api/v4/adaptive/process-matured` | Process eligible delayed outcomes into adaptive state |
| GET | `/api/v1/methodology` | Evidence + anchor + adaptive methodology |

---

## Tests and release verification

```bash
pip install -r requirements-dev.txt
python tools/verify_release.py
```

The verifier runs compilation, the full automated suite, JavaScript syntax validation, CSP/frontend dependency
scanning, anchor/adaptive dataset-hash verification, fixture-tier lockout, model/adaptive-artifact hash and
contract checks, forecast/realtime configuration drift checks, documentation consistency checks, and Docker
packaging/ownership checks. The current release gate passes **188 automated tests** before packaging.

A private owner handover may additionally include a `validated_research` 12-month monthly reference model. Its
manifest declares `REVIEW_REQUIRED`, so the public-source packager excludes the model artifact and bound evidence
until redistribution rights are explicitly cleared. Installation never pre-activates it; Live use still requires
explicit user activation.

---

## Documentation

[`ARCHITECTURE.md`](ARCHITECTURE.md) ·
[`MODEL_CARD.md`](MODEL_CARD.md) ·
[`FORECASTING.md`](FORECASTING.md) ·
[`REALTIME.md`](REALTIME.md) ·
[`VALIDATION_PROTOCOL.md`](VALIDATION_PROTOCOL.md) ·
[`SETTINGS.md`](SETTINGS.md) ·
[`DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md) ·
[`docs/DOCKER.md`](docs/DOCKER.md) ·
[`docs/HELP.md`](docs/HELP.md) ·
[`SECURITY.md`](SECURITY.md) ·
[`PRIVACY.md`](PRIVACY.md)

---

## License

**MIT** — see [`LICENSE`](LICENSE). Copyright © 2026 Rajeev Yadav. You may use, copy, modify and redistribute
FinCompass, including commercially, provided the MIT copyright and permission notice are retained. The software is
provided “as is”, without warranty of any kind.

---

<p align="center"><sub><strong>Educational only. Not financial advice or an assurance of future performance.</strong></sub></p>
