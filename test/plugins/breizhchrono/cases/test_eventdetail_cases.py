import pytest

from ranking.plugins.breizhchrono.eventdetail import extract_event_detail
from test._cases.pytest_utils import cases_parametrize


@pytest.mark.case
@cases_parametrize("test/plugins/breizhchrono/cases/data/eventdetail")
def test_extract_result_detail(case):
    result = extract_event_detail(case.load_html())

    assert result == case.expected
