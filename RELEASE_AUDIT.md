# FinCompass 1.0 — Adaptive / Event-Driven Release Audit

**Review date:** 2026-08-23  
**Baseline:** FinCompass validation-gated probabilistic forecasting release  
**Release:** `1.2.0`  
**Evidence engine:** `1.0.0-evidence1`  
**Normalized-data schema:** `1.0.0-normalized1`  
**Forecast anchor engine:** `1.0.0-prob1`  
**Realtime/adaptive engine:** `1.0.0-adaptive1`  
**Event schema:** `1.0.0-event1`  
**Adaptive state schema:** `1.0.0-state1`

## 1. Executive assessment

FinCompass 1.0 is a material architectural release. It moves the product from a static evidence + periodically trained probabilistic forecasting workbench to a **three-plane governed system**:

1. Bayesian current-evidence scoring;
2. a frozen, historically validated forward-event anchor;
3. an event-driven adaptive residual that can react to newly available information while preserving delayed-label, temporal-breadth, calibration/performance and drift safeguards.

The central design decision is conservative: **fresh information can change a candidate prediction immediately, but it cannot train the model immediately**. Bayesian adaptive parameters update only after the original target has matured and the realized outcome is known.

This prevents “realtime” from becoming uncontrolled self-training or outcome leakage.

### Release conclusion

The v1.0.0 package is suitable as a **research/freeware release candidate** from a code/regression-governance perspective. The bundled anchor and adaptive artifacts are both intentionally `fixture_only`; the package ships **zero live-eligible market models/states**. Real-market forecasting or adaptive-skill claims still require external point-in-time market validation under the supplied protocol.

## 2. Scope reviewed

The release review covered:

- application/version/cache contracts;
- evidence engine compatibility;
- frozen forecast-anchor pipeline;
- realtime source acquisition semantics;
- normalized event store and source-health state;
- adaptive feature construction;
- sequential Bayesian residual update;
- delayed-label lifecycle;
- adaptive settings/state lineage;
- activation and drift controls;
- anchor and adaptive registries;
- API versioning and rate limiting;
- Live/Settings frontend integration;
- privacy/security exposure of source/event data;
- Docker packaging boundaries;
- synthetic anchor/adaptive validation fixtures;
- automated release verification and documentation consistency.

## 3. v1 architecture and statistical boundary

### 3.1 Frozen anchor

The validated historical forecasting model remains an independent contract. v1 does not relabel the unchanged anchor architecture; its engine remains `1.0.0-prob1`.

The anchor retains the v1 controls:

- point-in-time feature construction;
- purged chronological train/validation/locked-test splits;
- target-horizon purge + embargo at every internal calibration/stacking boundary;
- Bayesian logistic + histogram gradient boosting + random forest ensemble;
- dedicated validation-stage stacking;
- final probability calibration;
- locked-test Brier/log-loss/AUC/calibration gates;
- moving observation-date-block + same-date cross-sectional bootstrap;
- purged/embargoed walk-forward stability;
- artifact SHA-256/model-ID binding;
- `fixture_only` / `rejected` / `validated_research` / `validated_market` tiers.

### 3.2 Adaptive residual

For an eligible anchor probability `p0`:

`logit(p_candidate) = logit(p0) + delta(x_event)`

The residual is a sequential Bayesian logistic approximation with Gaussian posterior state, configurable prior scale, forgetting factor and process noise. The applied residual is bounded by `adaptive_max_logit_shift` and can be forced to zero independently of the candidate prediction.

This design provides a deterministic fallback to the frozen anchor.

### 3.3 Anchor feature protection

A key v1 correction is that intraday observations do **not** overwrite the daily feature semantics of an anchor trained on daily snapshots. Fresh intraday/filing/macro information enters through the adaptive vector only.

This prevents a hidden feature-distribution change from being mislabeled as a realtime update to a validated anchor.

## 4. Event-source and freshness controls

### 4.1 Market

The freeware reference path uses best-effort yfinance/Yahoo polling. It is explicitly not represented as direct-exchange/tick streaming.

Improvements implemented:

- `market_return_1d` is prior-session close -> latest price, preserving overnight gaps;
- benchmark return uses the same boundary;
- market event and provider-check state are keyed by ticker + benchmark;
- short return/relative-return/volume z-context and intraday range are normalized into the event vector;
- stale market context prevents an adaptive market shift from being applied.

### 4.2 SEC

The live filing path records latest filing metadata/source time. Form/freshness signals decay exponentially by event age.

Separately, provider verification is monitored. If no successful SEC check occurs within the configured maximum staleness interval, SEC adaptive contributions are forced to zero until verification resumes.

This correctly distinguishes “the latest known filing is old” from “FinCompass may be missing a newer filing because the provider check is stale.”

### 4.3 Macro

FRED current-vintage yield-curve and high-yield spread changes are freshness-decayed. Provider-verification staleness is handled independently from event age.

Historical market validation must use vintage-aware reconstruction; current revised macro history cannot be copied backward as if revisions had been known in the past.

### 4.4 Provider cadence/deduplication defect fixed

An early v1 implementation scheduled polling from immutable event receipt time. When the provider returned the same event repeatedly, deduplication preserved the original timestamp and could therefore cause a provider to be polled again on every UI refresh after the cadence elapsed.

v1 final behavior schedules polling from explicit **last provider-check state**, while preserving immutable event provenance. Regression coverage was added.

## 5. Adaptive feature contract

The reference residual uses 13 features:

1. market return, prior session close -> latest;
2. benchmark-relative return;
3. rolling market return z-score;
4. rolling relative-return z-score;
5. volume z-score;
6. intraday range percentage;
7. exponentially decayed SEC filing freshness;
8. freshness-weighted 8-K/6-K indicator;
9. freshness-weighted 10-Q indicator;
10. freshness-weighted 10-K-family indicator;
11. freshness-weighted yield-curve change;
12. freshness-weighted high-yield spread change;
13. macro freshness.

External operator events remain `context_only` by default and therefore do not alter probability without a separately validated feature contract.

## 6. Delayed-label and state-lineage governance

### 6.1 No unresolved-outcome learning

New observations can update candidate probability immediately, but `state.update(...)` is reserved for matured labels.

Each matured target is processed in strict predict-before-update order:

1. score with the pre-outcome state;
2. record anchor/adaptive prequential losses;
3. update drift monitoring;
4. reveal the label;
5. update posterior state;
6. reevaluate activation.

### 6.2 Effective sample-size safeguard

Frequent refreshes must not create fake independent evidence.

The pending-label identity is limited to one observation per:

`ticker + anchor model + adaptive settings lineage + UTC observation date`

The activation gate separately requires a configurable minimum matured count, **unique observation dates**, and elapsed observation span.

### 6.3 Cross-configuration contamination defect fixed

Pending labels now preserve:

- adaptive settings fingerprint;
- complete originating adaptive settings contract;
- benchmark/target contract;
- event vector/entry prices.

When the label matures, it updates only the corresponding posterior lineage. Switching Balanced/Responsive/Conservative or custom settings cannot consume another profile's delayed outcome.

### 6.4 Adaptive identity

The immutable adaptive artifact identity is bound to:

- state SHA-256;
- base model ID;
- full settings contract;
- settings fingerprint;
- feature names;
- realtime engine version.

The adaptive ID is derived from that contract SHA-256.

## 7. Online Bayesian numerical implementation

An early implementation computed repeated pseudoinverses of the posterior covariance for each matured label. For a continuous adaptive workflow this was unnecessarily expensive and a numerical maintenance risk.

The final v1 sequential Gaussian approximation uses the algebraically equivalent **Woodbury/Sherman-Morrison rank-one covariance update**. This removes repeated matrix pseudoinversion from the matured-label hot path while preserving the intended online update semantics.

## 8. Activation and drift governance

### 8.1 Observation-date evaluation window

An important late-stage statistical correction changed the online evaluation window from “most recent N rows” to **most recent N observation dates**.

All observations on retained dates remain included, but Brier/log-loss are averaged with equal date weights. This prevents a large cross-sectional watchlist from either manufacturing or overwhelming temporal evidence merely through row count.

### 8.2 Activation checks

The residual can become active only when all configured checks pass:

