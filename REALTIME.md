# FinCompass 1.0 — Adaptive Near-Real-Time Research

## Purpose

FinCompass 1.0 adds a governed event-driven layer on top of the validation-gated forward-event anchor. It is designed to react to newly available market, filing and macro evidence without converting every browser refresh or fresh observation into a training sample.

The architecture separates three operations:

1. **Observation update** — provider checks update the current timestamped information state.
2. **Prediction update** — fresh eligible event features can change the adaptive candidate immediately.
3. **Parameter update** — Bayesian residual parameters change only after the original forecast target has matured and the realized outcome is available.

An unresolved observation never trains on itself.

## Anchor + adaptive residual architecture

Let `p0` be the probability produced by a live-eligible frozen anchor model. The adaptive layer operates in log-odds space:

`logit(p_candidate) = logit(p0) + delta(x_event)`

where `delta` is a sequential Bayesian residual over the v1 event-feature contract. The correction is bounded by `adaptive_max_logit_shift` and the final probability is clipped away from 0/1 by the configured probability clip.

The **applied** result differs from the candidate when governance blocks the residual. A warming, degraded, stale, settings-incompatible or non-live-eligible adaptive state contributes zero applied shift, so the live result falls back to `p0`.

This makes rollback deterministic and preserves the validated anchor.

## Anchor feature-contract protection

The anchor model keeps the same daily feature semantics under which it was trained and validated. v1 deliberately does **not** inject an intraday quote into a model validated on daily snapshots.

Fresh intraday, SEC filing and macro evidence enters through the separately validated adaptive event vector. This avoids silently changing the anchor's input distribution in the name of realtime responsiveness.

## Built-in event sources

### Market context

The freeware path uses best-effort yfinance/Yahoo intraday polling. Market context records provider/source time, latest stock/benchmark prices, short-window standardized moves, volume context and intraday range when available.

The reference `market_return_1d` uses **previous trading-session close -> latest price**, with a safe first-bar fallback only when prior-session data are unavailable. The benchmark return is built on the same boundary. This preserves overnight gaps rather than measuring only first intraday bar -> current bar.

Market events and provider cadence are scoped by **ticker + benchmark**. A snapshot computed against SPY cannot be reused for QQQ-relative evidence.

This path is not exchange-grade streaming. Delays, closed markets, gaps and provider throttling are expected and surfaced in freshness/provider state.

### SEC filing context

The SEC submissions path captures latest filing metadata and source time. When EDGAR supplies `acceptanceDateTime`, FinCompass uses that dissemination timestamp; filing date at 23:59:59 UTC is only a fallback. Filing evidence decays continuously with age using the configured event half-life. Form indicators are freshness-weighted for:

- 8-K / 6-K;
- 10-Q;
- 10-K / 20-F / 40-F families.

Historical anchor fundamentals continue to use filing-availability semantics. A filing is never backdated to its fiscal-period end.

SEC provider-verification age is tracked separately from event age. If FinCompass has not completed a successful SEC check within `max_sec_staleness_seconds`, SEC adaptive contributions are zeroed until verification recovers, even if an older known filing remains in the local store.

### Macro context

FRED current-vintage observations provide optional yield-curve and high-yield credit-spread context. Changes are exponentially freshness-weighted. Provider-verification age is independent from the age of the last known macro observation; a verification outage beyond `max_macro_staleness_seconds` suppresses the macro adaptive contribution until recovery.

Historical validation of macro features must use vintage-aware data rather than copying today's revised series backward.

### External operator feed

`POST /api/v1/events/ingest` accepts an authenticated operator-supplied event only when `FINCOMPASS_EVENT_INGEST_TOKEN` is configured.

Reference behavior is deliberately conservative:

- events are `context_only` by default;
- they have no probability effect without a separately validated feature contract;
- raw payloads remain local operational data;
- public Live/event responses redact external payload contents.

This allows later integration of licensed feeds without silently changing the statistical model or redistributing feed content through the public API.

## Adaptive feature contract

The v1 reference feature vector is:

1. `market_return_1d`
2. `benchmark_relative_return_1d`
3. `return_z_20`
4. `relative_return_z_20`
5. `volume_z_20`
6. `intraday_range_pct`
7. `sec_filing_freshness`
8. `sec_is_8k_6k`
9. `sec_is_10q`
10. `sec_is_10k_family`
11. `yield_curve_change`
12. `hy_spread_change`
13. `macro_freshness`

Adding or redefining a feature requires a documented source/effective-time contract and a new adaptive validation artifact. Context without validated predictive semantics remains context-only.

## Freshness semantics

v1 distinguishes:

- **source/event time** — when the underlying market/filing/macro information is effective or reported;
- **received time** — when FinCompass first stored that immutable event;
- **provider check time** — when FinCompass last attempted to verify the source;
- **last successful provider check** — the latest successful verification checkpoint.

An unchanged provider response does not rewrite an event timestamp. Poll scheduling uses provider-check state so deduplication cannot accidentally cause repeated polling after the nominal cadence window.

Event effects decay by event age. Provider-safety limits are evaluated against last successful verification age. The two controls solve different problems.

## Sequential Bayesian residual update

The adaptive state uses a regularized Gaussian posterior approximation for residual logistic regression with:

- Gaussian shrinkage prior;
- configurable forgetting factor;
- configurable process noise;
- bounded log-odds correction;
- posterior state uncertainty;
- per-feature log-odds contribution reporting.

Each matured label is processed in strict **predict-before-update** order:

1. compute the candidate probability from the state that existed before the outcome;
2. record anchor/candidate prequential losses;
3. update the anchor-relative drift statistic;
4. reveal the matured binary outcome;
5. update posterior mean/covariance;
6. recompute the activation gate.

The online covariance update uses the algebraically equivalent Woodbury/Sherman-Morrison rank-one form instead of repeated matrix pseudoinversion. This preserves the sequential Gaussian approximation while making continuous updates bounded and materially cheaper.

## Delayed/matured labels and state lineage

An eligible prediction can enter the local pending-label queue with:

- ticker;
- observation timestamp/date;
- anchor model ID;
- adaptive settings fingerprint;
- complete adaptive settings contract;
- anchor/candidate probability;
- event-feature vector;
- stock and benchmark entry prices;
- target horizon and hurdle;
- earliest maturity date.

The earliest maturity is only a scheduling bound. At resolution, FinCompass aligns stock and benchmark daily histories and uses the **H-th common trading-session close strictly after the observation date**. If that session is not yet available as of the maintenance date, the label remains pending. A late maintenance job therefore cannot silently lengthen the event horizon.

The label identity is limited to **one observation per ticker + anchor model + adaptive settings lineage + UTC observation date**. Repeated UI refreshes therefore do not create repeated labels for the same learning contract/day.

When a target matures, the queued settings contract is reconstructed and verified. The outcome updates only the posterior lineage that originally generated the prediction. Switching Balanced/Responsive/Conservative or a custom profile cannot consume another profile's pending evidence.

If the stored settings contract fails fingerprint validation, the outcome can be resolved operationally but is not applied to an adaptive posterior.

## Activation gate

A residual can influence the live probability only when all configured checks pass:

- minimum matured observations;
- minimum **unique observation dates**;
- minimum elapsed observation span;
- rolling adaptive Brier loss is non-inferior to the exact frozen anchor;
- rolling adaptive log loss is non-inferior to the exact frozen anchor;
- date-balanced adaptive ECE is within limit;
- no current anchor-relative variance-scaled EWMA deterioration alert.

The rolling evaluation window is defined in **observation dates**, not rows. All rows belonging to the retained dates are included, and Brier/log-loss are calculated with equal date weighting. A larger ticker watchlist therefore cannot manufacture temporal evidence by creating more cross-sectional rows on the same dates.

Statuses:

- `warming` — posterior exists but cannot alter the anchor;
- `active` — all gates pass and a bounded residual may be applied;
- `degraded` — current performance/drift controls block adaptive influence.

## Drift monitoring

v1 monitors:

`adaptive Brier loss - anchor Brier loss`

with a variance-scaled exponentially weighted moving statistic. Positive sustained excess loss indicates adaptive deterioration. The monitor has configurable allowance, smoothing coefficient, minimum observations and control multiplier.

