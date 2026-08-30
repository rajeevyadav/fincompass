"""Fixed-income analytics: known-answer cases + safe-fail boundaries.

Canonical checks are chosen so the arithmetic is exact or hand-verifiable:
a bond whose coupon equals its yield prices at par; a one-period zero-coupon
bond has Macaulay duration of exactly one year.
"""
import math

import pytest

from analytics import fixed_income as FI


# --- pricing ----------------------------------------------------------------

def test_par_bond_prices_at_face_when_coupon_equals_yield():
    # 5% semiannual coupon, 5% yield, 2y -> price == face
    assert FI.bond_price(1000.0, 0.05, 0.05, 2.0, freq=2) == pytest.approx(1000.0)


def test_premium_and_discount_relative_to_par():
    par = 1000.0
    premium = FI.bond_price(par, 0.06, 0.05, 5.0, freq=2)   # coupon > yield
    discount = FI.bond_price(par, 0.04, 0.05, 5.0, freq=2)  # coupon < yield
    assert premium > par > discount


def test_zero_coupon_price_is_discounted_face():
    # 1y annual zero at 5% -> 1000 / 1.05
    assert FI.bond_price(1000.0, 0.0, 0.05, 1.0, freq=1) == pytest.approx(1000.0 / 1.05)


# --- yield to maturity ------------------------------------------------------

def test_ytm_recovers_the_pricing_yield():
    price = FI.bond_price(1000.0, 0.06, 0.045, 7.0, freq=2)
    assert FI.yield_to_maturity(price, 1000.0, 0.06, 7.0, freq=2) == pytest.approx(0.045, abs=1e-6)


def test_ytm_of_par_bond_equals_coupon():
    assert FI.yield_to_maturity(1000.0, 1000.0, 0.05, 2.0, freq=2) == pytest.approx(0.05, abs=1e-6)


def test_current_yield_hand_calc():
    # 6% coupon on 1000 face, priced at 800 -> 60/800 = 7.5%
    assert FI.current_yield(1000.0, 0.06, 800.0) == pytest.approx(0.075)


# --- duration / convexity ---------------------------------------------------

def test_zero_coupon_macaulay_duration_equals_maturity():
    assert FI.macaulay_duration(1000.0, 0.0, 0.05, 1.0, freq=1) == pytest.approx(1.0)
    assert FI.macaulay_duration(1000.0, 0.0, 0.05, 5.0, freq=1) == pytest.approx(5.0)


def test_modified_duration_is_macaulay_over_one_plus_periodic_yield():
    mac = FI.macaulay_duration(1000.0, 0.05, 0.05, 3.0, freq=2)
    mod = FI.modified_duration(1000.0, 0.05, 0.05, 3.0, freq=2)
    assert mod == pytest.approx(mac / (1.0 + 0.05 / 2))


def test_coupon_bond_duration_is_less_than_maturity():
    # a coupon-paying bond returns cash before maturity -> duration < maturity
    assert FI.macaulay_duration(1000.0, 0.05, 0.05, 10.0, freq=2) < 10.0


def test_convexity_positive_and_dv01_matches_duration_approx():
    face, c, y, T, f = 1000.0, 0.05, 0.05, 10.0, 2
    assert FI.convexity(face, c, y, T, freq=f) > 0
    # DV01 ≈ modified_duration * price * 1bp
    price = FI.bond_price(face, c, y, T, freq=f)
    approx = FI.modified_duration(face, c, y, T, freq=f) * price * 1e-4
    assert FI.dv01(face, c, y, T, freq=f) == pytest.approx(approx, rel=1e-3)


def test_price_falls_as_yield_rises():
    lo = FI.bond_price(1000.0, 0.05, 0.04, 10.0, freq=2)
    hi = FI.bond_price(1000.0, 0.05, 0.08, 10.0, freq=2)
    assert lo > hi


# --- safe-fail boundaries ---------------------------------------------------

def test_invalid_inputs_return_nan_not_raise():
    assert math.isnan(FI.bond_price(0.0, 0.05, 0.05, 2.0))        # zero face
    assert math.isnan(FI.bond_price(1000.0, 0.05, 0.05, -1.0))    # negative maturity
    assert math.isnan(FI.bond_price(1000.0, 0.05, 0.05, 2.0, freq=0))  # invalid freq
    assert math.isnan(FI.bond_price(1000.0, 0.05, float("nan"), 2.0))  # non-finite yield
    assert math.isnan(FI.current_yield(1000.0, 0.06, 0.0))        # zero price
    assert math.isnan(FI.yield_to_maturity(0.0, 1000.0, 0.05, 2.0))    # zero price


def test_ytm_returns_nan_when_price_unreachable():
    # a price far above the sum of undiscounted cash flows cannot be bracketed
    unreachable = 10_000_000.0
    assert math.isnan(FI.yield_to_maturity(unreachable, 1000.0, 0.05, 2.0, freq=2))


def test_registry_has_fixed_income_metrics():
    from analytics import registry as R
    for mid in ["fixedincome.bond_price.v1", "fixedincome.ytm.v1",
                "fixedincome.macaulay_duration.v1", "fixedincome.modified_duration.v1",
                "fixedincome.convexity.v1", "fixedincome.dv01.v1",
                "fixedincome.current_yield.v1"]:
        assert R.definition(mid) is not None
