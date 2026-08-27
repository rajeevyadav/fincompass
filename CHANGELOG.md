# Changelog

All notable changes to FinCompass are documented here. This project follows
Semantic Versioning.

## [1.4.0] — 2026-08-26

Forecast and Live are now fully functional end to end.

### Working forecast + a bundled validated model
- A real historical monthly reference model reaches **`validated_research`**
  (passes the configured locked-test + bootstrap gates) and can be **selected and
  activated** so Forecast and Live actually produce probabilities. The model is a
  private, local-only artifact (`REVIEW_REQUIRED`) bundled into the exe; it is
  never published (git-ignored + excluded from the public source manifest). No
  model is pre-activated — the user selects and activates it.

### Broader search
- Screener adds a **market region** selector and **Browse full market sector** —
  an on-demand search that is **not limited to the 72-name starter list**; any
  discovered company can be analysed. Guided / Research experience modes.

### Housekeeping
- Header shows the **software version** instead of internal engine ids.
- Public/private release gate hardened: the manifest is the git-tracked public
  set, and the market-seed integrity scan skips when the private seed is absent
  (public/CI), enforcing fully when present. Private trained models are excluded
  from the public source by sharing status.

## [1.3.0] — 2026-08-25

Model Lab + local research data store, with a public/private split. See PR #6.

## [1.2.0] — 2026-08-24

Additive, non-breaking release.

### In-app forecast model build (no command line)
- New **Build forecast model** action on the Forecast tab trains a model from
  free public data entirely in-app — end users never run a script. Backed by a
  background job (`services/model_builder.py`) with SQLite-tracked progress and
  a pollable status endpoint.
- New endpoints: `POST /api/v4/forecast/build` and
  `GET /api/v4/forecast/build/status`.
- Newly built models are saved to a writable models directory
  (`FINCOMPASS_MODELS_DIR`, defaulting to the bundled `models/`), so packaged
  builds can train and activate models outside the read-only bundle.
- Removed the last command-line references from user-facing copy (no-model
  notices, forecast-status message, and the training-settings help text) in
  favor of the in-app action. A build that produces no gate-passing model is
  surfaced as expected honest behavior, not an error.

## [1.1.0] — 2026-08-24

Additive, non-breaking release. No change to the scoring engine, schemas or any
existing `/api/*` response field.

### Investor Posture indicators
- New presentation-layer card, **Investor Posture**, rendered directly below the
  five pillar boxes. Three mechanically-derived, model-free signals computed from
  existing pillar and uncertainty data: New-Position Priority, Accumulation Signal
  and Re-Underwrite Trigger. These are research signals, not buy/sell
  recommendations — there is no combined verdict score and no personalization.
- Additive `posture` field on the analysis response (`AnalysisOut`); all existing
  fields are unchanged.
- Guardrail tests assert no action verb appears in any generated indicator copy or
  identifier, and that indicator labels/values are Title Case while descriptions
  stay sentence case.

## [1.0.0] — 2026-08-23

Initial public release.

### Evidence engine
- Transparent 0–10 Bayesian research score across Quality, Financial
  Durability, Safety, Valuation and Cycle, with per-factor explanations.

### Validated forecast anchor
- Calibrated forward-event probability model that activates only after a real
  historical dataset passes temporal, calibration and locked-test validation
  gates. The bundled reference anchor is deterministic-synthetic
  (`fixture_only`) and is never live-eligible.

### Adaptive live layer
- Timestamped market / SEC-filing / FRED-macro context plus a bounded
  sequential Bayesian log-odds residual that may adjust the anchor only after a
  separate prequential activation gate passes. Strict matured-label-only
  parameter updates; predict-before-update monitoring.

### Packaging and integrity
- Self-hostable FastAPI + vanilla-JavaScript workbench; no accounts, ads,
  analytics, paid frontend libraries, or proprietary cloud backend.
- `tools/verify_release.py` gates the release: compilation, the full automated
  test suite, JavaScript syntax, CSP/frontend-dependency scan, anchor/adaptive
  dataset-hash verification, fixture-tier lockout, model/adaptive contract-hash
  checks, configuration-drift checks, documentation consistency, and Docker
  packaging/ownership checks.
