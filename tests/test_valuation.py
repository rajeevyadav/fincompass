"""DCF valuation: hand-calculated cases + boundary conditions.

The canonical example is chosen so the arithmetic is exact:
revenue 100, EBIT margin 20%, tax 25% -> NOPAT 15; D&A 5%, CapEx 5%; 1-year
horizon, 0% growth, WACC 10%, terminal growth 0% -> FCFF 15, TV 150, EV 150,
0 net debt, 10 shares -> intrinsic value 15.00/share.
"""
import math

import pytest

from analytics import statements as St
from analytics import valuation as Val


def _inputs(**kw):
    base = dict(revenue=100.0, ebit=20.0, effective_tax_rate=0.25,
                depreciation_amortization=5.0, capex=5.0, net_working_capital=10.0,
                shares_diluted=10.0, net_debt=0.0, currency="USD")
    base.update(kw)
    return Val.DCFInputs(**base)


def _assumptions(**kw):
    base = dict(wacc=0.10, horizon_years=1, revenue_growth=0.0, ebit_margin=0.20,
                tax_rate=0.25, capex_pct_revenue=0.05, da_pct_revenue=0.05,
                nwc_pct_revenue=0.10, terminal_method="perpetual", terminal_growth=0.0)
    base.update(kw)
    return Val.DCFAssumptions(**base)


def test_perpetual_dcf_hand_calc():
    res = Val.run_dcf(_inputs(), _assumptions())
    assert res["valid"] is True
    assert res["projections"][0]["fcff"] == pytest.approx(15.0)
    assert res["terminal_value"] == pytest.approx(150.0)
    assert res["enterprise_value"] == pytest.approx(150.0)
    assert res["value_per_share"] == pytest.approx(15.0)


def test_exit_multiple_dcf_hand_calc():
    res = Val.run_dcf(_inputs(), _assumptions(terminal_method="exit_multiple", exit_multiple=6.0))
    # EBITDA_H = EBIT 20 + D&A 5 = 25; TV = 6*25 = 150 -> same EV as the perpetual case
    assert res["terminal_value"] == pytest.approx(150.0)
    assert res["value_per_share"] == pytest.approx(15.0)


def test_terminal_growth_ge_wacc_fails_safely():
    res = Val.run_dcf(_inputs(), _assumptions(terminal_growth=0.10))  # == WACC
    assert res["valid"] is False
    assert "terminal_growth_ge_wacc" in res["validation_failures"]
    assert math.isnan(res["value_per_share"])


def test_invalid_wacc_and_shares_fail_safely():
    assert "invalid_wacc" in Val.run_dcf(_inputs(), _assumptions(wacc=0.0))["validation_failures"]
    assert "invalid_wacc" in Val.run_dcf(_inputs(), _assumptions(wacc=-0.05))["validation_failures"]
    assert "invalid_shares" in Val.run_dcf(_inputs(shares_diluted=0.0), _assumptions())["validation_failures"]


def test_missing_required_history_fails_safely():
    res = Val.run_dcf(_inputs(revenue=None), _assumptions())
    assert res["valid"] is False and "missing_revenue" in res["validation_failures"]
    assert math.isnan(res["enterprise_value"])


def test_negative_fcf_is_valid_not_an_error():
    # very high CapEx -> negative FCFF, but a valid (low/negative) valuation
    res = Val.run_dcf(_inputs(), _assumptions(capex_pct_revenue=0.50))
    assert res["valid"] is True
    assert res["projections"][0]["fcff"] < 0


def test_net_debt_bridge_zero_excess_and_negative():
    ev = Val.run_dcf(_inputs(net_debt=0.0), _assumptions())["enterprise_value"]
    zero = Val.run_dcf(_inputs(net_debt=0.0), _assumptions())
    assert zero["equity_value"] == pytest.approx(ev)
    excess = Val.run_dcf(_inputs(net_debt=-50.0), _assumptions())   # net cash
    assert excess["equity_value"] == pytest.approx(ev + 50.0)
    levered = Val.run_dcf(_inputs(net_debt=40.0), _assumptions())
    assert levered["equity_value"] == pytest.approx(ev - 40.0)


