"""Financial ratios computed from CANONICAL statement values only.

Inputs are the flat canonical view produced by ``statements.merged_values`` — no
provider vocabulary reaches these formulas. Conventions are explicit and
registered (see ``_register_all``): diluted shares for per-share metrics; EBIT =
operating income when not separately reported; EBITDA = EBIT + D&A; total debt =
short + long term; balance-sheet denominators use the two-period average when a
prior period is supplied, otherwise the ending balance. A non-positive or missing
denominator yields NaN (never a silently-zero input, never a divide-by-zero).
"""
from __future__ import annotations

import math
from typing import Dict, Optional

from analytics.registry import register

Values = Dict[str, Optional[float]]
NAN = float("nan")


def _num(values: Values, name: str) -> Optional[float]:
    v = values.get(name)
    return None if v is None else float(v)


def _safe_div(num: Optional[float], den: Optional[float], *, require_positive_den: bool = True) -> float:
    if num is None or den is None:
        return NAN
    if den == 0:
        return NAN
    if require_positive_den and den < 0:
        return NAN
    return float(num) / float(den)


def _avg(values: Values, prior: Optional[Values], name: str) -> Optional[float]:
    cur = _num(values, name)
    if cur is None:
        return None
    if prior is not None:
        p = _num(prior, name)
        if p is not None:
            return (cur + p) / 2.0
    return cur


# --- profitability ----------------------------------------------------------

def gross_margin(v: Values) -> float:
    return _safe_div(_num(v, "gross_profit"), _num(v, "revenue"))


def operating_margin(v: Values) -> float:
    return _safe_div(_num(v, "operating_income"), _num(v, "revenue"))


def net_margin(v: Values) -> float:
    return _safe_div(_num(v, "net_income"), _num(v, "revenue"))


def return_on_assets(v: Values, prior: Optional[Values] = None) -> float:
    return _safe_div(_num(v, "net_income"), _avg(v, prior, "total_assets"))


def return_on_equity(v: Values, prior: Optional[Values] = None) -> float:
    # non-positive equity -> NaN (ratio would be misleading, not meaningful)
    return _safe_div(_num(v, "net_income"), _avg(v, prior, "total_equity"))


def return_on_invested_capital(v: Values) -> float:
    ebit = _num(v, "ebit")
    pretax = _num(v, "pretax_income")
    tax = _num(v, "tax_expense")
    if ebit is None or pretax is None or pretax == 0 or tax is None:
        return NAN
    eff_tax = tax / pretax
    nopat = ebit * (1.0 - eff_tax)
    debt = _num(v, "total_debt") or 0.0
    equity = _num(v, "total_equity")
    cash = _num(v, "cash_and_equivalents") or 0.0
    if equity is None:
        return NAN
    invested = debt + equity - cash
    return _safe_div(nopat, invested)


# --- liquidity --------------------------------------------------------------

def current_ratio(v: Values) -> float:
    return _safe_div(_num(v, "current_assets"), _num(v, "current_liabilities"))


def quick_ratio(v: Values) -> float:
    # (current assets - inventory) / current liabilities; requires inventory to be
    # present (a missing inventory is NOT treated as zero).
    ca, inv, cl = _num(v, "current_assets"), _num(v, "inventory"), _num(v, "current_liabilities")
    if ca is None or inv is None:
        return NAN
    return _safe_div(ca - inv, cl)


def cash_ratio(v: Values) -> float:
    return _safe_div(_num(v, "cash_and_equivalents"), _num(v, "current_liabilities"))


# --- leverage / solvency ----------------------------------------------------

def debt_to_equity(v: Values) -> float:
    return _safe_div(_num(v, "total_debt"), _num(v, "total_equity"))


def debt_to_assets(v: Values) -> float:
    return _safe_div(_num(v, "total_debt"), _num(v, "total_assets"))


def net_debt_to_ebitda(v: Values) -> float:
    debt, cash, ebitda = _num(v, "total_debt"), _num(v, "cash_and_equivalents"), _num(v, "ebitda")
    if debt is None or ebitda is None:
        return NAN
    net_debt = debt - (cash or 0.0)
    return _safe_div(net_debt, ebitda, require_positive_den=True)  # negative EBITDA -> NaN


def interest_coverage(v: Values) -> float:
    return _safe_div(_num(v, "ebit"), _num(v, "interest_expense"), require_positive_den=False)


# --- efficiency -------------------------------------------------------------

def asset_turnover(v: Values, prior: Optional[Values] = None) -> float:
    return _safe_div(_num(v, "revenue"), _avg(v, prior, "total_assets"))


def inventory_turnover(v: Values, prior: Optional[Values] = None) -> float:
    return _safe_div(_num(v, "cost_of_revenue"), _avg(v, prior, "inventory"))


def receivables_turnover(v: Values, prior: Optional[Values] = None) -> float:
    return _safe_div(_num(v, "revenue"), _avg(v, prior, "receivables"))


def days_inventory(v: Values, prior: Optional[Values] = None) -> float:
    t = inventory_turnover(v, prior)
    return NAN if not math.isfinite(t) or t == 0 else 365.0 / t


def days_sales_outstanding(v: Values, prior: Optional[Values] = None) -> float:
    t = receivables_turnover(v, prior)
    return NAN if not math.isfinite(t) or t == 0 else 365.0 / t


# --- cash flow --------------------------------------------------------------

def operating_cash_flow_margin(v: Values) -> float:
    return _safe_div(_num(v, "operating_cash_flow"), _num(v, "revenue"))


def free_cash_flow_margin(v: Values) -> float:
    return _safe_div(_num(v, "free_cash_flow"), _num(v, "revenue"))


