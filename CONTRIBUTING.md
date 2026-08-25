# Contributing to FinCompass

Contributions should preserve the project's operating model: free, transparent, privacy-minimized, statistically explicit, reproducible, and self-hostable.

## Pull request requirements

1. Explain user impact and statistical/model-governance impact.
2. Add or update regression tests for behavior changes.
3. Run `python tools/verify_release.py`.
4. Update `MODEL_CARD.md` and `FORECASTING.md` for forecast-method changes.
5. Increment the relevant engine/schema version for semantic changes.
6. Update `CHANGELOG.md` for user-visible changes.
7. Do not add telemetry, advertising, account requirements, silent paid dependencies, or credential-bearing logging.
8. Do not tune against the locked test and then continue calling it locked.
9. Do not promote `fixture_only` or `rejected` artifacts to live forecasting.
10. Do not manually elevate a dataset/model to `validated_market` without substantiating point-in-time features, survivorship control, delistings, and corporate-action adjustment.
11. Any new historical feature must document its public `available_date` and include a look-ahead/leakage regression test.
12. Treat `.joblib` model artifacts as executable/trusted local artifacts; never accept untrusted model uploads or load arbitrary third-party joblib files.

## Forecast changes

For any target, feature, calibration, learner, ensemble, split, or gate change, record why it is needed and what development evidence supports it. Material changes informed by prior locked-test results require a new untouched test period before a new final validation claim.

## Release discipline

Keep changes focused. Preserve dataset/model manifests and hashes. Prefer simple, auditable methods unless a more complex method demonstrates improved out-of-sample probability quality and calibration under the same leakage-safe protocol.

## Contributing to the adaptive layer

Any pull request that changes event features, timestamp semantics, online update rules, gate thresholds, drift logic or adaptive state serialization must include:

1. a version/schema impact assessment;
2. deterministic regression tests;
3. regeneration of the locked synthetic adaptive fixture when its contract changes;
4. documentation of source time versus effective time;
5. evidence that an unresolved observation cannot update parameters;
6. evidence that `fixture_only` artifacts remain blocked from live use.

A new event source is context-only by default. Predictive use requires an explicit point-in-time historical validation contract.
