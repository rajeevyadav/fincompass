# FinCompass — Statistical Model Card

## 1. Scope

FinCompass contains **three separately governed analytical layers**. They must not be interpreted as one interchangeable score:

1. **Bayesian evidence score** — uncertainty-aware 0–10 research score from current fundamental/macro evidence.
2. **Forecast anchor** — calibrated forward-event probability learned from historical point-in-time data and activated only after locked temporal validation.
3. **Adaptive residual** — bounded sequential Bayesian log-odds correction driven by timestamped new information and activated only after separate prequential validation against the exact frozen anchor.

FinCompass is research software, not investment advice. None of these outputs is a guarantee of future performance.

## 2. Version identifiers

| Contract | Version |
|---|---|
| Application | `1.2.0` |
| Evidence engine | `1.0.0-evidence1` |
| Normalized data schema | `1.0.0-normalized1` |
| Forecast anchor engine | `1.0.0-prob1` |
| Realtime/adaptive engine | `1.0.0-adaptive1` |
| Event schema | `1.0.0-event1` |
| Adaptive state schema | `1.0.0-state1` |

The anchor engine and the adaptive layer are versioned independently; the adaptive layer sits alongside the validated anchor rather than changing its contract.

---

# Part A — Bayesian evidence score

## A1. Intended use

The evidence engine summarizes currently available company evidence across:

- Quality
- Financial Durability
- Safety
- Valuation
- Cycle

It is useful for structured screening/comparison and evidence inspection. It is **not** an estimate of the probability of a stock outperforming a benchmark.

## A2. Method

Metric values are transformed through continuous evidence functions rather than abrupt threshold buckets. Available evidence is aggregated with Bayesian shrinkage toward neutral when coverage is sparse. The engine reports:

- 0–10 composite score;
- pillar scores;
- evidence coverage;
- posterior uncertainty;
- dependence-sensitive composite interval;
- threshold probability ranges;
- data completeness/provider context.

Pillar dependence is not assumed away. Composite sensitivity includes independent and positively coupled scenarios rather than presenting an artificially narrow interval based on unsupported independence.

## A3. Limitations

The evidence model is heuristic/model-based research scoring. Its priors and evidence transforms are not empirical return probabilities. Missing/incorrect provider data can affect output. Financial-sector accounting semantics can differ materially from industrial-company ratios.

---

# Part B — Forecast anchor

## B1. Intended target

The default strict target is a binary forward event:

`stock forward return > benchmark forward return + hurdle`

under the exact horizon, benchmark, hurdle, sampling and price-series semantics recorded in the model/dataset manifests.

Changing target-defining settings creates a new forecasting problem and requires dataset reconstruction/retraining.

## B2. Learners

The reference anchor ensemble contains:

- Bayesian logistic regression with Gaussian prior, MAP fit and Laplace posterior covariance;
- histogram gradient boosting;
- regularized random forest;
- non-negative, sum-to-one stacking weights learned on a dedicated chronological validation stage.

## B3. Calibration / fitting separation

The historical pipeline uses chronological train, validation and locked-test regions. The validation region is split into three responsibilities:

1. component calibration;
2. ensemble stacking;
3. final ensemble calibration.

Each internal validation boundary is target-horizon purged so an earlier stage's forward label resolves before the next fitting stage begins. The configured business-day embargo is applied by the outer train/validation/test split and is not duplicated inside each validation role.

The locked test fits no parameter.

## B4. Anchor validation metrics

Acceptance evidence includes:

- Brier score and skill;
- log loss and skill;
- ROC AUC;
- average precision;
- expected calibration error;
- calibration slope/intercept;
- minimum test rows/classes;
- minimum unique test dates and elapsed test span;
- purged/embargoed walk-forward stability;
- moving observation-date-block + same-date cross-sectional cluster-bootstrap uncertainty.

The bootstrap moves consecutive observation-date blocks and carries all securities on a selected date together. This better represents serial dependence from overlapping horizons and same-date cross-sectional dependence than row-wise resampling.

## B5. Validation tiers

