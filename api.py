"""FinCompass REST API."""
from __future__ import annotations

import csv
import io
import logging
import json as _json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
import html as _htmlmod
import re as _remod
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import (
    APP_VERSION,
    CHART_PERIODS,
    DATA_SCHEMA_VERSION,
    DEFAULT_UNIVERSE,
    FRED_API_KEY,
    FMP_API_KEY,
    ALPHA_VANTAGE_KEY,
    PILLAR_WEIGHTS,
    RATE_LIMIT_BACKEND,
    SCORING_ENGINE_VERSION,
    TICKER_NAMES,
)
from services.analyzer import (
    _get_macro_cached,
    analyze_ticker,
    get_price_history_cached,
    get_screener_refresh_status,
    start_screener_refresh,
)
from services.cache import cache
from services.data_fetcher import fetcher
from services.macro_fetcher import get_health_snapshot as get_fred_health
from services.guardrails import GuardrailMiddleware, effective_rate_limit_backend, validate_ticker
from services.scoring import generate_thesis, get_label_color
from services.posture import build_posture
from services.model_builder import start_model_build, get_model_build_status
from services.training_readiness import evaluate_training_readiness
from forecasting.registry import clear_active_model, get_active_pointer, set_active_model
from forecasting.recipes import get_recipe as get_model_lab_recipe, list_instruments as list_model_lab_instruments, list_recipes as list_model_lab_recipes
from services.research_store import research_store
from services.research_data import start_refresh as start_research_refresh, refresh_status as research_refresh_status
from forecasting import FORECAST_ENGINE_VERSION
from forecasting.config import settings_from_dict, settings_schema
from services.forecast_service import forecast_ticker, get_forecast_status
from services.forecast_plan import build_forecast_plan
from services.market_catalog import COMMON_SECTORS, SUPPORTED_REGIONS, search_equities, search_symbol

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("FinCompass.API")

app = FastAPI(
    title="FinCompass API",
    description=(
        "Free systematic stock research with Bayesian evidence uncertainty and gated probabilistic forecasting — "
        "Quality · Financial durability · Safety · Valuation · Cycle. Educational only."
    ),
    version=APP_VERSION,
    # Default docs pull Swagger UI from a CDN, which the strict CSP blocks and
    # which fails offline. We self-host the assets and serve a custom /docs so
    # the API explorer works fully within the user's system (see /docs route).
    docs_url=None,
    redoc_url=None,
)
app.add_middleware(GuardrailMiddleware)


@app.get("/docs", include_in_schema=False)
def custom_swagger_ui():
    from fastapi.openapi.docs import get_swagger_ui_html
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title="FinCompass API — docs",
        swagger_js_url="/static/vendor/swagger-ui-bundle.js",
        swagger_css_url="/static/vendor/swagger-ui.css",
        swagger_favicon_url="/favicon.ico",
    )
app.mount("/static", StaticFiles(directory="static"), name="static")


class PillarOut(BaseModel):
    score: float
    weight: float
    evidence_coverage: float = 0.0
    credible_interval_90: List[float] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)


class AnalysisOut(BaseModel):
    ticker: str
    name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[float] = None
    engine_version: str
    composite: float
    raw_composite: Optional[float] = None
    label: str
    color: str
    thesis: str
    pillars: Dict[str, PillarOut]
    posture: Dict[str, Any] = Field(default_factory=dict)
    uncertainty: Dict[str, Any] = Field(default_factory=dict)
    data_quality: Dict[str, Any] = Field(default_factory=dict)
    source: Optional[str] = None
    cached: bool = False
    updated_at: Optional[str] = None
    request_id: Optional[str] = None


class ScreenerRow(BaseModel):
    ticker: str
    name: Optional[str] = None
    sector: Optional[str] = None
    composite: float
    label: str
    confidence: str
    evidence_coverage: float
    interval_low: float
    interval_high: float
    quality: float
    moat: float
    safety: float
    valuation: float
    cycle: float
    updated_at: Optional[str] = None


class HealthOut(BaseModel):
    status: str
    version: str
    engine_version: str
    forecast_engine_version: str
    data_schema_version: str
    universe_size: int
    pillars: Dict[str, float]
    guardrails: List[str]
    rate_limit_backend: str
    configured_rate_limit_backend: str
    optional_sources: Dict[str, bool]
    provider_health: Dict[str, Any] = Field(default_factory=dict)
    forecast_registry: Dict[str, Any] = Field(default_factory=dict)
    realtime_engine_version: Optional[str] = None
    realtime_status: Dict[str, Any] = Field(default_factory=dict)


def _rid(request: Request) -> Optional[str]:
    return getattr(request.state, "request_id", None)


def _csv_safe(value: Any) -> Any:
    """Prevent spreadsheet formula injection in exported text cells."""
    if not isinstance(value, str):
        return value
    if value.startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        return "'" + value
    return value


def _to_analysis(result: Dict[str, Any], cached: bool = False, request_id: str = None) -> AnalysisOut:
    pillars: Dict[str, PillarOut] = {}
    for key, value in result.get("pillars", {}).items():
        pillars[key] = PillarOut(
            score=value["score"],
            weight=value.get("weight", PILLAR_WEIGHTS.get(key, 0)),
            evidence_coverage=value.get("evidence_coverage", value.get("details", {}).get("bayesian", {}).get("evidence_coverage", 0.0)),
            credible_interval_90=value.get("credible_interval_90", value.get("details", {}).get("bayesian", {}).get("credible_interval_90", [])),
            details=value.get("details", {}),
        )
    return AnalysisOut(
        ticker=result.get("ticker", ""),
        name=result.get("name"),
        sector=result.get("sector"),
        industry=result.get("industry"),
        market_cap=result.get("market_cap"),
        engine_version=result.get("engine_version", SCORING_ENGINE_VERSION),
        composite=result["composite"],
        raw_composite=result.get("raw_composite"),
        label=result["label"],
        color=get_label_color(result["composite"]),
        thesis=generate_thesis(result),
        pillars=pillars,
        posture=build_posture(result),
        uncertainty=result.get("uncertainty", {}),
        data_quality=result.get("data_quality", {}),
        source=result.get("source"),
        cached=cached,
        updated_at=result.get("updated_at"),
        request_id=request_id,
    )


