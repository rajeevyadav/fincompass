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
