from services.peers import build_peer_reference
from services.scoring import score_valuation


def test_peer_reference_uses_robust_median_and_minimum_sample():
    rows = [
        {"sector": "Technology", "pe": 20},
        {"sector": "Technology", "pe": 22},
        {"sector": "Technology", "pe": 24},
        {"sector": "Technology", "pe": 26},
        {"sector": "Technology", "pe": 28},
        {"sector": "Technology", "pe": 200},
        {"sector": "Energy", "pe": 8},
        {"sector": "Energy", "pe": 9},
    ]
    ref = build_peer_reference(rows)
    assert ref["Technology"]["pe"]["n"] == 6
    assert 22 <= ref["Technology"]["pe"]["median"] <= 27
    assert "Energy" not in ref or "pe" not in ref.get("Energy", {})


def test_valuation_uses_live_sector_peer_median_when_available():
    rows = [{"sector": "Technology", "pe": x} for x in [18, 20, 22, 24, 26, 28]]
    ref = build_peer_reference(rows)
    _, details, _ = score_valuation({"sector": "Technology", "pe": 20}, peer_reference=ref)
    assert details["pe"]["baseline_source"] == "live sector peer median"
    assert details["pe"]["peer"]["n"] == 6