def _screener_rows(
    min_score: float = 0.0,
    sector: Optional[str] = None,
    limit: int = 200,
    min_coverage: float = 0.0,
    confidence: Optional[str] = None,
) -> List[ScreenerRow]:
    rows: List[ScreenerRow] = []
    for result in cache.get_all_scores():
        if float(result.get("composite", 0)) < min_score:
            continue
        sec = str(result.get("sector") or "")
        if sector and sector.lower() not in sec.lower():
            continue
        unc = result.get("uncertainty") or {}
        coverage = float(unc.get("evidence_coverage", 0.0))
        conf = str(unc.get("confidence") or "Low")
        if coverage < min_coverage:
            continue
        if confidence and confidence.lower() != conf.lower():
            continue
        interval = unc.get("credible_interval") or [result["composite"], result["composite"]]
        pillars = result.get("pillars", {})
        rows.append(ScreenerRow(
            ticker=result["ticker"],
            name=result.get("name"),
            sector=sec or None,
            composite=result["composite"],
            label=result["label"],
            confidence=conf,
            evidence_coverage=coverage,
            interval_low=float(interval[0]),
            interval_high=float(interval[1]),
            quality=float(pillars.get("quality", {}).get("score", 0)),
            moat=float(pillars.get("moat", {}).get("score", 0)),
            safety=float(pillars.get("safety", {}).get("score", 0)),
            valuation=float(pillars.get("valuation", {}).get("score", 0)),
            cycle=float(pillars.get("cycle", {}).get("score", 0)),
            updated_at=result.get("updated_at"),
        ))
    rows.sort(key=lambda x: (x.composite, x.evidence_coverage), reverse=True)
    return rows[:limit]


@app.get("/")
def root():
    return FileResponse("static/index.html")


_FAVICON_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    b'<circle cx="16" cy="16" r="15" fill="#0b1220" stroke="#39a9ff" stroke-width="2"/>'
    b'<polygon points="16,5 20.5,16 16,27 11.5,16" fill="#39a9ff"/></svg>'
)


@app.get("/favicon.ico")
def favicon():
    from fastapi.responses import Response
    return Response(content=_FAVICON_SVG, media_type="image/svg+xml")



# --- Local UI-preferences persistence (server-side, this install) ----------
# Mirrors the browser's UI state (runtime settings, training/realtime settings,
# watchlist, consent) into the local data directory so it survives across
# browsers and reinstalls. Local self-hosted state only; nothing leaves the
# machine (see PRIVACY.md).
from config import DATA_DIR as _UI_DATA_DIR
_PREFS_PATH = _UI_DATA_DIR / "ui_prefs.json"


def _read_prefs() -> Dict[str, str]:
    try:
        data = _json.loads(_PREFS_PATH.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_prefs(update: Dict[str, Any]) -> Dict[str, str]:
    prefs = _read_prefs()
    for k, v in list(update.items())[:200]:
        key = str(k)[:80]
        if v is None:
            prefs.pop(key, None)
        else:
            val = v if isinstance(v, str) else _json.dumps(v)
            if len(val) <= 200000:
                prefs[key] = val
    if len(prefs) > 200:
        prefs = dict(list(prefs.items())[-200:])
    _PREFS_PATH.write_text(_json.dumps(prefs), encoding="utf-8")
    return prefs


@app.get("/api/prefs")
def get_prefs():
    return _read_prefs()


@app.put("/api/prefs")
def put_prefs(payload: Dict[str, Any] = Body(default={})):
    return _write_prefs(payload if isinstance(payload, dict) else {})



@app.get("/api/health", response_model=HealthOut)
def health():
    return HealthOut(
        status="ok",
        version=APP_VERSION,
        engine_version=SCORING_ENGINE_VERSION,
        forecast_engine_version=FORECAST_ENGINE_VERSION,
        data_schema_version=DATA_SCHEMA_VERSION,
        universe_size=len(DEFAULT_UNIVERSE),
        pillars=PILLAR_WEIGHTS,
        guardrails=["request_id", "shared_rate_limit", "audit_log", "ticker_validation", "strict_csp", "cross_site_browser_block", "cache_versioning"],
        rate_limit_backend=effective_rate_limit_backend(),
        configured_rate_limit_backend=RATE_LIMIT_BACKEND,
        optional_sources={"fmp": bool(FMP_API_KEY), "alpha_vantage": bool(ALPHA_VANTAGE_KEY), "fred": bool(FRED_API_KEY)},
        provider_health={**fetcher.health_snapshot(), "fred": get_fred_health()},
        forecast_registry=get_forecast_status(),
        realtime_engine_version=REALTIME_ENGINE_VERSION if "REALTIME_ENGINE_VERSION" in globals() else "1.0.0-adaptive1",
        realtime_status=realtime_status() if "realtime_status" in globals() else {},
    )


@app.get("/api/macro")
def macro(request: Request):
    if not FRED_API_KEY:
        return {"available": False, "note": "FRED_API_KEY not configured; macro evidence is omitted rather than imputed.", "request_id": _rid(request)}
    data = _get_macro_cached()
    return {"available": bool(data), "data": data, "request_id": _rid(request)}


@app.get("/api/analyze/{ticker}", response_model=AnalysisOut)
def analyze(ticker: str, request: Request, force: bool = Query(False, description="Ignore score/fundamental cache and refresh")):
    ticker = validate_ticker(ticker)
    rid = _rid(request)
    if not force:
        cached = cache.get_score(ticker)
        if cached:
            logger.info("[%s] cache hit %s", rid, ticker)
            return _to_analysis(cached, cached=True, request_id=rid)
    result = analyze_ticker(ticker, force_refresh=force)
    if not result:
        raise HTTPException(status_code=404, detail=f"Could not analyze {ticker}. Check the symbol or try again later.")
    return _to_analysis(result, cached=False, request_id=rid)


@app.get("/api/compare")
def compare(request: Request, tickers: str = Query(..., description="Comma-separated tickers, max 10"), force: bool = Query(False)):
    parts = [validate_ticker(t) for t in tickers.split(",") if t.strip()]
    if not parts:
        raise HTTPException(400, "Provide at least one ticker")
    if len(parts) > 10:
        raise HTTPException(400, "Maximum 10 tickers")
    rid = _rid(request)
    results = []
    for ticker in parts:
        result = analyze_ticker(ticker, force_refresh=force)
        if result:
            results.append(_to_analysis(result, cached=False, request_id=rid))
    return {"count": len(results), "request_id": rid, "results": results}


@app.get("/api/screener", response_model=List[ScreenerRow])
def screener(
    request: Request,
    min_score: float = Query(0.0, ge=0, le=10),
    sector: Optional[str] = Query(None, max_length=64),
    limit: int = Query(80, ge=1, le=200),
    min_coverage: float = Query(0.0, ge=0, le=1),
    confidence: Optional[str] = Query(None, pattern="^(High|Medium|Low)$"),
    refresh: bool = Query(False, description="Backward-compatible non-blocking refresh trigger"),
):
    if refresh:
        start_screener_refresh()
    return _screener_rows(min_score, sector, limit, min_coverage, confidence)


@app.post("/api/screener/refresh")
def screener_refresh(request: Request):
    state = start_screener_refresh()
    return {**state, "request_id": _rid(request)}


@app.get("/api/screener/status")
def screener_status(request: Request):
    return {**get_screener_refresh_status(), "request_id": _rid(request)}


@app.get("/api/export/screener.csv")
def export_screener_csv(
    min_score: float = Query(0.0, ge=0, le=10),
    sector: Optional[str] = Query(None, max_length=64),
    min_coverage: float = Query(0.0, ge=0, le=1),
    confidence: Optional[str] = Query(None, pattern="^(High|Medium|Low)$"),
):
    rows = _screener_rows(min_score, sector, 200, min_coverage, confidence)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["ticker", "name", "sector", "score", "label", "confidence", "evidence_coverage", "interval_low", "interval_high", "quality", "moat_proxy", "safety", "valuation", "cycle", "updated_at"])
    for r in rows:
        writer.writerow([_csv_safe(x) for x in [r.ticker, r.name or "", r.sector or "", r.composite, r.label, r.confidence, r.evidence_coverage, r.interval_low, r.interval_high, r.quality, r.moat, r.safety, r.valuation, r.cycle, r.updated_at or ""]])
    buffer.seek(0)
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=fincompass-screener.csv"})


