"""FinCompass REST API v1.0.0."""
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
from forecasting import FORECAST_ENGINE_VERSION
from forecasting.config import settings_from_dict, settings_schema
from services.forecast_service import forecast_ticker, get_forecast_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("FinCompass.API")

app = FastAPI(
    title="FinCompass API",
    description=(
        "Free systematic stock research with Bayesian evidence uncertainty and gated probabilistic forecasting — "
        "Quality · Financial durability · Safety · Valuation · Cycle. Educational only."
    ),
    version=APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)
app.add_middleware(GuardrailMiddleware)
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
    return {"tickers": DEFAULT_UNIVERSE, "entries": entries, "count": len(DEFAULT_UNIVERSE)}


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
):
    ticker = validate_ticker(ticker)
    result = forecast_ticker(ticker, model_id=model_id, profile_name=profile)
    result["request_id"] = _rid(request)
    if not result.get("available"):
        return JSONResponse(status_code=409, content=result)
    return result


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
    ("/api/v1/methodology", methodology, ["GET"], None),
]:
    app.add_api_route(path, endpoint, methods=methods, response_model=response_model, include_in_schema=True)


# Forecasting API v2 compatibility aliases. FinCompass 3.0 publishes v3 as the
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
# FinCompass v4 adaptive / near-real-time API
# ---------------------------------------------------------------------------
from realtime import REALTIME_ENGINE_VERSION
from realtime.config import settings_from_dict as realtime_settings_from_dict, settings_schema as realtime_settings_schema
from realtime.store import store as realtime_store
from services.realtime_service import live_snapshot, process_matured_labels, realtime_status
import hmac as _hmac
import hashlib as _hashlib
import json as _json
import os as _os
from datetime import datetime as _datetime, timezone as _timezone


@app.get("/api/v4/forecast/status")
def forecast_status_v4(request: Request):
    return {**get_forecast_status(), "realtime_engine_version": REALTIME_ENGINE_VERSION, "request_id": _rid(request)}


@app.post("/api/v4/forecast/build")
def forecast_build_v4(request: Request, payload: Dict[str, Any] = Body(default={})):
    """Start an in-app forecast-model build from free public data (background job)."""
    profile = str((payload or {}).get("profile", "strict")) if isinstance(payload, dict) else "strict"
    state = start_model_build(profile=profile)
    return {**state, "request_id": _rid(request)}


@app.get("/api/v4/forecast/build/status")
def forecast_build_status_v4(request: Request):
    return {**get_model_build_status(), "request_id": _rid(request)}


@app.get("/api/v4/forecast/{ticker}")
def forecast_v4(ticker: str, request: Request, model_id: Optional[str] = Query(None, max_length=64), profile: Optional[str] = Query(None, max_length=64)):
    return forecast(ticker, request, model_id=model_id, profile=profile)


@app.post("/api/v4/forecast/settings/validate")
def forecast_settings_validate_v4(request: Request, payload: Dict[str, Any] = Body(...)):
    return validate_forecast_settings(request, dict(payload))


@app.get("/api/v4/realtime/status")
def realtime_status_v4(request: Request):
    return {**realtime_status(), "request_id": _rid(request)}


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
