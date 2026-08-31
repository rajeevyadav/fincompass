"""The browser app is a static, self-contained port. Its glossary must not drift
from the single registry, and its shell must wire the engine and every desk."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_web_glossary_matches_the_registry():
    src = json.loads((ROOT / "resources" / "glossary.json").read_text(encoding="utf-8"))
    web = json.loads((ROOT / "web" / "glossary.json").read_text(encoding="utf-8"))
    assert web == src, "web/glossary.json drifted from resources/glossary.json"


def test_web_shell_wires_engine_and_desks():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    for token in ("engine.js", "app.js", 'data-tab="dcf"', 'data-tab="options"',
                  'data-tab="bonds"', 'data-tab="portfolio"', 'data-tab="reference"'):
        assert token in html, token


def test_web_app_uses_only_the_local_engine():
    # The browser app must stay self-contained: no external scripts/CDNs/fetches
    # to other origins (the glossary is same-origin).
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert "http://" not in app and "https://" not in app
    assert "cdn" not in html.lower()
    # Only same-origin relative fetch.
    assert 'fetch("glossary.json")' in app