@app.get("/api/history/{ticker}")
def history(ticker: str, request: Request, period: str = Query("5y", description="1y | 3y | 5y | 10y | max")):
    ticker = validate_ticker(ticker)
    if period not in CHART_PERIODS:
        raise HTTPException(400, f"period must be one of {CHART_PERIODS}")
    df = get_price_history_cached(ticker, period)
    if df is None or (hasattr(df, "empty") and df.empty):
        raise HTTPException(404, "No price history available")
    records = []
    for idx, row in df.iterrows():
        records.append({
            "date": idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx),
            "open": round(float(row["Open"]), 4) if "Open" in row else None,
            "high": round(float(row["High"]), 4) if "High" in row else None,
            "low": round(float(row["Low"]), 4) if "Low" in row else None,
            "close": round(float(row["Close"]), 4),
            "volume": int(row["Volume"]) if "Volume" in row and row["Volume"] == row["Volume"] else None,
        })
    return {"ticker": ticker, "period": period, "points": records, "request_id": _rid(request)}


@app.get("/api/universe")
def universe():
    entries = [{"ticker": t, "name": TICKER_NAMES.get(t, t)} for t in DEFAULT_UNIVERSE]
    return {
        "tickers": DEFAULT_UNIVERSE,
        "entries": entries,
        "count": len(DEFAULT_UNIVERSE),
        "scope": "curated_starter_universe",
        "dynamic_market_search": True,
        "note": "This starter list powers fast local suggestions; it is not the market-access boundary.",
    }


