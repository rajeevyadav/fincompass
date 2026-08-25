# FinCompass — Realtime Event and Online-Learning Data Contract

This contract defines the minimum semantics for information entering the adaptive Live layer. The objective is to preserve point-in-time meaning, freshness, provenance and reproducibility while preventing unresolved future outcomes from leaking into model updates.

## Event requirements

Each normalized event must carry enough information to establish:

- source/provider family;
- event type;
- security scope when applicable;
- benchmark scope for relative-market features when applicable;
- event/as-of timestamp;
- local receipt/check timestamp;
- normalized payload used by the feature builder;
- stable deduplication identity;
- provenance metadata sufficient to distinguish public built-in sources from operator-supplied external context.

Event time and provider-check time are different concepts. Repeated successful checks for an unchanged event update source verification state without rewriting the immutable event timestamp.

## Built-in source families

### Market

The built-in market adapter is best-effort and near-real-time. Relative-market events are scoped to **ticker + benchmark**. The one-day return uses previous-session close to latest available price when prior-session data are available, so overnight gaps are not discarded.

### SEC

SEC events represent newly observed filing metadata. Filing effects decay by event age. Source-verification age is tracked separately so an old but still valid filing does not imply the provider has been checked recently.

### Macro

FRED-derived observations are timestamped context. Historical forecasting should use vintage-aware/revision-aware construction where required; the online layer must not pretend revised values were known before publication.

### External/operator event

Authenticated external ingest is intentionally generic. External payloads are stored locally but are context-only by default and redacted from public Live/event API responses. A licensed or proprietary event family must be independently validated before it is allowed to become a learned predictive feature.

## Freshness and staleness

Two controls apply:

1. **Event-age decay** — a valid older event contributes progressively less according to the configured half-life.
2. **Provider-verification staleness** — if a provider has not been successfully checked within the configured maximum staleness, that source's adaptive features are zeroed until verification resumes.

This prevents “no new event” from being confused with “we know there was no new event.”

## Prediction records

A live prediction record must bind at least:

- ticker;
- frozen anchor model ID;
- target definition / benchmark;
- adaptive settings fingerprint;
- observation date and as-of timestamp;
- anchor probability;
- candidate adaptive probability;
- whether the adaptive correction was permitted to apply;
- feature vector / explainable contributions;
- source freshness state.

Frequent refreshes may create many prediction snapshots, but they do **not** create many independent learning labels.

## Pending-label identity

At most one learning-label observation is created per ticker, base model, adaptive settings lineage and observation date for the governed target. Pending observations preserve the exact settings contract that generated them.

When the outcome matures, a processing pass may resolve labels from multiple settings profiles, but each label updates only its original adaptive lineage.

## Matured-label rule

No adaptive parameter update may use an outcome before the target horizon has completed. The system uses predict-before-update prequential ordering: score the observation using the pre-update state, record loss, then update the posterior using the matured label.

## Online evaluation independence

Activation cannot be earned by row count alone. The gate requires:

- a minimum number of matured observations;
- a minimum number of unique observation dates;
- a minimum elapsed date span;
- date-balanced Brier/log-loss comparison with the frozen anchor;
- calibration constraint;
- no active drift alert.

The rolling evaluation window is defined by recent **observation dates**, not simply the most recent N rows, so a large watchlist cannot manufacture temporal breadth.

## Fixture boundary

`datasets/realtime-fixtures/` is deterministic synthetic regression data. Its passing results validate code paths, state lineage, temporal gating and numerical behavior only. It is not evidence of market skill and cannot create a live-eligible adaptive artifact.
