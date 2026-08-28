"""Model freshness.

Compare a model's training cutoff with the newest currently-available compatible
market data and classify freshness with a deterministic, documented policy that
considers the horizon (not an arbitrary age threshold alone). Research mode can
expose the exact numbers and policy.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

# Policy ratio thresholds (lag_months / horizon_months). Documented + deterministic.
CURRENT_MAX_RATIO = 0.5       # < 0.5 horizon of new data → current
STALE_MIN_RATIO = 2.0         # >= 2 horizons of new data → stale
RECENT_FLOOR_MONTHS = 3.0     # never call a model stale if < 3 months behind


def _cutoff(manifest: Dict[str, Any]) -> Optional[pd.Timestamp]:
    dom = manifest.get("applicability_domain") or {}
    prov = manifest.get("dataset_provenance") or {}
    raw = dom.get("training_period_end") or prov.get("training_period_end")
    if not raw:
        return None
    try:
        return pd.Timestamp(raw).tz_localize(None).normalize()
    except Exception:
        return None


def assess_model_freshness(
    manifest: Dict[str, Any],
    current_data_latest: Optional[Any],
    horizon_months: Optional[int] = None,
) -> Dict[str, Any]:
    """Return a freshness record for a model against the newest available data.

    status: "current" | "update_recommended" | "stale" | "unknown"
    """
    cutoff = _cutoff(manifest)
    dom = manifest.get("applicability_domain") or {}
    horizon = int(horizon_months or dom.get("target_horizon_months") or 12)

    latest = None
    if current_data_latest is not None:
        try:
            latest = pd.Timestamp(current_data_latest).tz_localize(None).normalize()
        except Exception:
            latest = None

    if cutoff is None or latest is None:
        return {
            "status": "unknown", "training_cutoff": (cutoff.date().isoformat() if cutoff is not None else None),
            "current_data_latest": (latest.date().isoformat() if latest is not None else None),
            "model_data_lag_days": None, "model_data_lag_months": None,
            "new_matured_targets_available": None, "horizon_months": horizon,
            "policy": "lag/horizon ratio; needs both a training cutoff and current data date",
        }

    lag_days = max(0, (latest - cutoff).days)
    lag_months = round(lag_days / 30.44, 1)
    # Newly matured labels since cutoff ≈ observations old enough that their
    # horizon-forward outcome is now known.
    new_matured = max(0.0, round(lag_months - horizon, 1))
    ratio = lag_months / horizon if horizon else 0.0

    if lag_months < RECENT_FLOOR_MONTHS or ratio < CURRENT_MAX_RATIO:
        status = "current"
    elif ratio < STALE_MIN_RATIO:
        status = "update_recommended"
    else:
        status = "stale"

    return {
        "status": status,
        "training_cutoff": cutoff.date().isoformat(),
        "current_data_latest": latest.date().isoformat(),
        "model_data_lag_days": lag_days,
        "model_data_lag_months": lag_months,
        "new_matured_targets_available": new_matured,
        "horizon_months": horizon,
        "policy": f"ratio=lag_months/horizon; current<{CURRENT_MAX_RATIO}, stale>={STALE_MIN_RATIO}, recent floor {RECENT_FLOOR_MONTHS}mo",
        "ratio": round(ratio, 2),
    }
