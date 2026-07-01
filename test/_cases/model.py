import json
from pathlib import Path

import yaml


class Case:
    def __init__(self, path: Path):
        self.path = path
        self.meta = yaml.safe_load((path / "meta.yaml").read_text())

        self.id = self.meta["id"]

    def load_html(self):
        return (self.path / "input.html").read_text()

    @property
    def expected(self):
        return json.loads((self.path / "expected.json").read_text())
