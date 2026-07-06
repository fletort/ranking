import pytest

from ranking.plugins.breizhchrono.resultdetail import extract_result_detail
from test._cases.pytest_utils import cases_parametrize


@pytest.mark.case
@cases_parametrize("test/plugins/breizhchrono/cases/data/resultdetail")
def test_extract_result_detail(case):
    result = extract_result_detail(case.load_html())

    assert result == case.expected
