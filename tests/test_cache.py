import json
from pathlib import Path

from services.cache import Cache
from config import SCORING_ENGINE_VERSION


def sample_result():
    return {
        "ticker": "ABC",
        "engine_version": SCORING_ENGINE_VERSION,
        "composite": 7.1,
        "raw_composite": 7.4,
        "label": "Acceptable",
        "pillars": {"quality": {"score": 7, "weight": 0.25, "details": {}}},
        "uncertainty": {"confidence": "Medium", "evidence_coverage": 0.7, "credible_interval": [6, 8]},
        "data_quality": {},
        "name": "ABC Inc",
        "sector": "Technology",
        "industry": "Software",
        "market_cap": 1,
        "source": "fixture",
    }


def test_score_round_trip_preserves_v2_metadata(tmp_path: Path):
    c = Cache(tmp_path / "cache.db")
    c.set_score("ABC", sample_result())
    got = c.get_score("ABC")
    assert got["engine_version"] == SCORING_ENGINE_VERSION
    assert got["uncertainty"]["confidence"] == "Medium"
    assert got["raw_composite"] == 7.4


def test_old_engine_score_is_invalidated(tmp_path: Path):
    c = Cache(tmp_path / "cache.db")
    c.set_score("ABC", sample_result())
    with c._get_conn() as conn:
        conn.execute("UPDATE scores SET engine_version='1.5.0' WHERE ticker='ABC'")
    assert c.get_score("ABC") is None
    assert c.get_all_scores() == []


def test_refresh_claim_is_shared_and_non_overlapping(tmp_path: Path):
    a = Cache(tmp_path / "cache.db")
    b = Cache(tmp_path / "cache.db")
    first, _ = a.claim_screener_refresh(72)
    second, state = b.claim_screener_refresh(72)
    assert first is True
    assert second is False
    assert state["status"] == "running"


def test_legacy_fundamentals_schema_is_not_reused(tmp_path: Path):
    c = Cache(tmp_path / "cache.db")
    with c._get_conn() as conn:
        conn.execute(
            "INSERT INTO fundamentals(ticker,data_json,source,updated_at) VALUES(?,?,?,datetime('now'))",
            ("OLD", json.dumps({"ticker": "OLD", "debt_to_equity": 151}), "legacy"),
        )
    assert c.get_fundamentals("OLD") is None
    assert c.get_all_fundamentals() == []


def test_current_fundamentals_schema_round_trip(tmp_path: Path):
    from config import DATA_SCHEMA_VERSION
    c = Cache(tmp_path / "cache.db")
    c.set_fundamentals("NEW", {"ticker": "NEW", "debt_to_equity": 1.51})
    got = c.get_fundamentals("NEW")
    assert got["_data_schema_version"] == DATA_SCHEMA_VERSION
    assert got["debt_to_equity"] == 1.51


def test_stale_model_build_claim_reports_reclaimed_experiment(tmp_path: Path):
    c = Cache(tmp_path / "cache.db")
    stale = {
        "status": "running",
        "phase": "train",
        "experiment_id": "exp-stale",
        "recipe_id": "core-us-6m",
        "updated_at": "2000-01-01T00:00:00+00:00",
    }
    with c._get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO meta (key,value) VALUES ('model_build', ?)",
            (json.dumps(stale),),
        )
    claimed, state = c.claim_model_build(5, stale_minutes=1)
    assert claimed is True
    assert state["reclaimed_experiment_id"] == "exp-stale"
    assert state["reclaimed_recipe_id"] == "core-us-6m"
    assert state["status"] == "running"