def free_cash_flow_yield(v: Values, market_cap: Optional[float]) -> float:
    return _safe_div(_num(v, "free_cash_flow"), market_cap)


def cash_conversion(v: Values) -> float:
    # FCF / net income; non-positive net income -> NaN (conversion undefined)
    return _safe_div(_num(v, "free_cash_flow"), _num(v, "net_income"))


# --- per share --------------------------------------------------------------

def eps_diluted(v: Values) -> float:
    return _safe_div(_num(v, "net_income"), _num(v, "shares_diluted"))


def book_value_per_share(v: Values) -> float:
    return _safe_div(_num(v, "total_equity"), _num(v, "shares_diluted"))


def free_cash_flow_per_share(v: Values) -> float:
    return _safe_div(_num(v, "free_cash_flow"), _num(v, "shares_diluted"))


_EQ = ["equity"]


def _register_all() -> None:
    P = "profitability"; L = "liquidity"; V = "leverage"; E = "efficiency"; C = "cashflow"; S = "per_share"
    defs = [
        ("ratio.gross_margin.v1", "Gross margin", P, "gross_profit / revenue", ["gross_profit", "revenue"], "ratio_percent"),
        ("ratio.operating_margin.v1", "Operating margin", P, "operating_income / revenue", ["operating_income", "revenue"], "ratio_percent"),
        ("ratio.net_margin.v1", "Net margin", P, "net_income / revenue", ["net_income", "revenue"], "ratio_percent"),
        ("ratio.return_on_assets.v1", "Return on assets", P, "net_income / avg(total_assets)", ["net_income", "total_assets"], "ratio_percent"),
        ("ratio.return_on_equity.v1", "Return on equity", P, "net_income / avg(total_equity); non-positive equity -> NaN", ["net_income", "total_equity"], "ratio_percent"),
        ("ratio.return_on_invested_capital.v1", "Return on invested capital", P, "EBIT*(1-eff_tax) / (total_debt+equity-cash)", ["ebit", "tax_expense", "pretax_income", "total_debt", "total_equity", "cash_and_equivalents"], "ratio_percent"),
        ("ratio.current_ratio.v1", "Current ratio", L, "current_assets / current_liabilities", ["current_assets", "current_liabilities"], "ratio"),
        ("ratio.quick_ratio.v1", "Quick ratio", L, "(current_assets - inventory) / current_liabilities", ["current_assets", "inventory", "current_liabilities"], "ratio"),
        ("ratio.cash_ratio.v1", "Cash ratio", L, "cash / current_liabilities", ["cash_and_equivalents", "current_liabilities"], "ratio"),
        ("ratio.debt_to_equity.v1", "Debt to equity", V, "total_debt / total_equity", ["total_debt", "total_equity"], "ratio"),
        ("ratio.debt_to_assets.v1", "Debt to assets", V, "total_debt / total_assets", ["total_debt", "total_assets"], "ratio"),
        ("ratio.net_debt_to_ebitda.v1", "Net debt to EBITDA", V, "(total_debt - cash) / EBITDA; negative EBITDA -> NaN", ["total_debt", "cash_and_equivalents", "ebitda"], "ratio"),
        ("ratio.interest_coverage.v1", "Interest coverage", V, "EBIT / interest_expense", ["ebit", "interest_expense"], "ratio"),
        ("ratio.asset_turnover.v1", "Asset turnover", E, "revenue / avg(total_assets)", ["revenue", "total_assets"], "ratio"),
        ("ratio.inventory_turnover.v1", "Inventory turnover", E, "cost_of_revenue / avg(inventory)", ["cost_of_revenue", "inventory"], "ratio"),
        ("ratio.receivables_turnover.v1", "Receivables turnover", E, "revenue / avg(receivables)", ["revenue", "receivables"], "ratio"),
        ("ratio.days_inventory.v1", "Days inventory", E, "365 / inventory_turnover", ["cost_of_revenue", "inventory"], "ratio"),
        ("ratio.days_sales_outstanding.v1", "Days sales outstanding", E, "365 / receivables_turnover", ["revenue", "receivables"], "ratio"),
        ("ratio.ocf_margin.v1", "Operating cash-flow margin", C, "operating_cash_flow / revenue", ["operating_cash_flow", "revenue"], "ratio_percent"),
        ("ratio.fcf_margin.v1", "Free cash-flow margin", C, "free_cash_flow / revenue", ["free_cash_flow", "revenue"], "ratio_percent"),
        ("ratio.fcf_yield.v1", "Free cash-flow yield", C, "free_cash_flow / market_cap", ["free_cash_flow", "market_cap"], "ratio_percent"),
        ("ratio.cash_conversion.v1", "Cash conversion", C, "free_cash_flow / net_income", ["free_cash_flow", "net_income"], "ratio"),
        ("ratio.eps_diluted.v1", "EPS (diluted)", S, "net_income / shares_diluted", ["net_income", "shares_diluted"], "currency_per_share"),
        ("ratio.book_value_per_share.v1", "Book value per share", S, "total_equity / shares_diluted", ["total_equity", "shares_diluted"], "currency_per_share"),
        ("ratio.fcf_per_share.v1", "Free cash flow per share", S, "free_cash_flow / shares_diluted", ["free_cash_flow", "shares_diluted"], "currency_per_share"),
    ]
    for mid, name, cat, formula, inputs, units in defs:
        register(mid, name=name, category=cat, formula=formula, inputs=inputs, units=units,
                 sign_convention="higher is better" if cat in (P, C) else "context-dependent",
                 supported_asset_classes=_EQ, period_assumption="annual or TTM",
                 zero_denominator_policy="non-positive/missing denominator -> NaN",
                 reference="standard financial-statement analysis")


_register_all()
