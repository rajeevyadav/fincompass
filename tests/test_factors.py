"""Factor / OLS analytics: exact regressions + safe-fail."""
import math

import pytest

from analytics import factors as F


# --- OLS core ---------------------------------------------------------------

def test_perfect_linear_fit_recovers_slope_and_intercept():
    x = [0.0, 1.0, 2.0, 3.0, 4.0]
    y = [1.0, 3.0, 5.0, 7.0, 9.0]     # y = 2x + 1 exactly
    res = F.ols(y, x)
    assert res["coefficients"][0] == pytest.approx(1.0)   # intercept
    assert res["coefficients"][1] == pytest.approx(2.0)   # slope
    assert res["r_squared"] == pytest.approx(1.0)
    assert max(abs(r) for r in res["residuals"]) < 1e-9


def test_r_squared_between_zero_and_one_for_noisy_fit():
    x = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    y = [1.1, 1.9, 3.2, 3.9, 5.1, 5.8]
    res = F.ols(y, x)
    assert 0.9 < res["r_squared"] <= 1.0
    assert res["n"] == 6 and res["df_resid"] == 4


def test_multi_factor_ols_recovers_known_coefficients():
    # y = 1 + 2*f1 - 3*f2 exactly
    f1 = [1.0, 2.0, 3.0, 0.0, 5.0, 1.0]
    f2 = [0.0, 1.0, 1.0, 2.0, 0.0, 3.0]
    y = [1 + 2 * a - 3 * b for a, b in zip(f1, f2)]
    factors_matrix = list(zip(f1, f2))
    res = F.ols(y, factors_matrix)
    assert res["coefficients"][0] == pytest.approx(1.0)
    assert res["coefficients"][1] == pytest.approx(2.0)
    assert res["coefficients"][2] == pytest.approx(-3.0)


# --- convenience wrappers ---------------------------------------------------

def test_single_factor_model_alpha_beta():
    factor = [0.01, -0.02, 0.03, 0.00, 0.04, -0.01]
    asset = [0.005 + 1.5 * f for f in factor]   # alpha 0.005, beta 1.5
    m = F.single_factor_model(asset, factor)
    assert m["alpha"] == pytest.approx(0.005)
    assert m["beta"] == pytest.approx(1.5)
    assert m["r_squared"] == pytest.approx(1.0)


def test_factor_loadings_named():
    f1 = [0.01, 0.02, -0.01, 0.03, 0.00, 0.015]
    f2 = [0.00, 0.01, 0.02, -0.01, 0.03, 0.005]
    asset = [0.001 + 0.8 * a + 0.4 * b for a, b in zip(f1, f2)]
    out = F.factor_loadings(asset, list(zip(f1, f2)), ["mkt", "size"])
    assert out["loadings"]["mkt"]["beta"] == pytest.approx(0.8)
    assert out["loadings"]["size"]["beta"] == pytest.approx(0.4)
    assert out["alpha"] == pytest.approx(0.001)


def test_rolling_beta_warmup_and_value():
    asset = [0.02, 0.04, 0.06, 0.08, 0.10]
    market = [0.01, 0.02, 0.03, 0.04, 0.05]   # asset = 2 * market -> beta 2
    rb = F.rolling_beta(asset, market, window=3)
    assert math.isnan(rb[0]) and math.isnan(rb[1])   # warm-up
    assert rb[2] == pytest.approx(2.0)
    assert rb[-1] == pytest.approx(2.0)


# --- safe-fail --------------------------------------------------------------

def test_insufficient_observations_returns_nan():
    res = F.ols([1.0, 2.0], [1.0, 2.0])   # n == k (2 params, 2 obs)
    assert math.isnan(res["r_squared"]) and res["n"] == 0


def test_rank_deficient_design_returns_nan():
    # two identical regressors -> singular design
    f = [1.0, 2.0, 3.0, 4.0, 5.0]
    res = F.ols([1.0, 2.0, 2.5, 4.1, 5.2], list(zip(f, f)))
    assert math.isnan(res["r_squared"])


def test_mismatched_and_nonfinite_inputs_return_nan():
    assert math.isnan(F.ols([1.0, 2.0, 3.0], [1.0, 2.0])["r_squared"])         # length mismatch
    assert math.isnan(F.ols([1.0, 2.0, float("nan"), 4.0], [1.0, 2.0, 3.0, 4.0])["r_squared"])
    assert F.rolling_beta([0.01, 0.02], [0.01, 0.02], window=5)[0] != F.rolling_beta(
        [0.01, 0.02], [0.01, 0.02], window=5)[0]  # NaN (window > n)


def test_registry_has_factor_metrics():
    from analytics import registry as R
    for mid in ["factors.ols.v1", "factors.single_factor.v1",
                "factors.loadings.v1", "factors.rolling_beta.v1"]:
        assert R.definition(mid) is not None
