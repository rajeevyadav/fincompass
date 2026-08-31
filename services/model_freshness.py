"""Freshness for a pooled-family model, expressed as three separate concepts.

The earlier implementation compared the model's training cutoff against the
latest locally stored data for whichever ticker was being viewed. That is not a
correct definition of freshness for a pooled family model: a brand-new ticker
carrying current prices would, by that measure, make a perfectly good pooled
model look "stale" purely because the ticker itself is recent. The forecast for
a new in-domain name does not depend on the model having seen that name.

Freshness is therefore split into three questions that have distinct answers and
distinct owners:

* ``instrument_data_freshness`` - are the current ticker and its benchmark recent
  enough to compute today's features? This is about the *viewed instrument*.
* ``model_training_freshness`` - how old is the model *family* training corpus?
  This comes from model provenance, never from the viewed ticker.
* ``retrainability`` - has enough new compatible *family* data accumulated, and
  have enough new target labels matured, to make retraining meaningful?

A new ticker with current prices can raise ``instrument_data_freshness`` to
``current`` while leaving ``model_training_freshness`` and ``retrainability``
completely unchanged - which is the correct behaviour.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from services.research_store import research_store

# Average days per month, used to convert date lags to whole months for display.
_DAYS_PER_MONTH = 30.4375


def _today() -> pd.Timestamp:
    return pd.Timestamp(date.today())


def _ts(value: Any) -> Optional[pd.Timestamp]:
    if not value:
        return None
    try:
        return pd.Timestamp(value).tz_localize(None)
    except (TypeError, ValueError):
        try:
            return pd.Timestamp(value)
        except (TypeError, ValueError):
            return None


def _months_between(start: Optional[pd.Timestamp], end: Optional[pd.Timestamp]) -> Optional[float]:
    if start is None or end is None:
        return None
    return round(max(0, (end - start).days) / _DAYS_PER_MONTH, 1)


def _training_cutoff(manifest: Dict[str, Any]) -> Optional[pd.Timestamp]:
    prov = manifest.get("dataset_provenance") or {}
    domain = manifest.get("applicability_domain") or {}
    return _ts(prov.get("training_period_end") or domain.get("training_period_end"))


def _horizon_months(manifest: Dict[str, Any]) -> int:
    target = manifest.get("target") or {}
    domain = manifest.get("applicability_domain") or {}
    h = target.get("horizon_months") or domain.get("target_horizon_months")
    if h:
        return int(h)
    days = target.get("horizon_trading_days") or 252
    return int(round(float(days) / 21))


def _family_symbols(manifest: Dict[str, Any]) -> List[str]:
    domain = manifest.get("applicability_domain") or {}
    prov = manifest.get("dataset_provenance") or {}
    symbols = domain.get("training_symbols") or prov.get("training_assets") or []
    return [str(s).upper() for s in symbols]


def _instrument_data_freshness(symbol: str, benchmark_symbol: Optional[str]) -> Dict[str, Any]:
    """Is the viewed ticker (and its benchmark) recent enough for today's features?

    Measured against today, not against the model. A large lag here means the
    local price history is stale and a data refresh would help feature quality;
    it says nothing about the model corpus. ``absent`` simply means nothing is
    stored locally yet - a pooled forecast can still fetch history on demand.
    """
    today = _today()

    def one(sym: str) -> Dict[str, Any]:
        rows = research_store.coverage([sym]) if sym else []
        latest = _ts(rows[0].get("latest")) if rows else None
        if latest is None:
            return {"symbol": sym, "latest_local_data": None, "lag_days": None,
                    "lag_months": None, "status": "absent"}
        lag_days = max(0, int((today - latest).days))
        if lag_days <= 5:
            status = "current"
        elif lag_days <= 45:
            status = "recent"
        else:
            status = "stale"
        return {"symbol": sym, "latest_local_data": str(latest.date()),
                "lag_days": lag_days, "lag_months": _months_between(latest, today),
                "status": status}

    out = one(symbol)
    out["benchmark"] = one(benchmark_symbol) if benchmark_symbol else None
    return out


def _model_training_freshness(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """How old is the family training corpus? A property of the model, not the view.

    A fixed-cutoff reference anchor is expected to age; that is honest, not a
    fault. This reports the age so the user can judge it, but nothing here ever
    blocks a forecast.
    """
    cutoff = _training_cutoff(manifest)
    horizon = _horizon_months(manifest)
    if cutoff is None:
        return {"training_period_end": None, "age_months": None, "age_days": None,
                "target_horizon_months": horizon, "status": "unknown",
                "training_symbol_count": len(_family_symbols(manifest))}
    today = _today()
    age_days = max(0, int((today - cutoff).days))
    age_months = _months_between(cutoff, today)
    # Age is judged relative to the forecast horizon: a corpus older than roughly
    # one horizon has had time for a full cohort of new labels to mature.
    if age_months is None:
        status = "unknown"
    elif age_months < max(6, horizon / 2):
        status = "current"
    elif age_months < max(12, horizon):
        status = "aging"
    else:
        status = "old"
    return {"training_period_end": str(cutoff.date()), "age_days": age_days,
            "age_months": age_months, "target_horizon_months": horizon,
            "status": status, "training_symbol_count": len(_family_symbols(manifest))}


def _retrainability(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Has enough new *family* data accumulated, and enough labels matured, to
    make retraining meaningful?

    Measured over the model's own training universe, never over the single viewed
    ticker. New labels only count once they have matured: a label for an
    observation at date d does not exist until one forecast horizon has elapsed,
    so newly matured labels come from observations no later than ``today - h``.
    """
    cutoff = _training_cutoff(manifest)
    horizon = _horizon_months(manifest)
    family = _family_symbols(manifest)
    base = {"training_cutoff": str(cutoff.date()) if cutoff is not None else None,
            "target_horizon_months": horizon, "family_symbol_count": len(family),
            "newest_family_observation": None, "family_symbols_with_new_data": 0,
            "new_family_observation_months": None, "newly_matured_label_months": None,
            "matured_label_cutoff": None, "update_available": False,
            "update_recommended": False, "update_required": False}
    if cutoff is None or not family:
        base["reason"] = "The model does not record a training cutoff or universe."
        return base
    today = _today()
    matured_cutoff = today - pd.Timedelta(days=int(round(horizon * _DAYS_PER_MONTH)))
    base["matured_label_cutoff"] = str(matured_cutoff.date())
    coverage = {str(r.get("symbol", "")).upper(): r for r in research_store.coverage(family)}
    newest: Optional[pd.Timestamp] = None
    with_new = 0
    for sym in family:
        latest = _ts((coverage.get(sym) or {}).get("latest"))
        if latest is None:
            continue
        if latest > cutoff:
            with_new += 1
            if newest is None or latest > newest:
                newest = latest
    base["family_symbols_with_new_data"] = with_new
    if newest is not None:
        base["newest_family_observation"] = str(newest.date())
        base["new_family_observation_months"] = _months_between(cutoff, newest)
        # Only observations at or before the maturity cutoff have a known label.
        matured_edge = min(newest, matured_cutoff)
        base["newly_matured_label_months"] = _months_between(cutoff, matured_edge)
    matured = base["newly_matured_label_months"] or 0
    base["update_available"] = with_new > 0
    # Recommend an update once a meaningful cohort of new labels has matured -
    # roughly half a horizon - so the extra data can actually change the fit.
    base["update_recommended"] = matured >= max(3, horizon / 2)
    if not base["update_available"]:
        base["reason"] = "No compatible family data newer than the training cutoff is stored locally."
    elif base["update_recommended"]:
        base["reason"] = "New family observations with matured labels have accumulated since training."
    else:
        base["reason"] = "Some new family data exists, but too few new labels have matured to change the fit."
    return base


def evaluate_model_freshness(manifest: Dict[str, Any], ticker: str,
                             benchmark_symbol: Optional[str] = None) -> Dict[str, Any]:
    """Return the three freshness concepts plus a compatibility ``status``.

    ``status`` mirrors ``model_training_freshness.status`` so existing callers
    that only read a single freshness label keep working, but the three nested
    blocks are the correct, unambiguous answer.
    """
    if not manifest:
        return {"status": "unknown", "reason": "No model selected.",
                "instrument_data_freshness": _instrument_data_freshness(ticker, benchmark_symbol),
                "model_training_freshness": None, "retrainability": None}
    model = _model_training_freshness(manifest)
    return {
        "status": model["status"],
        "instrument_data_freshness": _instrument_data_freshness(ticker, benchmark_symbol),
        "model_training_freshness": model,
        "retrainability": _retrainability(manifest),
    }
