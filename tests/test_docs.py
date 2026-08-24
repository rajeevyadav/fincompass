"""The bundled help/legal pages must render as styled HTML, not raw Markdown."""
import pytest
from fastapi.testclient import TestClient

import api

client = TestClient(api.app)

DOC_ROUTES = ["/help", "/legal/disclaimer", "/legal/terms", "/legal/privacy"]


@pytest.mark.parametrize("path", DOC_ROUTES)
def test_doc_route_renders_html(path):
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    assert body.lstrip().lower().startswith("<!doctype html")
    assert "<h1>" in body                      # markdown heading was converted
    assert "/static/app.css" in body           # CSP-safe external stylesheet
    assert "# " not in body                     # no raw markdown heading leaked


def test_md_to_html_basics():
    html = api._md_to_html("# Title\n\n- a\n- b\n\n**bold** and `code`")
    assert "<h1>Title</h1>" in html
    assert "<ul>" in html and "<li>a</li>" in html
    assert "<strong>bold</strong>" in html
    assert "<code>code</code>" in html


def test_md_to_html_escapes_html():
    # Raw HTML/script in a doc must be escaped, never passed through.
    html = api._md_to_html("<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
