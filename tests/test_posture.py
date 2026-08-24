"""
Tests for the Investor Posture indicators (D-001). Covers the acceptance cases
from the directive plus two blocking guardrails:
  - no action verb appears in any generated indicator copy or identifier;
  - indicator labels/values are Title Case while descriptions are sentence case.
"""
import re

import pytest

from services.posture import (
    accumulation_signal,
    build_posture,
    new_position_priority,
    re_underwrite_trigger,
)

# §3 blocking guardrail: none of these (as whole words) may appear in generated
# indicator copy or identifiers. Word boundaries so "closer"/"accordingly" pass.
BANNED_VERBS = ["buy", "sell", "trim", "hold", "add", "exit", "enter", "open", "close"]
_BANNED_RE = re.compile(r"\b(" + "|".join(BANNED_VERBS) + r")\b", re.IGNORECASE)


def result(composite=8.5, confidence="High", interval=(8.0, 9.0), **pillar_scores):
    """Build a minimal scoring-result dict with the given pillar scores."""
    defaults = {"quality": 8.0, "moat": 8.0, "safety": 8.0, "valuation": 8.0, "cycle": 8.0}
    defaults.update(pillar_scores)
    return {
        "composite": composite,
        "uncertainty": {"confidence": confidence, "credible_interval": list(interval)},
        "pillars": {k: {"score": v} for k, v in defaults.items()},
    }


def _all_indicator_strings(posture):
    out = []
    for ind in posture["indicators"]:
        out.extend([ind["key"], ind["label"], ind["value"], ind["description"], ind["tone"]])
    return out


# --- §2.1 New-Position Priority ------------------------------------------------

def test_new_position_high():
    ind = new_position_priority(8.5, "High", 1.0, result()["pillars"])
    assert ind["value"] == "High"
    assert ind["tone"] == "success"


def test_new_position_low_on_weak_composite():
    ind = new_position_priority(5.0, "High", 1.0, result()["pillars"])
    assert ind["value"] == "Low"


def test_new_position_low_on_low_confidence():
    ind = new_position_priority(9.0, "Low", 1.0, result()["pillars"])
    assert ind["value"] == "Low"


def test_new_position_medium_names_actual_weak_pillar():
    pillars = result(safety=5.0)["pillars"]
    ind = new_position_priority(7.0, "Medium", 1.0, pillars)
    assert ind["value"] == "Medium"
    assert "safety" in ind["description"]


def test_new_position_medium_falls_back_to_interval():
    # No pillar below the weak floor -> mentions the wide interval instead.
    ind = new_position_priority(7.0, "Medium", 2.5, result()["pillars"])
    assert ind["value"] == "Medium"
    assert "the wide interval" in ind["description"]


# --- §2.2 Accumulation Signal --------------------------------------------------

def test_accumulation_yes():
    ind = accumulation_signal(result(quality=8.0, moat=8.0, valuation=4.0)["pillars"])
    assert ind["value"] == "Yes"


def test_accumulation_momentum_zone():
    ind = accumulation_signal(result(quality=8.0, moat=8.0, valuation=7.5)["pillars"])
    assert ind["value"] == "No — Momentum Zone"


def test_accumulation_value_trap():
    ind = accumulation_signal(result(quality=5.0, moat=5.0, valuation=4.0)["pillars"])
    assert ind["value"] == "No — Check For Value Trap"


def test_accumulation_plain_no():
    ind = accumulation_signal(result(quality=6.0, moat=6.0, valuation=6.0)["pillars"])
    assert ind["value"] == "No"


# --- §2.3 Re-Underwrite Trigger ------------------------------------------------

def test_re_underwrite_no_weak_pillar():
    ind = re_underwrite_trigger(result()["pillars"])
    assert ind["value"] == "No"
    assert ind["tone"] == "success"


def test_re_underwrite_single_weak():
    ind = re_underwrite_trigger(result(safety=5.0)["pillars"])
    assert ind["value"] == "Yes — Safety"
    assert "leverage and liquidity" in ind["description"]


def test_re_underwrite_multiple_weak_comma_titlecase():
    ind = re_underwrite_trigger(result(safety=5.0, valuation=4.0)["pillars"])
    assert ind["value"] == "Yes — Safety, Valuation"


# --- Acceptance: whole-object shape -------------------------------------------

def test_build_posture_no_weak_pillar_is_no_no():
    # A stock with no weak pillar but no clean accumulation/momentum shape.
    posture = build_posture(result(quality=6.5, moat=6.5, safety=6.5, valuation=6.5, cycle=6.5))
    by_key = {i["key"]: i for i in posture["indicators"]}
    assert by_key["accumulation_signal"]["value"] == "No"
    assert by_key["re_underwrite_trigger"]["value"] == "No"


def test_build_posture_has_three_indicators_and_caption():
    posture = build_posture(result())
    assert len(posture["indicators"]) == 3
    assert "research signals" in posture["caption"]


# --- Blocking guardrail: no action verbs across >=10 synthetic fixtures --------

def _fixtures():
    combos = []
    scores = [3.0, 4.0, 4.9, 5.0, 5.9, 6.0, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5]
    confs = ["High", "Medium", "Low"]
    for i, q in enumerate(scores):
        combos.append(result(
            composite=q,
            confidence=confs[i % 3],
            interval=(q - 1, q + 1.5),
            quality=q, moat=scores[-i - 1], safety=scores[(i + 2) % len(scores)],
            valuation=scores[(i + 4) % len(scores)], cycle=scores[(i + 1) % len(scores)],
        ))
    return combos


def test_no_action_verbs_in_generated_copy():
    fixtures = _fixtures()
    assert len(fixtures) >= 10
    for r in fixtures:
        for s in _all_indicator_strings(build_posture(r)):
            hit = _BANNED_RE.search(s)
            assert hit is None, f"banned verb {hit.group(0)!r} in generated copy: {s!r}"


def test_no_combined_verdict_field():
    # Presentation layer must not synthesize a single combined verdict/score.
    posture = build_posture(result())
    assert "verdict" not in posture
    assert "score" not in posture
    for ind in posture["indicators"]:
        assert "score" not in ind


# --- Blocking guardrail: Title-Case labels/values vs sentence-case descriptions

def _is_title_case(text):
    # Every alphabetic word starts uppercase (ignoring short joiners/em-dash).
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", text)
    joiners = {"a", "an", "and", "the", "or", "for", "of", "to", "in"}
    return all(w[0].isupper() for w in words if w.lower() not in joiners)


@pytest.mark.parametrize("r", _fixtures())
def test_label_titlecase_description_sentencecase(r):
    for ind in build_posture(r)["indicators"]:
        assert _is_title_case(ind["label"]), ind["label"]
        # Descriptions are sentence case: they contain lowercase words beyond
        # the first, so they must NOT read as Title Case.
        assert not _is_title_case(ind["description"]), ind["description"]
