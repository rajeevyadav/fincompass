from html.parser import HTMLParser
from pathlib import Path


class Inspector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.controls = []
        self.labelledby = []
        self.inline_handlers = []
        self.inline_styles = []

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if data.get("id"):
            self.ids.append(data["id"])
        if data.get("aria-controls"):
            self.controls.extend(data["aria-controls"].split())
        if data.get("aria-labelledby"):
            self.labelledby.extend(data["aria-labelledby"].split())
        for key, _ in attrs:
            if key and key.lower().startswith("on"):
                self.inline_handlers.append(key)
        if "style" in data:
            self.inline_styles.append(data["style"])


def test_static_html_has_unique_accessibility_targets_and_no_inline_code():
    parser = Inspector()
    parser.feed(Path("static/index.html").read_text(encoding="utf-8"))
    assert len(parser.ids) == len(set(parser.ids))
    ids = set(parser.ids)
    assert all(target in ids for target in parser.controls)
    assert all(target in ids for target in parser.labelledby)
    assert parser.inline_handlers == []
    assert parser.inline_styles == []


def test_model_lab_ui_exposes_data_recipe_experiment_and_explicit_activation_workflow():
    html = Path("static/index.html").read_text(encoding="utf-8")
    js = Path("static/app.js").read_text(encoding="utf-8")
    for element_id in [
        "model-lab-panel", "research-data-status", "btn-update-research-data",
        "build-recipe", "recipe-readiness", "btn-build-model", "model-lab-experiments", "btn-refresh-experiments",
    ]:
        assert f'id="{element_id}"' in html
    assert "validated candidate is never made live automatically" in html
    assert "/api/v4/model-lab/data/refresh" in js
    assert "/api/v4/model-lab/experiments/" in js
    assert "Can FinCompass train this model?" in js
    assert "/readiness" in js
    # The "not auto-activated" guarantee now lives in the presentation layer.
    presentation = Path("static/presentation.js").read_text(encoding="utf-8")
    assert "Not active until you explicitly activate it." in presentation
    assert "Model built and activated" not in js


def test_guided_and_research_modes_expose_simple_and_advanced_workflows():
    html = Path("static/index.html").read_text(encoding="utf-8")
    js = Path("static/app.js").read_text(encoding="utf-8")
    for element_id in [
        "experience-mode", "btn-guided-update-train", "guided-model-message",
        "btn-live-compare", "live-compare-out", "btn-forecast-compare-models",
    ]:
        assert f'id="{element_id}"' in html
    assert "Forecast in three steps" in html
    assert "Compare all conditions" in html
    assert "/api/v4/realtime/${encodeURIComponent(ticker)}/compare" in js
    assert "process-matured" in js
    assert "realtime_engine_version" in js
