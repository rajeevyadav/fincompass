"""
Tests for the in-app forecast model builder (background job + endpoints).

The heavy dataset/network/train work is never exercised here — we stub the
worker thread so only the job state machine, profile handling and the HTTP
contract are validated.
"""
import threading

import pytest
from fastapi.testclient import TestClient

import api
import services.model_builder as mb
from services.cache import cache

client = TestClient(api.app)


@pytest.fixture(autouse=True)
def _reset_build_state():
    # Start each test from a clean job slot.
    cache.update_model_build(status="idle", phase="idle")
    yield
    cache.update_model_build(status="idle", phase="idle")


class _DummyThread:
    """Stand-in for threading.Thread that never runs the worker."""
    def __init__(self, *a, **k):
        self.started = False

    def start(self):
        self.started = True


@pytest.fixture
def no_thread(monkeypatch):
    monkeypatch.setattr(mb.threading, "Thread", _DummyThread)


# --- cache job state machine ---------------------------------------------------

def test_claim_is_exclusive_while_running():
    ok1, state1 = cache.claim_model_build(10)
    assert ok1 is True and state1["status"] == "running"
    ok2, state2 = cache.claim_model_build(10)
    assert ok2 is False  # a second claim is refused while one is running


def test_update_and_get_roundtrip():
    cache.claim_model_build(5)
    cache.update_model_build(phase="train", completed=3, message="Training")
    s = cache.get_model_build()
    assert s["phase"] == "train"
    assert s["completed"] == 3
    assert s["message"] == "Training"


# --- start_model_build ---------------------------------------------------------

def test_start_launches_thread_and_claims(no_thread):
    result = mb.start_model_build(profile="standard")
    assert result["started"] is True
    assert result["status"] == "running"
    assert result["profile"] == "standard"


def test_start_normalizes_unknown_profile(no_thread):
    result = mb.start_model_build(profile="bogus")
    assert result["profile"] == "strict"


def test_start_is_refused_when_already_running(no_thread):
    first = mb.start_model_build()
    assert first["started"] is True
    second = mb.start_model_build()
    assert second["started"] is False  # slot already claimed


# --- HTTP contract -------------------------------------------------------------

def test_build_status_endpoint_reports_idle():
    r = client.get("/api/v4/forecast/build/status")
    assert r.status_code == 200
    assert r.json()["status"] in {"idle", "unknown"}


def test_build_endpoint_starts_job(monkeypatch):
    calls = {}

    def fake_start(profile="strict", tickers=None, *, recipe_id="core-us-6m"):
        calls["profile"] = profile
        calls["recipe_id"] = recipe_id
        return {"status": "running", "started": True, "profile": profile, "recipe_id": recipe_id}

    monkeypatch.setattr(api, "start_model_build", fake_start)
    r = client.post("/api/v4/forecast/build", json={"profile": "exploratory"})
    assert r.status_code == 200
    body = r.json()
    assert body["started"] is True
    assert calls["profile"] == "exploratory"
    assert calls["recipe_id"] == "core-us-6m"
    assert "request_id" in body


def test_build_endpoint_accepts_recipe_and_optional_profile(monkeypatch):
    calls = {}

    def fake_start(profile=None, tickers=None, *, recipe_id='core-us-6m'):
        calls.update(profile=profile, recipe_id=recipe_id)
        return {'status': 'running', 'started': True, 'profile': profile, 'recipe_id': recipe_id}

    monkeypatch.setattr(api, 'start_model_build', fake_start)
    r = client.post('/api/v4/forecast/build', json={'recipe_id': 'nasdaq-growth-6m'})
    assert r.status_code == 200
    assert calls == {'profile': None, 'recipe_id': 'nasdaq-growth-6m'}
    assert r.json()['recipe_id'] == 'nasdaq-growth-6m'


def test_reclaimed_build_marks_prior_experiment_interrupted(no_thread, monkeypatch):
    with cache._get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO meta (key,value) VALUES ('model_build', ?)",
            ('{"status":"running","phase":"train","experiment_id":"exp-old","recipe_id":"core-us-6m","updated_at":"2000-01-01T00:00:00+00:00"}',),
        )
    calls = []
    monkeypatch.setattr(mb.research_store, "mark_experiment_interrupted", lambda experiment_id, message: calls.append((experiment_id, message)) or True)
    result = mb.start_model_build(recipe_id="core-us-6m")
    assert result["started"] is True
    assert calls and calls[0][0] == "exp-old"
    assert "interrupted" in calls[0][1].lower()