@app.get("/api/market/search")
def market_search(
    request: Request,
    q: Optional[str] = Query(None, max_length=120),
    sector: Optional[str] = Query(None, max_length=80),
    region: str = Query("us", min_length=2, max_length=2),
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(100, ge=1, le=250),
):
    try:
        if q and not sector:
            result = search_symbol(q, limit=min(limit, 50))
        else:
            result = search_equities(sector=sector, region=region, text=q, offset=offset, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result["request_id"] = _rid(request)
    return result


@app.get("/api/market/meta")
def market_meta(request: Request):
    return {
        "sectors": COMMON_SECTORS,
        "regions": sorted(SUPPORTED_REGIONS),
        "per_request_max": 250,
        "starter_universe_size": len(DEFAULT_UNIVERSE),
        "request_id": _rid(request),
    }


@app.get("/api/methodology")
def methodology():
    return {
        "name": "FinCompass Evidence + Forecasting Framework",
        "version": APP_VERSION,
        "engine_version": SCORING_ENGINE_VERSION,
        "pillars": {
            "quality": {"weight": 0.25, "focus": "ROE, ROIC, margins, free-cash-flow margin and growth evidence"},
            "moat": {"weight": 0.20, "focus": "Financial durability proxies only: capital returns and margin power"},
            "safety": {"weight": 0.20, "focus": "Debt/equity, liquidity and interest coverage, with sector applicability controls"},
            "valuation": {"weight": 0.20, "focus": "P/E, P/B, EV/EBITDA and P/S, using robust live sector medians when enough peers exist and reduced-weight absolute fallbacks otherwise"},
            "cycle": {"weight": 0.15, "focus": "Current valuation/quality regime plus optional FRED yield-curve, credit-spread and sector commodity context"},
        },
        "statistics": {
            "metric_transform": "Continuous piecewise-linear curves replace threshold jumps.",
            "aggregation": "Normalized metric scores are fractional evidence in a Beta conjugate model with a neutral prior.",
            "missing_data": "Missing evidence causes posterior shrinkage toward neutral and wider uncertainty rather than an unqualified neutral score.",
            "peer_model": "Sector references use live medians/IQRs with minimum peer counts to reduce outlier sensitivity. When peer context is unavailable, absolute fallback evidence is down-weighted so uncertainty expands.",
            "uncertainty": "Deterministic Monte Carlo propagates pillar posteriors. The reported 90% model interval envelopes independent and perfect-positive-dependence scenarios so overlapping pillars do not create false precision.",
            "probability_scope": "Posterior probabilities refer to the FinCompass evidence score only; they are not probabilities of profit, return or market outperformance. Probability ranges expose sensitivity to unknown pillar dependence.",
        },
        "labels": {"Strong": "≥ 8.0", "Acceptable": "6.0 – 7.9", "Weak": "< 6.0"},
        "guardrails": ["Engine-versioned cache", "Shared rate limiting", "Background screener refresh", "CSP", "Strict ticker validation"],
        "philosophy": "Free forever. Transparent. Evidence scores and forward-event forecasts remain separate, versioned, and explicitly validated.",
        "disclaimer": "Educational only. Not financial advice or a return forecast.",
    }


@app.get("/api/v3/forecast/status")
def forecast_status(request: Request):
    return {**get_forecast_status(), "request_id": _rid(request)}


@app.get("/api/v3/forecast/{ticker}")
def forecast(
    ticker: str,
    request: Request,
    model_id: Optional[str] = Query(None, max_length=64),
    profile: Optional[str] = Query(None, max_length=64),
    horizon_months: Optional[int] = Query(None, ge=1, le=60),
):
    ticker = validate_ticker(ticker)
    result = forecast_ticker(ticker, model_id=model_id, profile_name=profile, horizon_months=horizon_months)
    result["request_id"] = _rid(request)
    if not result.get("available"):
        return JSONResponse(status_code=409, content=result)
    return result



@app.get("/api/v2/analytics/{ticker}/overview")
def analytics_overview_v2(ticker: str, request: Request):
    """Deterministic price/performance/risk/technical analytics for one instrument."""
    from analytics.performance import performance_summary
    from analytics.risk import risk_summary
    from analytics.technicals import technical_summary
    from services.forecast_service import _get_price_history
    from services.instrument_classification import classify_instrument
    from services.benchmark_resolver import resolve_benchmark
    from services.fundamentals import build_fundamentals
    ticker = validate_ticker(ticker)
    frame = _get_price_history(ticker)
    if frame is None or frame.empty:
        return {"available": False, "ticker": ticker, "message": "Price history unavailable.", "request_id": _rid(request)}
    instrument = classify_instrument(ticker)
    benchmark = resolve_benchmark(instrument)
    bench_frame = None
    if benchmark.get("supported"):
        bench_frame = _get_price_history(str(benchmark.get("symbol")))
    perf = performance_summary(frame["Close"], bench_frame["Close"] if bench_frame is not None and not bench_frame.empty else None)
    # Company fundamentals (financial ratios + a scenario DCF) for equities.
    # Degrades to {available: False, reason} for non-equities or missing statements.
    try:
        market_cap = None
        try:
            snap = fetcher.get_fundamentals(ticker) if "fetcher" in globals() else None
            market_cap = (snap or {}).get("market_cap")
        except Exception:
            market_cap = None
        fundamentals = build_fundamentals(ticker, instrument=instrument, market_cap=market_cap)
    except Exception:
        fundamentals = {"available": False, "reason": "Fundamentals are unavailable for this instrument."}
    return {
        "available": True, "ticker": ticker, "instrument": instrument, "benchmark": benchmark,
        "performance": perf, "risk": risk_summary(frame["Close"]), "technicals": technical_summary(frame),
        "fundamentals": fundamentals,
        "formula_transparency": {"engine": "FinCompass deterministic analytics kernel", "version": "2.0"},
        "request_id": _rid(request),
    }

@app.get("/api/v3/settings/schema")
def forecast_settings_schema(request: Request):
    return {"settings": settings_schema(), "registry": get_forecast_status(), "request_id": _rid(request)}


@app.post("/api/v3/settings/validate")
def validate_forecast_settings(request: Request, payload: Dict[str, Any] = Body(...)):
    profile = str(payload.pop("_profile", "strict")) if isinstance(payload, dict) else "strict"
    try:
        validated = settings_from_dict(payload, base=profile)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "valid": True,
        "profile": profile,
        "settings": validated.to_dict(),
        "note": "Target/model settings are training configuration. Changing them requires rebuilding the dataset and retraining; they never mutate an existing model manifest.",
        "request_id": _rid(request),
    }


@app.get("/api/v3/methodology")
def methodology_v3():
    base = methodology()
    base["forecasting"] = {
        "engine_version": FORECAST_ENGINE_VERSION,
        "target": "Probability that the forward return represented by the configured dataset price series exceeds the benchmark return plus the configured hurdle over a fixed trading-day horizon.",
        "models": ["Bayesian logistic regression with Laplace posterior", "histogram gradient boosting", "random forest"],
        "calibration": "The chronological validation partition is split into three stages: component calibration, ensemble stacking, and final ensemble calibration. Target-end purge plus the configured embargo is applied at each internal boundary. The locked test is never used for fitting.",
        "validation": "Purged chronological train/validation/test partitions, purged/embargoed internal validation stages, locked-test probability metrics, moving date-block plus same-date cross-sectional cluster bootstrap, and purged/embargoed walk-forward stability checks.",
        "activation_gate": "Synthetic fixtures can never activate live forecasts. A real model must pass configured gates to earn validated_research or validated_market status.",
        "validated_market_requirements": ["point-in-time features", "survivorship control", "delistings included", "corporate-action-adjusted prices", "locked-test validation gates passed"],
        "probability_scope": "Unlike the evidence-score posterior, this engine estimates an empirical forward event probability, but only for the exact target and data protocol recorded in the model manifest.",
    }
    return base


