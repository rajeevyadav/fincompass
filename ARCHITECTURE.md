# FinCompass 1.0.0 — Architecture

## 1. Product boundary

FinCompass 1.0 is a local/self-hosted research workbench with **three deliberately separated analytical planes**:

```text
CURRENT PUBLIC FUNDAMENTALS / MACRO
            |
            v
 normalization -> peer context -> Bayesian evidence score -> screener / compare / watchlist

HISTORICAL POINT-IN-TIME DATA
            |
            v
 feature builder -> purged temporal splits -> train/calibrate -> locked test -> anchor registry
                                                                            |
                                                                            v
                                                                validated anchor p0
                                                                            |
FRESH TIMESTAMPED EVENTS                                                    |
 market / filings / macro -> event store -> adaptive features --------------+
                                                                            |
                                                                            v
                                                     gated Bayesian residual delta
                                                                            |
                                                                            v
                                                             live probability p_live

DELAYED OUTCOMES
 pending prediction -> exact H-th common-session target -> realized label -> predict-before-update -> adaptive state/gate
```

The evidence score is not a return forecast. The anchor forecast and adaptive residual are independently versioned and independently gated. If no eligible anchor exists, FinCompass does not invent a forecast. If an adaptive state is warming, degraded, stale, incompatible with the selected settings, or not live-eligible, its applied residual is zero.

## 2. Versioned analytical contracts

- Application: `1.2.0`
- Evidence engine: `1.0.0-evidence1`
- Normalized data schema: `1.0.0-normalized1`
- Forecast anchor engine: `1.0.0-prob1`
- Realtime/adaptive engine: `1.0.0-adaptive1`
- Event schema: `1.0.0-event1`
- Adaptive state schema: `1.0.0-state1`

A version change invalidates only the state/cache family whose semantics changed. The evidence, realtime and adaptive contracts are versioned independently of the frozen anchor engine.

## 3. Evidence plane

The evidence plane retains the hardened Bayesian research workflow:

- provider normalization and unit correction;
- schema-versioned fundamental cache;
- robust live peer medians/IQRs;
- continuous metric evidence functions;
- Bayesian sparse-evidence shrinkage;
- dependence-sensitive composite uncertainty;
- provider health and background screener refresh;
- watchlist, compare, screener and CSV export workflows.

It can operate when no forecast model exists.

