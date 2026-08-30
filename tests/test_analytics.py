"""Hand-calculated verification of the analytics kernel (no external oracle).

Each expected value is derived by hand from the formula, plus edge cases
(constant series, zero denominators, NaN/Inf, short history).
"""
import numpy as np
import pandas as pd
import pytest

from analytics import common as C
from analytics import performance as P
from analytics import risk as R
from analytics import registry as REG


# --- common -----------------------------------------------------------------

def test_simple_returns_and_cumulative():
    prices = pd.Series([100.0, 110.0, 99.0])
    r = C.simple_returns(prices)
    assert r.tolist() == pytest.approx([0.10, -0.10])
    # compounded: 1.1 * 0.9 - 1 = -0.01
    assert C.cumulative_return(r) == pytest.approx(-0.01)


def test_annualize_return_geometric():
    # 12 monthly returns of exactly 0 -> 0% annualized
    r = pd.Series([0.0] * 12)
    assert C.annualize_return(r, "monthly") == pytest.approx(0.0)


def test_clean_drops_non_finite():
    s = pd.Series([0.01, np.nan, np.inf, -0.02])
    assert C._clean(s).tolist() == pytest.approx([0.01, -0.02])


# --- performance ------------------------------------------------------------

def test_volatility_zero_for_constant_returns():
    assert P.volatility(pd.Series([0.01] * 30)) == pytest.approx(0.0)


def test_sharpe_nan_when_no_dispersion():
    # zero std -> guarded to NaN, not a divide-by-zero
    assert np.isnan(P.sharpe_ratio(pd.Series([0.01] * 30)))


def test_max_drawdown_hand_calc():
    # wealth 1 -> 1.5 -> 0.75 ; peak 1.5 ; drawdown = 0.75/1.5 - 1 = -0.5
    assert P.max_drawdown(pd.Series([0.5, -0.5])) == pytest.approx(-0.5)


def test_beta_of_double_market_is_two():
    rng = np.random.default_rng(0)
    m = pd.Series(rng.normal(0, 0.01, 300))
    a = 2.0 * m
    assert P.beta(a, m) == pytest.approx(2.0, abs=1e-9)


def test_tracking_error_zero_and_ir_nan_when_identical():
    b = pd.Series([0.01, -0.02, 0.03, 0.0, 0.015])
    assert P.tracking_error(b, b) == pytest.approx(0.0)
    assert np.isnan(P.information_ratio(b, b))


def test_downside_deviation_hand_calc():
    # returns [-0.1, 0.1], MAR 0: downside = [-0.1, 0]; rms = sqrt(0.005)
    dd = P.downside_deviation(pd.Series([-0.1, 0.1]), mar_annual=0.0, frequency="daily")
    assert dd == pytest.approx(np.sqrt(0.005) * np.sqrt(252))


# --- risk -------------------------------------------------------------------

def test_historical_var_constant_loss():
    assert R.historical_var(pd.Series([-0.02] * 50), confidence=0.95) == pytest.approx(0.02)


def test_gaussian_var_hand_calc():
    from scipy.stats import norm
    r = pd.Series([-0.02, 0.02])  # mean 0, sample std = 0.02*sqrt(2)
    std = r.std(ddof=1)
    expected = -(0.0 + norm.ppf(0.05) * std)
    assert R.gaussian_var(r, 0.95) == pytest.approx(expected)


def test_cvar_at_least_var():
    rng = np.random.default_rng(1)
    r = pd.Series(rng.normal(0, 0.02, 1000))
    assert R.conditional_var(r, 0.95) >= R.historical_var(r, 0.95)


def test_var_never_described_as_max_loss():
    d = REG.definition("risk.var.historical.v1")
    assert "NOT maximum loss" in d["sign_convention"]


def test_max_drawdown_duration_counts_run():
    # wealth 1.1,0.99,0.891,1.3365 -> dd 0,-0.1,-0.19,0 -> run of 2
    assert R.max_drawdown_duration(pd.Series([0.1, -0.1, -0.1, 0.5])) == 2


def test_ewma_zero_for_constant_returns():
    assert R.ewma_volatility(pd.Series([0.01] * 40)) == pytest.approx(0.0)


# --- registry / result contract --------------------------------------------

def test_result_envelope_has_formula_and_version():
    env = REG.result("performance.sharpe.v1", 1.2345, period="TTM", as_of="2026-06-30")
    assert env["formula_id"] == "performance.sharpe.v1"
    assert env["method_version"] == "1"
    assert env["metric"] == "Sharpe ratio"
    assert env["display_value"] == "1.23"  # units=ratio -> 2dp
    assert env["period"] == "TTM" and env["as_of"] == "2026-06-30"


def test_every_registered_metric_has_complete_definition():
    required = {"metric_id", "name", "category", "formula", "inputs", "units",
                "sign_convention", "supported_asset_classes", "version"}
    assert REG.REGISTRY, "registry should be populated on import"
    for mid, d in REG.REGISTRY.items():
        assert required <= set(d), f"{mid} missing keys"
        assert d["inputs"] and d["supported_asset_classes"]
