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

    def fake_start(profile="strict", tickers=None):
        calls["profile"] = profile
        return {"status": "running", "started": True, "profile": profile}

    monkeypatch.setattr(api, "start_model_build", fake_start)
    r = client.post("/api/v4/forecast/build", json={"profile": "exploratory"})
    assert r.status_code == 200
    body = r.json()
    assert body["started"] is True
    assert calls["profile"] == "exploratory"
    assert "request_id" in body
