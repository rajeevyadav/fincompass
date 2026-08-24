"""FinCompass Bayesian evidence scoring engine v4.0.

The engine separates three things that the v1 rules mixed together:
1. metric transformation: continuous, monotonic curves (no threshold cliffs),
2. evidence aggregation: a transparent Beta conjugate model that shrinks
   sparse evidence toward neutral,
3. decision presentation: 0-10 posterior score, 90% credible interval,
   evidence coverage and confidence.

Important: the posterior is uncertainty in the FinCompass *evidence score*.
It is not a calibrated probability of future return, profit, or outperformance.
"""
from __future__ import annotations

from hashlib import sha256
from typing import Any, Dict, Iterable, List, Optional, Tuple
import math

import numpy as np

from config import (
    BAYES_CREDIBLE_LEVEL,
    BAYES_DRAWS,
    BAYES_EVIDENCE_SCALE,
    BAYES_PRIOR_ALPHA,
    BAYES_PRIOR_BETA,
    PILLAR_WEIGHTS,
    SCORE_LABELS,
    SCORING_ENGINE_VERSION,
)
from services.peers import peer_stat


def _clamp(value: float, low: float = 0.0, high: float = 10.0) -> float:
    return max(low, min(high, value))


def _safe(value, default=None):
    if value is None:
        return default
    try:
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (TypeError, ValueError):
        return default


def _interp(value: float, anchors: Iterable[Tuple[float, float]]) -> float:
    """Continuous piecewise-linear score through ordered (x, score) anchors."""
    pts = sorted((float(x), float(y)) for x, y in anchors)
    if value <= pts[0][0]:
        return _clamp(pts[0][1])
    if value >= pts[-1][0]:
        return _clamp(pts[-1][1])
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= value <= x1:
            if x1 == x0:
                return _clamp((y0 + y1) / 2)
            t = (value - x0) / (x1 - x0)
            return _clamp(y0 + t * (y1 - y0))
    return 5.0