- minimum matured labels;
- minimum unique observation dates;
- minimum elapsed observation span;
- Brier non-inferiority vs exact frozen anchor;
- log-loss non-inferiority vs exact frozen anchor;
- ECE within limit;
- no active anchor-relative drift alert.

### 8.3 Drift monitor

The final reference drift control is a variance-scaled EWMA on:

`adaptive Brier loss - anchor Brier loss`

An earlier Page-Hinkley-like threshold proved overly sensitive at the bounded Brier-differential scale in synthetic regression testing. The final EWMA formulation is calibrated to the monitored loss distribution and can recover when deterioration resolves. Reactivation still requires the full gate.

## 9. Bundled anchor regression fixture

The v1 anchor regression fixture remains bundled intentionally to verify the unchanged anchor contract.

### Artifact

- model ID: `efd41fec7d9d24fd`
- model SHA-256: `efd41fec7d9d24fd79756b6fd02619f1d501c1ece465598bae3b9fe413487711`
- validation tier: `fixture_only`

### Data

- training: 6,528 rows;
- validation: 1,920 rows;
- locked test: 2,304 rows / 72 observation dates.

### Locked synthetic test

| Metric | Result |
|---|---:|
| Brier skill | 0.117815 |
| Log-loss skill | 0.091430 |
| ROC AUC | 0.699801 |
| Average precision | 0.623286 |
| ECE | 0.035934 |
| Calibration slope | 0.800691 |

The 90% moving-block bootstrap lower bounds are approximately 0.10898 Brier skill, 0.08343 log-loss skill and 0.69373 ROC AUC; the ECE upper bound is approximately 0.04917. All four development walk-forward folds show positive Brier skill.

This remains synthetic software/statistical evidence only.

## 10. Bundled adaptive streaming regression fixture

### Data/hashes

- warmup observations: 1,200;
- warmup SHA-256: `5c6151bcb49ed69aabce0d855eb2bd9beba2a87c64139663671a52f0752e458e`;
- locked observations: 600;
- locked SHA-256: `7890f78e80f6c5b4898fe302c7e3f5f0386756ca6874b9092ffcce766a8f7785`;
- fixture-manifest SHA-256: `819855bf072e066ceaca84ff75f6d6f04d560233c4808442a8e7d8bf86336557`.

### Adaptive artifact

- adaptive ID: `50732cca02f306ed`;
- base anchor: `efd41fec7d9d24fd`;
- settings fingerprint: `f54949dee65f84d6`;
- state SHA-256: `200704ed3add4c16728d923795feeaca670441f83eb347a169cb691b9c3f7ee3`;
- contract SHA-256: `50732cca02f306edfe35b3b6c9d40c44b375ee495de34f9c746874425e8f090a`;
- tier: `fixture_only`.

### Locked stream results

| Metric | Frozen anchor | Adaptive evaluation | Improvement |
|---|---:|---:|---:|
| Brier | 0.235658 | 0.204069 | +0.031588 |
| Log loss | 0.664106 | 0.596988 | +0.067118 |

Final recent-date gate after the locked stream:

- 250 evaluated observation dates;
- 250 unique dates;
- 498-day span;
- Brier improvement: +0.037821;
- log-loss improvement: +0.079019;
- ECE: 0.061924;
- drift triggered: false;
- all configured checks: pass.

The saved 1,200-row warm-start state passes the synthetic warmup gate, and the locked evaluation copy independently continues to pass. The validation report preserves both phases separately.

Because the entire stream is synthetic and its market-data controls are not real-market evidence, the artifact remains `fixture_only` and cannot warm-start live probability output.

## 11. Privacy/security hardening specific to v1

### Closed issues

- raw ticker/benchmark-scoped provider-status keys are not exposed by public realtime status;
- public external-event views redact operator payloads;
- external ingest is disabled without an explicit bearer secret;
- constant-time token comparison is used;
- market/provider source state is scoped to prevent cross-ticker/benchmark evidence reuse;
- adaptive state/pending labels are settings-fingerprint bound;
- synthetic/rejected adaptive artifacts fail closed;
- stale/warming/degraded/incompatible adaptive state applies zero residual;
- dedicated realtime, adaptive-maintenance and ingest rate-limit groups are present.

The public health/status layer reports aggregate provider health rather than another user's research symbols in a shared deployment.

