from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

import api
from realtime import REALTIME_ENGINE_VERSION
from realtime.adaptive import FEATURE_NAMES, evaluate_gate, initial_state, predict, state_key, update_state, vectorize
from realtime.config import PROFILES, RealtimeSettings, settings_from_dict
from realtime.features import build_adaptive_features, exp_decay, provider_verified_recently
from realtime.registry import load_adaptive_artifact, save_adaptive_artifact
from realtime.store import RealtimeStore

client = TestClient(api.app)


def _store(tmp_path):
    return RealtimeStore(tmp_path / "rt.sqlite")


def _settings(**kw):
    base=RealtimeSettings(min_matured_observations=2,min_unique_observation_dates=2,min_observation_span_days=1,online_eval_window=5,drift_min_samples=99)
    return RealtimeSettings(**{**base.to_dict(),**kw}).validate()


def _perf_row(d, pa, pp, y):
    import math
    return {"observation_date":d,"anchor_probability":pa,"adaptive_probability":pp,"label":y,"brier_anchor":(pa-y)**2,"brier_adaptive":(pp-y)**2,"log_anchor":-(y*math.log(pa)+(1-y)*math.log(1-pa)),"log_adaptive":-(y*math.log(pp)+(1-y)*math.log(1-pp))}


def test_realtime_profiles_validate():
    assert set(PROFILES)=={"balanced","responsive","conservative"}
    assert all(v.validate() for v in PROFILES.values())


def test_realtime_settings_reject_unknown_field():
    try: settings_from_dict({"made_up":1})
    except ValueError: pass
    else: assert False


def test_realtime_settings_reject_string_boolean():
    try: settings_from_dict({"enable_online_learning":"false"})
    except ValueError: pass
    else: assert False


def test_settings_fingerprint_changes_with_learning_semantics():
    a=settings_from_dict({},"balanced"); b=settings_from_dict({"process_noise":0.002},"balanced")
    assert a.fingerprint()!=b.fingerprint()


def test_state_key_binds_model_and_settings():
    a=settings_from_dict({},"balanced"); b=settings_from_dict({},"responsive")
    assert state_key("m1",a)!=state_key("m1",b)
    assert state_key("m1",a)!=state_key("m2",a)


def test_event_decay_halves_at_half_life():
    assert abs(exp_decay(36*3600,36)-0.5)<1e-9


def test_provider_verification_staleness():
    now=datetime(2026,1,2,tzinfo=timezone.utc)
    check={"last_success_at":(now-timedelta(seconds=30)).isoformat()}
    assert provider_verified_recently(check,60,now)
    assert not provider_verified_recently(check,20,now)


def test_stale_sec_and_macro_features_are_zeroed():
    now=datetime(2026,1,5,tzinfo=timezone.utc); s=_settings(max_sec_staleness_seconds=60,max_macro_staleness_seconds=60)
    old=(now-timedelta(hours=3)).isoformat()
    features=build_adaptive_features(None,{"source_time":old,"payload":{"form":"8-K"}},{"source_time":old,"payload":{"yield_curve_change":1,"hy_spread_change":1}},None,{"last_success_at":old},{"last_success_at":old},s,now)
    assert features["sec_is_8k_6k"]==0
    assert features["yield_curve_change"]==0


def test_vector_contract_is_fixed_and_finite():
    x=vectorize({"market_return_1d":float("nan"),"sec_is_10q":1})
    assert len(x)==len(FEATURE_NAMES)
    assert np.isfinite(x).all()


def test_candidate_shift_is_bounded():
    s=_settings(adaptive_max_logit_shift=0.2); st=initial_state(s); st["mean"]=[100.0]*len(FEATURE_NAMES)
    p=predict(0.5,{k:1 for k in FEATURE_NAMES},st,s)
    assert abs(p["bounded_logit_shift"])<=0.2+1e-12


