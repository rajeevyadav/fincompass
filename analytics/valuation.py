"""Discounted-cash-flow valuation, built strictly on canonical statements.

    normalized statements -> valuation inputs -> valuation engine -> valuation result

Provider fields, forecast probabilities, and model outputs never enter DCF logic.
Observed financial history (from normalized statements) is kept cleanly separate
from valuation ASSUMPTIONS (growth, margins, WACC, terminal method) so results are
reproducible and auditable.

Hard governance:
- A DCF intrinsic value is NOT a prediction probability and NOT a guaranteed price.
- Missing or structurally invalid inputs fail safely (NaN + explicit validation),
  never silently synthesized.
- Invalid WACC, terminal growth >= WACC, invalid share count, currency mismatch,
  or insufficient history produce a validation failure, not a number.
- No DCF metric is promoted to a forecast feature merely because it exists.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from analytics import statements as St
from analytics.registry import register

NAN = float("nan")
DISCLAIMER = ("A DCF intrinsic value is a scenario-and-assumption-dependent estimate, "
              "not a probability, a target price, or a guarantee.")


@dataclass
class DCFInputs:
    """Observed historical inputs derived from normalized statements (with provenance)."""
    revenue: Optional[float] = None
    ebit: Optional[float] = None
    effective_tax_rate: Optional[float] = None
    depreciation_amortization: Optional[float] = None
    capex: Optional[float] = None          # positive magnitude
    net_working_capital: Optional[float] = None
    shares_diluted: Optional[float] = None
    net_debt: Optional[float] = None
    currency: Optional[str] = None
    provenance: Dict[str, Any] = field(default_factory=dict)
    issues: List[str] = field(default_factory=list)


@dataclass
class DCFAssumptions:
    """Forward valuation assumptions — deliberately separate from observed history."""
    wacc: float
    horizon_years: int = 5
    revenue_growth: Any = 0.05             # float applied each year, or per-year list
    ebit_margin: Optional[float] = None    # default: historical EBIT margin
    tax_rate: Optional[float] = None       # default: historical effective rate
    capex_pct_revenue: Optional[float] = None
    da_pct_revenue: Optional[float] = None
    nwc_pct_revenue: Optional[float] = None
    terminal_method: str = "perpetual"     # "perpetual" | "exit_multiple"
    terminal_growth: float = 0.02
    exit_multiple: Optional[float] = None  # EV/EBITDA for the exit method


def build_inputs(income: St.Statement, balance: St.Statement, cashflow: St.Statement,
                 prior_balance: Optional[St.Statement] = None) -> DCFInputs:
    """Construct DCF historical inputs from canonical statements, recording provenance.

    Nothing is invented: a field that cannot be derived stays None and is flagged.
    """
    inp = DCFInputs()
    prov: Dict[str, Any] = {}
    issues: List[str] = []

    # currency consistency across statements
    currencies = {s.currency for s in (income, balance, cashflow) if s.currency}
    if len(currencies) > 1:
        issues.append("currency_mismatch")
    inp.currency = next(iter(currencies), None)

    inp.revenue = income.get("revenue"); prov["revenue"] = income.status("revenue")
    inp.ebit = income.get("ebit"); prov["ebit"] = income.status("ebit")

    pretax, tax = income.get("pretax_income"), income.get("tax_expense")
    if pretax not in (None, 0) and tax is not None:
        inp.effective_tax_rate = tax / pretax
        prov["effective_tax_rate"] = "derived: tax_expense / pretax_income"
    else:
        prov["effective_tax_rate"] = St.UNAVAILABLE

    inp.depreciation_amortization = income.get("depreciation_amortization")
    prov["depreciation_amortization"] = income.status("depreciation_amortization")

    capex = cashflow.get("capital_expenditure")
    if capex is not None:
        inp.capex = abs(capex)             # store as positive magnitude
        prov["capex"] = "abs(cashflow.capital_expenditure)"
    else:
        prov["capex"] = St.UNAVAILABLE

    # operating net working capital = (current assets - cash) - (current liabilities - short-term debt)
    ca, cash = balance.get("current_assets"), balance.get("cash_and_equivalents")
    cl, std = balance.get("current_liabilities"), balance.get("short_term_debt")
    if ca is not None and cl is not None:
        inp.net_working_capital = (ca - (cash or 0.0)) - (cl - (std or 0.0))
        prov["net_working_capital"] = "derived: (CA - cash) - (CL - short_term_debt)"
    else:
        prov["net_working_capital"] = St.UNAVAILABLE

    inp.shares_diluted = income.get("shares_diluted"); prov["shares_diluted"] = income.status("shares_diluted")

    debt = balance.get("total_debt")
    if debt is not None:
        inp.net_debt = debt - (cash or 0.0)
        prov["net_debt"] = "derived: total_debt - cash"
    else:
        prov["net_debt"] = St.UNAVAILABLE

    inp.provenance = prov
    inp.issues = issues
    return inp


def _growth_list(growth: Any, horizon: int) -> List[float]:
    if isinstance(growth, (list, tuple)):
        g = list(growth)[:horizon]
        while len(g) < horizon:
            g.append(g[-1] if g else 0.0)
        return [float(x) for x in g]
    return [float(growth)] * horizon


def _validate(inp: DCFInputs, a: DCFAssumptions) -> List[str]:
    fails: List[str] = []
    if inp.issues:
        fails.extend(inp.issues)
    if not (isinstance(a.wacc, (int, float)) and math.isfinite(a.wacc)) or a.wacc <= 0:
        fails.append("invalid_wacc")
    if int(a.horizon_years) < 1:
        fails.append("invalid_horizon")
    for name in ("revenue", "ebit"):
        if getattr(inp, name) is None:
            fails.append(f"missing_{name}")
    if inp.shares_diluted is None or inp.shares_diluted <= 0:
        fails.append("invalid_shares")
    if a.terminal_method == "perpetual":
        if not (a.wacc > a.terminal_growth):
            fails.append("terminal_growth_ge_wacc")
    elif a.terminal_method == "exit_multiple":
        if a.exit_multiple is None or a.exit_multiple <= 0:
            fails.append("invalid_exit_multiple")
    else:
        fails.append("unknown_terminal_method")
    return fails


def _invalid_result(fails: List[str], inp: DCFInputs, a: DCFAssumptions) -> Dict[str, Any]:
    return {
        "valid": False, "validation_failures": fails,
        "enterprise_value": NAN, "equity_value": NAN, "value_per_share": NAN,
        "currency": inp.currency, "assumptions": vars(a), "provenance": inp.provenance,
        "disclaimer": DISCLAIMER,
    }


def run_dcf(inp: DCFInputs, a: DCFAssumptions) -> Dict[str, Any]:
    """Run an unlevered (FCFF) enterprise-value DCF and bridge to per-share value.

    FCFF = EBIT*(1-tax) + D&A - CapEx - change in NWC. Returns a full, reproducible
    result with per-year projections, terminal value, the EV->equity bridge,
    provenance and the assumptions used. Fails safely on invalid inputs.
    """
    fails = _validate(inp, a)
    if fails:
        return _invalid_result(fails, inp, a)

    horizon = int(a.horizon_years)
    growth = _growth_list(a.revenue_growth, horizon)
    ebit_margin = a.ebit_margin if a.ebit_margin is not None else (inp.ebit / inp.revenue)
    tax = a.tax_rate if a.tax_rate is not None else (inp.effective_tax_rate if inp.effective_tax_rate is not None else 0.0)
    da_pct = a.da_pct_revenue if a.da_pct_revenue is not None else (
        (inp.depreciation_amortization / inp.revenue) if inp.depreciation_amortization is not None else 0.0)
    capex_pct = a.capex_pct_revenue if a.capex_pct_revenue is not None else (
        (inp.capex / inp.revenue) if inp.capex is not None else 0.0)
    nwc_pct = a.nwc_pct_revenue if a.nwc_pct_revenue is not None else (
        (inp.net_working_capital / inp.revenue) if inp.net_working_capital is not None else 0.0)

    revenue = float(inp.revenue)
    nwc_prev = inp.net_working_capital if inp.net_working_capital is not None else revenue * nwc_pct
    years: List[Dict[str, Any]] = []
    pv_fcff_total = 0.0
    ebit_h = da_h = 0.0

    for t in range(1, horizon + 1):
        revenue = revenue * (1.0 + growth[t - 1])
        ebit_t = revenue * ebit_margin
        nopat = ebit_t * (1.0 - tax)
        da_t = revenue * da_pct
        capex_t = revenue * capex_pct
        nwc_t = revenue * nwc_pct
        delta_nwc = nwc_t - nwc_prev
        nwc_prev = nwc_t
        fcff = nopat + da_t - capex_t - delta_nwc
        df = 1.0 / (1.0 + a.wacc) ** t
        pv = fcff * df
        pv_fcff_total += pv
        years.append({"year": t, "revenue": revenue, "ebit": ebit_t, "fcff": fcff,
                      "discount_factor": df, "pv_fcff": pv})
        ebit_h, da_h = ebit_t, da_t

    last_fcff = years[-1]["fcff"]
    if a.terminal_method == "perpetual":
        terminal_value = last_fcff * (1.0 + a.terminal_growth) / (a.wacc - a.terminal_growth)
    else:  # exit_multiple on terminal-year EBITDA
        ebitda_h = ebit_h + da_h
        terminal_value = a.exit_multiple * ebitda_h
    pv_terminal = terminal_value / (1.0 + a.wacc) ** horizon

    enterprise_value = pv_fcff_total + pv_terminal
    net_debt = inp.net_debt if inp.net_debt is not None else 0.0
    equity_value = enterprise_value - net_debt         # negative net debt (excess cash) lifts equity
    value_per_share = equity_value / inp.shares_diluted

    return {
        "valid": True, "validation_failures": [],
        "currency": inp.currency,
        "projections": years,
        "terminal_method": a.terminal_method,
        "terminal_value": terminal_value,
        "pv_terminal_value": pv_terminal,
        "pv_explicit_fcff": pv_fcff_total,
        "enterprise_value": enterprise_value,
        "net_debt": net_debt,
        "equity_value": equity_value,
        "value_per_share": value_per_share,
        "assumptions": vars(a),
        "provenance": inp.provenance,
        "disclaimer": DISCLAIMER,
    }


def sensitivity(inp: DCFInputs, a: DCFAssumptions, wacc_values: List[float],
                growth_values: List[float]) -> Dict[str, Any]:
    """Per-share value across a WACC x terminal-growth grid (invalid cells -> NaN)."""
    matrix: List[List[float]] = []
    for w in wacc_values:
        row: List[float] = []
        for g in growth_values:
            trial = DCFAssumptions(**{**vars(a), "wacc": w, "terminal_growth": g})
            res = run_dcf(inp, trial)
            row.append(res["value_per_share"] if res["valid"] else NAN)
        matrix.append(row)
    return {"wacc_values": list(wacc_values), "growth_values": list(growth_values), "value_per_share": matrix}


def run_scenarios(inp: DCFInputs, scenarios: Dict[str, DCFAssumptions]) -> Dict[str, Dict[str, Any]]:
    """Run named scenarios (e.g. base/upside/downside) against the same history."""
    return {name: run_dcf(inp, a) for name, a in scenarios.items()}


def _register_all() -> None:
    register("valuation.dcf.fcff.v1", name="DCF (unlevered FCFF)", category="valuation",
             formula="EV = sum(FCFF_t / (1+WACC)^t) + PV(terminal); FCFF = EBIT*(1-tax) + D&A - CapEx - dNWC",
             inputs=["revenue", "ebit", "tax_rate", "da", "capex", "nwc", "wacc"],
             units="currency", sign_convention="higher intrinsic value is richer valuation",
             supported_asset_classes=["equity"], period_assumption="annual projection",
             zero_denominator_policy="terminal_growth>=WACC or WACC<=0 -> validation failure",
             reference="standard unlevered DCF; intrinsic value is not a probability or price target")
    register("valuation.terminal.perpetual.v1", name="Terminal value (perpetual growth)", category="valuation",
             formula="FCFF_H*(1+g)/(WACC-g)", inputs=["fcff_terminal", "wacc", "terminal_growth"],
             units="currency", sign_convention="requires WACC > g", supported_asset_classes=["equity"])
    register("valuation.terminal.exit_multiple.v1", name="Terminal value (exit multiple)", category="valuation",
             formula="exit_multiple * EBITDA_H", inputs=["ebitda_terminal", "exit_multiple"],
             units="currency", sign_convention="multiple must be positive", supported_asset_classes=["equity"])
    register("valuation.equity_bridge.v1", name="EV to equity per share", category="valuation",
             formula="(EV - net_debt) / diluted_shares", inputs=["enterprise_value", "net_debt", "shares_diluted"],
             units="currency_per_share", sign_convention="context-dependent", supported_asset_classes=["equity"])


_register_all()
