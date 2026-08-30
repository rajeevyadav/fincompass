# FinanceToolkit Adoption Matrix

External reference: <https://github.com/JerBouma/FinanceToolkit> (MIT). This matrix records, per capability area, how FinCompass will (or will not) use it. **No FinanceToolkit code has been copied or vendored yet** — see `THIRD_PARTY_NOTICES.md`. FinCompass's core freeware operation must never require FinanceToolkit or a paid provider.

Decision legend: `ADOPT_CODE` (vendor MIT code, isolated + attributed) · `ADAPT_CONCEPT` (reimplement natively from the public formula) · `USE_AS_REFERENCE` (cross-check only) · `NOT_NEEDED` · `DEFER` (after Track A lifecycle is green) · `BLOCKED_BY_DATA` · `BLOCKED_BY_LICENSE`.

| FinanceToolkit capability | FinCompass target | Decision | Reason | License action | Data need | Test strategy |
|---|---|---|---|---|---|---|
| ratios/ (profitability, liquidity, leverage, efficiency, valuation, per-share) | `analytics/ratios` | ADAPT_CONCEPT | transparent, stable formulas; native keeps provider independence | none (no copy) | normalized statements (free: yfinance/SEC) | hand-calc unit tests + FinanceToolkit cross-check |
| performance/ (returns, Sharpe/Sortino/Calmar, beta/alpha, capture) | `analytics/performance` | ADAPT_CONCEPT | standard formulas; explicit annualization | none | prices (local store) | hand-calc + edge cases |
| risk/ (vol, EWMA, drawdown, VaR, CVaR, EVT) | `analytics/risk` | ADAPT_CONCEPT | must control VaR wording (never "max loss") | none | prices | hand-calc + distribution tests |
| technicals/ (SMA/EMA/MACD/RSI/ATR/Bollinger…) | `analytics/technicals` | ADAPT_CONCEPT | deterministic; not auto Forecast features | none | prices | reference series |
| econometrics/ (OLS, rolling reg, diagnostics) | `analytics/econometrics` (Research) | ADAPT_CONCEPT | keep "significance ≠ investment significance" | none | any | numpy/statsmodels-style checks |
| economics/ (GDP, CPI, rates, curve) | `analytics/economics` | DEFER | needs vintage/point-in-time handling | none | FRED (free) | vintage-aware tests |
| fixedincome/ (PV, YTM, duration, convexity) | `analytics/fixed_income` | ADAPT_CONCEPT | closed-form; testable with known inputs | none | user inputs | known-answer tests |
| options/ (BSM, binomial, Greeks, IV) | `analytics/options` | ADAPT_CONCEPT | closed-form; state assumptions | none | user inputs | known-answer Greeks |
| portfolio/ (weights, risk contribution, allocation) | `analytics/portfolio` | ADAPT_CONCEPT | local-first; never avg Forecast probs | none | local holdings | synthetic portfolios |
| performance factor models (FF factors) | `analytics/factors` | DEFER | factor data licensing/sourcing to verify | verify factor-data license | factor returns | loading/rolling tests |
| normalization/ (statement field mapping) | `analytics/normalization` | ADAPT_CONCEPT | must not equate different accounting fields | none | statements | provenance tests |
| cache/ | existing FinCompass cache/research store | NOT_NEEDED | FinCompass already has a durable store | none | — | existing |
| discovery/ | existing `market_catalog` + instrument catalog | ADAPT_CONCEPT | keep provider abstraction | none | free providers | existing + new |
| FinanceDatabase (symbol DB) | instrument catalog | BLOCKED_BY_LICENSE | separate license/redistribution terms unverified | verify before any copy | — | n/a until cleared |
| Jupyter/notebook tooling | — | NOT_NEEDED | not a runtime dependency | none | — | — |

**This cycle:** Track A (retrain/replacement lifecycle) is the release-critical priority; all Track B analytics are `DEFER`/`ADAPT_CONCEPT` and **not yet implemented**. When implemented, each metric gets a versioned formula-registry entry, an independent hand-calculated unit test, and an optional FinanceToolkit cross-check (never the sole oracle).
