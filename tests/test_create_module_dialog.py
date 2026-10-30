import re
from html.parser import HTMLParser
from pathlib import Path


class DialogFields(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def test_create_module_title_selector_points_to_input():
    source = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")
    modal = re.search(r"function appModal\(.*?(?=\nfunction addDeleteButtons)", source, re.S).group()
    create = re.search(r"function createModule\(.*?(?=\nfunction )", source, re.S).group()

    heading_id = re.search(r"setAttribute\('aria-labelledby','([^']+)'\)", modal).group(1)
    input_id = re.search(r'<input id="([^"]+)"', create).group(1)
    selector_id = re.search(r"querySelector\('#([^']+)'\)\.value\.trim\(\)", create).group(1)

    fields = DialogFields()
    fields.feed(modal)
    fields.feed(create)
    matches = [(tag, attrs) for tag, attrs in fields.elements if attrs.get("id") == selector_id]

    assert selector_id == input_id
    assert heading_id != selector_id
    assert len(matches) == 1
    assert matches[0][0] == "input"
