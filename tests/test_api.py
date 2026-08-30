from fastapi.testclient import TestClient

import api
from config import APP_VERSION, SCORING_ENGINE_VERSION

client = TestClient(api.app)


def test_health_and_security_headers():
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["version"] == APP_VERSION
    assert data["engine_version"] == SCORING_ENGINE_VERSION
    assert data["rate_limit_backend"] in {"sqlite", "redis", "memory"}
    assert "provider_health" in data
    assert "Content-Security-Policy" in r.headers
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_methodology_explicitly_limits_probability_interpretation():
    r = client.get("/api/methodology")
    assert r.status_code == 200
    scope = r.json()["statistics"]["probability_scope"].lower()
    assert "not probabilities of profit" in scope


def test_versioned_health_alias():
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["engine_version"] == SCORING_ENGINE_VERSION


def test_frontend_is_self_contained_and_csp_compatible():
    r = client.get("/")
    assert r.status_code == 200
    html = r.text.lower()
    assert "<style" not in html
    assert "style=" not in html
    assert "cdn.jsdelivr" not in html
    # The bundle may carry a cache-busting version query (?v=<hash>).
    assert '<script src="/static/app.js' in html
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]


def test_versioned_export_alias_exists():
    r = client.get("/api/v1/export/screener.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")


def test_cross_site_browser_api_request_is_blocked():
    r = client.get("/api/v1/health", headers={"Sec-Fetch-Site": "cross-site", "Origin": "https://example.invalid"})
    assert r.status_code == 403
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]
    assert "access-control-allow-origin" not in r.headers


def test_csv_export_neutralizes_formula_injection(monkeypatch):
    dangerous = api.ScreenerRow(
        ticker="SAFE", name="=2+2", sector="@sector", composite=7.0, label="Acceptable",
        confidence="Medium", evidence_coverage=0.8, interval_low=6.0, interval_high=8.0,
        quality=7.0, moat=7.0, safety=7.0, valuation=7.0, cycle=7.0, updated_at="2026-08-23",
    )
    monkeypatch.setattr(api, "_screener_rows", lambda *args, **kwargs: [dangerous])
    r = client.get("/api/v1/export/screener.csv")
    assert r.status_code == 200
    assert "'=2+2" in r.text
    assert "'@sector" in r.text


def test_model_lab_data_and_recipe_endpoints(monkeypatch):
    class StubStore:
        def audit(self):
            return {"rows": 12, "symbols_with_data": 2, "coverage": []}
        def fetch_history(self, limit):
            assert limit == 20
            return [{"fetch_id": "f1", "status": "complete"}]
        def raw_sources(self, limit):
            assert limit == 25
            return [{"sha256": "a" * 64, "file_name": "SPY.csv"}]
        def coverage(self, symbols=None):
            return [{"symbol": str(symbol).upper(), "rows": 0} for symbol in (symbols or [])]

    monkeypatch.setattr(api, "research_store", StubStore())
    monkeypatch.setattr(api, "research_refresh_status", lambda: {"status": "idle"})

    data = client.get("/api/v4/model-lab/data")
    assert data.status_code == 200
    body = data.json()
    assert body["audit"]["rows"] == 12
    assert body["refresh"]["status"] == "idle"
    assert body["recent_fetches"][0]["fetch_id"] == "f1"

    recipes = client.get("/api/v4/model-lab/recipes")
    assert recipes.status_code == 200
    ids = {r["recipe_id"] for r in recipes.json()["recipes"]}
    assert {"core-us-6m", "nasdaq-growth-6m", "global-proxy-6m", "cross-asset-regime-6m"} <= ids
    symbols = {r["symbol"] for r in recipes.json()["instruments"]}
    assert {"IWM", "EWJ", "MCHI", "TLT", "XIC.TO", "XIU.TO"} <= symbols


def test_model_lab_refresh_endpoint_validates_and_starts_incremental_refresh(monkeypatch):
    called = {}

    def fake_start(symbols, *, overlap_calendar_days):
        called["symbols"] = symbols
        called["overlap"] = overlap_calendar_days
        return {"started": True, "status": "running"}

    monkeypatch.setattr(api, "start_research_refresh", fake_start)
    response = client.post(
        "/api/v4/model-lab/data/refresh",
        json={"symbols": ["SPY", "QQQ"], "overlap_calendar_days": 7},
    )
    assert response.status_code == 200
    assert response.json()["started"] is True
    assert called == {"symbols": ["SPY", "QQQ"], "overlap": 7}

    invalid = client.post("/api/v4/model-lab/data/refresh", json={"overlap_calendar_days": 91})
    assert invalid.status_code == 422
