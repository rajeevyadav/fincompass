"""Runtime orchestration for validated frozen-anchor forecast models in FinCompass."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import pandas as pd

from forecasting.features import asof_merge_fundamentals, build_price_features, build_monthly_relative_features
from forecasting.registry import load_best_forecast_model, load_model, registry_status
from forecasting.sec_fundamentals import SecClient, fetch_ticker_fundamental_history
from services.analyzer import get_price_history_cached
from services.research_store import research_store
from services.instrument_classification import classify_instrument, resolve_instrument
from services.benchmark_resolver import resolve_benchmark
from services.model_selection import select_model, applicability




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
        status["message"] = "No forecast-eligible model family is installed. Guided Forecast does not require an active Live anchor; installed pooled Bayesian/validated families are selected by horizon and applicability."
    return status


def forecast_ticker(ticker: str, model_id: Optional[str] = None, profile_name: Optional[str] = None, horizon_months: Optional[int] = None) -> Dict[str, Any]:
    instrument = resolve_instrument(ticker)
    resolved_benchmark = resolve_benchmark(instrument)
    if instrument.get("asset_class") == "unknown" or not resolved_benchmark.get("supported"):
        return {"available": False, "blocked_by_preflight": True, "reason_code": "UNSUPPORTED_INSTRUMENT", "message": "FinCompass can analyze this instrument, but no scientifically appropriate Forecast benchmark/model family is available yet.", "instrument": instrument, "benchmark": resolved_benchmark}
    requested_horizon = int(horizon_months or 12)
    if model_id:
        model, manifest = load_model(model_id=model_id, profile_name=profile_name, minimum_tier="bayesian_baseline")
        if model is None or manifest is None:
            return {"available": False, "message": "The selected model artifact is unavailable or failed integrity checks."}
        verdict = applicability(manifest, instrument, resolved_benchmark)
        if not verdict.get("supported"):
            return {"available": False, "blocked_by_preflight": True, **verdict, "instrument": instrument, "benchmark": resolved_benchmark}
    else:
        selected = select_model(instrument, resolved_benchmark, requested_horizon).get("selected")
        if selected is None:
            return {"available": False, "blocked_by_preflight": True, "reason_code": "NO_APPLICABLE_MODEL_FAMILY", "message": "FinCompass has no Forecast model family for this market and horizon yet. Analytics remain available.", "instrument": instrument, "benchmark": resolved_benchmark, "horizon_months": requested_horizon}
        model, manifest = load_model(model_id=str(selected.get("model_id")), minimum_tier="bayesian_baseline")
        if model is None or manifest is None:
            return {"available": False, "message": "The selected model artifact is unavailable or failed integrity checks."}
    benchmark = str(resolved_benchmark.get("symbol") or (manifest.get("target") or {}).get("benchmark") or model.settings.get("benchmark") or "SPY").upper()
    stock = _get_price_history(ticker)
    bench = _get_price_history(benchmark)
    if stock is None or bench is None or stock.empty or bench.empty:
        return {"available": False, "message": "Price history unavailable for the ticker or benchmark.", "model_id": manifest.get("model_id")}
    provenance = manifest.get("dataset_provenance") or {}
    feature_contract = str(provenance.get("feature_contract") or "price_relative_v1")
    if feature_contract.startswith("monthly_relative"):
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
    prediction = model.predict_with_uncertainty(sample)[0]
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
        "evidence_strength": "Limited" if manifest.get("validation_tier") == "bayesian_baseline" else "Validated research" if manifest.get("validation_tier") == "validated_research" else "Validated market",
        "live_eligible": manifest.get("validation_tier") in {"validated_research", "validated_market"},
        "disclaimer": (
            "This Bayesian reference probability is mathematically valid and calibrated where supported, but stronger out-of-sample predictive skill has not been established. It is not a recommendation."
            if manifest.get("validation_tier") == "bayesian_baseline" else
            "A validated probability is an empirical model estimate for the defined event, not a guarantee, target price, or recommendation."
        ),
    }