def _inline_md(text: str) -> str:
    t = _htmlmod.escape(text)
    t = _remod.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = _remod.sub(r"`(.+?)`", r"<code>\1</code>", t)
    t = _remod.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', t)
    return t


def _md_to_html(md: str) -> str:
    """Minimal, dependency-free Markdown -> HTML for the bundled doc/legal pages.

    Supports headings, unordered lists, fenced code, horizontal rules, and the
    inline emphasis/code/link forms actually used by our docs. CSP-safe: emits
    classes only, no inline styles.
    """
    out: List[str] = []
    in_code = in_list = False
    for line in md.splitlines():
        if line.strip().startswith("```"):
            out.append("</pre>" if in_code else '<pre class="doc-code">')
            in_code = not in_code
            continue
        if in_code:
            out.append(_htmlmod.escape(line))
            continue
        if in_list and not line.lstrip().startswith(("- ", "* ")):
            out.append("</ul>")
            in_list = False
        if not line.strip():
            continue
        h = _remod.match(r"(#{1,6})\s+(.*)", line)
        if h:
            lvl = len(h.group(1))
            out.append("<h%d>%s</h%d>" % (lvl, _inline_md(h.group(2)), lvl))
            continue
        if line.strip() in ("---", "***", "___"):
            out.append("<hr>")
            continue
        if line.lstrip().startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>%s</li>" % _inline_md(line.lstrip()[2:]))
            continue
        out.append("<p>%s</p>" % _inline_md(line))
    if in_list:
        out.append("</ul>")
    if in_code:
        out.append("</pre>")
    return "\n".join(out)


def _doc_page(title: str, rel_path: str, missing: str) -> HTMLResponse:
    p = Path(rel_path)
    body = _md_to_html(p.read_text(encoding="utf-8")) if p.exists() else ("<p>%s</p>" % missing)
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>' + _htmlmod.escape(title) + ' - FinCompass</title>'
        '<link rel="icon" type="image/svg+xml" href="/favicon.ico">'
        '<link rel="stylesheet" href="/static/app.css">'
        '</head><body class="doc-body"><main class="doc-page card">'
        '<p><a href="/">← Back to FinCompass</a></p>'
        + body + '</main></body></html>'
    )
    return HTMLResponse(page)


@app.get("/legal/disclaimer")
def legal_disclaimer():
    return _doc_page("Disclaimer", "legal/DISCLAIMER.md", "Disclaimer unavailable.")


@app.get("/legal/terms")
def legal_terms():
    return _doc_page("Terms of Use", "legal/TERMS.md", "Terms unavailable.")


@app.get("/legal/privacy")
def legal_privacy():
    return _doc_page("Privacy Notice", "PRIVACY.md", "Privacy notice unavailable.")


@app.get("/help")
def help_page():
    return _doc_page("Help", "docs/HELP.md", "Help unavailable.")


@app.get("/user-manual.pdf")
def user_manual_pdf():
    p = Path("docs/FinCompass-User-Manual.pdf")
    if not p.exists():
        raise HTTPException(404, "User manual unavailable")
    return FileResponse(str(p), media_type="application/pdf", filename="FinCompass-User-Manual.pdf")


@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    rid = _rid(request)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "request_id": rid}, headers={"X-Request-ID": rid or ""})


# Versioned aliases for external consumers. Existing /api/* paths remain the
# compatibility surface for the bundled UI; new integrations should prefer v1.
for path, endpoint, methods, response_model in [
    ("/api/v1/health", health, ["GET"], HealthOut),
    ("/api/v1/macro", macro, ["GET"], None),
    ("/api/v1/analyze/{ticker}", analyze, ["GET"], AnalysisOut),
    ("/api/v1/compare", compare, ["GET"], None),
    ("/api/v1/screener", screener, ["GET"], List[ScreenerRow]),
    ("/api/v1/screener/refresh", screener_refresh, ["POST"], None),
    ("/api/v1/screener/status", screener_status, ["GET"], None),
    ("/api/v1/export/screener.csv", export_screener_csv, ["GET"], None),
    ("/api/v1/history/{ticker}", history, ["GET"], None),
    ("/api/v1/universe", universe, ["GET"], None),
    ("/api/v1/market/search", market_search, ["GET"], None),
    ("/api/v1/market/meta", market_meta, ["GET"], None),
    ("/api/v1/methodology", methodology, ["GET"], None),
]:
    app.add_api_route(path, endpoint, methods=methods, response_model=response_model, include_in_schema=True)


# Forecasting API v2 compatibility aliases. FinCompass publishes v3 as the
# primary forecasting surface; these aliases avoid breaking pre-release v2 clients.
for path, endpoint, methods in [
    ("/api/v2/forecast/status", forecast_status, ["GET"]),
    ("/api/v2/forecast/{ticker}", forecast, ["GET"]),
    ("/api/v2/settings/schema", forecast_settings_schema, ["GET"]),
    ("/api/v2/settings/validate", validate_forecast_settings, ["POST"]),
    ("/api/v2/methodology", methodology_v3, ["GET"]),
]:
    app.add_api_route(path, endpoint, methods=methods, include_in_schema=False)

# ---------------------------------------------------------------------------
# FinCompass adaptive / near-real-time API
# ---------------------------------------------------------------------------
from realtime import REALTIME_ENGINE_VERSION
from realtime.config import settings_from_dict as realtime_settings_from_dict, settings_schema as realtime_settings_schema
from realtime.store import store as realtime_store
from services.realtime_service import compare_live_profiles, live_snapshot, process_matured_labels, realtime_status
import hmac as _hmac
import hashlib as _hashlib
import json as _json
import os as _os
from datetime import datetime as _datetime, timezone as _timezone


