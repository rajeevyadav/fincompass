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
    # A pooled model can forecast a valid, in-domain instrument by fetching the
    # required history on demand — local store coverage is only needed for the
    # richer Live tracking, not for a one-shot forecast. So a producible forecast
    # is the primary action even before a local data refresh; the refresh is
    # surfaced as advisory (data_update_available), never as a blocking step.
    can_produce = bool(selected) and preflight.get("computationally_compatible") \
        and preflight.get("scientifically_supported")
    if instrument.get("asset_class") == "unknown" or not benchmark.get("supported"):
        action = "unsupported"
    elif can_produce:
        # Model age never blocks the forecast (fixed-cutoff reference anchors could
        # otherwise loop on "update"). Freshness/update stays advisory below.
        action = "forecast"
    elif selected is None:
        action = "update_data" if not data_ready else "build_model"
    elif not data_ready:
        action = "update_data"
    else:
        action = "unsupported"
    # Whether an in-app model update is even possible is decided by the selected
    # model's explicit training contract — never inferred. A stale-but-valid model
    # keeps forecasting; an update is optional maintenance, never a prerequisite.
    contract = (selected or {}).get("training_contract") or {}
    stale = bool(freshness and freshness.get("status") in {"retrain_recommended", "stale"})
    model_update_available = bool(contract.get("retrain_supported")) and stale
    return {
        "instrument": instrument,
        "horizon_months": int(horizon_months),
        "benchmark": benchmark,
        "data_status": {"ready": data_ready},
        "model": selected,
        "model_freshness": freshness,
        "preflight": preflight,
        "recommended_action": action,
        "can_forecast_now": action == "forecast",
        "data_update_available": (not data_ready),
        "model_update_available": model_update_available,
        "model_update_required": False,
        "training_contract": contract or None,
        "eligible_model_count": len(selected_info.get("eligible") or []),
    }
