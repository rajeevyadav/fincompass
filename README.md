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

Local research workbench for one question:

> Over the next year, how likely is this company to do better than the S&P 500?

It runs on your machine. No account, no subscription, no ad network, no cloud model API.

A Forecast is a probability for that exact event. It is not a target price, not expected return, and not advice to buy or sell.

---

## What it is

Four layers, kept apart on purpose.

| Layer | Job |
|---|---|
| **Evidence** | 0–10 snapshot of quality, durability, safety, valuation, cycle. About *now*, not next year. |
| **Forecast** | Calibrated probability that the name beats a stated benchmark over a stated horizon. |
| **Live** | Watches the frozen Forecast. A Limited-evidence model is tracking only. A stronger model may apply a small residual only after delayed outcomes pass a gate. |
| **Analytics** | Performance, risk, statements, ratios, DCF, bonds, options, portfolio, factors. Useful desks. Not Forecast features unless a versioned contract admits them. |

Two screens, one number:

- **Guided** — ticker in, percent out, a plain evidence label, and at most five verbs: Don't decide, Watch, DCA a little, Hold, Trim. Limited evidence may only Watch.
- **Research** — the same percent as an equation: target, features, split, scores, tier, manifest.

If Guided and Research ever disagree on *p*, the product is wrong.

---

## Get started

The end user should not need a terminal.

| Platform | How |
|---|---|
| Windows installer | Run the Setup executable. Launch from the Start menu. Windowed, no console. |
| Windows portable | Double-click `run.bat`. |
| macOS / Linux | `./run.sh` |

The app opens at [http://127.0.0.1:8000/](http://127.0.0.1:8000/). Watchlist, settings, local prices, and models you build live in a per-user directory and survive upgrades.

**From source**

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn api:app --host 127.0.0.1 --port 8000
```

Desktop build (Windows):

```text
build_exe.bat            # dist\FinCompass.exe
build_installer.bat      # versioned Setup (Inno Setup)
```

---

## Normal path

```text
ticker → identify market → check local data → pooled family model → Forecast → Watch / Start Live
```

You do not train a private model for every new US common stock. The ticker supplies today's features. The family model was fit on a declared universe.

If prices are missing, update data and continue. If the family study is old, Forecast can stay available; refreshing the study is optional. If a refresh fails, the current Forecast stays.

Default Guided horizon is **12 months versus the S&P 500 family**. Other horizons belong in Research.

---

## Model ladder

Validity is not the same thing as skill.

| Tier | Meaning | Forecast | Live |
|---|---|---|---|
| Invalid | Broken chronology, fit, features, or domain | No | No |
| Limited evidence (Bayesian baseline) | Coherent probability; stronger skill not shown | Yes | Tracking only |
| Research validated | Configured locked-test gates passed on the declared corpus | Yes | Adaptive eligible, still gated |
| Market validated | Those gates plus stronger universe and point-in-time controls | Yes | Same |

Shipped 12-month US artifacts include Bayesian baselines at 6 / 12 / 24 / 36 months and one research-validated 12-month ensemble. Regime models are research alternatives, not Guided defaults.

The bundled historical sample is small and survivorship-incomplete. Locked-test skill on that sample is modest. Treat bundled percents as a demonstration of the machinery, not as proof the market is predictable. On that sample, many names print nearly the same probability — roughly the historical hit rate. Guided should say so.

---

## What a percent means

**61% · next 12 months · versus the S&P 500 · studied guess**

means: under this model and contract, the estimated probability of that event is 0.61.

It does not mean the stock rises 61%, the model is 61% accurate, or you should buy it.

Limited evidence → Watch.
Research validated may allow DCA a little / Hold / Trim under a versioned action policy. That policy sits *on* the probability. It is not inside the trainer. There is no "buy all" and no auto position size.

---

## Data

Forecast training uses a durable local research store. Updates fetch an overlap window and the missing tail, journal revisions, and keep source hashes. Training does not silently download a new universe.

SEC-style fundamentals, when a model asks for them, join on **filing date**, not fiscal period-end.

---

## Develop

| Path | Role |
|---|---|
| `forecasting/` | Features, split, Bayesian reference, ensemble, metrics, registry |
| `services/` | Forecast plan, selection, freshness, research store, action policy |
| `realtime/` | Live residual, gate, pending labels |
| `analytics/` | Deterministic calculations |
| `models/` | Bundled artifacts and manifests |
| `tests/` | Behaviour tests |
| `docs/` / `paper/` | User guide and manuscript sources |

Run tests with `pytest`. Do not treat a green unit suite as proof that a packaged new ticker can Forecast and start Live. That path needs a packaged run.

Comments explain invariants, not tickets. Process labels (tracks, phases, directive IDs) do not belong in production source.

---

## Limits

- Not investment advice. Not a broker.
- No universal model. Wrong asset class or region → no Forecast, analytics may still run.
- Long-horizon labels overlap. Row count is not independent sample size.
- Free public prices can be revised, late, or missing.
- Live adaptation can stay frozen for a long time. That is correct when labels have not matured.
- A high evidence score is not a high Forecast. A DCF is not a Forecast.

---

## License and privacy

See `LICENSE`, `PRIVACY.md`, and `THIRD_PARTY_NOTICES.md`. Research data and models stay on the machine that runs the app unless you export them.

---

## Disclaimer

Educational research software. A probability can be wrong on this name and this date. Position size, tax, and suitability are yours.