def test_per_share_invariant_under_consistent_unit_scaling():
    # scale all monetary inputs AND shares by the same factor -> per-share unchanged
    k = 1000.0
    scaled = _inputs(revenue=100.0 * k, ebit=20.0 * k, depreciation_amortization=5.0 * k,
                     capex=5.0 * k, net_working_capital=10.0 * k, net_debt=0.0,
                     shares_diluted=10.0 * k)
    res = Val.run_dcf(scaled, _assumptions())
    assert res["value_per_share"] == pytest.approx(15.0)


def test_sensitivity_grid_shapes_and_invalid_cells():
    grid = Val.sensitivity(_inputs(), _assumptions(), [0.08, 0.10], [0.0, 0.10])
    assert len(grid["value_per_share"]) == 2 and len(grid["value_per_share"][0]) == 2
    # growth 0.10 == WACC 0.10 -> that cell is invalid (NaN)
    assert math.isnan(grid["value_per_share"][1][1])
    assert grid["value_per_share"][0][0] > 0


def test_scenarios_run_independently():
    out = Val.run_scenarios(_inputs(), {
        "base": _assumptions(),
        "upside": _assumptions(revenue_growth=0.10, horizon_years=3),
        "downside": _assumptions(revenue_growth=-0.05, horizon_years=3),
    })
    assert set(out) == {"base", "upside", "downside"}
    assert out["upside"]["value_per_share"] > out["downside"]["value_per_share"]


# --- integration with the canonical statement layer -------------------------

def test_build_inputs_from_canonical_statements_with_provenance():
    inc = St.normalize({"revenue": 100.0, "ebit": 20.0, "pretax_income": 20.0,
                        "tax_expense": 5.0, "depreciation_amortization": 5.0,
                        "shares_diluted": 10.0}, {}, kind=St.INCOME, period_type="annual", currency="USD")
    bal = St.normalize({"current_assets": 40.0, "current_liabilities": 20.0,
                        "cash_and_equivalents": 10.0, "short_term_debt": 0.0,
                        "total_debt": 30.0}, {}, kind=St.BALANCE, period_type="annual", currency="USD")
    cf = St.normalize({"operating_cash_flow": 18.0, "capital_expenditure": -5.0},
                      {}, kind=St.CASHFLOW, period_type="annual", currency="USD")
    inp = Val.build_inputs(inc, bal, cf)
    assert inp.revenue == 100.0 and inp.ebit == 20.0
    assert inp.effective_tax_rate == pytest.approx(0.25)
    assert inp.capex == 5.0                       # abs of -5
    assert inp.net_debt == pytest.approx(20.0)    # total_debt 30 - cash 10
    # NWC = (CA - cash) - (CL - std) = (40-10) - (20-0) = 10
    assert inp.net_working_capital == pytest.approx(10.0)
    assert inp.provenance["net_debt"].startswith("derived")
    res = Val.run_dcf(inp, _assumptions())
    # EV 150 - net debt 20 = equity 130 -> 13.00/share (the bridge applied)
    assert res["valid"] and res["value_per_share"] == pytest.approx(13.0)


def test_currency_mismatch_fails_safely():
    inc = St.normalize({"revenue": 100.0, "ebit": 20.0, "shares_diluted": 10.0},
                       {}, kind=St.INCOME, period_type="annual", currency="USD")
    bal = St.normalize({"current_assets": 40.0, "current_liabilities": 20.0, "total_debt": 30.0,
                        "cash_and_equivalents": 10.0}, {}, kind=St.BALANCE, period_type="annual", currency="EUR")
    cf = St.normalize({"capital_expenditure": -5.0}, {}, kind=St.CASHFLOW, period_type="annual", currency="USD")
    inp = Val.build_inputs(inc, bal, cf)
    assert "currency_mismatch" in inp.issues
    assert Val.run_dcf(inp, _assumptions())["valid"] is False
