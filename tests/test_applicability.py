"""Instrument classification + benchmark resolution (Phase 4, items 4/5)."""
from services.instrument_classification import classify_instrument
from services.benchmark_resolver import resolve_benchmark


def test_classify_us_equity_from_catalogue():
    c = classify_instrument("AAPL")
    assert c["available"] and c["asset_class"] == "equity"
    assert c["region"] == "US" and c["security_type"] == "US equity"


def test_classify_canadian_equity_from_suffix():
    c = classify_instrument("XIU.TO")
    assert c["available"] and c["region"] == "CA"
    assert c["currency"] == "CAD"


def test_classify_crypto_and_index_and_european():
    assert classify_instrument("BTC-USD")["asset_class"] == "crypto"
    assert classify_instrument("^GSPC")["asset_class"] == "index"
    de = classify_instrument("SAP.DE")
    assert de["region"] == "DE" and de["asset_class"] == "equity"


def test_unknown_symbol_is_unavailable_not_assumed_us():
    c = classify_instrument("ZZZZ")
    assert c["available"] is False
    assert c["asset_class"] == "unknown" and c["region"] is None


def test_benchmark_resolution_by_region():
    us = resolve_benchmark(classify_instrument("AAPL"))
    assert us["supported"] and us["benchmark_symbol"] == "^GSPC"
    assert us["benchmark_name"] == "S&P 500" and us["benchmark_family"] == "US_LARGE_CAP"
    ca = resolve_benchmark(classify_instrument("XIU.TO"))
    assert ca["supported"] and ca["benchmark_symbol"] == "^GSPTSE"


def test_benchmark_unsupported_for_crypto_and_unclassified():
    crypto = resolve_benchmark(classify_instrument("BTC-USD"))
    assert crypto["supported"] is False
    unknown = resolve_benchmark(classify_instrument("ZZZZ"))
    assert unknown["supported"] is False
    assert unknown["reason"] == "INSTRUMENT_CLASSIFICATION_UNAVAILABLE"
