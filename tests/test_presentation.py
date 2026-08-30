"""Tests for the Guided presentation/translation layer (static/presentation.js).

The mapping functions are pure JS; we exercise them under node and assert the
plain-language contract. Skips cleanly if node is
unavailable (the release verifier enforces node separately).
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PRES = ROOT / "static" / "presentation.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not available")


def _run(expr: str):
    """Load presentation.js into a global scope and evaluate a JS expression."""
    script = (
        "const g=globalThis;"
        + PRES.read_text(encoding="utf-8")
        + f"\nprocess.stdout.write(JSON.stringify(({expr})));"
    )
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_probability_bands_map_to_plain_language():
    target = {"benchmark": "SPY", "horizon_months": 12}
    near = _run("FCP.describeForecastProbability(0.52,false,%s)" % json.dumps(target))
    lean = _run("FCP.describeForecastProbability(0.62,false,%s)" % json.dumps(target))
    strong = _run("FCP.describeForecastProbability(0.72,false,%s)" % json.dumps(target))
    assert near["band"] == "neutral" and "even" in near["interpretation"].lower()
    assert lean["band"] == "lean-up" and "uncertainty" in lean["interpretation"].lower()
    assert strong["band"] == "signal-up"
    # symmetric downside
    down = _run("FCP.describeForecastProbability(0.30,false,%s)" % json.dumps(target))
    assert down["band"] == "signal-down" and "underperformance" in down["interpretation"].lower()


def test_abstain_forces_neutral_and_percentages_are_coarse():
    target = {"benchmark": "SPY", "horizon_months": 12}
    res = _run("FCP.describeForecastProbability(0.68,true,%s)" % json.dumps(target))
    assert res["isNeutral"] is True
    assert res["percent"] == "68%"  # whole-percent, no false precision
    assert "decision-neutral" in res["interpretation"].lower()


def test_no_recommendation_language_anywhere():
    """Guided strings must never say Buy/Sell/Hold or imply a guarantee."""
    banned = ["buy", "sell", "hold", "guaranteed", "profit", "safe to", "will beat"]
    samples = []
    for p in (0.2, 0.48, 0.55, 0.66, 0.8):
        samples.append(_run("FCP.describeForecastProbability(%s,false,{\"benchmark\":\"SPY\",\"horizon_months\":12})" % p))
    for tier in ("validated_research", "validated_market", "rejected", "fixture_only", "unknown"):
        samples.append(_run("FCP.describeModelTier(%s)" % json.dumps(tier)))
    blob = json.dumps(samples).lower()
    for word in banned:
        assert word not in blob, f"forbidden phrase surfaced: {word}"


def test_model_tier_plain_labels():
    research = _run("FCP.describeModelTier('validated_research')")
    assert research["label"] == "Research validated"
    assert research["level"] == "research"
    assert "trading signal" in research["blurb"].lower()
    fixture = _run("FCP.describeModelTier('fixture_only')")
    assert fixture["level"] == "blocked"


def test_live_state_classification():
    drift = _run("FCP.describeLiveState({gate:'active',drift:true,sourceHealth:'ok',shiftApplied:true})")
    assert drift["code"] == "BASE_ONLY_DRIFT"
    stale = _run("FCP.describeLiveState({gate:'active',drift:false,sourceHealth:'stale',shiftApplied:true})")
    assert stale["code"] == "BASE_ONLY_STALE"
    warming = _run("FCP.describeLiveState({gate:'warming',drift:false,sourceHealth:'ok',shiftApplied:false})")
    assert warming["code"] == "BASE_ONLY_WARMING"
    active = _run("FCP.describeLiveState({gate:'active',drift:false,sourceHealth:'ok',shiftApplied:true})")
    assert active["code"] == "ACTIVE"
    degraded = _run("FCP.describeLiveState({gate:'active',drift:false,sourceHealth:'ok',shiftApplied:false})")
    assert degraded["code"] == "BASE_ONLY_DEGRADED"


def test_probability_change_is_deterministic_from_shift():
    same = _run("FCP.describeProbabilityChange(0.62,0.62)")
    assert same["deltaPoints"] == 0 and "not materially" in same["sentence"].lower()
    down = _run("FCP.describeProbabilityChange(0.62,0.61)")
    assert down["deltaPoints"] == -1 and "decreased" in down["sentence"].lower()


def test_gate_failures_map_to_understandable_reasons():
    msgs = _run("FCP.describeGateFailures(['roc_auc','bootstrap_auc_low','brier_skill','walk_forward_stability'])")
    joined = " ".join(msgs).lower()
    assert "rank future winners" in joined
    assert "reference forecast" in joined
    assert "stable enough" in joined
    # deduplicated: roc_auc and bootstrap_auc_low collapse to one line
    assert len(msgs) == 3


def test_training_failure_distinguishes_notready_failed_rejected():
    nr = _run("FCP.describeTrainingFailure('NOT_READY',{})")
    tf = _run("FCP.describeTrainingFailure('TRAINING_FAILED',{})")
    rj = _run("FCP.describeTrainingFailure('REJECTED',{})")
    assert "not enough data" in nr["title"].lower()
    assert "could not complete" in tf["title"].lower()
    assert "did not pass" in rj["title"].lower()


def test_friendly_benchmark_names_replace_raw_tickers():
    assert _run("FCP.friendlyBenchmark('^GSPC')") == "S&P 500"
    assert _run("FCP.friendlyBenchmark('SPY')") == "S&P 500"
    assert _run("FCP.friendlyBenchmark('^IXIC')") == "Nasdaq Composite"
    # unknown index keeps a cleaned symbol, never the raw caret form
    assert _run("FCP.friendlyBenchmark('^ABCXYZ')") == "ABCXYZ"
    assert _run("FCP.friendlyBenchmark('')") == "its benchmark"


def test_event_categories_are_plain():
    assert _run("FCP.describeEventCategory('sec','8-K filing')") == "Company filing"
    assert _run("FCP.describeEventCategory('fred','cpi')") == "Macro environment"
    assert _run("FCP.describeEventCategory('market','price_move')") == "Price / market movement"


def test_live_state_from_snapshot_maps_warming_and_active():
    warming = _run("FCP.liveStateFromSnapshot({gate:{status:'warming'},adaptive_shift_applied:false})")
    assert warming["code"] == "BASE_ONLY_WARMING"
    active = _run("FCP.liveStateFromSnapshot({gate:{status:'active'},adaptive_shift_applied:true,source_health:{market:{status:'fresh'}}})")
    assert active["code"] == "ACTIVE"
    drift = _run("FCP.liveStateFromSnapshot({gate:{status:'active'},drift:{alert:true},adaptive_shift_applied:true})")
    assert drift["code"] == "BASE_ONLY_DRIFT"


def test_live_card_uses_guided_state_and_no_raw_jargon_up_front():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    live = js[js.index("async function runLive"):js.index("async function runLiveCompare")]
    assert "FCP.liveStateFromSnapshot" in live
    assert "FCP.friendlyBenchmark" in live
    assert "Current forecast" in live and "Original forecast" in live
    # raw internals appear only inside the technical disclosure
    tech = live[live.index('class="gf-tech"'):]
    for term in ("Log-odds contribution", "Gate status", "Settings fingerprint"):
        assert term in tech
    head = live[:live.index('class="gf-tech"')]
    for term in ("adaptive live state", "Frozen anchor", "residual", "Log-odds"):
        assert term not in head


def test_forecast_reason_codes_map_to_plain_language():
    b = _run("FCP.describeForecastReason('BENCHMARK_UNAVAILABLE',{benchmark:'^GSPC'})")
    assert "S&P 500" in b and "^GSPC" not in b
    h = _run("FCP.describeForecastReason('INSUFFICIENT_HISTORY',{available_rows:21})")
    assert "21 rows" in h
    n = _run("FCP.describeForecastReason('NO_ELIGIBLE_MODEL',{})")
    assert "validated model" in n
    # domain reason codes (Phase 4)
    ac = _run("FCP.describeForecastReason('UNSUPPORTED_ASSET_CLASS',{asset_class:'crypto',supported:['equity']})")
    assert "equity" in ac and "crypto" in ac
    bm = _run("FCP.describeForecastReason('BENCHMARK_MISMATCH',{})")
    assert "benchmark" in bm.lower()


def test_preflight_requires_all_three_flags_to_run():
    ready = _run("FCP.describeForecastPreflight({status:'ready',reasons:[],data_ready:true,computationally_compatible:true,scientifically_supported:true})")
    assert ready["canRun"] is True
    # scientifically unsupported blocks even when data + compute are fine
    unsup = _run("FCP.describeForecastPreflight({status:'unsupported',data_ready:true,computationally_compatible:true,scientifically_supported:false,reasons:[{code:'UNSUPPORTED_REGION',message_data:{region:'JP',supported:['US']}}]})")
    assert unsup["canRun"] is False
    needs = _run("FCP.describeForecastPreflight({status:'needs_data',data_ready:false,computationally_compatible:false,scientifically_supported:true,reasons:[{code:'INSUFFICIENT_HISTORY',message_data:{available_rows:10}}]})")
    assert needs["canRun"] is False and needs["action"] == "Update data"
    nomodel = _run("FCP.describeForecastPreflight({status:'unsupported',data_ready:false,computationally_compatible:false,scientifically_supported:false,reasons:[{code:'NO_ELIGIBLE_MODEL',message_data:{}}]})")
    assert nomodel["canRun"] is False and nomodel["noModel"] is True


def test_experiment_outcome_distinguishes_notready_failed_rejected_validated():
    nr = _run("FCP.describeExperimentOutcome('not_ready')")
    assert nr["kind"] == "not_ready" and "not enough data" in nr["title"].lower()
    fl = _run("FCP.describeExperimentOutcome('failed')")
    assert fl["kind"] == "failed" and "could not complete" in fl["title"].lower()
    rj = _run("FCP.describeExperimentOutcome('rejected','rejected',['roc_auc','brier_skill'])")
    assert rj["kind"] == "rejected" and len(rj["reasons"]) == 2 and "did not pass" in rj["title"].lower()
    vd = _run("FCP.describeExperimentOutcome('validated','validated_research',[])")
    assert vd["kind"] == "validated" and "activate" in vd["title"].lower()


def test_freshness_and_evidence_mappings():
    stale = _run("FCP.describeFreshness({status:'stale',training_cutoff:'2022-06-30',model_data_lag_months:50})")
    assert stale["level"] == "bad" and "out of date" in stale["label"].lower()
    cur = _run("FCP.describeFreshness({status:'current',training_cutoff:'2026-06-30'})")
    assert cur["level"] == "ok"
    strong = _run("FCP.describeEvidenceStrength({roc_auc:0.62,brier_skill:0.04})")
    assert strong["label"] == "Stronger evidence"
    limited = _run("FCP.describeEvidenceStrength({})")
    assert limited["label"] == "Limited evidence"


def test_instrument_identity_hides_provider_metadata():
    r = _run("FCP.describeInstrument({symbol:'SHOP.TO',name:'Shopify Inc.',security_type:'CA equity',exchange:'Toronto Stock Exchange',country:'Canada',region:'CA'})")
    assert r["title"] == "Shopify Inc."
    assert "Toronto Stock Exchange" in r["subtitle"] and "Canada" in r["subtitle"]


def test_guided_flow_is_plan_driven_and_one_button_live():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert "/api/v4/forecast-plan/" in js
    assert "runGuidedFlow" in js and "guidedStartLive" in js
    assert "data-start-live" in js and "data-guided-update" in js and "data-guided-train" in js
    # plain horizon selector, no trading-day codes in the guided control
    assert "How far ahead?" in html
    assert "126d" not in html and "252d" not in html
    # the primary forecast button drives the plan flow
    assert 'addEventListener("click", runGuidedFlow)' in js


def test_model_comparison_is_plain_and_hides_ids_metrics():
    cmp = _run("FCP.describeModelComparison({training_cutoff:'2022-06-30',horizon_months:12,benchmark:'^GSPC',validation_tier:'validated_research',freshness:{status:'stale'}},{training_cutoff:'2026-08-28',horizon_months:12,benchmark:'^GSPC',validation_tier:'validated_research',freshness:{status:'current'}})")
    labels = [r["label"] for r in cmp["rows"]]
    assert "Market data through" in labels and "Freshness" in labels
    blob = " ".join(r["current"] + " " + r["newer"] for r in cmp["rows"])
    assert "S&P 500" in blob and "^GSPC" not in blob            # friendly benchmark
    assert "roc_auc" not in blob.lower() and "brier" not in blob.lower()  # no raw metrics


def test_update_model_and_explicit_replacement_wiring_present():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "/api/v4/models/${encodeURIComponent(modelId)}/update" in js
    assert "guidedUpdateModel" in js and "renderCandidateComparison" in js
    assert "data-use-newer" in js and "data-keep-current" in js
    assert "Use newer model" in js and "Keep current model" in js
    # replacement activates only on explicit user action (Use newer), not on validation
    assert "guidedUseNewerModel" in js


def test_forecast_card_uses_translation_layer_and_hides_metrics_by_default():
    """The Guided Forecast card leads with meaning and demotes metrics to a disclosure."""
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert "presentation.js" in html  # loaded before app.js
    assert "FCP.describeForecastProbability" in js
    assert "FCP.describeModelTier" in js
    assert 'class="gf-tech"' in js  # Technical Details disclosure
    # metrics still present, but inside the <details> technical block
    tech_idx = js.index('class="gf-tech"')
    assert js.index("Locked-test Brier skill", tech_idx) > tech_idx
    assert js.index("Locked-test ROC AUC", tech_idx) > tech_idx
    # no recommendation language in the forecast rendering
    for word in ("Buy", "Sell", "Hold recommendation"):
        assert word not in js[js.index("async function runForecast"):js.index("async function runForecast")+4000]