- `fixture_only` — synthetic software/statistical regression only; never live-eligible.
- `rejected` — failed configured validation gates.
- `validated_research` — statistical gates passed on real historical data, but documented market-data limitations remain.
- `validated_market` — statistical gates passed and the dataset documents evidence for point-in-time features, survivorship/delisting controls and corporate-action-adjusted market data.

## B6. Bundled anchor fixture

The bundled deterministic synthetic reference anchor is deliberately `fixture_only`.

Model ID: `efd41fec7d9d24fd`

Locked synthetic test summary:

| Metric | Result |
|---|---:|
| Test rows | 2,304 |
| Test observation dates | 72 |
| Brier skill | 0.117815 |
| Log-loss skill | 0.091430 |
| ROC AUC | 0.699801 |
| Average precision | 0.623286 |
| ECE | 0.035934 |
| Calibration slope | 0.800691 |

The strict moving-block bootstrap lower bounds remain positive for Brier/log-loss skill, and all four development walk-forward folds have positive Brier skill. These results establish deterministic statistical-pipeline regression behavior against a known simulated signal only; they do not establish market alpha.

---

## B7. Private bundled 12-month research reference

The private owner handover can include one real-history reference anchor in addition to the deterministic fixture.
It is **not part of the public-source package** because its provenance sharing state is `REVIEW_REQUIRED`.

- Model ID: `80e63fcbc21ce820`
- Validation tier: `validated_research`
- Target: asset monthly-close return over 12 months exceeds S&P 500 monthly-close return over the same interval
- Runtime feature contract: `monthly_relative_v1` (observed daily/live histories are aggregated to month-end; missing daily observations are not fabricated)
- Training period recorded in manifest: 1990-01-31 through 2022-06-30
- Upstream sample declaration recorded in manifest: Yahoo Finance via Matplotlib `sample_data/Stocks.csv`
- Sharing status: `REVIEW_REQUIRED`
- Activation: explicit only; no active-model pointer is shipped

Locked-test evidence (100 moving-date-block bootstrap draws):

| Metric | Result |
|---|---:|
| Test rows | 532 |
| Distinct test dates | 76 |
| Test span | 2,283 days |
| ROC AUC | 0.576221 |
| Brier skill | 0.036425 |
| Log-loss skill | 0.026983 |
| ECE | 0.044712 |
| Calibration slope | 1.272327 |

All 14 configured exploratory gate checks passed without changing their thresholds. This supports the
`validated_research` designation only. It does **not** establish a `validated_market` tier, future investment
performance, or redistribution rights for the trained artifact. The 6-month and 24-month prototypes tested during
this checkpoint remained rejected by their configured gates; the available monthly history did not support a
three-stage leakage-safe 36-month calibration protocol. Failed horizons were not promoted.

---

# Part C — Adaptive realtime residual

## C1. Purpose

The adaptive layer addresses the fact that a frozen historical model cannot directly reflect newly arrived information between full retraining cycles.

It does **not** discard historical validation. The frozen anchor remains the baseline probability `p0`; new timestamped event evidence is modeled as a separately governed residual:

`logit(p_candidate) = logit(p0) + delta(x_event)`

Only an `active` adaptive state may apply a bounded non-zero `delta`.

## C2. Reference event features

- previous-session-close -> latest stock return;
- matching benchmark-relative return;
- rolling stock/relative return z-scores;
- volume z-score;
- intraday range percentage;
- exponentially decayed SEC filing freshness;
- freshness-weighted filing-family indicators;
- freshness-weighted yield-curve change;
- freshness-weighted high-yield credit-spread change.

The base anchor retains its validated daily feature semantics; intraday event data is not injected directly into the anchor.

## C3. Online Bayesian method

The residual is a sequential logistic approximation with a Gaussian posterior state. Controls include:

- prior scale;
- forgetting factor;
- process noise;
- output probability clip;
- maximum absolute logit shift.

Outcomes update the posterior only after maturity, in predict-before-update order. Maturity resolution uses the exact H-th common stock/benchmark trading-session endpoint after the observation date rather than the latest price at job-run time. The covariance update uses a rank-one Woodbury/Sherman-Morrison form rather than repeated pseudoinversion.

## C4. Adaptive activation gate

A correction may apply only when all checks pass:

