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
_GROWTH_GRID = [0.015, 0.025, 0.035]


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

        income = latest_column(getattr(t, "income_stmt", None))
        balance = latest_column(getattr(t, "balance_sheet", None))
        cashflow = latest_column(getattr(t, "cashflow", None))
        if not (income and balance):
            return None
        currency = None
        try:
            currency = (t.fast_info or {}).get("currency")
        except Exception:
            currency = None
        return {"income": income, "balance": balance, "cashflow": cashflow,
                "currency": currency}
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


def _build_dcf(income: St.Statement, balance: St.Statement, cashflow: St.Statement) -> Dict[str, Any]:
    inp = Val.build_inputs(income, balance, cashflow)
    base = Val.DCFAssumptions(wacc=_DEFAULT_WACC, horizon_years=5, revenue_growth=0.04,
                              ebit_margin=None, tax_rate=None, capex_pct_revenue=None,
                              da_pct_revenue=None, nwc_pct_revenue=None,
                              terminal_method="perpetual",
                              terminal_growth=_DEFAULT_TERMINAL_GROWTH)
    result = Val.run_dcf(inp, base)
    grid = Val.sensitivity(inp, base, _WACC_GRID, _GROWTH_GRID)
    # Collapse the sensitivity grid to a low/high per-share range (finite cells only).
    finite_cells = [c for row in grid.get("value_per_share", []) for c in row if _finite(c)]
    low = min(finite_cells) if finite_cells else None
    high = max(finite_cells) if finite_cells else None
    return {
        "valid": bool(result.get("valid")),
        "validation_failures": result.get("validation_failures", []),
        "value_per_share": _clean(result.get("value_per_share")),
        "enterprise_value": _clean(result.get("enterprise_value")),
        "equity_value": _clean(result.get("equity_value")),
        "currency": inp.currency,
        "range_low": _clean(low),
        "range_high": _clean(high),
        "assumptions": {
            "wacc": _DEFAULT_WACC,
            "terminal_growth": _DEFAULT_TERMINAL_GROWTH,
            "horizon_years": 5,
            "wacc_grid": _WACC_GRID,
            "terminal_growth_grid": _GROWTH_GRID,
            "terminal_method": "perpetual",
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
        dcf = _build_dcf(income, balance, cashflow)
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