## 12. UI/product integration

v1 adds a dedicated **Live** workspace rather than overloading the static Forecast card.

The Live surface exposes:

- anchor probability;
- adaptive candidate/applied probability;
- whether the shift is permitted;
- state/gate/drift status;
- event/source timestamps and freshness;
- provider verification;
- top feature-level log-odds contributions;
- recent sanitized event chronology;
- adaptive settings profile/lineage.

The Settings workspace exposes validated typed realtime profiles (`balanced`, `responsive`, `conservative`) and complete JSON contracts. Changing adaptive learning semantics creates a new state lineage rather than silently mutating an existing artifact.

## 13. API / compatibility

v1 retains `/api/v1/*` evidence compatibility and `/api/v1/*` forecast compatibility while introducing semantic v1 surfaces:

- `/api/v1/forecast/*` — frozen validated anchor;
- `/api/v1/realtime/*` — freshness-aware live state;
- `/api/v1/adaptive/*` — matured-label maintenance;
- `/api/v1/events/*` — authenticated operator ingest;
- `/api/v1/settings/schema` — combined settings schema;
- `/api/v1/methodology` — combined methodology.

This namespace separation reduces the risk that an evidence posterior, frozen forward-event forecast and adaptive live probability are confused as the same statistical object.

## 14. Automated release verification

The frozen v1.2.0 source tree passes:

**115 / 115 automated tests**

plus:

- Python compilation;
- JavaScript syntax validation;
- strict frontend CSP/no-runtime-CDN scan;
- v1 Live workspace/API wiring scan;
- anchor fixture hash/temporal/tier validation;
- adaptive fixture/hash/stream-validation checks;
- anchor model SHA/model-ID binding;
- adaptive state SHA/contract/adaptive-ID binding;
- synthetic live-lockout checks for anchor and adaptive registries;
- forecast/realtime configuration-profile drift checks;
- Docker packaging/ownership static checks;
- documentation consistency checks before final packaging.

The automated suite includes regressions for ticker/benchmark polling scope, provider-check cadence, previous-session-close one-day return, provider-verification staleness, settings-lineage delayed labels, observation-date evaluation windows, external-payload redaction, fixture lockout and frontend adaptive registry/status semantics.

## 15. Market-data limitations / claims not made

The release does not claim:

- direct-exchange or tick-grade streaming;
- predictive value for any event solely because it is recent;
- validated real-market incremental adaptive skill from the bundled synthetic stream;
- comprehensive historical-universe/delisting coverage from the default freeware dataset path;
- guaranteed corporate-action equivalence across free providers;
- permanent calibration after model/adaptive activation;
- profitability, suitability or individualized investment advice.

`validated_market` requires external evidence for point-in-time information, no-lookahead event reconstruction, survivorship/delisting controls and corporate-action-adjusted prices. The bundled artifacts deliberately do not satisfy that market claim.

## 16. Required external validation before stronger claims

Before describing v1 as validated realtime/adaptive market forecasting, the release owner should:

1. build a real timestamped historical event stream with source/effective times;
2. reconstruct macro series with correct historical vintages;
3. document historical universe/survivorship/delisting handling;
4. independently verify stock/benchmark corporate-action treatment;
5. pre-register the frozen anchor, adaptive feature contract, update/gate settings and untouched event-test interval;
6. validate incremental adaptive Brier/log-loss/calibration versus the exact frozen anchor across multiple regimes;
7. run stale-provider/outage simulations;
8. validate any licensed news/NLP/event feed independently before predictive use;
9. complete real browser assistive-technology testing;
10. complete deployment-specific TLS/reverse-proxy/Docker smoke testing and, for high-traffic operation, an independent security review.

## 17. Release disposition

**Code/statistical regression status:** PASS  
**Bundled anchor market-forecast status:** `fixture_only`  
**Bundled adaptive market-skill status:** `fixture_only`  
**Live-eligible bundled anchor models:** 0  
**Live-eligible bundled adaptive states:** 0

FinCompass 1.0 therefore ships a substantially stronger adaptive forecasting architecture while preserving a fail-closed claims boundary: the software can ingest and reason over new information continuously, but the package does not promote synthetic validation into market credibility.
