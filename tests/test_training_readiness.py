"""Hard data-readiness gates (§8) and the training gate that blocks builds.

Uses a fake research store so each gate can be exercised deterministically with
no network or real corpus.
"""
import pandas as pd
import pytest

from services import training_readiness as tr


class _FakeStore:
    def __init__(self, coverage_rows, frames=None):
        self._cov = coverage_rows
        self._frames = frames or {}

    def coverage(self, symbols=None):
        want = {str(s).upper() for s in (symbols or [])}
        return [r for r in self._cov if not want or str(r["symbol"]).upper() in want]

    def read_price_history(self, symbol, start=None, end=None):
        return self._frames.get(symbol.upper(), pd.DataFrame(columns=["Close"]))


def _recipe(monkeypatch, recipe):
    monkeypatch.setattr(tr, "get_recipe", lambda rid: dict(recipe))


def _store(monkeypatch, coverage_rows, frames=None):
    monkeypatch.setattr(tr, "research_store", _FakeStore(coverage_rows, frames))


BASE_RECIPE = {"recipe_id": "r", "name": "R", "benchmark": "^GSPC",
               "tickers": ["AAPL"], "horizon_trading_days": 126, "feature_contract": "price_relative_v1"}


def _row(symbol, rows, earliest="2005-01-01", latest="2024-01-01", providers="stooq"):
    return {"symbol": symbol, "rows": rows, "earliest": earliest, "latest": latest,
            "providers": providers, "price_basis": "adjusted"}


def _good_frame(n=4000):
    idx = pd.date_range("2005-01-01", periods=n, freq="D")
    return pd.DataFrame({"Close": range(1, n + 1)}, index=idx)


def _codes(result):
    return {g["code"] for g in result["gates"]}


def test_missing_benchmark_gate(monkeypatch):
    _recipe(monkeypatch, BASE_RECIPE)
    _store(monkeypatch, [_row("^GSPC", 0), _row("AAPL", 4000)], {"AAPL": _good_frame()})
    r = tr.evaluate_training_readiness("r")
    assert r["ready"] is False and "MISSING_BENCHMARK" in _codes(r)


def test_missing_targets_gate(monkeypatch):
    _recipe(monkeypatch, BASE_RECIPE)
    _store(monkeypatch, [_row("^GSPC", 4000), _row("AAPL", 0)])
    r = tr.evaluate_training_readiness("r")
    assert "MISSING_TARGETS" in _codes(r)
    assert r["universe"]["excluded"] == [{"symbol": "AAPL", "reason": "NO_LOCAL_HISTORY"}]


def test_insufficient_history_gate(monkeypatch):
    _recipe(monkeypatch, BASE_RECIPE)
    _store(monkeypatch, [_row("^GSPC", 4000), _row("AAPL", 300)], {"AAPL": _good_frame(300)})
    r = tr.evaluate_training_readiness("r")
    g = next(x for x in r["gates"] if x["code"] == "INSUFFICIENT_HISTORY_FOR_HORIZON")
    assert g["symbols"] == ["AAPL"] and "years" in str(g["required"])


def test_benchmark_alignment_gate(monkeypatch):
    _recipe(monkeypatch, BASE_RECIPE)
    # benchmark ends ~14 months before the target
    _store(monkeypatch, [
        _row("^GSPC", 4000, latest="2022-11-01"),
        _row("AAPL", 4000, latest="2024-01-01"),
    ], {"AAPL": _good_frame()})
    r = tr.evaluate_training_readiness("r")
    g = next(x for x in r["gates"] if x["code"] == "BENCHMARK_ALIGNMENT")
    assert "^GSPC" in g["symbols"] and "months" in str(g["actual"])


def test_duplicate_and_nonpositive_and_missing_gates(monkeypatch):
    _recipe(monkeypatch, BASE_RECIPE)
    idx = pd.to_datetime(["2005-01-01", "2005-01-01", "2005-01-03", "2005-01-04"])
    frame = pd.DataFrame({"Close": [10.0, 11.0, -5.0, None]}, index=idx)
    _store(monkeypatch, [_row("^GSPC", 4000), _row("AAPL", 4000)], {"AAPL": frame})
    r = tr.evaluate_training_readiness("r")
    codes = _codes(r)
    assert "DUPLICATE_DATES" in codes
    assert "NONPOSITIVE_PRICES" in codes
    assert "EXCESSIVE_MISSING" in codes


def test_missing_provenance_gate(monkeypatch):
    _recipe(monkeypatch, BASE_RECIPE)
    _store(monkeypatch, [_row("^GSPC", 4000), _row("AAPL", 4000, providers="")], {"AAPL": _good_frame()})
    r = tr.evaluate_training_readiness("r")
    assert "MISSING_PROVENANCE" in _codes(r)


def test_stale_data_gate(monkeypatch):
    _recipe(monkeypatch, BASE_RECIPE)
    _store(monkeypatch, [_row("^GSPC", 4000), _row("AAPL", 4000, latest="2010-01-01")], {"AAPL": _good_frame()})
    r = tr.evaluate_training_readiness("r")
    assert "STALE_DATA" in _codes(r)


def test_feature_contract_incompatible_gate(monkeypatch):
    recipe = dict(BASE_RECIPE, feature_contract="mystery_v9")
    _recipe(monkeypatch, recipe)
    _store(monkeypatch, [_row("^GSPC", 4000), _row("AAPL", 4000)], {"AAPL": _good_frame()})
    r = tr.evaluate_training_readiness("r")
    assert "FEATURE_CONTRACT_INCOMPATIBLE" in _codes(r)


def test_every_failure_carries_full_structure(monkeypatch):
    _recipe(monkeypatch, BASE_RECIPE)
    _store(monkeypatch, [_row("^GSPC", 0), _row("AAPL", 4000)], {"AAPL": _good_frame()})
    r = tr.evaluate_training_readiness("r")
    for g in r["gates"]:
        assert set(g) >= {"code", "symbols", "actual", "required", "explanation", "action"}
        assert g["explanation"] and g["action"]


def test_ready_when_everything_present(monkeypatch):
    # Enough instruments x history that the cross-sectional matured-label
    # estimate clears min_test_samples (500) for the 126-day horizon.
    syms = [f"S{i:02d}" for i in range(12)]
    _recipe(monkeypatch, dict(BASE_RECIPE, tickers=syms))
    cov = [_row("^GSPC", 8000)] + [_row(s, 8000) for s in syms]
    frames = {s: _good_frame(8000) for s in syms}
    # keep 'now' close to the data's latest so STALE_DATA does not trip
    monkeypatch.setattr(tr, "_now_ts", lambda: pd.Timestamp("2024-01-15"))
    _store(monkeypatch, cov, frames)
    r = tr.evaluate_training_readiness("r")
    assert r["ready"] is True, [g["code"] for g in r["gates"]]
    assert r["gates"] == []
    assert all(c["status"] == "pass" for c in r["checklist"])
