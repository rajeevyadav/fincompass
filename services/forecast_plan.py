"""Single Guided product-level plan for ticker -> data -> model -> forecast."""
from __future__ import annotations
from typing import Any, Dict
from services.instrument_classification import classify_instrument, resolve_instrument
from services.benchmark_resolver import resolve_benchmark
from services.model_selection import select_model
from services.model_freshness import evaluate_model_freshness
from services.preflight import evaluate_preflight
from services.research_store import research_store


def _ready(symbol: str) -> bool:
    rows = research_store.coverage([symbol])
    return bool(rows and int(rows[0].get("rows") or 0) > 0)


def build_forecast_plan(ticker: str, horizon_months: int = 12) -> Dict[str, Any]:
    instrument = resolve_instrument(ticker)
    benchmark = resolve_benchmark(instrument)
    data_ready = _ready(instrument["symbol"]) and (not benchmark.get("supported") or _ready(str(benchmark.get("symbol") or "")))
    selected_info = select_model(instrument, benchmark, horizon_months) if benchmark.get("supported") else {"selected": None, "eligible": [], "rejected": []}
    selected = selected_info.get("selected")
    preflight = evaluate_preflight(instrument, benchmark, selected, data_ready=data_ready)
    freshness = evaluate_model_freshness(selected, instrument["symbol"]) if selected else None
    preflight_ok = all(preflight.get(k) for k in ("data_ready", "computationally_compatible", "scientifically_supported"))
    if instrument.get("asset_class") == "unknown" or not benchmark.get("supported"):
        action = "unsupported"
    elif not data_ready:
        action = "update_data"
    elif selected is None:
        action = "build_model"
    elif preflight_ok:
        # A selected, applicable model forecasts now. Model freshness is advisory
        # only: the shipped reference anchors have a fixed training cutoff that a
        # user data refresh cannot advance, so it must never gate the forecast
        # (doing so left the Guided flow stuck on "update model" forever).
        action = "forecast"
    elif freshness and freshness.get("status") in {"retrain_recommended", "stale"}:
        action = "update_model"
    else:
        action = "unsupported"
    return {
        "instrument": instrument,
        "horizon_months": int(horizon_months),
        "benchmark": benchmark,
        "data_status": {"ready": data_ready},
        "model": selected,
        "model_freshness": freshness,
        "preflight": preflight,
        "recommended_action": action,
        "eligible_model_count": len(selected_info.get("eligible") or []),
    }
