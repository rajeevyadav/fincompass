# Revision notes

The manuscript remains a single progressive argument intended to be readable by a technically curious newcomer while retaining enough mathematical detail for specialist review.

Current revision changes:

- Removed product-version branding from the manuscript; release identification belongs to the software release metadata, not the scientific argument.
- Corrected the temporal-validation description to match the tested implementation:
  - the configured embargo applies at the broad train-to-validation and validation-to-test boundaries;
  - component calibration, ensemble stacking, and final calibration remain chronological and use strict forward-target purging;
  - the full outer embargo is **not** repeated inside each validation sub-stage.
- Added the operational rule that a passing candidate is not automatically live; activation is explicit and separate from model creation.
- Updated the bundled-data scope statement to distinguish deterministic synthetic regression fixtures from the small real historical research-only bootstrap corpus.
- Preserved the claims boundary: neither the synthetic fixtures nor the bootstrap corpus are evidence of live market forecasting skill.

Earlier major revisions retained in this edition:

- Added the final author identity: Rajeev Yadav, Ph.D.; rajeevyadav@gmail.com.
- Reorganized the exposition around a concrete forecasting example before introducing formal notation.
- Clearly separated evidence-score uncertainty, empirical forward-event probability, and adaptive posterior correction.
- Added/expanded the mathematical specification for exact common-session targets, point-in-time information availability, fractional-Beta evidence aggregation, Bayesian logistic MAP/Laplace inference, separated component calibration and constrained stacking, dependence-aware bootstrap validation, bounded online log-odds adaptation, matured-label learning, date-balanced online loss, drift control, and fail-closed live use.
- Added a complete end-to-end worked example.
- Kept software/statistical regression results explicitly separated from market-performance claims.
- Rebuilt figures and typography as a conventional academic paper with no external figure dependencies.
