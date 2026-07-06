from pathlib import Path

from .model import Case


def load_cases(base_path):
    base_path = Path(base_path)

    cases = [Case(p) for p in sorted(base_path.iterdir()) if p.is_dir()]

    return cases