**Design constraint (carried forward from prior versions, restated here so it
isn't lost in future rewrites):** no signal anywhere in the Evidence plane's
Cycle pillar may be a fixed-calendar or non-causal cycle theory — no Benner
cycle, no 18.6-year land cycle, no similarly-shaped repeating-calendar
overlay, regardless of how it's badged (reference, context, "just FYI"). Every
Cycle-pillar signal must have a real, live-data-driven causal mechanism
(credit markets pricing risk, yield curve reflecting rate expectations,
commodity price relative to trend). This constraint is about the *Evidence*
score specifically; it does not prohibit the separately-gated Forecast-anchor
or Adaptive planes below, which are allowed to be predictive because they are
explicitly labeled as forecasts and validation-gated rather than presented as
default context on every ticker.

## 4. Forecast-anchor plane

### 4.1 Dataset construction

`forecasting/features.py` creates backward-looking market features. Forward shifts are confined to target construction so leakage checks can establish that changing future prices cannot alter earlier features.

`forecasting/sec_fundamentals.py` reconstructs annual SEC CompanyFacts features using filing-availability dates, not fiscal-period dates. Amendments are handled by fiscal year and missing debt concepts remain missing rather than being interpreted as zero.

`forecasting/dataset.py` writes chronologically split train/validation/test bundles, SHA-256 file hashes, target definition, provenance, split metadata and conservative data-quality flags.

### 4.2 Temporal split and fitting

`forecasting/split.py`:

1. sorts by observation date;
2. forms chronological train/validation/test regions;
3. purges rows whose forward target crosses a later fitting/evaluation boundary;
4. applies the configured business-day embargo;
5. records exact ranges and row counts.

The validation region is itself divided into three non-overlapping chronological stages, each separated by target-horizon purge + embargo:

1. component calibration;
2. ensemble stacking/weight selection;
3. final ensemble calibration.

The locked test fits no parameter.

### 4.3 Anchor learners and validation

`forecasting/model.py` fits:

- Bayesian logistic regression with Laplace posterior covariance;
- optional histogram gradient boosting;
- optional regularized random forest;
- non-negative, sum-to-one ensemble weights learned on the dedicated stacking stage.

Acceptance evidence includes Brier/log-loss skill, ROC AUC, average precision, ECE, calibration slope/intercept, purged walk-forward stability, temporal breadth, and moving observation-date-block bootstrap uncertainty that carries the full same-date cross-section together.

### 4.4 Anchor registry

`forecasting/registry.py` binds every model ID to the serialized artifact SHA-256 and records settings, target, feature list, dataset hashes/provenance, validation report and tier.

Only `validated_research` and `validated_market` anchors can be loaded for live forecasting. `fixture_only` and `rejected` artifacts are inspectable but fail closed.

## 5. Adaptive/event plane

### 5.1 Event acquisition and store

`realtime/providers.py` supplies best-effort public-source context:

- market snapshots from the configured free market provider;
- latest SEC filing metadata;
- current-vintage FRED macro observations.

`realtime/store.py` persists normalized append-only events, provider-check status, delayed labels, adaptive runtime states and live snapshots in local SQLite.

Events are immutable. Provider **verification/check time** is tracked separately from event/source time so an unchanged event does not trigger repeated polling and stale-provider detection does not rewrite provenance.

Market polling state and market events are scoped by **ticker + benchmark**. SEC state is ticker-scoped. Macro state is global. This prevents a relative-return feature computed against one benchmark from being reused under another benchmark contract.

### 5.2 Adaptive feature contract

The reference adaptive vector contains:

- prior-session-close to latest market return;
- corresponding benchmark-relative return;
- rolling return and relative-return z-scores;
- rolling volume z-score;
- intraday range percentage;
- exponentially decayed SEC filing freshness;
- freshness-weighted 8-K/6-K, 10-Q, and 10-K-family indicators;
- freshness-weighted yield-curve and high-yield-spread changes.

SEC/macro contributions are zeroed if the provider has not been successfully verified within the configured maximum staleness window, even when an older known event still exists locally.

### 5.3 Anchor + adaptive residual

Let `p0` be the eligible anchor probability. The adaptive candidate is:

`logit(p_candidate) = logit(p0) + delta(x_event)`

`delta` is a sequential Bayesian logistic residual with Gaussian shrinkage, forgetting factor and process noise. The applied log-odds correction is clipped to `adaptive_max_logit_shift`; output probability is bounded by the configured probability clip.

The anchor keeps its validated daily feature semantics. The adaptive layer does **not** inject an intraday observation directly into an anchor trained on daily snapshots. Fresh intraday/filing/macro information enters only through the separately governed adaptive vector.

### 5.4 Delayed-label learning

A fresh event may change a candidate prediction immediately, but it may not update model parameters. Eligible predictions enter a pending-label queue that records:

- ticker;
- anchor model ID;
- adaptive settings fingerprint and complete settings contract;
- observation time/date;
- anchor/adaptive probabilities;
- event vector;
- stock/benchmark entry prices;
- target horizon and hurdle;
- earliest maturity.

The pending-label identity includes the adaptive settings lineage, and at most one learning observation is created per ticker + anchor + settings lineage + UTC observation date. When the target matures, the outcome updates only the adaptive state that generated that prediction.

### 5.5 Sequential update and activation gate

`realtime/adaptive.py` processes each matured outcome in strict predict-before-update order. Posterior covariance is updated with a Woodbury/Sherman-Morrison rank-one form rather than repeated matrix pseudoinversion.

The gate requires:

- minimum matured observations;
- minimum unique observation dates;
- minimum elapsed observation span;
- Brier and log-loss non-inferiority versus the exact frozen anchor;
- date-balanced ECE below limit;
- no variance-scaled EWMA anchor-relative deterioration alert.

The evaluation window is defined in **observation dates**, not rows. All rows within retained dates are included, and Brier/log-loss are date-balanced so a broad watchlist cannot manufacture temporal evidence by increasing cross-sectional row count.

Statuses are `warming`, `active`, or `degraded`. Only `active` can apply a non-zero residual.

### 5.6 Adaptive registry and state lineage

`realtime/registry.py` binds immutable adaptive artifact identity to:

- base model ID;
- realtime engine version;
- full adaptive settings + fingerprint;
- feature list;
- serialized state hash;
- stream validation manifest;
- validation tier.

The adaptive artifact ID is derived from the contract SHA-256. A state trained under Balanced cannot be reinterpreted as Responsive/Conservative or a custom contract.

The bundled reference adaptive artifact is `fixture_only` and therefore cannot warm-start live probabilities.

## 6. API namespaces

### `/api/v1/*`

Evidence analysis, history and screener compatibility.

### `/api/v1/*`

Retained anchor-forecast compatibility surface.

### `/api/v1/forecast/*`

Validated frozen-anchor forecast/status/settings aliases.

### `/api/v1/realtime/*`

Freshness-aware live snapshots, sanitized event chronology, adaptive/source status and realtime settings.

### `/api/v1/adaptive/*`

Explicit matured-label maintenance.

### `/api/v1/events/*`

Authenticated operator event ingest. External payloads are `context_only` by default and redacted from public Live/event responses.

### `/api/v1/settings/schema` and `/api/v1/methodology`

Combined typed configuration and methodology contracts.

## 7. UI

The self-contained vanilla HTML/CSS/JavaScript frontend has no runtime CDN dependency. Workspaces are:

- Analyze
- Screener
- Compare
- Watchlist
- Forecast
- **Live**
- Settings
- Methodology

Live displays anchor vs candidate/applied adaptive probability, source freshness/verification, top log-odds feature contributions, event chronology, gate state, drift state and adaptive lineage. Browser refresh cadence controls presentation/acquisition only; it does not manufacture learning observations.

## 8. Security/privacy trust boundaries

- strict self-only CSP;
- browser cross-site API request block;
- request IDs and endpoint-group rate limits;
- shared SQLite limiter / optional Redis for multi-host deployments;
- API-key-safe upstream requests;
- hashed audit client identifiers by default;
- CSV formula-injection hardening;
- model/dataset/adaptive-state hash verification;
- aggregate public source health (no raw ticker-scoped polling keys);
- external operator payload redaction on public APIs;
- immutable bundled artifacts separated from mutable runtime state under `data/`.

## 9. Failure behavior

- **No eligible anchor:** forecast/live probability returns unavailable; no evidence-score substitution.
- **Adaptive state warming/degraded/incompatible:** applied residual = 0.
- **Stale market context:** adaptive market shift is not applied.
- **Unverified/stale SEC or macro provider:** corresponding adaptive feature contribution is zero until successful verification resumes.
- **Dataset/model/state hash mismatch:** load/train/verification fails.
- **Synthetic artifact:** remains `fixture_only`; never live-eligible.
- **External event without validated feature contract:** context only; no probability effect.

See `FORECASTING.md`, `REALTIME.md`, `MODEL_CARD.md`, `VALIDATION_PROTOCOL.md`, and `datasets/MARKET_DATA_CONTRACT.md` for the statistical/data contracts.