def test_rank_one_update_keeps_covariance_symmetric_positive():
    s=_settings(); st=initial_state(s); new,_=update_state(0.55,{"market_return_1d":0.2,"sec_is_8k_6k":1},1,st,s)
    cov=np.asarray(new["covariance"])
    assert np.allclose(cov,cov.T)
    assert np.linalg.eigvalsh(cov).min()>0


def test_gate_requires_temporal_breadth():
    s=_settings(); rows=[_perf_row("2026-01-01",0.5,0.4,0),_perf_row("2026-01-01",0.5,0.4,0)]
    gate=evaluate_gate(rows,{"alert":False},s)
    assert not gate["active"]
    assert not gate["checks"]["min_unique_observation_dates"]


def test_gate_can_activate_when_adaptive_is_better():
    s=_settings(max_ece=0.25); rows=[_perf_row("2026-01-01",0.6,0.2,0),_perf_row("2026-01-03",0.4,0.8,1)]
    gate=evaluate_gate(rows,{"alert":False},s)
    assert gate["active"]
    assert gate["metrics"]["brier_improvement"]>0


def test_store_event_dedup_preserves_first_event(tmp_path):
    db=_store(tmp_path); e={"event_id":"e1","source":"sec","scope_key":"AAPL","event_type":"filing","ticker":"AAPL","source_time":"2026-01-01T00:00:00+00:00","received_at":"2026-01-01T00:01:00+00:00","payload":{"form":"8-K"}}
    assert db.add_event(e); assert not db.add_event(e); assert len(db.list_events("AAPL"))==1


def test_provider_check_updates_without_mutating_event(tmp_path):
    db=_store(tmp_path); e={"event_id":"e1","source":"sec","scope_key":"AAPL","event_type":"filing","ticker":"AAPL","source_time":"2026-01-01T00:00:00+00:00","received_at":"2026-01-01T00:01:00+00:00","payload":{}}
    db.add_event(e); db.record_provider_check("sec","AAPL",True,checked_at="2026-01-02T00:00:00+00:00")
    assert db.latest_event("sec","AAPL")["received_at"]==e["received_at"]
    assert db.provider_check("sec","AAPL")["last_checked_at"].startswith("2026-01-02")


def test_pending_label_uniqueness_includes_settings_lineage(tmp_path):
    db=_store(tmp_path); a=settings_from_dict({},"balanced"); b=settings_from_dict({},"responsive")
    def row(fp,settings,lid): return {"label_id":lid,"ticker":"AAPL","benchmark":"SPY","base_model_id":"m1","settings_fingerprint":fp,"settings":settings.to_dict(),"observation_ts":"2026-01-01T00:00:00+00:00","observation_date":"2026-01-01","earliest_maturity":"2026-02-01","anchor_probability":0.5,"candidate_probability":0.55,"features":{},"stock_entry_price":100,"benchmark_entry_price":500,"horizon_trading_days":21,"excess_return_threshold":0}
    assert db.upsert_pending_label(row(a.fingerprint(),a,"a"))
    assert not db.upsert_pending_label(row(a.fingerprint(),a,"a2"))
    assert db.upsert_pending_label(row(b.fingerprint(),b,"b"))


def test_performance_window_is_defined_by_dates_not_rows(tmp_path):
    db=_store(tmp_path)
    for i in range(4): db.add_performance("s","2026-01-01",0.5,0.4,0)
    db.add_performance("s","2026-01-02",0.5,0.4,0); db.add_performance("s","2026-01-03",0.5,0.4,0)
    rows=db.performance_recent_dates("s",2)
    assert {r["observation_date"] for r in rows}=={"2026-01-02","2026-01-03"}


def test_external_payload_is_redacted_from_public_event_view(tmp_path):
    db=_store(tmp_path); db.add_event({"event_id":"x","source":"external","scope_key":"AAPL","event_type":"news","ticker":"AAPL","source_time":"2026-01-01T00:00:00+00:00","payload":{"licensed":"secret"},"external_payload":True,"context_only":True})
    public=db.list_events("AAPL",public=True)[0]; private=db.list_events("AAPL",public=False)[0]
    assert public["payload"].get("redacted") is True
    assert private["payload"]["licensed"]=="secret"


