"""Hard data-readiness gates evaluated BEFORE any Model Lab training.

Training must not start unless every hard gate passes. Each failure carries a
machine-readable code, the actual value, the required minimum, the affected
symbol(s), a plain-language explanation, and the exact corrective action, so the
UI can render "DATA NEEDS ATTENTION" with concrete steps and never surface an
opaque traceback for a predictable data condition.

Thresholds are derived from the real pipeline settings (ForecastSettings) — no
arbitrary numbers. Where a conservative pre-check is used (e.g. minimum usable
history) it is documented as such and stays *below* what the locked-test gates
themselves enforce, so this layer only catches obvious pre-conditions and never
substitutes for scientific validation.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from forecasting.config import settings_from_dict
from forecasting.recipes import get_recipe
from services.research_store import research_store

# Feature contracts the trainer knows how to build.
KNOWN_FEATURE_CONTRACTS = {"price_relative_v1", "monthly_relative_v1"}

# Conservative data-quality tolerances (documented, not gate thresholds).
MAX_MISSING_CLOSE_FRACTION = 0.02   # >2% missing Close in required span → attention
STALE_LATEST_BAR_DAYS = 400         # newest bar older than this → obviously stale
BENCHMARK_ALIGNMENT_TOLERANCE_DAYS = 45  # benchmark may lag a target by at most this
TRADING_DAYS_PER_YEAR = 252
CAL_PER_TRADING = 7.0 / 5.0         # calendar/trading-day conversion


def _years(trading_days: float) -> float:
    return round(trading_days / TRADING_DAYS_PER_YEAR, 1)


def _min_required_trading_days(settings) -> int:
    """Conservative minimum usable per-symbol history for the horizon.

    Must cover: a feature lookback (~1y), the target maturation horizon, two
    embargo gaps between train/validation/test, and a locked-test window of at
    least ``min_test_span_days``. Kept deliberately conservative.
    """
    lookback = TRADING_DAYS_PER_YEAR
    horizon = int(settings.horizon_trading_days)
    embargo = int(settings.embargo_trading_days)
    test_span_td = int(round(int(settings.min_test_span_days) / CAL_PER_TRADING))
    return lookback + horizon + 2 * embargo + test_span_td


def _fail(code, *, symbols=None, actual=None, required=None, explanation="", action="") -> Dict[str, Any]:
    return {
        "code": code,
        "symbols": sorted(symbols) if symbols else [],
        "actual": actual,
        "required": required,
        "explanation": explanation,
        "action": action,
    }


def _coverage_map(symbols: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    rows = research_store.coverage(list(symbols)) if symbols else []
    return {str(r.get("symbol") or "").upper(): r for r in rows}


def _now_ts() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC").tz_localize(None)


def evaluate_training_readiness(
    recipe_id: str,
    tickers_override: Optional[List[str]] = None,
    profile: str = "strict",
) -> Dict[str, Any]:
    """Return a single readiness result for a recipe.

    {status: "ready"|"not_ready", ready: bool, recipe_id, benchmark, horizon_*,
     universe: {requested, usable, excluded[]}, gates: [failure,...], checklist:[...]}
    """
    recipe = get_recipe(recipe_id)
    benchmark = str(recipe.get("benchmark") or "").upper()
    targets = [str(t).upper() for t in (tickers_override or recipe.get("tickers") or []) if str(t).strip()]
    targets = [t for t in dict.fromkeys(targets) if t != benchmark]
    feature_contract = str(recipe.get("feature_contract") or "price_relative_v1")

    settings = settings_from_dict(
        {"horizon_trading_days": int(recipe["horizon_trading_days"]), "benchmark": benchmark},
        base=profile if profile in ("strict", "standard", "exploratory") else "strict",
    )
    required_td = _min_required_trading_days(settings)

    cov = _coverage_map([benchmark, *targets])
    bench_row = cov.get(benchmark) or {}
    bench_rows = int(bench_row.get("rows") or 0)
    bench_latest = pd.Timestamp(bench_row["latest"]) if bench_row.get("latest") else None
    bench_earliest = pd.Timestamp(bench_row["earliest"]) if bench_row.get("earliest") else None

    gates: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []

    # --- feature contract compatibility (recipe-level) ---------------------
    if feature_contract not in KNOWN_FEATURE_CONTRACTS:
        gates.append(_fail(
            "FEATURE_CONTRACT_INCOMPATIBLE", actual=feature_contract, required=sorted(KNOWN_FEATURE_CONTRACTS),
            explanation="This recipe declares a feature contract the trainer does not implement.",
            action="Use a recipe with a supported feature contract.",
        ))

    # --- benchmark presence ------------------------------------------------
    if bench_rows <= 0:
        gates.append(_fail(
            "MISSING_BENCHMARK", symbols=[benchmark], actual=0, required=required_td,
            explanation=f"No local price history for the benchmark {benchmark}; the outperformance target cannot be built.",
            action=f"Update local data for {benchmark}, then re-check.",
        ))

    # --- per-target checks; build the usable universe ----------------------
    usable: List[str] = []
    for sym in targets:
        row = cov.get(sym) or {}
        rows = int(row.get("rows") or 0)
        if rows <= 0:
            excluded.append({"symbol": sym, "reason": "NO_LOCAL_HISTORY"})
            continue

        earliest = pd.Timestamp(row["earliest"]) if row.get("earliest") else None
        latest = pd.Timestamp(row["latest"]) if row.get("latest") else None
        providers = str(row.get("providers") or "").strip()

        # missing provenance / provider metadata
        if not providers:
            gates.append(_fail(
                "MISSING_PROVENANCE", symbols=[sym], actual="none", required="provider recorded",
                explanation=f"{sym} has price rows without a recorded data provider, so its lineage cannot be verified.",
                action=f"Re-import {sym} through Update data so provider provenance is recorded.",
            ))

        # obviously stale newest bar
        if latest is not None:
            age_days = (_now_ts() - latest).days
            if age_days > STALE_LATEST_BAR_DAYS:
                gates.append(_fail(
                    "STALE_DATA", symbols=[sym], actual=f"{age_days} days old", required=f"<= {STALE_LATEST_BAR_DAYS} days",
                    explanation=f"{sym}'s most recent price bar is {age_days} days old.",
                    action=f"Update local data for {sym}.",
                ))

        # insufficient history for the selected horizon
        if rows < required_td:
            gates.append(_fail(
                "INSUFFICIENT_HISTORY_FOR_HORIZON", symbols=[sym], actual=f"{_years(rows)} years",
                required=f"{_years(required_td)} years",
                explanation=(f"A {_years(settings.horizon_trading_days)}-year-horizon model needs at least "
                             f"{_years(required_td)} years of usable history; {sym} has about {_years(rows)}."),
                action=f"Extend local history for {sym} (Update data) or choose a shorter horizon.",
            ))

        # Benchmark alignment: only the TAIL matters — the benchmark must not end
        # well before the target, or recent target observations cannot be scored.
        # A benchmark that *starts* later than a very old stock is normal (e.g. an
        # index/ETF postdates the equity); the dataset builder simply uses the
        # overlapping window, and the history/sample-count gates already bound it,
        # so a head-start gap is NOT a blocker.
        if bench_latest is not None and latest is not None:
            gap = (latest - bench_latest).days
            if gap > BENCHMARK_ALIGNMENT_TOLERANCE_DAYS:
                months = round(gap / 30.0, 1)
                gates.append(_fail(
                    "BENCHMARK_ALIGNMENT", symbols=[benchmark, sym], actual=f"{months} months",
                    required=f"<= {round(BENCHMARK_ALIGNMENT_TOLERANCE_DAYS/30.0,1)} months",
                    explanation=f"{benchmark} history ends about {months} months before {sym}; recent observations cannot be scored.",
                    action=f"Update {benchmark} before training.",
                ))

        # deep per-series quality: duplicates, monotonicity, invalid/missing prices
        frame = research_store.read_price_history(sym)
        if frame is not None and not frame.empty:
            idx = frame.index
            dups = int(idx.duplicated().sum())
            if dups > 0:
                gates.append(_fail(
                    "DUPLICATE_DATES", symbols=[sym], actual=dups, required=0,
                    explanation=f"{sym} has {dups} duplicated dates, which would corrupt return construction.",
                    action=f"Re-import {sym} through Update data to rebuild a clean series.",
                ))
            if not idx.is_monotonic_increasing:
                gates.append(_fail(
                    "NON_MONOTONIC_DATES", symbols=[sym], actual="unordered", required="ascending",
                    explanation=f"{sym}'s dates are not in ascending order after normalization.",
                    action=f"Re-import {sym} through Update data.",
                ))
            close = frame["Close"] if "Close" in frame.columns else pd.Series(dtype=float)
            nonpositive = int(((close <= 0) & close.notna()).sum())
            if nonpositive > 0:
                gates.append(_fail(
                    "NONPOSITIVE_PRICES", symbols=[sym], actual=nonpositive, required=0,
                    explanation=f"{sym} has {nonpositive} nonpositive/invalid closing prices.",
                    action=f"Re-import {sym} from a corrected source through Update data.",
                ))
            missing_frac = float(close.isna().mean()) if len(close) else 1.0
            if missing_frac > MAX_MISSING_CLOSE_FRACTION:
                gates.append(_fail(
                    "EXCESSIVE_MISSING", symbols=[sym], actual=f"{round(missing_frac*100,1)}%",
                    required=f"<= {round(MAX_MISSING_CLOSE_FRACTION*100,1)}%",
                    explanation=f"{sym} is missing closing prices on {round(missing_frac*100,1)}% of its dates.",
                    action=f"Re-import {sym} to fill gaps through Update data.",
                ))

        usable.append(sym)

    # --- universe-level gates ---------------------------------------------
    if not usable:
        gates.append(_fail(
            "MISSING_TARGETS", actual=0, required=1,
            explanation="No target series with local history are available for this recipe.",
            action="Update local data for this recipe's symbols, then re-check.",
        ))

    # estimated locked-test sample sufficiency (cross-sectional)
    if usable and bench_rows > 0:
        sample_step = int(settings.sample_step_trading_days)
        per_symbol_samples = max(0, (min(int((cov.get(s) or {}).get("rows") or 0) for s in usable) - required_td)) // max(sample_step, 1)
        est_total = per_symbol_samples * len(usable)
        est_test = int(est_total * float(settings.test_fraction))
        if est_test < int(settings.min_test_samples):
            gates.append(_fail(
                "INSUFFICIENT_MATURED_LABELS", symbols=usable, actual=est_test, required=int(settings.min_test_samples),
                explanation=("There are not enough matured, dated observations to build a locked test of the required size "
                             f"(estimated {est_test}, need {int(settings.min_test_samples)})."),
                action="Add more history or more instruments to this recipe through Update data.",
            ))

    ready = not gates
    return {
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "recipe_id": recipe_id,
        "recipe_name": recipe.get("name"),
        "benchmark": benchmark,
        "horizon_trading_days": int(recipe["horizon_trading_days"]),
        "feature_contract": feature_contract,
        "required_history_years": _years(required_td),
        "universe": {
            "requested": targets,
            "usable": usable,
            "excluded": excluded,
        },
        "gates": gates,
        "checklist": _checklist(gates, bench_rows, usable),
    }


def _checklist(gates: List[Dict[str, Any]], bench_rows: int, usable: List[str]) -> List[Dict[str, Any]]:
    """The 'Can FinCompass train this model?' panel rows."""
    codes = {g["code"] for g in gates}
    def ok(cond):
        return "pass" if cond else "fail"
    return [
        {"label": "Enough historical data", "status": ok("INSUFFICIENT_HISTORY_FOR_HORIZON" not in codes and "MISSING_TARGETS" not in codes)},
        {"label": "Benchmark available", "status": ok("MISSING_BENCHMARK" not in codes and bench_rows > 0)},
        {"label": "Enough completed outcomes", "status": ok("INSUFFICIENT_MATURED_LABELS" not in codes)},
        {"label": "Data quality passed", "status": ok(not (codes & {"DUPLICATE_DATES", "NON_MONOTONIC_DATES", "NONPOSITIVE_PRICES", "EXCESSIVE_MISSING", "STALE_DATA", "MISSING_PROVENANCE"}))},
        {"label": "Validation periods can be constructed", "status": ok(not (codes & {"BENCHMARK_ALIGNMENT", "FEATURE_CONTRACT_INCOMPATIBLE", "INSUFFICIENT_MATURED_LABELS"}))},
    ]
