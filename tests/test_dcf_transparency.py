"""The Guided DCF must expose its full scenario mathematics for Research: base
normalization, growth anchor + source, terminal value share, and the raw
scenario range before any display bound."""
from __future__ import annotations

from services.fundamentals import build_fundamentals


def _fetch(_ticker):
    # Newest-first histories; one negative FCF year to exercise the exclusion path.
    return {
        "income": {"Total Revenue": 400.0, "Diluted Average Shares": 15.0},
        "balance": {"Total Debt": 20.0, "Cash And Cash Equivalents": 70.0},
        "cashflow": {"Free Cash Flow": 100.0, "Operating Cash Flow": 120.0,
                     "Capital Expenditure": -20.0},
        "currency": "USD",
        "revenue_history": [400.0, 360.0, 320.0, 300.0],
        "fcf_history": [100.0, 90.0, -10.0, 70.0],
    }


def test_dcf_exposes_full_scenario_surface():
    out = build_fundamentals("TEST", instrument={"instrument_type": "equity"},
                             market_price=120.0, fetch=_fetch)
    dcf = out["dcf"]
    assert dcf["valid"] is True

    # Base normalization is disclosed, including the excluded negative year.
    norm = dcf["base_fcf_normalization"]
    assert norm["method"] == "mean_of_recent_positive_reported_fcf"
    assert norm["negative_years_excluded"] == 1  # the -10 sits inside the 3-year window
    assert norm["reported_fcf_history"] == [100.0, 90.0, -10.0, 70.0]
    assert norm["years_used"] == 2

    # Growth anchor names its source series.
    assert dcf["growth_anchor"]["source"] in {"fcf_cagr", "revenue_cagr"}

    # Terminal value and its share of EV are present.
    assert dcf["terminal_value"] is not None
    assert 0.0 < dcf["terminal_value_pct_of_ev"] < 1.0

    # Raw scenario range is exposed alongside the (possibly clamped) shown range.
    assert dcf["raw_scenario_range"]["low"] is not None
    assert dcf["raw_scenario_range"]["high"] >= dcf["raw_scenario_range"]["low"]
    assert "applied" in dcf["display_range_clamp"]

    # Bridge inputs are surfaced.
    assert dcf["net_debt"] is not None and dcf["shares_diluted"] == 15.0


def test_dcf_excludes_negative_year_in_window_and_flags_caution():
    def fetch_cyclical(_t):
        d = _fetch(_t)
        # Put the negative year inside the recent 3-year averaging window.
        d["fcf_history"] = [100.0, -30.0, 90.0, 70.0]
        return d

    dcf = build_fundamentals("CYC", instrument={"instrument_type": "equity"},
                             market_price=100.0, fetch=fetch_cyclical)["dcf"]
    norm = dcf["base_fcf_normalization"]
    assert norm["negative_years_excluded"] == 1
    assert norm["cyclical_caution"] is True
