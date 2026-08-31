"""In-process smoke checks mirroring tools/package_smoke_test.py — the behaviors a
packaged app must satisfy, restricted to the ones that do not require a live data
provider so they are deterministic on CI. The full HTTP smoke test runs against
the built package as part of release acceptance."""
from __future__ import annotations

from fastapi.testclient import TestClient

from api import app

client = TestClient(app)


def test_health_reports_bundled_assets():
    h = client.get("/api/health").json()
    assert h["status"] == "ok"
    assert h["version"]
    assert int(h.get("universe_size") or 0) > 0
    assert isinstance(h.get("forecast_registry"), dict)


def test_glossary_registry_serves():
    g = client.get("/api/v2/glossary").json()
    assert g.get("available") is True and len(g.get("terms") or []) > 0


def test_bundled_user_manual_serves():
    r = client.get("/user-manual.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"


def test_unsupported_ticker_fails_safely_not_500():
    r = client.get("/api/v4/forecast/NOTAREALTICKER999")
    assert r.status_code < 500


def test_analytics_overview_does_not_crash():
    # May degrade without a provider, but must never 5xx and must return a shape.
    r = client.get("/api/v2/analytics/AAPL/overview")
    assert r.status_code < 500
    body = r.json()
    assert ("available" in body) or ("performance" in body)
