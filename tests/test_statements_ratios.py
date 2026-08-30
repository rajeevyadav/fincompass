"""Statement normalization + ratio integrity (hand-calc + pathological inputs)."""
import math

from analytics import statements as S
from analytics import ratios as Ra


# provider-style alias maps (kept OUT of the ratio formulas)
YF_INCOME = {"Total Revenue": "revenue", "Cost Of Revenue": "cost_of_revenue",
             "Operating Income": "operating_income", "Net Income": "net_income",
             "Diluted Average Shares": "shares_diluted"}
YF_BALANCE = {"Total Assets": "total_assets", "Total Equity": "total_equity",
              "Current Assets": "current_assets", "Current Liabilities": "current_liabilities",
              "Inventory": "inventory", "Short Term Debt": "short_term_debt",
              "Long Term Debt": "long_term_debt", "Cash And Cash Equivalents": "cash_and_equivalents"}
YF_CASHFLOW = {"Operating Cash Flow": "operating_cash_flow", "Capital Expenditure": "capital_expenditure"}


# --- normalization ----------------------------------------------------------

def test_provider_aliases_map_to_canonical_with_status_and_scale():
    raw = {"Total Revenue": 100.0, "Net Income": 12.0}  # provider vocabulary
    st = S.normalize(raw, YF_INCOME, kind=S.INCOME, period_type="annual",
                     currency="USD", unit_scale=1_000.0, provenance={"provider": "yfinance"})
    assert st.get("revenue") == 100_000.0                 # unit scale applied
    assert st.status("revenue") == S.MAPPED               # via alias
    assert st.currency == "USD" and st.period_type == "annual"


def test_missing_field_is_unavailable_not_zero():
    st = S.normalize({"Total Revenue": 100.0}, YF_INCOME, kind=S.INCOME, period_type="annual")
    assert st.get("cost_of_revenue") is None              # NOT 0.0
    assert st.status("cost_of_revenue") == S.UNAVAILABLE


def test_not_applicable_for_bank_inventory():
    st = S.normalize({"Total Assets": 900.0}, YF_BALANCE, kind=S.BALANCE, period_type="annual",
                     not_applicable={"inventory"})
    assert st.get("inventory") is None and st.status("inventory") == S.NOT_APPLICABLE


def test_derive_fills_gross_profit_total_debt_and_fcf():
    inc = S.derive(S.normalize({"Total Revenue": 100.0, "Cost Of Revenue": 60.0},
                               YF_INCOME, kind=S.INCOME, period_type="annual"))
    assert inc.get("gross_profit") == 40.0 and inc.status("gross_profit") == S.DERIVED
    bal = S.derive(S.normalize({"Short Term Debt": 20.0, "Long Term Debt": 80.0},
                               YF_BALANCE, kind=S.BALANCE, period_type="annual"))
    assert bal.get("total_debt") == 100.0 and bal.status("total_debt") == S.DERIVED
    cf = S.derive(S.normalize({"Operating Cash Flow": 50.0, "Capital Expenditure": -15.0},
                              YF_CASHFLOW, kind=S.CASHFLOW, period_type="annual"))
    assert cf.get("free_cash_flow") == 35.0 and cf.status("free_cash_flow") == S.DERIVED


# --- ratios: hand-calculated ------------------------------------------------

def V(**kw):
    return dict(kw)


def test_margins_and_per_share_hand_calc():
    v = V(revenue=100.0, gross_profit=40.0, operating_income=20.0, net_income=10.0,
          shares_diluted=5.0)
    assert Ra.gross_margin(v) == 0.40
    assert Ra.operating_margin(v) == 0.20
    assert Ra.net_margin(v) == 0.10
    assert Ra.eps_diluted(v) == 2.0


def test_roe_uses_average_when_prior_supplied_else_ending():
    cur = V(net_income=10.0, total_equity=100.0)
    prior = V(total_equity=80.0)
    assert Ra.return_on_equity(cur, prior) == 10.0 / 90.0   # average
    assert Ra.return_on_equity(cur) == 0.10                 # ending


def test_leverage_and_coverage_hand_calc():
    v = V(total_debt=100.0, cash_and_equivalents=20.0, ebitda=40.0, ebit=50.0,
          interest_expense=10.0, total_equity=200.0, total_assets=400.0)
    assert Ra.net_debt_to_ebitda(v) == 2.0     # (100-20)/40
    assert Ra.interest_coverage(v) == 5.0      # 50/10
    assert Ra.debt_to_equity(v) == 0.5
    assert Ra.debt_to_assets(v) == 0.25


def test_quick_ratio_and_roic_hand_calc():
    assert Ra.quick_ratio(V(current_assets=100.0, inventory=30.0, current_liabilities=50.0)) == 1.4
    roic = Ra.return_on_invested_capital(
        V(ebit=100.0, pretax_income=100.0, tax_expense=25.0, total_debt=50.0,
          total_equity=100.0, cash_and_equivalents=25.0))
    assert roic == 0.6   # 100*(1-0.25)/(50+100-25) = 75/125


# --- pathological -----------------------------------------------------------

def test_zero_revenue_margins_are_nan():
    v = V(revenue=0.0, gross_profit=0.0, net_income=-5.0)
    assert math.isnan(Ra.gross_margin(v)) and math.isnan(Ra.net_margin(v))


def test_negative_equity_roe_is_nan():
    assert math.isnan(Ra.return_on_equity(V(net_income=10.0, total_equity=-50.0)))


def test_negative_ebitda_net_debt_is_nan():
    assert math.isnan(Ra.net_debt_to_ebitda(V(total_debt=100.0, cash_and_equivalents=0.0, ebitda=-20.0)))


def test_zero_denominators_are_nan_not_crash():
    assert math.isnan(Ra.current_ratio(V(current_assets=100.0, current_liabilities=0.0)))
    assert math.isnan(Ra.interest_coverage(V(ebit=50.0, interest_expense=0.0)))
    assert math.isnan(Ra.cash_conversion(V(free_cash_flow=10.0, net_income=0.0)))


def test_missing_inputs_yield_nan_never_silent_zero():
    # inventory missing -> quick ratio undefined (not computed as if inventory were 0)
    assert math.isnan(Ra.quick_ratio(V(current_assets=100.0, current_liabilities=50.0)))
    # revenue missing -> margin NaN
    assert math.isnan(Ra.net_margin(V(net_income=10.0)))
