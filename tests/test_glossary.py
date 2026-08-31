"""One glossary registry feeds both the searchable Reference page and the inline
KPI tooltips, so a definition can never drift between the two."""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from api import app

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)

_REQUIRED = {"id", "term", "category", "tooltip", "plain_meaning", "why_it_matters",
             "fincompass_use", "limitation", "technical_definition", "see_also"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", re.sub(r"\([^)]*\)", "", s.lower()))).strip()


def test_glossary_file_is_well_formed():
    data = json.loads((ROOT / "resources" / "glossary.json").read_text(encoding="utf-8"))
    terms = data["terms"]
    assert len(terms) >= 50
    cats = set(data["categories"])
    ids = set()
    for t in terms:
        assert _REQUIRED <= set(t), f"{t.get('id')} missing fields"
        assert t["category"] in cats
        assert t["id"] not in ids, f"duplicate id {t['id']}"
        ids.add(t["id"])
    # see_also references must resolve.
    for t in terms:
        for ref in t["see_also"]:
            assert ref in ids, f"{t['id']} -> unknown see_also {ref}"


def test_glossary_route_serves_registry():
    r = client.get("/api/v2/glossary").json()
    assert r["available"] is True
    assert len(r["terms"]) >= 50


def test_every_analytics_kpi_label_has_a_glossary_tooltip():
    terms = client.get("/api/v2/glossary").json()["terms"]
    tips = {_norm(t["term"]) for t in terms if t.get("tooltip")}
    # The KPI labels the analytics panel renders as bare .k-label text.
    labels = ["Annualized return", "Volatility", "Sharpe", "Sortino", "Max drawdown",
              "Beta", "Historical VaR (95%)", "Conditional VaR", "EWMA volatility",
              "WACC", "Terminal growth", "Modified duration", "Convexity", "Duration",
              "Current yield", "RSI", "ROE"]
    missing = [l for l in labels if _norm(l) not in tips]
    assert not missing, f"KPIs without a glossary tooltip: {missing}"


def test_reference_page_is_wired():
    app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert 'data-page="reference"' in index
    assert 'id="glossary-search"' in index
    assert "function loadGlossary" in app_js and "function renderGlossary" in app_js