def _blend_peer(
    absolute_score: float,
    value: float,
    stat: Optional[Dict[str, float]],
    *,
    higher_is_better: bool,
    peer_weight: float = 0.25,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """Blend absolute anchors with a robust sector-relative IQR score."""
    if not stat or stat.get("n", 0) < 5:
        return absolute_score, None
    iqr = max(float(stat.get("iqr") or 0.0), 1e-9)
    z_iqr = (value - float(stat["median"])) / iqr
    if not higher_is_better:
        z_iqr = -z_iqr
    # One IQR above/below median moves the peer score by ~2.2 points.
    peer_score = _clamp(5.0 + 2.2 * z_iqr, 1.0, 9.5)
    blended = absolute_score * (1.0 - peer_weight) + peer_score * peer_weight
    return _clamp(blended), {
        "median": stat["median"],
        "p25": stat["p25"],
        "p75": stat["p75"],
        "n": stat["n"],
        "peer_score": round(peer_score, 2),
    }


def _evidence_metric(
    details: Dict[str, Any],
    evidences: List[Dict[str, Any]],
    key: str,
    value: Optional[float],
    score: Optional[float],
    weight: float,
    peer: Optional[Dict[str, Any]] = None,
    note: Optional[str] = None,
):
    if value is None or score is None:
        return
    row: Dict[str, Any] = {"value": value, "score": round(_clamp(score), 2), "weight": weight}
    if peer:
        row["peer"] = peer
    if note:
        row["note"] = note
    details[key] = row
    evidences.append({"key": key, "score": _clamp(score), "weight": float(weight)})


def _bayes_aggregate(
    evidences: List[Dict[str, Any]],
    expected_weight: float,
    *,
    prior_alpha: float = BAYES_PRIOR_ALPHA,
    prior_beta: float = BAYES_PRIOR_BETA,
) -> Tuple[float, Dict[str, Any]]:
    """Fractional Beta update over normalized 0-1 metric evidence."""
    present_weight = sum(max(0.0, float(e["weight"])) for e in evidences)
    raw = (
        sum(float(e["score"]) * float(e["weight"]) for e in evidences) / present_weight
        if present_weight > 0 else 5.0
    )
    alpha = float(prior_alpha)
    beta = float(prior_beta)
    for e in evidences:
        w = max(0.0, float(e["weight"])) * BAYES_EVIDENCE_SCALE
        p = _clamp(float(e["score"])) / 10.0
        alpha += w * p
        beta += w * (1.0 - p)
    posterior = 10.0 * alpha / (alpha + beta)
    coverage = min(1.0, present_weight / max(expected_weight, 1e-9))
    return _clamp(posterior), {
        "raw_score": round(raw, 2),
        "posterior_alpha": round(alpha, 4),
        "posterior_beta": round(beta, 4),
        "evidence_coverage": round(coverage, 4),
        "observed_weight": round(present_weight, 3),
        "expected_weight": round(expected_weight, 3),
        "metric_count": len(evidences),
    }


def _pillar_interval(alpha: float, beta: float, rng: np.random.Generator) -> Tuple[float, float]:
    draws = rng.beta(alpha, beta, size=BAYES_DRAWS) * 10.0
    tail = (1.0 - BAYES_CREDIBLE_LEVEL) / 2.0
    lo, hi = np.quantile(draws, [tail, 1.0 - tail])
    return round(float(lo), 2), round(float(hi), 2)


def score_quality(
    fund: Dict[str, Any], peer_reference: Optional[Dict[str, Any]] = None
) -> Tuple[float, Dict[str, Any], Dict[str, float]]:
    details: Dict[str, Any] = {}
    ev: List[Dict[str, Any]] = []
    sector = str(fund.get("sector") or "")

    specs = [
        ("roe", 1.10, [(-0.20, 1.0), (0.00, 2.5), (0.04, 4.0), (0.08, 6.0), (0.12, 7.4), (0.18, 9.0), (0.25, 9.8), (0.40, 10.0)], True),
        ("roic", 1.35, [(-0.15, 1.0), (0.00, 2.5), (0.05, 5.0), (0.08, 6.4), (0.12, 8.0), (0.18, 9.5), (0.28, 10.0)], True),
        ("operating_margin", 1.00, [(-0.20, 1.0), (0.00, 2.5), (0.04, 4.0), (0.08, 6.0), (0.15, 8.0), (0.25, 9.5), (0.40, 10.0)], True),
        ("net_margin", 0.80, [(-0.20, 1.0), (0.00, 2.5), (0.03, 4.0), (0.06, 6.0), (0.12, 8.0), (0.20, 9.5), (0.35, 10.0)], True),
        ("gross_margin", 0.55, [(-0.10, 1.0), (0.10, 3.0), (0.15, 4.0), (0.25, 5.5), (0.40, 7.5), (0.55, 9.0), (0.75, 9.8)], True),
        ("fcf_margin", 0.85, [(-0.20, 1.0), (0.00, 3.0), (0.05, 5.0), (0.10, 6.5), (0.20, 8.5), (0.35, 9.5), (0.50, 10.0)], True),
        ("revenue_growth", 0.45, [(-0.30, 1.5), (-0.10, 3.0), (0.00, 5.0), (0.08, 6.5), (0.15, 8.0), (0.30, 9.0), (0.60, 9.3)], True),
        ("earnings_growth", 0.45, [(-0.50, 1.0), (-0.15, 3.0), (0.00, 5.0), (0.10, 6.5), (0.20, 8.0), (0.40, 9.0), (0.80, 9.2)], True),
    ]
    for key, weight, anchors, higher in specs:
        val = _safe(fund.get(key))
        if val is None:
            continue
        absolute = _interp(val, anchors)
        blended, peer = _blend_peer(
            absolute, val, peer_stat(peer_reference, sector, key),
            higher_is_better=higher, peer_weight=0.25,
        )
        _evidence_metric(details, ev, key, val, blended, weight, peer)

    expected = sum(s[1] for s in specs)
    score, bayes = _bayes_aggregate(ev, expected)
    if not ev:
        details["note"] = "No usable quality metrics; posterior remains at the neutral prior."
    details["bayesian"] = bayes
    return score, details, {"alpha": bayes["posterior_alpha"], "beta": bayes["posterior_beta"]}


def score_moat(
    fund: Dict[str, Any], peer_reference: Optional[Dict[str, Any]] = None
) -> Tuple[float, Dict[str, Any], Dict[str, float]]:
    """Financial durability proxy; intentionally not a claim of a true moat."""
    details: Dict[str, Any] = {
        "definition": "Financial durability proxy from returns and margin power; qualitative competitive advantages are not directly observed."
    }
    ev: List[Dict[str, Any]] = []
    sector = str(fund.get("sector") or "")

    specs = [
        ("capital_returns", "roic", 1.40, [(-0.10, 1.5), (0.00, 3.0), (0.06, 5.0), (0.09, 6.5), (0.14, 8.2), (0.20, 9.5), (0.30, 10.0)]),
        ("gross_margin_power", "gross_margin", 0.95, [(-0.10, 1.0), (0.15, 3.5), (0.30, 6.0), (0.45, 8.0), (0.60, 9.5), (0.75, 10.0)]),
        ("operating_margin", "operating_margin", 0.95, [(-0.10, 1.0), (0.00, 2.5), (0.08, 5.5), (0.15, 7.5), (0.25, 9.0), (0.40, 10.0)]),
        ("fcf_margin", "fcf_margin", 0.70, [(-0.20, 1.0), (0.00, 3.0), (0.08, 5.5), (0.15, 7.2), (0.25, 8.8), (0.40, 9.7)]),
    ]
    for out_key, source_key, weight, anchors in specs:
        val = _safe(fund.get(source_key))
        # ROE is a fallback for capital returns only if ROIC is missing.
        if source_key == "roic" and val is None:
            val = _safe(fund.get("roe"))
            source_for_peer = "roe"
            fallback_note = "ROIC unavailable; ROE used as a weaker proxy."
        else:
            source_for_peer = source_key
            fallback_note = None
        if val is None:
            continue
        absolute = _interp(val, anchors)
        blended, peer = _blend_peer(
            absolute, val, peer_stat(peer_reference, sector, source_for_peer),
            higher_is_better=True, peer_weight=0.30,
        )
        _evidence_metric(details, ev, out_key, val, blended, weight, peer, fallback_note)

    expected = sum(s[2] for s in specs)
    score, bayes = _bayes_aggregate(ev, expected)
    if not ev:
        details["note"] = "No usable durability-proxy metrics; posterior remains at the neutral prior."
    details["bayesian"] = bayes
    return score, details, {"alpha": bayes["posterior_alpha"], "beta": bayes["posterior_beta"]}


def score_safety(
    fund: Dict[str, Any], peer_reference: Optional[Dict[str, Any]] = None
) -> Tuple[float, Dict[str, Any], Dict[str, float]]:
    details: Dict[str, Any] = {}
    ev: List[Dict[str, Any]] = []
    sector = str(fund.get("sector") or "")
    financial = sector == "Financial Services"

    specs_weight = {"debt_to_equity": 1.15, "current_ratio": 0.95, "interest_coverage": 1.25}
    # Conventional industrial balance-sheet ratios do not map cleanly to banks,
    # brokers and insurers. Neutral + low confidence is more honest than a false
    # penalty/reward from structurally high leverage.
    applicable = {k: (not financial) for k in specs_weight}
    if financial:
        details["sector_adjustment"] = (
            "Conventional debt/equity, current ratio and interest coverage are not used for Financial Services; "
            "Safety remains prior-dominated unless sector-appropriate data are added."
        )

    de = _safe(fund.get("debt_to_equity"))
    if de is not None and applicable["debt_to_equity"]:
        if de > 5:
            de /= 100.0
        if de < 0:
            s = 2.0
            peer = None
            note = "Negative debt/equity can indicate negative book equity; it is not treated as low leverage."
        else:
            s = _interp(de, [(0.0, 9.8), (0.25, 9.5), (0.5, 8.3), (1.0, 6.4), (1.8, 4.4), (3.0, 2.6), (6.0, 1.5)])
            s, peer = _blend_peer(s, de, peer_stat(peer_reference, sector, "debt_to_equity"), higher_is_better=False, peer_weight=0.20)
            note = None
        _evidence_metric(details, ev, "debt_to_equity", de, s, specs_weight["debt_to_equity"], peer, note)

    cr = _safe(fund.get("current_ratio"))
    if cr is not None and applicable["current_ratio"]:
        s = _interp(cr, [(0.0, 1.0), (0.7, 2.5), (0.9, 4.0), (1.2, 6.0), (1.8, 8.0), (2.5, 9.4), (5.0, 9.7)])
        s, peer = _blend_peer(s, cr, peer_stat(peer_reference, sector, "current_ratio"), higher_is_better=True, peer_weight=0.15)
        _evidence_metric(details, ev, "current_ratio", cr, s, specs_weight["current_ratio"], peer)

    ic = _safe(fund.get("interest_coverage"))
    if ic is not None and applicable["interest_coverage"]:
        s = _interp(ic, [(-5.0, 1.0), (0.0, 1.5), (2.0, 4.0), (4.0, 6.5), (8.0, 8.5), (15.0, 9.7), (30.0, 10.0)])
        s, peer = _blend_peer(s, ic, peer_stat(peer_reference, sector, "interest_coverage"), higher_is_better=True, peer_weight=0.20)
        _evidence_metric(details, ev, "interest_coverage", ic, s, specs_weight["interest_coverage"], peer)

    expected = sum(w for k, w in specs_weight.items() if applicable[k])
    if expected <= 0:
        # Keep uncertainty broad instead of pretending a full-data neutral score.
        score, bayes = _bayes_aggregate([], 1.0)
    else:
        score, bayes = _bayes_aggregate(ev, expected)
    if not ev and not financial:
        details["note"] = "No usable balance-sheet metrics; posterior remains at the neutral prior."
    details["bayesian"] = bayes
    return score, details, {"alpha": bayes["posterior_alpha"], "beta": bayes["posterior_beta"]}


def _relative_multiple_score(relative: float) -> float:
    # Continuous version of v1's sector-relative intuition.
    return _interp(relative, [(0.25, 9.7), (0.60, 9.2), (0.80, 8.1), (1.00, 6.7), (1.25, 5.2), (1.60, 3.7), (2.00, 2.4), (3.00, 1.2)])


def score_valuation(
    fund: Dict[str, Any],
    current_price: Optional[float] = None,
    peer_reference: Optional[Dict[str, Any]] = None,
) -> Tuple[float, Dict[str, Any], Dict[str, float]]:
    details: Dict[str, Any] = {}
    ev: List[Dict[str, Any]] = []
    sector = str(fund.get("sector") or "").strip()

    weights = {"pe": 1.25, "pb": 0.70, "ev_ebitda": 1.05, "ps": 0.60}
    fallback_anchors = {
        "pb": [(0.2, 9.5), (1.2, 8.6), (2.5, 7.1), (4.5, 5.3), (7.0, 3.5), (12.0, 2.0), (25.0, 1.0)],
        "ev_ebitda": [(2.0, 9.5), (8.0, 8.8), (12.0, 7.4), (16.0, 6.1), (22.0, 4.4), (35.0, 2.5), (60.0, 1.2)],
        "ps": [(0.2, 9.2), (1.5, 8.2), (3.0, 6.7), (5.5, 4.9), (10.0, 3.0), (20.0, 1.5)],
    }

    for key in ("pe", "pb", "ev_ebitda", "ps"):
        val = _safe(fund.get(key))
        if val is None:
            continue
        if val <= 0:
            # Negative multiples normally indicate a negative denominator; they
            # are not "cheaper than zero" and should never score as a bargain.
            _evidence_metric(
                details, ev, key, val, 2.0, weights[key], None,
                "Non-positive multiple; treated as weak valuation evidence, not as a bargain."
            )
            continue

        stat = peer_stat(peer_reference, sector, key)
        if key == "pe" and stat and stat.get("median", 0) > 0:
            baseline = float(stat["median"])
            rel = val / baseline
            s = _relative_multiple_score(rel)
            peer = {
                "median": round(baseline, 4),
                "n": int(stat["n"]),
                "source": "live sector peer median",
                "relative": round(rel, 4),
            }
            _evidence_metric(details, ev, key, val, s, weights[key], peer)
            details[key]["sector_baseline"] = round(baseline, 4)
            details[key]["relative"] = round(rel, 4)
            details[key]["baseline_source"] = "live sector peer median"
        elif key == "pe":
            # No static sector P/E table: it goes stale silently. With too few
            # live peers, use a broad absolute curve and reduce evidence weight
            # so Bayesian shrinkage reflects the weaker contextual evidence.
            s = _interp(val, [(3.0, 9.2), (8.0, 8.4), (12.0, 7.5), (18.0, 6.3), (25.0, 5.1), (35.0, 4.0), (55.0, 2.8), (90.0, 1.7)])
            fallback_weight = weights[key] * 0.70
            _evidence_metric(details, ev, key, val, s, fallback_weight, None, "Absolute fallback curve used at reduced evidence weight; live sector peer sample unavailable.")
            details[key]["baseline_source"] = "reduced-weight absolute fallback"
        elif stat and stat.get("median", 0) > 0:
            baseline = float(stat["median"])
            rel = val / baseline
            s = _relative_multiple_score(rel)
            peer = {"median": baseline, "n": int(stat["n"]), "source": "live sector peer median", "relative": round(rel, 4)}
            _evidence_metric(details, ev, key, val, s, weights[key], peer)
            details[key]["relative"] = round(rel, 4)
            details[key]["baseline_source"] = "live sector peer median"
        else:
            s = _interp(val, fallback_anchors[key])
            fallback_weight = weights[key] * 0.70
            _evidence_metric(details, ev, key, val, s, fallback_weight, None, "Absolute fallback curve used at reduced evidence weight; live sector peer sample unavailable.")

    expected = sum(weights.values())
    score, bayes = _bayes_aggregate(ev, expected)
    if not ev:
        details["note"] = "No usable valuation multiples; posterior remains at the neutral prior."
    details["bayesian"] = bayes
    return score, details, {"alpha": bayes["posterior_alpha"], "beta": bayes["posterior_beta"]}


def score_cycle(
    fund: Optional[Dict[str, Any]] = None,
    macro: Optional[Dict[str, Any]] = None,
    commodity: Optional[Dict[str, Any]] = None,
) -> Tuple[float, Dict[str, Any], Dict[str, float]]:
    """Current regime evidence only; never a calendar or return forecast."""
    fund = fund or {}
    details: Dict[str, Any] = {}
    ev: List[Dict[str, Any]] = []
    sector = str(fund.get("sector") or "")

    # Absolute valuation regime (company-specific proxy for market selectivity).
    pe = _safe(fund.get("pe"))
    if pe is not None:
        if pe <= 0:
            s = 2.5
            regime = "Loss-making / non-positive P/E"
        else:
            s = _interp(pe, [(5.0, 9.0), (11.0, 8.3), (16.0, 7.3), (22.0, 6.0), (32.0, 4.5), (50.0, 3.0), (100.0, 1.8)])
            regime = "Current valuation regime"
        _evidence_metric(details, ev, "valuation_regime", pe, s, 1.00, None, regime)

    # Quality buffer as its own bounded signal rather than an additive nudge.
    roic = _safe(fund.get("roic"))
    roe = _safe(fund.get("roe"))
    capital_return = roic if roic is not None else roe
    if capital_return is not None:
        s = _interp(capital_return, [(-0.10, 2.0), (0.00, 3.5), (0.08, 5.5), (0.14, 7.0), (0.20, 8.5), (0.30, 9.5)])
        _evidence_metric(details, ev, "quality_buffer", capital_return, s, 0.55, None, "ROIC used when available; otherwise ROE.")

    if macro:
        yc = _safe(macro.get("yield_curve_10y2y"))
        if yc is not None:
            # Continuous mapping: deeply inverted = caution, positive slope = supportive.
            s = _interp(yc, [(-2.0, 2.5), (-1.0, 3.5), (0.0, 5.0), (0.5, 6.2), (1.5, 7.5), (3.0, 8.2)])
            _evidence_metric(details, ev, "yield_curve_10y2y", yc, s, 0.70, None, "Macro context, not a recession timer.")
        spread = _safe(macro.get("credit_spread_hy_oas"))
        if spread is not None:
            s = _interp(spread, [(1.5, 8.5), (3.0, 7.2), (4.0, 6.0), (6.0, 4.0), (9.0, 2.5), (15.0, 1.2)])
            _evidence_metric(details, ev, "credit_spread_hy_oas", spread, s, 0.80, None, "Lower high-yield spreads are more supportive; extremes remain risk context only.")

    if commodity:
        rel = _safe(commodity.get("relative_to_trend"))
        direction = int(commodity.get("direction", 1) or 1)
        if rel is not None and rel > 0:
            # Symmetric log distance around 1.0, direction-adjusted.
            directional = math.log(rel) * direction
            s = _interp(directional, [(-0.70, 2.5), (-0.35, 4.0), (0.0, 5.5), (0.35, 7.2), (0.70, 8.5)])
            _evidence_metric(details, ev, "commodity_context", rel, s, 0.35, None, commodity.get("name"))
            details["commodity"] = {
                "name": commodity.get("name", commodity.get("commodity", "Commodity")),
                "relative": rel,
                "direction": direction,
                "latest": commodity.get("latest"),
                "trailing_mean": commodity.get("trailing_mean"),
                "trailing_median": commodity.get("trailing_median"),
                "observations": commodity.get("observations"),
            }

    # Expected weight reflects optional macro configuration: missing company
    # evidence counts as missing; absent FRED configuration does not pretend the
    # tool observed macro data it never requested.
    expected = 1.55 + (1.50 if macro else 0.0) + (0.35 if commodity else 0.0)
    score, bayes = _bayes_aggregate(ev, expected)
    details["sector_context"] = sector or None
    details["macro_available"] = bool(macro)
    details["note"] = (
        "Cycle is a current-regime evidence pillar. It does not forecast returns or a calendar date for a recession/recovery."
    )
    details["bayesian"] = bayes
    return score, details, {"alpha": bayes["posterior_alpha"], "beta": bayes["posterior_beta"]}


def _seed_for(fundamentals: Dict[str, Any]) -> int:
    ticker = str(fundamentals.get("ticker") or fundamentals.get("name") or "unknown")
    raw = f"{SCORING_ENGINE_VERSION}:{ticker}".encode("utf-8")
    return int.from_bytes(sha256(raw).digest()[:8], "big", signed=False)


def compute_scores(
    fundamentals: Dict[str, Any],
    current_price: Optional[float] = None,
    macro: Optional[Dict[str, Any]] = None,
    commodity: Optional[Dict[str, Any]] = None,
    peer_reference: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    q, qd, qp = score_quality(fundamentals, peer_reference)
    m, md, mp = score_moat(fundamentals, peer_reference)
    s, sd, sp = score_safety(fundamentals, peer_reference)
    v, vd, vp = score_valuation(fundamentals, current_price, peer_reference)
    c, cd, cp = score_cycle(fundamentals, macro, commodity)

    raw_pillars = {"quality": (q, qd, qp), "moat": (m, md, mp), "safety": (s, sd, sp), "valuation": (v, vd, vp), "cycle": (c, cd, cp)}
    rng = np.random.default_rng(_seed_for(fundamentals))
    pillars: Dict[str, Dict[str, Any]] = {}
    draws_by_pillar: Dict[str, np.ndarray] = {}

    for key, (score, details, posterior) in raw_pillars.items():
        alpha = float(posterior["alpha"])
        beta = float(posterior["beta"])
        draws = rng.beta(alpha, beta, size=BAYES_DRAWS) * 10.0
        draws_by_pillar[key] = draws
        tail = (1.0 - BAYES_CREDIBLE_LEVEL) / 2.0
        lo, hi = np.quantile(draws, [tail, 1.0 - tail])
        details["bayesian"]["credible_interval_90"] = [round(float(lo), 2), round(float(hi), 2)]
        pillars[key] = {
            "score": round(score, 2),
            "details": details,
            "weight": PILLAR_WEIGHTS[key],
            "evidence_coverage": details["bayesian"]["evidence_coverage"],
            "credible_interval_90": [round(float(lo), 2), round(float(hi), 2)],
        }

    # Dependence matters: Quality, Durability and Cycle can reuse some of the
    # same underlying accounting evidence. Treating pillar posteriors as fully
    # independent can therefore make a composite interval look more precise
    # than the model warrants. We do not invent an empirical covariance matrix.
    # Instead, propagate two transparent dependence scenarios:
    #   1) independent pillar draws, and
    #   2) comonotonic (perfect positive rank dependence) pillar draws.
    # The reported 90% model interval is the envelope of both scenarios. This
    # is a conservative sensitivity analysis, not a claim that either scenario
    # is the true financial-data-generating process.
    independent_draws = np.zeros(BAYES_DRAWS, dtype=float)
    positive_dependence_draws = np.zeros(BAYES_DRAWS, dtype=float)
    raw_composite = 0.0
    weighted_coverage = 0.0
    for key, weight in PILLAR_WEIGHTS.items():
        pillar_draws = draws_by_pillar[key]
        independent_draws += pillar_draws * weight
        positive_dependence_draws += np.sort(pillar_draws) * weight
        raw_composite += float(pillars[key]["details"]["bayesian"]["raw_score"]) * weight
        weighted_coverage += float(pillars[key]["evidence_coverage"]) * weight

    composite = round(float(np.mean(independent_draws)), 2)
    tail = (1.0 - BAYES_CREDIBLE_LEVEL) / 2.0
    ind_lo, ind_hi = np.quantile(independent_draws, [tail, 1.0 - tail])
    dep_lo, dep_hi = np.quantile(positive_dependence_draws, [tail, 1.0 - tail])
    lo, hi = min(float(ind_lo), float(dep_lo)), max(float(ind_hi), float(dep_hi))
    width = float(hi - lo)

    p_strong_scenarios = [
        float(np.mean(independent_draws >= 8.0)),
        float(np.mean(positive_dependence_draws >= 8.0)),
    ]
    p_acceptable_scenarios = [
        float(np.mean(independent_draws >= 6.0)),
        float(np.mean(positive_dependence_draws >= 6.0)),
    ]
    p_strong = p_strong_scenarios[0]
    p_acceptable = p_acceptable_scenarios[0]

    independent_width = float(ind_hi - ind_lo)
    if weighted_coverage >= 0.80 and independent_width <= 2.0:
        confidence = "High"
    elif weighted_coverage >= 0.55 and independent_width <= 3.0:
        confidence = "Medium"
    else:
        confidence = "Low"
    # A very wide perfect-positive-dependence sensitivity envelope caps an
    # otherwise High label at Medium; do not let a convenient independence
    # assumption conceal structural overlap risk. Sparse evidence remains Low.
    if confidence == "High" and width > 3.0:
        confidence = "Medium"

    label = "Weak"
    for (low, high), lab in SCORE_LABELS.items():
        if low <= composite < high:
            label = lab
            break

    available = 0
    expected_fields = [
        "roe", "roic", "operating_margin", "net_margin", "gross_margin", "fcf_margin",
        "revenue_growth", "earnings_growth", "debt_to_equity", "current_ratio",
        "interest_coverage", "pe", "pb", "ev_ebitda", "ps",
    ]
    for key in expected_fields:
        if _safe(fundamentals.get(key)) is not None:
            available += 1
    data_completeness = available / len(expected_fields)

    return {
        "engine_version": SCORING_ENGINE_VERSION,
        "composite": composite,
        "raw_composite": round(_clamp(raw_composite), 2),
        "label": label,
        "pillars": pillars,
        "uncertainty": {
            "credible_level": BAYES_CREDIBLE_LEVEL,
            # Backward-compatible alias. The compatibility value is deliberately a
            # dependence-sensitive model-interval envelope, not a single
            # independence-assuming credible interval.
            "credible_interval": [round(lo, 2), round(hi, 2)],
            "model_interval_90": [round(lo, 2), round(hi, 2)],
            "interval_width": round(width, 2),
            "independent_interval_width": round(independent_width, 2),
            "dependence_sensitivity": {
                "independent_interval_90": [round(float(ind_lo), 2), round(float(ind_hi), 2)],
                "positive_dependence_interval_90": [round(float(dep_lo), 2), round(float(dep_hi), 2)],
                "method": "Envelope of independent and comonotonic pillar-posterior scenarios",
            },
            "probability_strong_score": round(p_strong, 4),
            "probability_strong_score_range": [round(min(p_strong_scenarios), 4), round(max(p_strong_scenarios), 4)],
            "probability_acceptable_or_better_score": round(p_acceptable, 4),
            "probability_acceptable_or_better_score_range": [round(min(p_acceptable_scenarios), 4), round(max(p_acceptable_scenarios), 4)],
            "confidence": confidence,
            "evidence_coverage": round(weighted_coverage, 4),
            "interpretation": (
                "Probabilities describe uncertainty in the FinCompass evidence score, not future investment returns. "
                "Ranges show sensitivity to unknown positive dependence between overlapping pillars."
            ),
        },
        "data_quality": {
            "metric_completeness": round(data_completeness, 4),
            "metrics_available": available,
            "metrics_expected": len(expected_fields),
            "source": fundamentals.get("source", "unknown"),
            "fetched_at": fundamentals.get("fetched_at"),
        },
        "source": fundamentals.get("source", "unknown"),
        "name": fundamentals.get("name"),
        "sector": fundamentals.get("sector"),
        "industry": fundamentals.get("industry"),
        "market_cap": fundamentals.get("market_cap"),
    }


def get_label_color(score: float) -> str:
    if score >= 8.0:
        return "#16a34a"
    if score >= 6.0:
        return "#ca8a04"
    return "#dc2626"


def generate_thesis(result: Dict[str, Any]) -> str:
    """Generate a short, uncertainty-aware plain-English thesis card."""
    name = result.get("name") or result.get("ticker", "This company")
    composite = float(result["composite"])
    label = result["label"]
    pillars = result["pillars"]
    strengths: List[str] = []
    weaknesses: List[str] = []

    q = pillars["quality"]["score"]
    m = pillars["moat"]["score"]
    s = pillars["safety"]["score"]
    v = pillars["valuation"]["score"]
    c = pillars["cycle"]["score"]

    if q >= 7.5: strengths.append("strong profitability and return evidence")
    elif q < 5.0: weaknesses.append("weak profitability evidence")
    if m >= 7.5: strengths.append("strong financial durability proxies")
    elif m < 5.0: weaknesses.append("limited durability proxies")
    if s >= 7.5: strengths.append("strong balance-sheet evidence")
    elif s < 5.0: weaknesses.append("balance-sheet concerns or weak evidence")
    if v >= 7.5: strengths.append("attractive valuation evidence")
    elif v < 5.0: weaknesses.append("demanding or weak valuation evidence")
    if c >= 7.0: strengths.append("supportive current-regime context")
    elif c < 5.0: weaknesses.append("less supportive current-regime context")

    thesis = f"**{name}** has a FinCompass evidence score of **{composite:.2f}** ({label}). "
    if strengths:
        thesis += "Positives: " + ", ".join(strengths) + ". "
    if weaknesses:
        thesis += "Watch-outs: " + ", ".join(weaknesses) + ". "

    unc = result.get("uncertainty") or {}
    interval = unc.get("credible_interval")
    confidence = unc.get("confidence")
    if interval and confidence:
        thesis += f"Model confidence is {confidence.lower()} with a 90% evidence-score interval of {interval[0]:.2f}-{interval[1]:.2f}. "
    thesis += "Use this as a research triage signal, not a buy/sell recommendation or return forecast."
    return thesis
