"""Option-chain and Treasury-curve shaping, verified against injected providers
so no network is used. Guards the endpoints that make options and bonds real.
"""
import pytest

from services import options_chain as OC
from services import rates as R


class _FakeChain:
    def __init__(self, calls, puts):
        self.calls, self.puts = calls, puts


class _FakeFrame:
    """Minimal stand-in for a provider DataFrame with to_dict('records')."""
    def __init__(self, records):
        self._records = records
        self.empty = not records

    def to_dict(self, _orient):
        return self._records


class _FakeTicker:
    def __init__(self):
        self.options = ("2026-09-18", "2026-12-18")
        self.fast_info = {"last_price": 190.0}

    def option_chain(self, expiry):
        return _FakeChain(
            calls=_FakeFrame([{"strike": 185.0, "lastPrice": 8.2, "bid": 8.0, "ask": 8.4,
                               "impliedVolatility": 0.28, "volume": 120, "openInterest": 900}]),
            puts=_FakeFrame([{"strike": 185.0, "lastPrice": 4.1, "bid": 3.9, "ask": 4.3,
                              "impliedVolatility": 0.30, "volume": 60, "openInterest": 500}]),
        )


# --- option chain -----------------------------------------------------------

def test_available_expiries_lists_real_dates_and_spot():
    out = OC.available_expiries("AAPL", fetch=lambda t: _FakeTicker())
    assert out["available"] is True
    assert out["expiries"] == ["2026-09-18", "2026-12-18"]
    assert out["spot"] == 190.0


def test_chain_for_returns_calls_and_puts():
    out = OC.chain_for("AAPL", "2026-09-18", fetch=lambda t: _FakeTicker())
    assert out["available"] is True
    assert out["calls"][0]["strike"] == 185.0
    assert out["calls"][0]["implied_volatility"] == 0.28
    assert out["puts"][0]["last"] == 4.1


def test_unknown_expiry_degrades():
    out = OC.chain_for("AAPL", "1999-01-01", fetch=lambda t: _FakeTicker())
    assert out["available"] is False and "expiries" in out


def test_no_provider_degrades_not_raises():
    assert OC.available_expiries("AAPL", fetch=lambda t: None)["available"] is False


def test_instrument_without_options_degrades():
    class _NoOpts:
        options = ()
    assert OC.available_expiries("BRK.A", fetch=lambda t: _NoOpts())["available"] is False


# --- treasury curve ---------------------------------------------------------

def test_treasury_curve_shapes_points():
    fake = {"^IRX": 5.1, "^FVX": 4.2, "^TNX": 4.3, "^TYX": 4.5}
    out = R.treasury_curve(fetch=lambda s: fake.get(s))
    assert out["available"] is True
    tenors = [p["tenor"] for p in out["points"]]
    assert tenors == ["3M", "5Y", "10Y", "30Y"]
    assert out["points"][2]["yield_percent"] == 4.3


def test_treasury_curve_folds_times_ten_convention():
    # some feeds quote the index x10 (42.5 -> 4.25%)
    out = R.treasury_curve(fetch=lambda s: 42.5 if s == "^TNX" else None)
    assert out["points"][0]["yield_percent"] == pytest.approx(4.25)


def test_treasury_curve_unavailable_degrades():
    assert R.treasury_curve(fetch=lambda s: None)["available"] is False
