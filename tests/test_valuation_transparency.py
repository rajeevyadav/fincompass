"""
Tests for the valuation-transparency block (D-002 §2.2–§2.4). Covers the
mechanical/sector risk flags, the methodology footer, and the §3 blocking
guardrails:
  - no rating / price-target / "average of approaches" language in output;
  - no company-specific string ever appears in the sector-tag flags.
"""
import re

import pytest

from config import NON_AFFILIATION_NOTICE, SECTOR_RISK_TAGS
from services.valuation_transparency import (
    build_valuation_transparency,
    mechanical_flags,
    methodology_footer,
    sector_flags,
)

# §3 blocking guardrail: none of these may appear anywhere in generated output.
BANNED = ["buy", "sell", "strong buy", "price target", "pt:", "fair value", "upside",
          "average of", "target price", "overweight", "underweight"]
_BANNED_RE = re.compile(r"(" + "|".join(re.escape(b) for b in BANNED) + r")", re.IGNORECASE)


def result(sector="Technology", **pillar_scores):
    defaults = {"quality": 8.0, "moat": 8.0, "safety": 8.0, "valuation": 8.0, "cycle": 8.0}
    defaults.update(pillar_scores)
    pillars = {k: {"score": v} for k, v in defaults.items()}
    pillars["valuation"]["details"] = {
        "pe": {"value": 18.2, "sector_baseline": 22.0, "relative": 0.827,
               "peer": {"median": 22.0, "n": 14}},
    }
    return {"sector": sector, "pillars": pillars}


def _all_strings(block):
    # The implied_price_note is fixed, directive-sanctioned copy that negates a
    # price target ("does not average these into a price target"); it is pinned
    # exactly below rather than scanned for banned substrings.
    rf = block["risk_flags"]
    out = list(rf["mechanical"]) + list(rf["sector"]) + [rf["caption"]]
    out += [block["methodology"], block["non_affiliation"]]
    return out


# --- Mechanical flags mirror weak pillars (§2.2 tier 1) ------------------------

def test_mechanical_flags_match_weak_pillars():
    flags = mechanical_flags(result(safety=5.0, valuation=4.0)["pillars"])
    assert any("leverage" in f.lower() for f in flags)
    assert any("rich" in f.lower() or "price" in f.lower() for f in flags)


def test_mechanical_flags_empty_when_no_weak_pillar():
    assert mechanical_flags(result()["pillars"]) == []


@pytest.mark.parametrize("scores", [
    {"safety": 3.0}, {"quality": 4.0, "cycle": 4.9}, {"moat": 5.0, "valuation": 2.0},
])
def test_mechanical_flags_varied_fixtures(scores):
    flags = mechanical_flags(result(**scores)["pillars"])
    assert len(flags) == sum(1 for v in scores.values() if v < 6.0)


# --- Sector flags: generic only, never company-specific (§2.2 tier 2, §3) ------

def test_sector_flags_are_generic_lookup():
    assert sector_flags("Energy") == SECTOR_RISK_TAGS["Energy"]
    assert sector_flags("Unknown Sector") == []


def test_sector_flags_never_company_specific():
    # No ticker-like tokens or company-specific narrative anywhere in the table.
    ticker_like = re.compile(r"\$[A-Z]{1,5}\b|\b[A-Z]{2,5} (probe|investigation|lawsuit)\b")
    for tags in SECTOR_RISK_TAGS.values():
        for t in tags:
            assert not ticker_like.search(t), t
            assert "BTC" not in t and "DOJ" not in t


# --- Methodology footer (§2.3) -------------------------------------------------

def test_methodology_footer_uses_live_baseline_and_n():
    footer = methodology_footer(result()["pillars"])
    assert "22.0x" in footer and "14 peer" in footer


def test_methodology_footer_fallback_when_no_peer_sample():
    pillars = result()["pillars"]
    pillars["valuation"]["details"] = {"pe": {"value": 18.2}}  # no sector_baseline/peer
    footer = methodology_footer(pillars)
    assert "fallback" in footer.lower()


# --- Whole-block shape + guardrails --------------------------------------------

def test_build_block_shape_and_non_affiliation():
    block = build_valuation_transparency(result())
    assert block["non_affiliation"] == NON_AFFILIATION_NOTICE
    # The only place "price target" may appear is this negating disclaimer.
    assert block["implied_price_note"] == (
        "Each lens shown independently. FinCompass does not average these into a "
        "price target — see Methodology."
    )


def test_no_rating_or_price_target_language():
    for scores in [{}, {"safety": 3.0, "valuation": 2.0}, {"quality": 4.0}]:
        block = build_valuation_transparency(result(**scores))
        for s in _all_strings(block):
            hit = _BANNED_RE.search(s)
            assert hit is None, f"banned language {hit.group(0)!r} in: {s!r}"
