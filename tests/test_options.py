"""European option analytics: reference values, parity, and safe-fail.

Canonical reference case (widely tabulated): S=100, K=100, r=5%, q=0, σ=20%,
T=1y -> call ≈ 10.4506, put ≈ 5.5735, call delta = N(d1) ≈ 0.6368.
"""
import math

import pytest

from analytics import options as O


CASE = dict(spot=100.0, strike=100.0, rate=0.05, vol=0.20, expiry=1.0)


# --- pricing ----------------------------------------------------------------

def test_atm_call_and_put_reference_values():
    assert O.price(O.CALL, **CASE) == pytest.approx(10.4506, abs=1e-3)
    assert O.price(O.PUT, **CASE) == pytest.approx(5.5735, abs=1e-3)


def test_put_call_parity_holds_exactly():
    c = O.price(O.CALL, **CASE)
    p = O.price(O.PUT, **CASE)
    s, k, r, T = CASE["spot"], CASE["strike"], CASE["rate"], CASE["expiry"]
    # c - p = S e^-qT - K e^-rT  (q = 0 here)
    assert (c - p) == pytest.approx(s - k * math.exp(-r * T), abs=1e-9)


def test_deep_itm_call_approaches_forward_minus_pv_strike():
    c = O.price(O.CALL, spot=200.0, strike=100.0, rate=0.05, vol=0.20, expiry=1.0)
    assert c > 100.0 * (1 - math.exp(-0.05))  # well above intrinsic-of-forward floor


# --- greeks -----------------------------------------------------------------

def test_call_delta_matches_reference_and_put_via_parity():
    dc = O.delta(O.CALL, **CASE)
    dp = O.delta(O.PUT, **CASE)
    assert dc == pytest.approx(0.6368, abs=1e-3)
    assert (dc - dp) == pytest.approx(1.0, abs=1e-9)  # e^-qT (q=0)


def test_gamma_and_vega_shared_by_call_and_put_and_positive():
    g = O.gamma(**CASE)
    v = O.vega(**CASE)
    assert g > 0 and v > 0


def test_vega_matches_finite_difference():
    v = O.vega(**CASE)
    h = 1e-4
    up = O.price(O.CALL, spot=100.0, strike=100.0, rate=0.05, vol=0.20 + h, expiry=1.0)
    dn = O.price(O.CALL, spot=100.0, strike=100.0, rate=0.05, vol=0.20 - h, expiry=1.0)
    assert v == pytest.approx((up - dn) / (2 * h), rel=1e-4)


def test_delta_matches_finite_difference():
    d = O.delta(O.CALL, **CASE)
    h = 1e-3
    up = O.price(O.CALL, spot=100.0 + h, strike=100.0, rate=0.05, vol=0.20, expiry=1.0)
    dn = O.price(O.CALL, spot=100.0 - h, strike=100.0, rate=0.05, vol=0.20, expiry=1.0)
    assert d == pytest.approx((up - dn) / (2 * h), rel=1e-5)


def test_long_option_theta_is_negative_and_rho_signs():
    assert O.theta(O.CALL, **CASE) < 0
    assert O.rho(O.CALL, **CASE) > 0
    assert O.rho(O.PUT, **CASE) < 0


# --- implied volatility -----------------------------------------------------

def test_implied_vol_round_trips_the_pricing_vol():
    px = O.price(O.CALL, **CASE)
    iv = O.implied_volatility(O.CALL, px, spot=100.0, strike=100.0, rate=0.05, expiry=1.0)
    assert iv == pytest.approx(0.20, abs=1e-5)


def test_implied_vol_of_put_round_trips():
    px = O.price(O.PUT, **CASE)
    iv = O.implied_volatility(O.PUT, px, spot=100.0, strike=100.0, rate=0.05, expiry=1.0)
    assert iv == pytest.approx(0.20, abs=1e-5)


# --- safe-fail --------------------------------------------------------------

def test_invalid_inputs_return_nan_not_raise():
    assert math.isnan(O.price(O.CALL, spot=0.0, strike=100.0, rate=0.05, vol=0.2, expiry=1.0))
    assert math.isnan(O.price(O.CALL, spot=100.0, strike=100.0, rate=0.05, vol=0.2, expiry=0.0))
    assert math.isnan(O.price(O.CALL, spot=100.0, strike=100.0, rate=0.05, vol=0.0, expiry=1.0))
    assert math.isnan(O.price("swap", spot=100.0, strike=100.0, rate=0.05, vol=0.2, expiry=1.0))
    assert math.isnan(O.gamma(spot=-1.0, strike=100.0, rate=0.05, vol=0.2, expiry=1.0))


def test_implied_vol_nan_when_price_unreachable():
    # a price above the spot is impossible for a call -> not bracketed
    assert math.isnan(O.implied_volatility(O.CALL, 500.0, spot=100.0, strike=100.0, rate=0.05, expiry=1.0))
    assert math.isnan(O.implied_volatility(O.CALL, 0.0, spot=100.0, strike=100.0, rate=0.05, expiry=1.0))


def test_registry_has_option_metrics():
    from analytics import registry as R
    for mid in ["options.bsm_price.v1", "options.delta.v1", "options.gamma.v1",
                "options.vega.v1", "options.theta.v1", "options.rho.v1",
                "options.implied_vol.v1"]:
        assert R.definition(mid) is not None