- minimum matured labels;
- minimum unique observation dates;
- minimum elapsed observation span;
- date-balanced adaptive Brier non-inferiority vs exact frozen anchor;
- date-balanced adaptive log-loss non-inferiority vs exact frozen anchor;
- date-balanced ECE below configured maximum;
- no current anchor-relative variance-scaled EWMA deterioration alert.

The rolling evaluation window is measured in **observation dates**, not rows. All observations on each included date remain in the evaluation, but Brier/log-loss weight dates equally. This prevents ticker breadth from being mistaken for temporal sample size.

## C5. State lineage / configuration governance

Adaptive state is bound to:

- exact base model ID;
- full adaptive settings contract;
- settings fingerprint;
- realtime engine version;
- feature list;
- serialized state hash;
- validation dataset/stream manifest.

Changing Balanced/Responsive/Conservative/custom learning semantics creates a different state lineage. Pending labels preserve the originating settings contract and update only that lineage at maturity.

## C6. Freshness and fail-closed behavior

v1 distinguishes event age from provider-verification age.

- Event effects decay by age.
- SEC/macro features are suppressed if the last successful provider verification exceeds the configured safety limit.
- Stale market context cannot apply an adaptive market residual.
- Warming/degraded/incompatible states apply zero shift.
- External operator events are context-only by default.

## C7. Bundled adaptive fixture

The bundled adaptive artifact is synthetic `fixture_only` and cannot warm-start live predictions.

- Adaptive ID: `50732cca02f306ed`
- Base model: `efd41fec7d9d24fd`
- Settings fingerprint: `f54949dee65f84d6`
- State SHA-256: `200704ed3add4c16728d923795feeaca670441f83eb347a169cb691b9c3f7ee3`
- Contract SHA-256: `50732cca02f306edfe35b3b6c9d40c44b375ee495de34f9c746874425e8f090a`

Locked 600-observation synthetic stream:

| Metric | Anchor | Adaptive | Absolute improvement |
|---|---:|---:|---:|
| Brier | 0.235658 | 0.204069 | +0.031588 |
| Log loss | 0.664106 | 0.596988 | +0.067118 |

Final recent-date gate after the locked stream:

- 250 unique observation dates;
- 498-day observation span;
- Brier improvement +0.037821;
- log-loss improvement +0.079019;
- ECE 0.061924;
- no drift alert;
- all configured gate checks pass.

The saved warm-start fixture state passes its synthetic end-of-warmup gate, and the locked evaluation copy independently continues to pass. Because the entire artifact is synthetic, it remains `fixture_only` regardless of these metrics.

---

# Part D — Data and operational limitations

## D1. Public/free data

Free market polling is best-effort and may be delayed, incomplete or rate-limited. It is not represented as direct-exchange streaming.

SEC filing timing uses EDGAR acceptance time when available (with filing-date fallback), but concept coverage differs by issuer. Current-vintage FRED macro data must not be treated as historically unrevised; market-grade macro backtests require vintage-aware reconstruction.

The default free historical universe cannot prove comprehensive survivorship/delisting coverage and therefore cannot automatically earn `validated_market`.

## D2. External event feeds

Operator-ingested events require authorization and are context-only in the reference implementation. A licensed/news/NLP source needs its own timestamp contract, rights review, feature definition and incremental validation before it may affect probability.

## D3. Non-stationarity

Neither anchor nor adaptive validation guarantees future calibration. Structural breaks, changing market microstructure, provider changes, issuer behavior and regime shifts can invalidate learned relationships. v1 therefore preserves the frozen anchor, monitors adaptive prequential performance, supports degradation/zero-shift fallback, and keeps model/state identities immutable.

## D4. Decision boundary

A forecast probability is not expected return, target price, trade sizing, portfolio allocation or personalized advice. Transaction costs, taxes, liquidity, borrow, slippage, tail loss and capacity are not fully represented by the binary event probability.

## Compatibility note

The forecast anchor engine remains `1.0.0-prob1` for compatibility and provenance. v1's new behavior is carried by application/evidence/data versions and the `1.0.0-adaptive1` realtime residual contract. This is intentional version separation, not stale labeling.
