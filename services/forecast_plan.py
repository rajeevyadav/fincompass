"""Forecast plan orchestrator.

ONE backend endpoint's worth of product logic: given a user-entered ticker and an
understandable horizon, resolve the instrument, its benchmark, data status,
eligible/trainable/unsupported models, model freshness, and the single
``recommended_action`` the Guided UI should take. The frontend must not
reconstruct this from many endpoints.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from forecasting.recipes import list_recipes
from services.instrument_classification import classify_instrument
from services.benchmark_resolver import resolve_benchmark, benchmark_family_of
from services.model_selection import find_models
from services.model_freshness import assess_model_freshness
from services.preflight import forecast_preflight
from services.training_readiness import evaluate_training_readiness
from services.research_store import research_store

# Recommended actions the Guided UI can take.
FORECAST = "forecast"
UPDATE_DATA = "update_data"
TRAIN = "train"
UNSUPPORTED = "unsupported"

# Readiness gate codes that a data update can plausibly fix.
_DATA_FIXABLE = {"MISSING_BENCHMARK", "MISSING_TARGETS", "INSUFFICIENT_HISTORY_FOR_HORIZON",
                 "BENCHMARK_ALIGNMENT", "STALE_DATA", "INSUFFICIENT_MATURED_LABELS",
                 "DUPLICATE_DATES", "NON_MONOTONIC_DATES", "NONPOSITIVE_PRICES",
                 "EXCESSIVE_MISSING", "MISSING_PROVENANCE"}


def _latest(symbol: Optional[str]):
    if not symbol:
        return None
    try:
        return research_store.latest_date(symbol)
    except Exception:
        return None


def _pick_recipe(classification: Dict[str, Any], horizon_months: int,
                 benchmark_policy: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Find a training recipe whose horizon and benchmark family fit this request."""
    want_td = int(horizon_months) * 21  # ~21 trading days/month
    best = None
    for r in list_recipes():
        htd = int(r.get("horizon_trading_days") or 0)
        if abs(htd - want_td) > 21:  # within ~1 month
            continue
        # match on benchmark FAMILY (SPY and ^GSPC are both US_LARGE_CAP)
        want_family = benchmark_policy.get("benchmark_family")
        recipe_family = benchmark_family_of(r.get("benchmark"))
        if want_family and recipe_family and recipe_family != want_family:
            continue
        best = r
        break
    return best


def build_forecast_plan(ticker: str, horizon_months: int = 12) -> Dict[str, Any]:
    ticker = str(ticker or "").upper()
    horizon_months = int(horizon_months or 12)
    classification = classify_instrument(ticker, allow_provider=True)
    benchmark_policy = resolve_benchmark(classification)

    plan: Dict[str, Any] = {
        "instrument": classification,
        "horizon_months": horizon_months,
        "benchmark": benchmark_policy,
        "data_status": {},
        "models": {"eligible": [], "trainable": [], "unsupported": []},
        "model_freshness": None,
        "alternatives": [],
        "recommended_action": UNSUPPORTED,
        "message": None,
    }

    if not classification.get("available"):
        plan["message"] = "FinCompass could not identify this instrument's market and type."
        return plan
    if not benchmark_policy.get("supported"):
        plan["message"] = ("FinCompass does not yet have a benchmark policy for this instrument's "
                           "market, so it cannot make a scientifically supportable forecast.")
        return plan

    search = find_models(classification, benchmark_policy, horizon_months)
    plan["models"]["eligible"] = search["eligible"]
    plan["models"]["unsupported"] = search["unsupported"]
    plan["alternatives"] = search["alternatives"]

    ticker_latest = _latest(ticker)
    bench_latest = _latest(benchmark_policy.get("benchmark_symbol"))
    current_latest = max([d for d in (ticker_latest, bench_latest) if d is not None], default=None)
    plan["data_status"] = {
        "ticker_latest": (ticker_latest.date().isoformat() if ticker_latest is not None else None),
        "benchmark_latest": (bench_latest.date().isoformat() if bench_latest is not None else None),
    }

    if search["eligible"]:
        top = search["eligible"][0]
        pf = forecast_preflight(ticker, model_id=top.get("model_id"))
        plan["preflight"] = {k: pf.get(k) for k in
                             ("status", "data_ready", "computationally_compatible",
                              "scientifically_supported", "reasons")}
        plan["model_freshness"] = assess_model_freshness(
            {"applicability_domain": top.get("applicability_domain")}, current_latest, horizon_months)
        plan["data_status"]["data_ready"] = bool(pf.get("data_ready"))
        if not pf.get("data_ready"):
            plan["recommended_action"] = UPDATE_DATA
            plan["update_symbols"] = [s for s in [ticker, top.get("benchmark")] if s]
            plan["message"] = "More market history is needed before this forecast can be produced."
        else:
            plan["recommended_action"] = FORECAST
            plan["message"] = "A validated model is ready for this instrument."
        return plan

    # No eligible model at this horizon → can we train one?
    recipe = _pick_recipe(classification, horizon_months, benchmark_policy)
    if recipe:
        recipe_symbols = [s for s in [recipe.get("benchmark"), *(recipe.get("tickers") or [])] if s]
        readiness = evaluate_training_readiness(recipe["recipe_id"])
        if readiness.get("ready"):
            plan["models"]["trainable"] = [{"recipe_id": recipe["recipe_id"], "name": recipe.get("name"),
                                            "horizon_months": horizon_months}]
            plan["recommended_action"] = TRAIN
            plan["message"] = "A model can be built with the available data."
            plan["readiness"] = readiness
            return plan
        gate_codes = {g["code"] for g in readiness.get("gates", [])}
        if gate_codes and gate_codes <= _DATA_FIXABLE:
            plan["recommended_action"] = UPDATE_DATA
            plan["update_symbols"] = recipe_symbols
            plan["message"] = "More current data are needed before a model can be built."
            plan["readiness"] = readiness
            plan["models"]["trainable"] = [{"recipe_id": recipe["recipe_id"], "name": recipe.get("name"),
                                            "horizon_months": horizon_months, "blocked_by_data": True}]
            return plan
        # non-data gates → scientifically insufficient
        plan["recommended_action"] = UNSUPPORTED
        plan["message"] = (f"There is not enough historical evidence to build a reliable "
                          f"{horizon_months}-month model for this instrument yet.")
        plan["readiness"] = readiness
        return plan

    # No recipe for this horizon and no eligible model → unsupported; offer alternatives
    plan["recommended_action"] = UNSUPPORTED
    plan["message"] = (f"FinCompass does not yet have a validated {horizon_months}-month model "
                      "for this security.")
    return plan
