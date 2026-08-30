# FinCompass Feature Registry

**Analytics breadth is not automatic model-feature breadth.** A metric in `analytics/` (see `docs/ANALYTICS_REFERENCE.md`) is available for research and display, but **nothing enters a validated forecast model without explicit registration here plus full training and validation** through the governed Model Lab pipeline. This preserves the locked-test governance and guards against multiple-testing / model-search inflation.

Each candidate feature is declared explicitly, e.g.:

```json
{
  "feature_id": "risk.volatility_63d.v1",
  "source_metric": "risk.volatility.v1",
  "lookback": 63,
  "point_in_time_safe": true,
  "supported_asset_classes": ["equity", "etf"],
  "missing_policy": "reject"
}
```

## Currently registered forecast features

The bundled `monthly_relative_v1` contract's features remain the only validated
forecast inputs (relative-return momentum; see the model manifest). **No** analytics-kernel
metric has been promoted to a forecast feature yet.

| feature_id | source_metric | lookback | point_in_time_safe | assets | status |
|---|---|---|---|---|---|
| _(none promoted)_ | — | — | — | — | analytics kernel is display/research-only |

## Governance
- Point-in-time safety is required before any fundamental/macro-derived feature can enter historical training.
- Feature selection must not mine the locked test; candidate features are chosen on development/validation history only.
- Promotion to a model feature is an explicit, reviewed step — never automatic from analytics availability.
