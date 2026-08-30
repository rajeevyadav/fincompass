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
        income = latest_column(income_frame)
        balance = latest_column(getattr(t, "balance_sheet", None))
        cashflow = latest_column(getattr(t, "cashflow", None))
        if not (income and balance):
            return None
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
                "currency": currency, "revenue_history": revenue_history}
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


def _base_free_cash_flow(inp: Val.DCFInputs, cashflow: St.Statement) -> Optional[float]:
    """The company's reported free cash flow, or operating cash flow minus capex.

    Using reported FCF avoids the large understatement of the EBIT reconstruction,
    which omits the non-cash charges and working-capital swings that operating
    cash flow already reflects.
    """
    fcf = cashflow.get("free_cash_flow")
    if _finite(fcf):
        return float(fcf)
    ocf = cashflow.get("operating_cash_flow")
    if _finite(ocf) and _finite(inp.capex):
        return float(ocf) - float(inp.capex)  # inp.capex is a positive magnitude
    return None


def _historical_growth(revenue_history: Optional[List[float]]) -> Optional[float]:
    """Compound annual revenue growth from the reported years (newest first)."""
    rev = [float(x) for x in (revenue_history or []) if _finite(x) and float(x) > 0]
    if len(rev) < 2:
        return None
    newest, oldest, years = rev[0], rev[-1], len(rev) - 1
    if oldest <= 0 or years <= 0:
        return None
    try:
        return (newest / oldest) ** (1.0 / years) - 1.0
    except (ValueError, ZeroDivisionError):
        return None


def _taper(start: float, end: float, n: int = _HORIZON_YEARS) -> List[float]:
    return [start + (end - start) * i / (n - 1) for i in range(n)]


def _growth_paths(revenue_history: Optional[List[float]]) -> Dict[str, List[float]]:
    """Ten-year growth paths anchored on the company's own history when available.

    The base path tapers from the historical growth (clamped to a sane band) toward
    a mature rate; the upside allows a materially higher trajectory so the range
    overlaps mainstream analyst-driven estimates, and the downside brackets it low.
    Falls back to generic paths when history is missing.
    """
    g = _historical_growth(revenue_history)
    if g is None:
        return _GROWTH_PATHS
    # A modest floor: a cash-generative company with temporarily flat revenue
    # (buybacks lift per-share cash flow faster than revenue) should not be valued
    # as a no-growth business. Cap keeps the upside credible.
    g = max(0.05, min(0.20, g))
    return {
        "downside": _taper(max(0.02, g - 0.03), 0.02),
        "base": _taper(g, max(0.04, g * 0.6)),
        # A modest premium over history, capped, so the upside stays credible
        # rather than compounding into an absurd terminal value.
        "upside": _taper(min(0.18, g + 0.05), max(0.05, g * 0.8)),
    }


def _build_dcf(income: St.Statement, balance: St.Statement, cashflow: St.Statement,
               revenue_history: Optional[List[float]] = None) -> Dict[str, Any]:
    inp = Val.build_inputs(income, balance, cashflow)
    fcf = _base_free_cash_flow(inp, cashflow)
    shares = inp.shares_diluted
    net_debt = float(inp.net_debt) if _finite(inp.net_debt) else 0.0
    if not (_finite(fcf) and _finite(shares) and shares > 0):
        return {"valid": False, "currency": inp.currency,
                "reason": "A cash-flow DCF needs reported free cash flow and a share count.",
                "inputs_provenance": inp.provenance, "input_issues": inp.issues,
                "disclaimer": Val.DISCLAIMER}
    paths = _growth_paths(revenue_history)
    hist_growth = _historical_growth(revenue_history)
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
    # Keep the reported band within a sensible multiple of the central estimate so
    # a single WACC-x-growth corner cannot present an absurd high or low.
    base_ps = base.get("value_per_share")
    low = min(values) if values else None
    high = max(values) if values else None
    if _finite(base_ps) and base_ps > 0 and low is not None and high is not None:
        low = max(low, base_ps * 0.4)
        high = min(high, base_ps * 2.5)
    return {
        "valid": bool(base.get("valid")),
        "method": "free_cash_flow_to_equity",
        "value_per_share": _clean(base.get("value_per_share")),
        "enterprise_value": _clean(base.get("enterprise_value")),
        "equity_value": _clean(base.get("equity_value")),
        "currency": inp.currency,
        "range_low": _clean(low),
        "range_high": _clean(high),
        "base_free_cash_flow": _clean(fcf),
        "scenarios": scenarios,
        "historical_revenue_growth": _clean(hist_growth),
        "assumptions": {
            "method": "free_cash_flow_to_equity",
            "wacc": _DEFAULT_WACC, "terminal_growth": _DEFAULT_TERMINAL_GROWTH,
            "horizon_years": _HORIZON_YEARS, "wacc_grid": _WACC_GRID, "growth_paths": paths,
            "growth_anchored_on_history": hist_growth is not None,
        },
        "inputs_provenance": inp.provenance,
        "input_issues": inp.issues,
        "disclaimer": Val.DISCLAIMER,
    }


def build_fundamentals(ticker: str, *, instrument: Optional[Dict[str, Any]] = None,
                       market_cap: Optional[float] = None,
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
        dcf = _build_dcf(income, balance, cashflow, revenue_history=raw.get("revenue_history"))
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
