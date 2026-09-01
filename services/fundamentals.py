"""Fundamental analytics for the guided flow: canonical statements -> ratios + DCF.

This is the seam between the raw fundamental data the app can already fetch and
the provider-independent analytics kernel (``analytics/``). It maps a provider's
statement rows into canonical statements (provider vocabulary never reaches a
formula), then computes a compact set of financial ratios and a scenario DCF
intrinsic-value range for equity instruments.

Governance carried through from the kernel:
  * A ratio or DCF value is descriptive analysis of reported fundamentals, not a
    forecast, a probability, or a price target, and none of it is a model input.
  * The DCF is an assumption-dependent scenario, shown with its assumptions and a
    range (never a single guaranteed price). Missing history stays missing
    (NaN/unavailable) — nothing is invented.
  * On any fetch/shape problem the block degrades to ``available: False`` with a
    plain reason rather than raising into the guided flow.

The network fetch is injected (``fetch`` parameter) so the assembly is unit-
tested against fixtures without any provider call.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Callable, Dict, List, Optional

from analytics import ratios as Ra
from analytics import statements as St
from analytics import valuation as Val

logger = logging.getLogger(__name__)

DISCLAIMER = (
    "These figures describe reported fundamentals and an assumption-based DCF "
    "scenario. They are not a forecast, a probability, or a price target, and "
    "they are never used as inputs to the model."
)

# Provider (yfinance-style) statement row labels -> canonical fields. Provider
# vocabulary is confined to these maps; the analytics formulas only ever see
# canonical names.
INCOME_ALIASES = {
    "Total Revenue": "revenue", "Operating Revenue": "revenue",
    "Cost Of Revenue": "cost_of_revenue",
    "Gross Profit": "gross_profit",
    "Operating Income": "operating_income", "Total Operating Income As Reported": "operating_income",
    "EBIT": "ebit", "Normalized EBITDA": "ebitda", "EBITDA": "ebitda",
    "Reconciled Depreciation": "depreciation_amortization",
    "Interest Expense": "interest_expense",
    "Pretax Income": "pretax_income",
    "Tax Provision": "tax_expense",
    "Net Income": "net_income", "Net Income Common Stockholders": "net_income",
    "Basic Average Shares": "shares_basic",
    "Diluted Average Shares": "shares_diluted",
    "Diluted EPS": "eps_diluted",
}
BALANCE_ALIASES = {
    "Total Assets": "total_assets",
    "Current Assets": "current_assets",
    "Cash And Cash Equivalents": "cash_and_equivalents",
    "Cash Cash Equivalents And Short Term Investments": "cash_and_equivalents",
    "Inventory": "inventory",
    "Receivables": "receivables", "Accounts Receivable": "receivables",
    "Total Liabilities Net Minority Interest": "total_liabilities",
    "Current Liabilities": "current_liabilities",
    "Payables": "payables", "Accounts Payable": "payables",
    "Current Debt": "short_term_debt", "Current Debt And Capital Lease Obligation": "short_term_debt",
    "Long Term Debt": "long_term_debt", "Long Term Debt And Capital Lease Obligation": "long_term_debt",
    "Total Debt": "total_debt",
    "Total Equity Gross Minority Interest": "total_equity", "Stockholders Equity": "total_equity",
}
CASHFLOW_ALIASES = {
    "Operating Cash Flow": "operating_cash_flow", "Cash Flow From Continuing Operating Activities": "operating_cash_flow",
    "Capital Expenditure": "capital_expenditure",
    "Free Cash Flow": "free_cash_flow",
    "Cash Dividends Paid": "dividends_paid", "Common Stock Dividend Paid": "dividends_paid",
}

# Default forward DCF assumptions. Deliberately generic and shown to the user;
# the point is a scenario range, not a precise target.
_DEFAULT_WACC = 0.09
_DEFAULT_TERMINAL_GROWTH = 0.025
_WACC_GRID = [0.08, 0.09, 0.10, 0.11]
# A ten-year explicit forecast, matching the convention of common open-source DCF
# models, then a perpetual-growth terminal value. Revenue/FCF growth is the
# dominant driver, so the scenario range varies it (not only WACC).
_HORIZON_YEARS = 10
_GROWTH_PATHS = {
    "downside": [0.03, 0.03, 0.03, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02],
    "base": [0.10, 0.09, 0.08, 0.08, 0.07, 0.06, 0.05, 0.05, 0.04, 0.04],
    "upside": [0.18, 0.16, 0.15, 0.13, 0.12, 0.10, 0.09, 0.08, 0.07, 0.06],
}


def _finite(x: Any) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _clean(x: Any) -> Optional[float]:
    """JSON-safe number: NaN/inf -> None."""
    return float(x) if _finite(x) else None


def _fetch_yfinance_statements(ticker: str) -> Optional[Dict[str, Dict[str, float]]]:
    """Most-recent annual income/balance/cashflow rows as {label: value} dicts.

    Returns None when yfinance or the statements are unavailable. Kept tiny and
    dependency-guarded so the guided flow never hard-depends on it.
    """
    try:
        import yfinance as yf  # local import: optional dependency
    except Exception:
        return None
    try:
        t = yf.Ticker(ticker.replace(".", "-"))

        def latest_column(frame) -> Dict[str, float]:
            if frame is None or getattr(frame, "empty", True):
                return {}
            col = frame.iloc[:, 0]  # most recent reported period
            out: Dict[str, float] = {}
            for label, value in col.items():
                if value is not None and _finite(value):
                    out[str(label)] = float(value)
            return out

        income_frame = getattr(t, "income_stmt", None)
        cashflow_frame = getattr(t, "cashflow", None)
        income = latest_column(income_frame)
        balance = latest_column(getattr(t, "balance_sheet", None))
        cashflow = latest_column(cashflow_frame)
        if not (income and balance):
            return None
        # Free cash flow across the reported years (newest first) so the DCF can
        # anchor its base on a multi-year average and its growth on FCF's own
        # history — buybacks and margin shifts move FCF, not only revenue.
        fcf_history: list = []
        try:
            if cashflow_frame is not None and not getattr(cashflow_frame, "empty", True):
                for label in ("Free Cash Flow",):
                    if label in cashflow_frame.index:
                        fcf_history = [float(v) for v in cashflow_frame.loc[label].values if _finite(v)]
                        break
        except Exception:
            fcf_history = []
        # Revenue across the reported years (newest first) so the DCF can anchor
        # its growth on the company's own history rather than a generic assumption.
        revenue_history: list = []
        try:
            if income_frame is not None and not getattr(income_frame, "empty", True):
                for label in ("Total Revenue", "Operating Revenue"):
                    if label in income_frame.index:
                        revenue_history = [float(v) for v in income_frame.loc[label].values if _finite(v)]
                        break
        except Exception:
            revenue_history = []
        currency = None
        try:
            currency = (t.fast_info or {}).get("currency")
        except Exception:
            currency = None
        return {"income": income, "balance": balance, "cashflow": cashflow,
                "currency": currency, "revenue_history": revenue_history,
                "fcf_history": fcf_history}
    except Exception as e:  # pragma: no cover - network/provider variance
        logger.warning("fundamentals fetch failed %s: %s", ticker, type(e).__name__)
        return None


# Which ratios to surface, in display order, and how each is computed from the
# merged canonical values. Each entry: (metric_id, label, callable(values)).
_RATIO_SPECS = [
    ("ratio.gross_margin.v1", "Gross margin", lambda v, mc: Ra.gross_margin(v)),
    ("ratio.operating_margin.v1", "Operating margin", lambda v, mc: Ra.operating_margin(v)),
    ("ratio.net_margin.v1", "Net margin", lambda v, mc: Ra.net_margin(v)),
    ("ratio.return_on_equity.v1", "Return on equity", lambda v, mc: Ra.return_on_equity(v)),
    ("ratio.return_on_invested_capital.v1", "Return on invested capital", lambda v, mc: Ra.return_on_invested_capital(v)),
    ("ratio.current_ratio.v1", "Current ratio", lambda v, mc: Ra.current_ratio(v)),
    ("ratio.debt_to_equity.v1", "Debt to equity", lambda v, mc: Ra.debt_to_equity(v)),
    ("ratio.net_debt_to_ebitda.v1", "Net debt / EBITDA", lambda v, mc: Ra.net_debt_to_ebitda(v)),
    ("ratio.interest_coverage.v1", "Interest coverage", lambda v, mc: Ra.interest_coverage(v)),
    ("ratio.free_cash_flow_margin.v1", "Free cash-flow margin", lambda v, mc: Ra.free_cash_flow_margin(v)),
    ("ratio.free_cash_flow_yield.v1", "Free cash-flow yield", lambda v, mc: Ra.free_cash_flow_yield(v, mc)),
    ("ratio.eps_diluted.v1", "EPS (diluted)", lambda v, mc: Ra.eps_diluted(v)),
]


def _build_ratios(values: Dict[str, Optional[float]], market_cap: Optional[float]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for metric_id, label, fn in _RATIO_SPECS:
        try:
            val = fn(values, market_cap)
        except Exception:
            val = float("nan")
        out.append({"metric_id": metric_id, "label": label, "value": _clean(val),
                    "available": _finite(val)})
    return out


# The three-stage split of the ten-year explicit forecast: a high-growth stage,
# then a linear transition to the stable rate that the perpetual terminal uses.
_HIGH_YEARS = 5
_TRANSITION_YEARS = _HORIZON_YEARS - _HIGH_YEARS
# Damodaran's cardinal rule for stable growth: a mature firm cannot outgrow the
# economy forever, so terminal growth is capped at a proxy for the risk-free rate.
_STABLE_GROWTH_CAP = 0.03


def _cagr(series_newest_first: Optional[List[float]]) -> Optional[float]:
    """Compound annual growth from a newest-first series with positive endpoints."""
    vals = [float(x) for x in (series_newest_first or []) if _finite(x)]
    if len(vals) < 2:
        return None
    newest, oldest, years = vals[0], vals[-1], len(vals) - 1
    if oldest <= 0 or newest <= 0 or years <= 0:
        return None
    try:
        return (newest / oldest) ** (1.0 / years) - 1.0
    except (ValueError, ZeroDivisionError):
        return None


def _base_free_cash_flow_detail(inp: Val.DCFInputs, cashflow: St.Statement,
                                fcf_history: Optional[List[float]] = None) -> Dict[str, Any]:
    """The base free cash flow the DCF grows forward, with full provenance.

    Prefers a multi-year average of reported free cash flow (up to three years) so
    a single unusually high or low year does not set the whole valuation; this is
    the smoothing the reference verifier applies. Falls back to the most recent
    reported FCF, then to operating cash flow minus capex. Using reported FCF
    avoids the large understatement of the EBIT reconstruction, which omits the
    non-cash charges and working-capital swings that operating cash flow reflects.

    The returned detail names the method, how many years were averaged, and how
    many negative years were excluded from the average - a normalization that can
    bias the base upward for genuinely cyclical or cash-burning companies, so it
    must be visible rather than silent.
    """
    hist = [float(x) for x in (fcf_history or []) if _finite(x)]
    window = hist[:3]
    positive = [x for x in window if x > 0]
    excluded_negative = len(window) - len(positive)
    if len(positive) >= 2:
        return {"base_free_cash_flow": sum(positive) / len(positive),
                "base_method": "mean_of_recent_positive_reported_fcf",
                "years_available": len(hist), "years_used": len(positive),
                "negative_years_excluded": excluded_negative,
                "cyclical_caution": excluded_negative > 0}
    fcf = cashflow.get("free_cash_flow")
    if _finite(fcf):
        return {"base_free_cash_flow": float(fcf), "base_method": "latest_reported_fcf",
                "years_available": len(hist), "years_used": 1,
                "negative_years_excluded": 0, "cyclical_caution": False}
    ocf = cashflow.get("operating_cash_flow")
    if _finite(ocf) and _finite(inp.capex):
        return {"base_free_cash_flow": float(ocf) - float(inp.capex),
                "base_method": "operating_cash_flow_minus_capex",
                "years_available": len(hist), "years_used": 1,
                "negative_years_excluded": 0, "cyclical_caution": False}
    return {"base_free_cash_flow": None, "base_method": None, "years_available": len(hist),
            "years_used": 0, "negative_years_excluded": 0, "cyclical_caution": False}


def _base_free_cash_flow(inp: Val.DCFInputs, cashflow: St.Statement,
                         fcf_history: Optional[List[float]] = None) -> Optional[float]:
    return _base_free_cash_flow_detail(inp, cashflow, fcf_history)["base_free_cash_flow"]


def _historical_growth_detail(revenue_history: Optional[List[float]],
                              fcf_history: Optional[List[float]] = None):
    """The growth rate the DCF anchors on, and which series it came from.

    Prefers free-cash-flow CAGR, which captures buybacks and margin expansion that
    revenue growth alone misses (the reason a cash-rich, flat-revenue name was
    previously undervalued). Falls back to revenue CAGR when FCF history is thin.
    Returns ``(growth, source)`` where source is ``"fcf_cagr"``/``"revenue_cagr"``/None.
    """
    g_fcf = _cagr(fcf_history)
    if g_fcf is not None:
        return g_fcf, "fcf_cagr"
    g_rev = _cagr(revenue_history)
    return (g_rev, "revenue_cagr") if g_rev is not None else (None, None)


def _historical_growth(revenue_history: Optional[List[float]],
                       fcf_history: Optional[List[float]] = None) -> Optional[float]:
    return _historical_growth_detail(revenue_history, fcf_history)[0]


def _growth_paths(revenue_history: Optional[List[float]],
                  fcf_history: Optional[List[float]] = None) -> Dict[str, List[float]]:
    """Three-stage growth paths anchored on the company's own history.

    Each path is a Damodaran three-stage vector: a constant high-growth stage, a
    linear transition, then the stable rate the perpetual terminal uses. The base
    anchors on historical FCF/revenue growth (clamped to a sane band); the upside
    allows a higher trajectory so the range overlaps mainstream estimates; the
    downside brackets it low. Falls back to generic paths when history is missing.
    """
    g = _historical_growth(revenue_history, fcf_history)
    if g is None:
        return _GROWTH_PATHS
    # A modest floor and cap keep both ends credible: a cash-generative company
    # with temporarily flat revenue is not a no-growth business, and no company
    # compounds at 20%+ for a decade without an absurd terminal value.
    g = max(0.05, min(0.20, g))
    stable = min(_STABLE_GROWTH_CAP, max(0.02, g * 0.5))
    path = lambda high: Val.three_stage_growth_path(high, stable, _HIGH_YEARS, _TRANSITION_YEARS)
    return {
        "downside": path(max(0.02, g - 0.03)),
        "base": path(g),
        # A modest premium over history, capped, so the upside stays credible.
        "upside": path(min(0.18, g + 0.05)),
    }


def _growth_quality(income: St.Statement, balance: St.Statement, cashflow: St.Statement,
                    assumed_growth: Optional[float]) -> Optional[Dict[str, Any]]:
    """Damodaran's consistency check: growth must be paid for by reinvestment.

    Sustainable growth = reinvestment rate x return on invested capital, where the
    reinvestment rate is net reinvestment (capex less depreciation) over after-tax
    operating income (NOPAT). When the DCF's assumed growth exceeds what the
    company's own reinvestment and returns can fund, the growth is optimistic and
    the intrinsic value is likely overstated - a flag a careful reader should see.
    """
    v = St.merged_values(income, balance, cashflow)
    roic = Ra.return_on_invested_capital(v)
    ebit, pretax, tax = v.get("ebit"), v.get("pretax_income"), v.get("tax_expense")
    capex, da = v.get("capital_expenditure"), v.get("depreciation_amortization")
    if not (_finite(ebit) and _finite(pretax) and pretax and _finite(tax) and _finite(roic)):
        return None
    nopat = float(ebit) * (1.0 - float(tax) / float(pretax))
    if not (_finite(nopat) and nopat > 0):
        return None
    net_reinvestment = (abs(float(capex)) if _finite(capex) else 0.0) - (float(da) if _finite(da) else 0.0)
    reinvestment_rate = net_reinvestment / nopat
    sustainable = reinvestment_rate * float(roic)
    supported = not (_finite(assumed_growth) and assumed_growth > sustainable + 0.02)
    return {
        "roic": _clean(roic), "reinvestment_rate": _clean(reinvestment_rate),
        "sustainable_growth": _clean(sustainable), "assumed_growth": _clean(assumed_growth),
        "supported": bool(supported),
        "note": ("Assumed growth is within what reinvestment and returns can fund."
                 if supported else
                 "Assumed growth is higher than reinvestment x ROIC can fund, so this DCF's growth "
                 "may be optimistic and the value overstated."),
    }


def _build_dcf(income: St.Statement, balance: St.Statement, cashflow: St.Statement,
               revenue_history: Optional[List[float]] = None,
               fcf_history: Optional[List[float]] = None,
               market_price: Optional[float] = None) -> Dict[str, Any]:
    inp = Val.build_inputs(income, balance, cashflow)
    base_detail = _base_free_cash_flow_detail(inp, cashflow, fcf_history)
    fcf = base_detail["base_free_cash_flow"]
    shares = inp.shares_diluted
    net_debt = float(inp.net_debt) if _finite(inp.net_debt) else 0.0
    if not (_finite(fcf) and _finite(shares) and shares > 0):
        return {"valid": False, "currency": inp.currency,
                "reason": "A cash-flow DCF needs reported free cash flow and a share count.",
                "inputs_provenance": inp.provenance, "input_issues": inp.issues,
                "disclaimer": Val.DISCLAIMER}
    paths = _growth_paths(revenue_history, fcf_history)
    hist_growth, growth_source = _historical_growth_detail(revenue_history, fcf_history)
    # The whole scenario grid: three growth paths x the WACC band. The base value
    # is the central path at the default WACC; the range spans the whole grid.
    values: List[float] = []
    scenarios: Dict[str, Optional[float]] = {}
    for name, path in paths.items():
        r = Val.dcf_from_free_cash_flow(fcf, path, _DEFAULT_WACC, _DEFAULT_TERMINAL_GROWTH, net_debt, shares)
        scenarios[name] = _clean(r.get("value_per_share"))
        for w in _WACC_GRID:
            rr = Val.dcf_from_free_cash_flow(fcf, path, w, _DEFAULT_TERMINAL_GROWTH, net_debt, shares)
            if rr.get("valid") and _finite(rr.get("value_per_share")):
                values.append(float(rr["value_per_share"]))
    base = Val.dcf_from_free_cash_flow(fcf, paths["base"], _DEFAULT_WACC,
                                       _DEFAULT_TERMINAL_GROWTH, net_debt, shares)
    # The raw scenario surface, before any display bounding. Research must see the
    # unclipped mathematics; we constrain what is *shown*, not what is computed.
    raw_low = min(values) if values else None
    raw_high = max(values) if values else None
    # Keep the reported band within a sensible multiple of the central estimate so
    # a single WACC-x-growth corner cannot present an absurd high or low. This is a
    # display bound only, disclosed here with its exact factors.
    base_ps = base.get("value_per_share")
    low, high, clamp_applied = raw_low, raw_high, False
    clamp_low_factor, clamp_high_factor = 0.4, 2.5
    if _finite(base_ps) and base_ps > 0 and raw_low is not None and raw_high is not None:
        low = max(raw_low, base_ps * clamp_low_factor)
        high = min(raw_high, base_ps * clamp_high_factor)
        clamp_applied = (low != raw_low) or (high != raw_high)
    # Reverse DCF: the stage-1 growth today's price implies, so a reader can judge
    # the market's expectation directly instead of debating our assumptions.
    stable = min(_STABLE_GROWTH_CAP, max(0.02, (hist_growth or 0.06) * 0.5))
    implied_growth = None
    if _finite(market_price) and float(market_price) > 0:
        implied_growth = Val.implied_fcf_growth(
            float(market_price), fcf, _DEFAULT_WACC, _DEFAULT_TERMINAL_GROWTH,
            net_debt, shares, _HIGH_YEARS, _TRANSITION_YEARS, stable)
    terminal_value = base.get("terminal_value")
    pv_terminal = base.get("pv_terminal_value")
    ev = base.get("enterprise_value")
    terminal_pct = (float(pv_terminal) / float(ev)) if (_finite(pv_terminal) and _finite(ev) and ev) else None
    return {
        "valid": bool(base.get("valid")),
        "method": "free_cash_flow_to_equity",
        "value_per_share": _clean(base.get("value_per_share")),
        "enterprise_value": _clean(ev),
        "equity_value": _clean(base.get("equity_value")),
        "currency": inp.currency,
        "range_low": _clean(low),
        "range_high": _clean(high),
        "base_free_cash_flow": _clean(fcf),
        "scenarios": scenarios,
        "historical_revenue_growth": _clean(hist_growth),
        "implied_growth": _clean(implied_growth),
        # Full raw scenario surface and the display bound applied to it.
        "raw_scenario_range": {"low": _clean(raw_low), "high": _clean(raw_high)},
        "display_range_clamp": {"applied": bool(clamp_applied),
                                "low_factor": clamp_low_factor, "high_factor": clamp_high_factor,
                                "note": "Shown range bounded to base x [0.4, 2.5]; raw scenario range is above."},
        "base_fcf_normalization": {
            "method": base_detail["base_method"],
            "reported_fcf_history": [_clean(x) for x in (fcf_history or []) if _finite(x)],
            "years_available": base_detail["years_available"],
            "years_used": base_detail["years_used"],
            "negative_years_excluded": base_detail["negative_years_excluded"],
            "cyclical_caution": base_detail["cyclical_caution"],
        },
        "growth_anchor": {"annual_rate": _clean(hist_growth), "source": growth_source},
        "growth_quality": _growth_quality(income, balance, cashflow, paths.get("base", [None])[0]),
        "net_debt": _clean(net_debt),
        "shares_diluted": _clean(shares),
        "terminal_value": _clean(terminal_value),
        "pv_terminal_value": _clean(pv_terminal),
        "terminal_value_pct_of_ev": _clean(terminal_pct),
        "assumptions": {
            "method": "three_stage_free_cash_flow_to_equity",
            "wacc": _DEFAULT_WACC, "terminal_growth": _DEFAULT_TERMINAL_GROWTH,
            "horizon_years": _HORIZON_YEARS, "high_growth_years": _HIGH_YEARS,
            "transition_years": _TRANSITION_YEARS, "stable_growth": _clean(stable),
            "wacc_grid": _WACC_GRID, "growth_paths": paths,
            "growth_anchored_on_history": hist_growth is not None,
            "growth_source": growth_source,
        },
        "inputs_provenance": inp.provenance,
        "input_issues": inp.issues,
        "disclaimer": Val.DISCLAIMER,
    }


def build_fundamentals(ticker: str, *, instrument: Optional[Dict[str, Any]] = None,
                       market_cap: Optional[float] = None,
                       market_price: Optional[float] = None,
                       fetch: Callable[[str], Optional[Dict[str, Any]]] = _fetch_yfinance_statements
                       ) -> Dict[str, Any]:
    """Assemble the fundamentals block (ratios + scenario DCF) for the guided flow.

    Degrades to ``{"available": False, "reason": ...}`` for non-equity
    instruments or on any fetch/shape problem — never raises into the caller.
    """
    ticker = str(ticker or "").upper()
    itype = str((instrument or {}).get("instrument_type") or (instrument or {}).get("type") or "").lower()
    if instrument is not None and itype and itype not in {"equity", "stock", "adr", "share"}:
        return {"available": False, "reason": "Fundamental ratios and DCF apply to individual companies, "
                "not to this instrument type."}

    try:
        raw = fetch(ticker)
    except Exception as e:
        logger.warning("fundamentals fetch error %s: %s", ticker, type(e).__name__)
        raw = None
    if not raw or not raw.get("income") or not raw.get("balance"):
        return {"available": False, "reason": "Company financial statements are not available for this instrument."}

    currency = raw.get("currency")
    income = St.derive(St.normalize(raw["income"], INCOME_ALIASES, kind=St.INCOME,
                                    period_type="annual", currency=currency))
    balance = St.derive(St.normalize(raw["balance"], BALANCE_ALIASES, kind=St.BALANCE,
                                     period_type="annual", currency=currency))
    cashflow = St.derive(St.normalize(raw.get("cashflow") or {}, CASHFLOW_ALIASES, kind=St.CASHFLOW,
                                      period_type="annual", currency=currency))

    values = St.merged_values(income, balance, cashflow)
    ratios = _build_ratios(values, market_cap)

    try:
        dcf = _build_dcf(income, balance, cashflow, revenue_history=raw.get("revenue_history"),
                         fcf_history=raw.get("fcf_history"), market_price=market_price)
    except Exception as e:
        logger.warning("DCF assembly failed %s: %s", ticker, type(e).__name__)
        dcf = {"valid": False, "reason": "A DCF could not be assembled from the available statements.",
               "disclaimer": Val.DISCLAIMER}

    available_ratios = sum(1 for r in ratios if r["available"])
    return {
        "available": True,
        "currency": currency,
        "coverage": {"ratios_available": available_ratios, "ratios_total": len(ratios)},
        "ratios": ratios,
        "dcf": dcf,
        "disclaimer": DISCLAIMER,
    }