def test_adaptive_registry_fixture_cannot_load_as_live(tmp_path):
    s=_settings(); st=initial_state(s); m=save_adaptive_artifact("anchor",s,st,{"passed":True},tier="fixture_only",name="fixture",root=tmp_path)
    live,manifest=load_adaptive_artifact(adaptive_id=m["adaptive_id"],minimum_tier="validated_research",root=tmp_path)
    assert live is None and manifest is None


def test_v4_settings_schema_endpoint():
    r=client.get("/api/v4/settings/schema")
    assert r.status_code==200
    body=r.json()
    assert "forecast" in body and "realtime" in body
    assert body["realtime"]["engine_version"] == REALTIME_ENGINE_VERSION


def test_v4_realtime_status_hides_scope_keys():
    r=client.get("/api/v4/realtime/status")
    assert r.status_code==200
    text=r.text
    assert "privacy_note" in text
    assert "scope_key" not in text


def test_v4_live_fails_closed_without_validated_anchor():
    r=client.get("/api/v4/realtime/AAPL")
    assert r.status_code==409
    assert r.json()["available"] is False


def test_v4_methodology_separates_fresh_prediction_from_parameter_update():
    r=client.get("/api/v4/methodology")
    assert r.status_code==200
    realtime=r.json()["realtime"]
    assert "after the original target matures" in realtime["learning_rule"]
    assert REALTIME_ENGINE_VERSION==realtime["engine_version"]


def test_date_balanced_ece_is_invariant_to_same_date_duplication():
    from realtime.adaptive import expected_calibration_error
    base = [
        _perf_row("2026-01-01", 0.5, 0.2, 0),
        _perf_row("2026-01-02", 0.5, 0.8, 1),
    ]
    duplicated = [base[0]] * 20 + [base[1]]
    assert abs(expected_calibration_error(base) - expected_calibration_error(duplicated)) < 1e-12


def test_exact_horizon_endpoint_uses_hth_common_session_and_asof_cutoff(monkeypatch):
    import pandas as pd
    import services.realtime_service as rt

    idx = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"])
    stock = pd.DataFrame({"Close": [100, 101, 102, 103, 104]}, index=idx)
    bench = pd.DataFrame({"Close": [200, 201, 202, 203, 204]}, index=idx)

    def fake_history(ticker, period):
        assert period == "max"
        return stock if ticker == "AAA" else bench

    monkeypatch.setattr(rt, "get_price_history_cached", fake_history)
    # H=3 after Jan 2 -> Jan 7, not the latest available Jan 8 close.
    out = rt._aligned_horizon_closes("AAA", "SPY", "2026-01-02", 3, "2026-01-08")
    assert out == {"target_date": "2026-01-07", "stock_close": 103.0, "benchmark_close": 203.0}
    # If processed before the H-th session exists, the label remains pending.
    assert rt._aligned_horizon_closes("AAA", "SPY", "2026-01-02", 3, "2026-01-06") is None


def test_sec_event_prefers_acceptance_timestamp(monkeypatch):
    import realtime.providers as providers

    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        def ticker_to_cik(self): return {"AAPL": 320193}
        def _json(self, *args, **kwargs):
            return {"filings": {"recent": {
                "form": ["8-K"],
                "filingDate": ["2026-08-20"],
                "acceptanceDateTime": ["2026-08-20T14:31:22.000Z"],
                "accessionNumber": ["0001"],
                "primaryDocument": ["x.htm"],
            }}}

    monkeypatch.setenv("SEC_USER_AGENT", "Researcher test@example.com")
    monkeypatch.setattr(providers, "SecClient", FakeClient)
    event = providers.fetch_sec_event("AAPL")
    assert event["source_time"].startswith("2026-08-20T14:31:22")
    assert event["payload"]["acceptance_datetime"] == "2026-08-20T14:31:22.000Z"