@app.get("/api/v4/forecast/status")
def forecast_status_v4(request: Request):
    return {**get_forecast_status(), "realtime_engine_version": REALTIME_ENGINE_VERSION, "request_id": _rid(request)}


@app.get("/api/v4/model-lab/data")
def model_lab_data_v4(request: Request):
    return {
        "audit": research_store.audit(),
        "refresh": research_refresh_status(),
        "recent_fetches": research_store.fetch_history(20),
        "raw_sources": research_store.raw_sources(25),
        "request_id": _rid(request),
    }


@app.get("/api/v4/model-lab/data/refresh/status")
def model_lab_refresh_status_v4(request: Request):
    return {**research_refresh_status(), "request_id": _rid(request)}


@app.post("/api/v4/model-lab/data/refresh")
def model_lab_refresh_v4(request: Request, payload: Dict[str, Any] = Body(default={})):
    payload = payload if isinstance(payload, dict) else {}
    raw_symbols = payload.get("symbols")
    symbols = None
    if raw_symbols is not None:
        if not isinstance(raw_symbols, list) or len(raw_symbols) > 100:
            raise HTTPException(422, "symbols must be a list of at most 100 tickers")
        catalogue = {str(row.get("symbol") or "").upper() for row in list_model_lab_instruments()}
        symbols = []
        for value in raw_symbols:
            candidate = str(value or "").strip().upper()
            if candidate in catalogue:
                # Reference indices such as ^GSPTSE and ^N225 are intentional
                # Model Lab symbols even though they are not normal equity
                # tickers accepted by the public analysis guardrail.
                symbols.append(candidate)
            else:
                symbols.append(validate_ticker(candidate))
    try:
        overlap = int(payload.get("overlap_calendar_days", 10))
    except (TypeError, ValueError):
        raise HTTPException(422, "overlap_calendar_days must be an integer")
    if overlap < 0 or overlap > 90:
        raise HTTPException(422, "overlap_calendar_days must be between 0 and 90")
    return {**start_research_refresh(symbols, overlap_calendar_days=overlap), "request_id": _rid(request)}


def _model_lab_recipe_readiness() -> List[Dict[str, Any]]:
    """Return recipe metadata annotated with local-corpus readiness.

    Readiness is descriptive only; it never relaxes training or validation. A
    recipe is trainable when its benchmark and at least one declared target are
    present locally. Missing targets remain visible so partial-corpus builds are
    never mistaken for full-universe runs.
    """
    recipes = list_model_lab_recipes()
    symbols = sorted({
        str(symbol).upper()
        for recipe in recipes
        for symbol in [recipe.get("benchmark"), *(recipe.get("tickers") or [])]
        if symbol
    })
    coverage = {
        str(row.get("symbol") or "").upper(): row
        for row in research_store.coverage(symbols)
    }
    out: List[Dict[str, Any]] = []
    for recipe in recipes:
        row = dict(recipe)
        benchmark = str(row.get("benchmark") or "").upper()
        targets = [str(x).upper() for x in (row.get("tickers") or [])]
        benchmark_rows = int((coverage.get(benchmark) or {}).get("rows") or 0)
        present = [symbol for symbol in targets if int((coverage.get(symbol) or {}).get("rows") or 0) > 0]
        missing = [symbol for symbol in targets if symbol not in present]
        row["readiness"] = {
            "trainable": benchmark_rows > 0 and bool(present),
            "benchmark_ready": benchmark_rows > 0,
            "benchmark_rows": benchmark_rows,
            "targets_present_count": len(present),
            "targets_required_count": len(targets),
            "target_symbols_present": present,
            "target_symbols_missing": missing,
        }
        out.append(row)
    return out


@app.get("/api/v4/model-lab/recipes")
def model_lab_recipes_v4(request: Request):
    recipes = _model_lab_recipe_readiness()
    live_ready = [
        row for row in recipes
        if row.get("live_eligible_target") is not False and (row.get("readiness") or {}).get("trainable")
    ]
    if live_ready:
        # Keep the novice default stable and interpretable: prefer the core
        # six-month contract when it is ready, then rank other live-eligible
        # recipes by local target coverage. Research mode still exposes every
        # recipe explicitly.
        core = next((row for row in live_ready if row.get("recipe_id") == "core-us-6m"), None)
        if core is not None:
            recommended = core
            reason = "Core US 6M is trainable from the local research store and is the default guided starting point."
        else:
            recommended = sorted(
                live_ready,
                key=lambda row: (
                    -int((row.get("readiness") or {}).get("targets_present_count") or 0),
                    str(row.get("recipe_id") or ""),
                ),
            )[0]
            reason = "A live-eligible recipe is already trainable from the local research store."
    else:
        recommended = next((row for row in recipes if row.get("recipe_id") == "core-us-6m"), recipes[0] if recipes else None)
        reason = "Update local data first; Core US 6M is the default guided starting point when no live-eligible recipe is ready."
    return {
        "recipes": recipes,
        "instruments": list_model_lab_instruments(),
        "recommended_recipe_id": recommended.get("recipe_id") if recommended else None,
        "recommended_reason": reason if recommended else "No recipes are configured.",
        "guided_workflow": [
            "Update local data",
            "Train the recommended recipe",
            "Inspect the locked-test result",
            "Explicitly activate only an eligible validated candidate",
            "Run Forecast or compare governed Live conditions",
        ],
        "request_id": _rid(request),
    }


@app.get("/api/v4/model-lab/experiments")
def model_lab_experiments_v4(request: Request, limit: int = Query(50, ge=1, le=200)):
    return {
        "experiments": research_store.list_experiments(limit),
        "active": get_active_pointer(),
        "request_id": _rid(request),
    }


@app.get("/api/v4/model-lab/experiments/{experiment_id}")
def model_lab_experiment_v4(experiment_id: str, request: Request):
    experiment = research_store.get_experiment(experiment_id)
    if not experiment:
        raise HTTPException(404, "experiment not found")
    return {"experiment": experiment, "active": get_active_pointer(), "request_id": _rid(request)}


