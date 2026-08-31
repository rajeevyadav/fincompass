"""'Why this result?' — the Forecast must explain why a model family was selected,
and, when none applies, which applicability condition failed in plain language."""
from __future__ import annotations

from services.model_selection import select_model, selection_rationale

_INSTR = {"asset_class": "equity", "region": "US", "security_type": "common_stock", "symbol": "AAPL"}
_BENCH = {"supported": True, "family": "US_LARGE_CAP", "symbol": "^GSPC"}


def test_selected_rationale_names_the_deciding_factors():
    sel = select_model(_INSTR, _BENCH, 12)
    r = selection_rationale(_INSTR, _BENCH, 12, sel["selected"], sel["rejected"], len(sel["eligible"]))
    assert r["available"] is True
    assert "12 months" in r["summary"] and "US_LARGE_CAP" in r["summary"]
    labels = {f["label"] for f in r["factors"]}
    assert {"Instrument", "Horizon", "Benchmark family", "Evidence tier", "Applicability"} <= labels


def test_unavailable_rationale_explains_the_failed_condition():
    crypto = {"asset_class": "crypto", "region": "US", "security_type": "token"}
    r = selection_rationale(crypto, _BENCH, 12, None, [], 0)
    assert r["available"] is False
    assert r["summary"].startswith("FinCompass can analyze this instrument, but")
    assert r["primary_reason_code"]


def test_forecast_service_attaches_why_selected():
    # The forecast response for a supported name carries the rationale (network
    # permitting); if the network is unavailable the call degrades to available=False
    # but must still be shape-safe.
    from services.forecast_service import forecast_ticker
    out = forecast_ticker("AAPL", horizon_months=12)
    if out.get("available"):
        assert out["why_selected"]["available"] is True
        assert out["why_selected"]["summary"]
    else:
        # Unsupported/again degraded paths carry a plain explanation.
        assert "why_unavailable" in out or "message" in out
