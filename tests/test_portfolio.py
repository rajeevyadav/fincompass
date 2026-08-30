"""Portfolio analytics: hand-calculated variance/risk decomposition + safe-fail."""
import math

import pytest

from analytics import portfolio as P


# --- return / variance ------------------------------------------------------

def test_portfolio_return_is_weighted_mean():
    assert P.portfolio_return([0.5, 0.5], [0.10, 0.20]) == pytest.approx(0.15)
    assert P.portfolio_return([0.25, 0.75], [0.04, 0.08]) == pytest.approx(0.07)


def test_uncorrelated_two_asset_variance_hand_calc():
    # vols 0.2 & 0.3, zero correlation, equal weights
    cov = [[0.04, 0.0], [0.0, 0.09]]
    var = P.portfolio_variance([0.5, 0.5], cov)
    assert var == pytest.approx(0.0325)                       # .25*.04 + .25*.09
    assert P.portfolio_volatility([0.5, 0.5], cov) == pytest.approx(math.sqrt(0.0325))


def test_perfectly_correlated_volatility_is_weighted_average():
    # corr = 1 -> portfolio vol = weighted average of component vols
    cov = [[0.04, 0.06], [0.06, 0.09]]                        # vols 0.2, 0.3, corr 1
    assert P.portfolio_volatility([0.5, 0.5], cov) == pytest.approx(0.25)


def test_diversification_reduces_volatility_below_weighted_average():
    cov = [[0.04, 0.0], [0.0, 0.09]]
    weighted_avg_vol = 0.5 * 0.2 + 0.5 * 0.3
    assert P.portfolio_volatility([0.5, 0.5], cov) < weighted_avg_vol


# --- risk contributions -----------------------------------------------------

def test_component_contributions_sum_to_volatility():
    cov = [[0.04, 0.0], [0.0, 0.09]]
    rc = P.risk_contributions([0.5, 0.5], cov)
    vol = P.portfolio_volatility([0.5, 0.5], cov)
    assert sum(rc["component"]) == pytest.approx(vol)
    assert sum(rc["percent"]) == pytest.approx(1.0)


def test_higher_vol_asset_carries_more_risk_at_equal_weight():
    cov = [[0.04, 0.0], [0.0, 0.09]]
    rc = P.risk_contributions([0.5, 0.5], cov)
    assert rc["component"][1] > rc["component"][0]  # 0.3-vol asset contributes more


# --- from return series -----------------------------------------------------

def test_covariance_and_portfolio_series_from_returns():
    # two assets, 4 periods
    returns = [[0.01, 0.02], [0.03, -0.01], [-0.02, 0.04], [0.05, 0.00]]
    cov = P.covariance_from_returns(returns)
    assert len(cov) == 2 and len(cov[0]) == 2
    assert cov[0][0] == pytest.approx(cov[0][0])  # finite, symmetric
    assert cov[0][1] == pytest.approx(cov[1][0])
    series = P.portfolio_return_series([0.5, 0.5], returns)
    assert series[0] == pytest.approx(0.015)      # mean of 0.01, 0.02


# --- normalization ----------------------------------------------------------

def test_normalize_weights_sums_to_one():
    w = P.normalize_weights([2.0, 2.0, 4.0])
    assert sum(w) == pytest.approx(1.0)
    assert w == pytest.approx([0.25, 0.25, 0.5])


# --- safe-fail --------------------------------------------------------------

def test_invalid_inputs_return_nan_not_raise():
    assert math.isnan(P.portfolio_return([0.5, 0.5], [0.1]))            # length mismatch
    assert math.isnan(P.portfolio_variance([0.5, 0.5], [[0.04, 0.0]]))  # non-square cov
    assert math.isnan(P.portfolio_variance([0.5, 0.5], [[0.04, 0.01], [0.99, 0.09]]))  # asymmetric
    assert math.isnan(P.portfolio_return([0.5, float("nan")], [0.1, 0.2]))  # non-finite weight
    assert all(math.isnan(x) for x in P.normalize_weights([1.0, -1.0]))     # zero sum


def test_zero_volatility_risk_contributions_are_nan():
    cov = [[0.0, 0.0], [0.0, 0.0]]
    rc = P.risk_contributions([0.5, 0.5], cov)
    assert all(math.isnan(x) for x in rc["component"])


def test_registry_has_portfolio_metrics():
    from analytics import registry as R
    for mid in ["portfolio.return.v1", "portfolio.variance.v1", "portfolio.volatility.v1",
                "portfolio.risk_contribution.v1", "portfolio.covariance.v1"]:
        assert R.definition(mid) is not None