@app.post("/api/v4/model-lab/experiments/{experiment_id}/activate")
def model_lab_activate_v4(experiment_id: str, request: Request):
    experiment = research_store.get_experiment(experiment_id)
    if not experiment:
        raise HTTPException(404, "experiment not found")
    if experiment.get("status") != "validated" or not experiment.get("model_id"):
        raise HTTPException(409, "only a validated experiment with a saved model can be activated")
    if (experiment.get("lineage") or {}).get("live_eligible_target") is False:
        raise HTTPException(409, "this experiment uses a research-only recipe and cannot be activated")
    try:
        pointer = set_active_model(str(experiment["model_id"]), experiment_id=experiment_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {"activated": True, "active": pointer, "experiment": experiment, "request_id": _rid(request)}


@app.post("/api/v4/forecast/models/{model_id}/activate")
def forecast_model_activate_v4(model_id: str, request: Request):
    """Activate an installed validated model, including bundled reference models."""
    try:
        pointer = set_active_model(str(model_id), activated_by="local_user")
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {"activated": True, "active": pointer, "request_id": _rid(request)}


@app.post("/api/v4/model-lab/active/deactivate")
def model_lab_deactivate_v4(request: Request):
    cleared = clear_active_model()
    return {"deactivated": cleared, "active": get_active_pointer(), "request_id": _rid(request)}


@app.post("/api/v4/forecast/build")
def forecast_build_v4(request: Request, payload: Dict[str, Any] = Body(default={})):
    """Start an offline-only Model Lab recipe build from retained local data."""
    payload = payload if isinstance(payload, dict) else {}
    recipe_id = str(payload.get("recipe_id") or "core-us-6m").strip().lower()
    profile_value = payload.get("profile")
    profile = str(profile_value).strip().lower() if profile_value not in (None, "") else None
    try:
        state = start_model_build(profile=profile, recipe_id=recipe_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {**state, "request_id": _rid(request)}


@app.get("/api/v4/forecast/build/status")
def forecast_build_status_v4(request: Request):
    return {**get_model_build_status(), "request_id": _rid(request)}


@app.get("/api/v4/forecast-plan/{ticker}")
def forecast_plan_v4(ticker: str, request: Request, horizon_months: int = Query(12, ge=1, le=60)):
    ticker = validate_ticker(ticker)
    return {**build_forecast_plan(ticker, horizon_months=horizon_months), "request_id": _rid(request)}


@app.get("/api/v4/model-lab/recipes/{recipe_id}/readiness")
def model_lab_readiness_v4(request: Request, recipe_id: str):
    """Hard data-readiness result for a recipe (the 'Can FinCompass train this?' panel)."""
    try:
        result = evaluate_training_readiness(str(recipe_id).strip().lower())
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    return {**result, "request_id": _rid(request)}


@app.get("/api/v4/models/{model_id}")
def model_detail_v4(model_id: str, request: Request):
    """Plain comparison fields for one model (for the candidate-vs-current view)."""
    from forecasting.registry import list_model_manifests, get_active_pointer
    mid = str(model_id).strip()
    m = next((x for x in list_model_manifests() if x.get("model_id") == mid), None)
    if not m:
        raise HTTPException(404, f"model not found: {mid}")
    dom = m.get("applicability_domain") or {}
    prov = m.get("dataset_provenance") or {}
    target = m.get("target") or {}
    active = get_active_pointer()
    return {
        "model_id": m.get("model_id"),
        "validation_tier": m.get("validation_tier"),
        "horizon_months": dom.get("target_horizon_months") or target.get("horizon_months"),
        "benchmark": target.get("benchmark"),
        "training_cutoff": dom.get("training_period_end") or prov.get("training_period_end"),
        "created_at": m.get("created_at"),
        "lineage": m.get("lineage"),
        "is_active": bool(active and active.get("model_id") == mid),
        "request_id": _rid(request),
    }


@app.post("/api/v4/models/{model_id}/update")
def model_update_v4(model_id: str, request: Request):
    """Retrain a model from the accumulated local corpus as a NEW candidate that
    records the given model as its parent. The active model is never replaced by
    this call — replacement stays an explicit, separate user action."""
    from forecasting.registry import list_model_manifests
    mid = str(model_id).strip()
    manifest = next((m for m in list_model_manifests() if m.get("model_id") == mid), None)
    if not manifest:
        raise HTTPException(404, f"model not found: {mid}")
    # Dispatch strictly from the model's declared training contract — never infer
    # a recipe from profile_name. A model that cannot be retrained in-app returns
    # a user-safe result (not an error) so the current forecast is never lost.
    contract = manifest.get("training_contract") or {}
    recipe_id = contract.get("recipe_id")
    if not contract.get("retrain_supported") or not recipe_id:
        return {
            "available": False, "retrain_supported": False, "keep_current": True,
            "model_id": mid, "trainer_family": contract.get("trainer_family"),
            "message": "This model cannot be updated in-app yet, so FinCompass kept the "
                       "current model. Your forecast remains available.",
            "request_id": _rid(request),
        }
    try:
        state = start_model_build(recipe_id=str(recipe_id), parent_model_id=mid)
    except ValueError as exc:
        # A rejected/not-ready build must not disturb the current model either.
        return {"available": False, "retrain_supported": True, "keep_current": True,
                "model_id": mid, "message": f"Update could not start: {exc}. The current "
                "model was kept and your forecast remains available.",
                "request_id": _rid(request)}
    return {**state, "available": True, "parent_model_id": mid,
            "training_contract": contract, "request_id": _rid(request)}


@app.get("/api/v4/forecast/{ticker}")
def forecast_v4(
    ticker: str, request: Request, model_id: Optional[str] = Query(None, max_length=64),
    profile: Optional[str] = Query(None, max_length=64), horizon_months: Optional[int] = Query(None, ge=1, le=60),
):
    ticker = validate_ticker(ticker)
    result = forecast_ticker(ticker, model_id=model_id, profile_name=profile, horizon_months=horizon_months)
    result["request_id"] = _rid(request)
    return result


@app.post("/api/v4/forecast/settings/validate")
def forecast_settings_validate_v4(request: Request, payload: Dict[str, Any] = Body(...)):
    return validate_forecast_settings(request, dict(payload))


@app.get("/api/v4/realtime/status")
def realtime_status_v4(request: Request):
    return {**realtime_status(), "request_id": _rid(request)}


@app.get("/api/v4/realtime/{ticker}/compare")
def realtime_compare_v4(
    ticker: str,
    request: Request,
    model_id: Optional[str] = Query(None, max_length=64),
    profile: Optional[str] = Query(None, max_length=64),
    force_sources: bool = Query(False),
):
    ticker = validate_ticker(ticker)
    result = compare_live_profiles(
        ticker, model_id=model_id, profile_name=profile, force_sources=force_sources
    )
    result["request_id"] = _rid(request)
    if not result.get("available"):
        return JSONResponse(status_code=409, content=result)
    return result


@app.get("/api/v4/realtime/{ticker}/events")
def realtime_events_v4(ticker: str, request: Request, limit: int = Query(30, ge=1, le=100)):
    ticker = validate_ticker(ticker)
    return {"ticker": ticker, "events": realtime_store.list_events(ticker=ticker, limit=limit, public=True), "request_id": _rid(request)}


@app.get("/api/v4/realtime/{ticker}")
def realtime_v4(
    ticker: str,
    request: Request,
    model_id: Optional[str] = Query(None, max_length=64),
    profile: Optional[str] = Query(None, max_length=64),
    realtime_profile: str = Query("balanced", pattern="^(balanced|responsive|conservative)$"),
    force_sources: bool = Query(False),
):
    ticker = validate_ticker(ticker)
    try:
        settings = realtime_settings_from_dict({}, base=realtime_profile)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    result = live_snapshot(ticker, model_id=model_id, profile_name=profile, realtime_settings=settings, force_sources=force_sources)
    result["request_id"] = _rid(request)
    if not result.get("available"):
        return JSONResponse(status_code=409, content=result)
    return result


@app.post("/api/v4/adaptive/process-matured")
def adaptive_process_v4(request: Request, payload: Dict[str, Any] = Body(default={})):
    as_of = payload.get("as_of_date") if isinstance(payload, dict) else None
    limit = int(payload.get("limit", 500)) if isinstance(payload, dict) else 500
    return {**process_matured_labels(as_of_date=as_of, limit=max(1, min(limit, 5000))), "request_id": _rid(request)}


@app.get("/api/v4/realtime/settings/schema")
def realtime_settings_schema_v4(request: Request):
    return {"settings": realtime_settings_schema(), "request_id": _rid(request)}


@app.post("/api/v4/realtime/settings/validate")
def realtime_settings_validate_v4(request: Request, payload: Dict[str, Any] = Body(...)):
    body = dict(payload or {})
    profile = str(body.pop("_profile", "balanced"))
    try:
        settings = realtime_settings_from_dict(body, base=profile)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    return {"valid": True, "profile": profile, "settings": settings.to_dict(), "settings_fingerprint": settings.fingerprint(), "note": "Learning-semantic changes create a distinct adaptive state lineage; they never reinterpret an existing posterior.", "request_id": _rid(request)}


@app.get("/api/v4/settings/schema")
def settings_schema_v4(request: Request):
    return {"forecast": settings_schema(), "realtime": realtime_settings_schema(), "forecast_registry": get_forecast_status(), "realtime_status": realtime_status(), "request_id": _rid(request)}


@app.get("/api/v4/methodology")
def methodology_v4():
    base = methodology_v3()
    base["version"] = APP_VERSION
    base["realtime"] = {
        "engine_version": REALTIME_ENGINE_VERSION,
        "architecture": "Frozen validated anchor plus bounded sequential Bayesian log-odds residual.",
        "learning_rule": "Fresh events can change the candidate immediately. Parameters update only after the original target matures, in predict-before-update order.",
        "gate": "Adaptive influence requires temporal breadth, date-balanced Brier/log-loss non-inferiority, ECE control, freshness and no active drift alert.",
        "sources": ["best-effort market context", "SEC filing metadata", "FRED macro context", "optional authenticated context-only operator events"],
        "claims_boundary": "Bundled adaptive fixtures are synthetic and cannot establish market skill or activate live forecasting.",
    }
    return base


@app.post("/api/v4/events/ingest")
def event_ingest_v4(request: Request, payload: Dict[str, Any] = Body(...)):
    secret = (_os.getenv("FINCOMPASS_EVENT_INGEST_TOKEN") or "").strip()
    if not secret:
        raise HTTPException(503, "External event ingest is disabled until FINCOMPASS_EVENT_INGEST_TOKEN is configured")
    auth = request.headers.get("Authorization", "")
    supplied = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not supplied or not _hmac.compare_digest(supplied.encode(), secret.encode()):
        raise HTTPException(401, "Invalid ingest token")
    ticker = validate_ticker(str(payload.get("ticker") or ""))
    source_time = str(payload.get("source_time") or _datetime.now(_timezone.utc).isoformat())
    event_type = str(payload.get("event_type") or "external_context")[:80]
    operator_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {"value": payload.get("payload")}
    digest = _hashlib.sha256(_json.dumps([ticker, source_time, event_type, operator_payload], sort_keys=True, default=str).encode()).hexdigest()
    event = {"event_id": digest, "source": "external", "scope_key": ticker, "event_type": event_type, "ticker": ticker, "source_time": source_time, "received_at": _datetime.now(_timezone.utc).isoformat(), "payload": operator_payload, "context_only": bool(payload.get("context_only", True)), "external_payload": True}
    inserted = realtime_store.add_event(event)
    return {"accepted": True, "inserted": inserted, "event_id": digest, "context_only": event["context_only"], "public_payload_redacted": True, "request_id": _rid(request)}