The alert is intentionally recoverable rather than permanently sticky. Clearing the drift alert does not itself reactivate the model; the complete activation gate must pass.

## Live snapshot provenance

Every v1 live snapshot can report:

- snapshot `as_of`;
- anchor model ID/tier and base probability;
- adaptive engine/state identity and settings fingerprint;
- candidate and applied probability;
- whether the adaptive shift was actually applied;
- source/event timestamps and ages;
- provider-verification state;
- freshness/staleness limits;
- normalized adaptive feature vector;
- top feature-level log-odds contributions;
- gate metrics/checks and drift state;
- recent sanitized ticker events;
- pending-label action.

A probability detached from these timestamps/model/state identifiers is not a complete v1 result.

## Adaptive validation tiers

Adaptive artifacts use four tiers:

- `fixture_only` — synthetic streaming/software regression only; never live-eligible;
- `rejected` — failed validation;
- `validated_research` — passed real historical event-stream validation but documented market-data limitations remain;
- `validated_market` — passed statistical validation and documents point-in-time event availability, no-lookahead controls, survivorship/delisting treatment, and corporate-action-adjusted market data with evidence.

## Bundled locked streaming fixture

`datasets/realtime-fixtures/` contains:

- `warmup.csv` — 1,200 synthetic chronological observations;
- `locked_test.csv` — 600 synthetic chronological observations;
- `fixture_manifest.json` + SHA-256 sidecar;
- `adaptive_stream_manifest.json`;
- `adaptive_validation_report.json`.

Protocol: synthetic warm start followed by a locked **prequential predict-before-update** stream.

Current locked-stream regression results:

- anchor Brier: **0.235658**;
- adaptive Brier: **0.204069**;
- absolute Brier improvement: **+0.031588**;
- anchor log loss: **0.664106**;
- adaptive log loss: **0.596988**;
- absolute log-loss improvement: **+0.067118**;
- locked observations: **600**.

At the end of the locked stream, the configured recent-date gate evaluates 250 independent observation dates spanning 498 days:

- Brier improvement: **+0.037821**;
- log-loss improvement: **+0.079019**;
- adaptive ECE: **0.061924**;
- drift alert: **false**;
- all activation checks: **pass**.

The warm-start state passes the synthetic regression gate, and the locked evaluation copy independently continues to pass after sequential adaptation. Both remain `fixture_only`; neither can influence live market forecasts.

Current bundled adaptive artifact:

- adaptive ID: `50732cca02f306ed`;
- state SHA-256: `200704ed3add4c16728d923795feeaca670441f83eb347a169cb691b9c3f7ee3`;
- contract SHA-256: `50732cca02f306edfe35b3b6c9d40c44b375ee495de34f9c746874425e8f090a`;
- settings fingerprint: `f54949dee65f84d6`;
- base anchor: `efd41fec7d9d24fd`;
- validation tier: `fixture_only`.

These results validate implementation/regression behavior against a known synthetic stream. They are **not evidence of market forecasting skill**.

## API

- `GET /api/v1/realtime/status`
- `GET /api/v1/realtime/{ticker}`
- `GET /api/v1/realtime/{ticker}/events`
- `POST /api/v1/adaptive/process-matured`
- `GET /api/v1/realtime/settings/schema`
- `POST /api/v1/realtime/settings/validate`
- `POST /api/v1/events/ingest`
- `GET /api/v1/settings/schema`
- `GET /api/v1/methodology`
- `GET /api/v1/forecast/status`
- `GET /api/v1/forecast/{ticker}`
- `POST /api/v1/forecast/settings/validate`

## What v1 does not claim

FinCompass does not claim that:

- free polling is tick-by-tick or exchange-grade;
- a recent event is predictive merely because it is recent;
- current unresolved observations are labels;
- repeated refreshes create independent statistical evidence;
- a synthetic adaptive fixture establishes incremental market skill;
- an adapter that once activated remains calibrated forever;
- current-vintage macro history can be used as if every revision had been known historically;
- `validated_research` or `validated_market` guarantees profitability.

Those boundaries are part of the governance design, not caveats to hide.
