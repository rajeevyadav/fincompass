"""Freshness is three separate concepts, and the viewed ticker must not be able
to make a pooled family model look stale."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

import services.model_freshness as mf


def _manifest(cutoff="2022-06-30", horizon=12, symbols=("AAA", "BBB", "CCC")):
    return {
        "applicability_domain": {"training_period_end": cutoff,
                                 "target_horizon_months": horizon,
                                 "training_symbols": list(symbols)},
        "dataset_provenance": {"training_period_end": cutoff, "training_assets": list(symbols)},
        "target": {"horizon_months": horizon},
    }


@pytest.fixture
def fake_coverage(monkeypatch):
    """Drive research_store.coverage from a symbol->latest-date table."""
    table = {}

    def coverage(symbols=None):
        syms = [s.upper() for s in (symbols or table.keys())]
        return [{"symbol": s, "latest": table.get(s)} for s in syms if s in table]

    monkeypatch.setattr(mf.research_store, "coverage", coverage)
    return table


def test_returns_three_distinct_concepts(fake_coverage):
    r = mf.evaluate_model_freshness(_manifest(), "AAA", "^GSPC")
    assert set(r) >= {"instrument_data_freshness", "model_training_freshness", "retrainability"}
    assert r["model_training_freshness"]["status"] in {"current", "aging", "old", "unknown"}


def test_new_ticker_with_current_prices_does_not_make_model_stale(fake_coverage):
    # A brand-new in-domain ticker carrying today's prices. It is NOT in the
    # family universe, so it must not touch model_training_freshness or
    # retrainability - only its own instrument_data_freshness.
    today = date.today().isoformat()
    fake_coverage["NVDA"] = today  # the viewed new ticker, current data
    # No family symbols have new data.
    r = mf.evaluate_model_freshness(_manifest(cutoff="2022-06-30"), "NVDA", None)

    assert r["instrument_data_freshness"]["status"] == "current"
    # Model corpus age is judged only from the training cutoff, independent of NVDA.
    mtf = r["model_training_freshness"]
    assert mtf["training_period_end"] == "2022-06-30"
    assert mtf["age_months"] > 12  # genuinely old corpus, regardless of NVDA
    # Retrainability saw no NEW family data, so no update is offered.
    assert r["retrainability"]["update_available"] is False
    assert r["retrainability"]["family_symbols_with_new_data"] == 0


def test_retrainability_counts_family_data_only(fake_coverage):
    # New, label-matured data on the family universe -> update recommended.
    old = date.today() - timedelta(days=400)  # well past a 12-month maturity
    fake_coverage["AAA"] = old.isoformat()
    fake_coverage["BBB"] = old.isoformat()
    # The viewed ticker is a family member here; still measured over the family.
    r = mf.evaluate_model_freshness(_manifest(cutoff="2019-01-01"), "AAA", None)
    rt = r["retrainability"]
    assert rt["update_available"] is True
    assert rt["family_symbols_with_new_data"] == 2
    assert rt["newly_matured_label_months"] is not None


def test_instrument_data_freshness_flags_stale_local_history(fake_coverage):
    fake_coverage["AAA"] = (date.today() - timedelta(days=120)).isoformat()
    r = mf.evaluate_model_freshness(_manifest(), "AAA", None)
    assert r["instrument_data_freshness"]["status"] == "stale"
    assert r["instrument_data_freshness"]["lag_days"] >= 100


def test_absent_local_data_is_not_an_error(fake_coverage):
    # Nothing stored locally: a pooled forecast can still fetch on demand.
    r = mf.evaluate_model_freshness(_manifest(), "ZZZ", None)
    assert r["instrument_data_freshness"]["status"] == "absent"


def test_missing_cutoff_is_unknown_not_crash(fake_coverage):
    m = _manifest()
    m["applicability_domain"]["training_period_end"] = None
    m["dataset_provenance"]["training_period_end"] = None
    r = mf.evaluate_model_freshness(m, "AAA", None)
    assert r["model_training_freshness"]["status"] == "unknown"
    assert r["retrainability"]["update_available"] is False
