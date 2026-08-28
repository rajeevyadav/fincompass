"""Runtime orchestration for validated frozen-anchor forecast models in FinCompass."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import pandas as pd

from forecasting.features import asof_merge_fundamentals, build_price_features, build_monthly_relative_features
from forecasting.registry import load_model, registry_status
from forecasting.sec_fundamentals import SecClient, fetch_ticker_fundamental_history
from services.analyzer import get_price_history_cached
from services.research_store import research_store




def _get_price_history(symbol: str) -> pd.DataFrame:
    """Prefer the durable research corpus; use the legacy network/cache path only as fallback."""
    local = research_store.read_price_history(symbol)
    if local is not None and not local.empty:
        return local
    remote = get_price_history_cached(symbol, "max")
    if remote is None:
        return pd.DataFrame()
    return remote

def get_forecast_status() -> Dict[str, Any]:
    status = registry_status()
    if not status["usable_models"]:
        status["message"] = (
            "No explicitly activated validated forecast model is available. Use Model Lab to "
            "train from retained local data, review the validation evidence, and explicitly activate "
            "an eligible candidate. Synthetic fixture models are never activated for live forecasts."
        )
    return status


def forecast_ticker(ticker: str, model_id: Optional[str] = None, profile_name: Optional[str] = None) -> Dict[str, Any]:
    try:
        model, manifest = load_model(model_id=model_id, profile_name=profile_name, minimum_tier="validated_research")
    except Exception as exc:
        return {"available": False, "status": "error",
                "reasons": [{"code": "MODEL_LOAD_ERROR", "message_data": {"detail": str(exc)}}],
                "message": "The forecast model could not be loaded."}
    if model is None or manifest is None:
        return {"available": False, **get_forecast_status()}
    benchmark = str((manifest.get("target") or {}).get("benchmark") or model.settings.get("benchmark") or "SPY").upper()
    stock = _get_price_history(ticker)
    bench = _get_price_history(benchmark)
    if stock is None or bench is None or stock.empty or bench.empty:
        return {"available": False, "message": "Price history unavailable for the ticker or benchmark.", "model_id": manifest.get("model_id")}
    provenance = manifest.get("dataset_provenance") or {}
    feature_contract = str(provenance.get("feature_contract") or "price_relative_v1")
    if feature_contract == "monthly_relative_v1":
        features = build_monthly_relative_features(stock, bench)
    else:
        features = build_price_features(stock, bench)
    if features.empty:
        return {"available": False, "message": "Insufficient price history to construct forecasting features.", "model_id": manifest.get("model_id")}
    sample = features.tail(1).copy()
    required_sec = [c for c in model.feature_names if c.startswith("sec_")]
    if required_sec:
        user_agent = os.getenv("SEC_USER_AGENT", "").strip()
        if not user_agent:
            return {
                "available": False,
                "message": "This model requires point-in-time SEC features; configure SEC_USER_AGENT to reconstruct them.",
                "model_id": manifest.get("model_id"),
            }
        history = fetch_ticker_fundamental_history(ticker, SecClient(user_agent=user_agent))
        sample = asof_merge_fundamentals(sample, history)
    missing = [c for c in model.feature_names if c not in sample.columns]
    if missing:
        return {"available": False, "message": f"Required model features unavailable: {', '.join(missing)}", "model_id": manifest.get("model_id")}
    try:
        prediction = model.predict_with_uncertainty(sample)[0]
    except Exception as exc:
        return {"available": False, "status": "error",
                "reasons": [{"code": "INFERENCE_ERROR", "message_data": {"detail": str(exc)}}],
                "message": "The forecast could not be computed for this stock.",
                "model_id": manifest.get("model_id")}
    asof = pd.Timestamp(sample.index[-1]).date().isoformat()
    target = manifest.get("target") or {}
    return {
        "available": True,
        "ticker": ticker.upper(),
        "as_of": asof,
        "model_id": manifest.get("model_id"),
        "validation_tier": manifest.get("validation_tier"),
        "target": target,
        "probability": prediction,
        "validation_summary": {
            "locked_test_metrics": (manifest.get("validation") or {}).get("locked_test_metrics"),
            "gate": (manifest.get("validation") or {}).get("gate"),
        },
        "disclaimer": "A validated probability is an empirical model estimate for the defined event, not a guarantee, target price, or recommendation.",
    }
