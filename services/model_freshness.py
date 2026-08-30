"""Model-training cutoff versus locally available compatible data."""
from __future__ import annotations
from datetime import date
from typing import Any, Dict
import pandas as pd
from services.research_store import research_store


def evaluate_model_freshness(manifest: Dict[str, Any], ticker: str) -> Dict[str, Any]:
    prov = manifest.get("dataset_provenance") or {}
    cutoff = prov.get("training_period_end") or ((manifest.get("applicability_domain") or {}).get("training_period_end"))
    coverage = research_store.coverage([ticker])
    latest = (coverage[0].get("latest") if coverage else None)
    if not cutoff:
        return {"status": "unknown", "reason": "Model training cutoff is not recorded.", "training_cutoff": None, "latest_local_data": latest}
    if not latest:
        return {"status": "unknown", "reason": "No local data available for freshness comparison.", "training_cutoff": cutoff, "latest_local_data": None}
    c = pd.Timestamp(cutoff).tz_localize(None)
    l = pd.Timestamp(latest).tz_localize(None)
    days = max(0, int((l-c).days))
    months = round(days / 30.4375, 1)
    h = int((manifest.get("target") or {}).get("horizon_months") or round(float((manifest.get("target") or {}).get("horizon_trading_days") or 252)/21))
    if days <= 60:
        status = "current"
    elif months < max(6, h/2):
        status = "new_data_available"
    elif months < max(12, h):
        status = "retrain_recommended"
    else:
        status = "stale"
    return {"status": status, "training_cutoff": str(pd.Timestamp(cutoff).date()), "latest_local_data": str(pd.Timestamp(latest).date()), "lag_days": days, "lag_months": months, "target_horizon_months": h}
