import pytest

from .loader import load_cases


def cases_parametrize(path, *, filter_fn=None):
    def decorator(test_func):
        cases = load_cases(path)

        if filter_fn:
            cases = [c for c in cases if filter_fn(c)]

        return pytest.mark.parametrize("case", cases, ids=lambda c: c.id)(test_func)

    return decorator
