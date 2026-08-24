# FinCompass 1.0 — Engineering / Validation TODO

## Closed in 1.0.0

- [x] Keep the validated historical forecast as an immutable anchor rather than continuously refitting the whole model.
- [x] Add append-only timestamped market, filing, macro and operator-event storage.
- [x] Add source freshness/staleness reporting and provider health.
- [x] Add bounded sequential Bayesian residual adaptation.
- [x] Prevent unresolved current information from being used as a training target.
- [x] Add delayed pending-label queue and matured-outcome processing.
- [x] Add prequential predict-before-update performance monitoring.
- [x] Add anchor-relative variance-scaled EWMA deterioration monitoring with recovery.
- [x] Require Brier/log-loss non-inferiority, calibration, sample-size and no-drift checks before adaptive influence.
- [x] Zero-shift fallback to validated anchor while warming/degraded/stale.
- [x] Add separate adaptive artifact registry and SHA-256-bound adaptive IDs.
- [x] Block synthetic adaptive artifacts from live warm starts.
- [x] Add deterministic adaptive warmup + locked prequential test fixtures.
- [x] Add balanced/responsive/conservative realtime profiles and typed validation.
- [x] Add Live workspace and advanced adaptive Settings UI.
- [x] Add v1 API namespace and authenticated context-only external ingest.
- [x] Preserve v1/v1 compatibility surfaces.
- [x] Extend CI/release verifier for adaptive artifacts, fixtures, configuration and Docker packaging.
- [x] Bind pending labels and adaptive states to exact settings fingerprints/contracts.
- [x] Scope market events/provider cadence to ticker + benchmark.
- [x] Use previous-session close for one-day market/relative-return event features.
- [x] Separate event age from provider-verification age and fail closed on stale verification.
- [x] Decay SEC filing/form and macro event contributions with freshness.
- [x] Make online evaluation windows observation-date based with equal-date Brier/log-loss weighting.
- [x] Require unique observation-date and elapsed-span breadth before adaptive activation.
- [x] Replace repeated online covariance pseudoinverses with a rank-one Woodbury update.
- [x] Aggregate public provider health and redact external event payloads to avoid shared-deployment symbol/feed leakage.
- [x] Reconcile all v1 documentation and Docker examples with the final statistical/event contract.

## Required before claiming real adaptive market skill

- [ ] Build a historically reconstructed event stream with source/effective timestamps for every predictive event feature.
- [ ] Use vintage-aware historical macro values rather than revised current history.
- [ ] Obtain/construct historically point-in-time constituent/universe membership.
- [ ] Include delisted securities and terminal/delisting returns.
- [ ] Independently verify corporate-action-adjusted stock and benchmark prices.
- [ ] Pre-register adaptive feature contract, anchor model, gate and untouched streaming test interval.
- [ ] Validate incremental adaptive Brier/log-loss skill versus the exact frozen anchor across regimes.
- [ ] Validate the consequence of provider delays/outages and simulated stale-source scenarios.
- [ ] Validate any news/NLP/event-feed feature separately before it can influence probability.

## Potential v1.x / v5 research

- [ ] Dynamic hierarchical sector/regime priors.
- [ ] Explicit latent-state/regime model with posterior regime probabilities.
- [ ] Multi-horizon anchor + adaptive heads.
- [ ] Conformal prediction/abstention layer for distribution shift.
- [ ] Bayesian change-point detection as a secondary drift diagnostic.
- [ ] Calibrated expected excess return and downside-risk models alongside event probability.
- [ ] Cross-sectional portfolio/decision layer only after transaction-cost and liquidity validation.
- [ ] Streaming connector SDK with signed source contracts and schema registry.

## Independent release validation

- [ ] Real VoiceOver/NVDA pass.
- [ ] Public TLS/reverse-proxy review.
- [ ] Live Docker build/run validation in an environment with Docker available.
- [ ] Explicit redistribution/open-source license chosen by the release owner.
- [ ] Independent security review before high-traffic public deployment.
- [ ] Live smoke tests with the operator's SEC/FRED/optional provider configuration.
