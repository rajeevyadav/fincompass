# FinCompass — Engineering / Validation TODO

## Completed platform controls

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

## Source-commit scope completed

- [x] Durable Model Lab SQLite research store with append/deduplicate/revision journaling.
- [x] Packaged real historical research-only bootstrap corpus with retained originals, provenance and SHA-256 manifest.
- [x] Incremental overlap/tail refresh with raw provider-frame retention.
- [x] Cross-asset catalogue and declarative training recipes.
- [x] Recipe readiness preflight in API/UI; untrainable recipes are identified before launch.
- [x] Corrected leakage-safe internal validation partitioning without duplicated outer embargo.
- [x] Experiment lifecycle, explicit activation, and activated-artifact hash verification.
- [x] Interrupted stale-build reclamation with experiment evidence retained.
- [x] Docker and Windows one-file packaging include config and market seed.
- [x] Release verifier enforces seed integrity and packaging contracts.

## One-shot source commit - operator workflow complete

- [x] Guided mode is the default and exposes a plain-language update -> train -> inspect -> activate -> forecast workflow.
- [x] Research mode preserves full recipe selection, advanced configuration, experiment lineage and model comparison.
- [x] Guided recipe recommendation prefers the Core US 6M contract when local data make it trainable.
- [x] Model selection, explicit activation, explicit deactivation and validated-model comparison are available in-app.
- [x] Live supports Conservative, Balanced and Responsive governed conditions.
- [x] Live condition comparison uses the same observed information and does not queue learning labels.
- [x] Normal manual Live refresh performs bounded matured-outcome maintenance before calculating the new state.
- [x] Beginner-oriented user manual source and verified PDF updated.
- [x] arXiv manuscript corrected to match the implemented outer-embargo/internal-purge validation contract.
- [x] Recovery-grade handoff and machine-readable source-of-truth map added.

## Required before claiming real adaptive market skill

> These are **evidence-generation requirements, not source-commit blockers**. They require point-in-time datasets, untouched future intervals, or independent empirical validation and must not be marked complete from code changes alone.

- [ ] Build a historically reconstructed event stream with source/effective timestamps for every predictive event feature.
- [ ] Use vintage-aware historical macro values rather than revised current history.
- [ ] Obtain/construct historically point-in-time constituent/universe membership.
- [ ] Include delisted securities and terminal/delisting returns.
- [ ] Independently verify corporate-action-adjusted stock and benchmark prices.
- [ ] Pre-register adaptive feature contract, anchor model, gate and untouched streaming test interval.
- [ ] Validate incremental adaptive Brier/log-loss skill versus the exact frozen anchor across regimes.
- [ ] Validate the consequence of provider delays/outages and simulated stale-source scenarios.
- [ ] Validate any news/NLP/event-feed feature separately before it can influence probability.

## Future research

> These are extension directions for a research user/professor and are intentionally not required for the one-shot source commit.

- [ ] Dynamic hierarchical sector/regime priors.
- [ ] Explicit latent-state/regime model with posterior regime probabilities.
- [ ] Multi-horizon anchor + adaptive heads.
- [ ] Conformal prediction/abstention layer for distribution shift.
- [ ] Bayesian change-point detection as a secondary drift diagnostic.
- [ ] Calibrated expected excess return and downside-risk models alongside event probability.
- [ ] Cross-sectional portfolio/decision layer only after transaction-cost and liquidity validation.
- [ ] Streaming connector SDK with signed source contracts and schema registry.

## Post-commit independent / deployment validation

> These require external accessibility tooling, deployment infrastructure, live provider credentials, or independent review. They remain deliberately open after source closure.

- [ ] Real VoiceOver/NVDA pass.
- [ ] Public TLS/reverse-proxy review.
- [ ] Live Docker build/run validation in an environment with Docker available.
- [x] Application source license present: MIT (`LICENSE`).
- [ ] Independently review third-party/provider redistribution terms before adding any additional bulk provider market data to the distributable source package.
- [ ] Independent security review before high-traffic public deployment.
- [ ] Live smoke tests with the operator's SEC/FRED/optional provider configuration.
