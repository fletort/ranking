from ranking.plugins.breizhchrono.plugin import normalize_breizhchrono


def test_normalize_breizhchrono_returns_same_result_for_different_timestamps() -> None:
    content1 = (
        "modal.find('.modal-body').load('/incorrectDatasForAjaxV6-2.jsp?"
        "ts=1781598792381',{noncache: new Date().getTime()});"
    )
    content2 = (
        "modal.find('.modal-body').load('/incorrectDatasForAjaxV6-2.jsp?"
        "ts=1781598785586',{noncache: new Date().getTime()});"
    )

    normalized1 = normalize_breizhchrono("", content1)
    normalized2 = normalize_breizhchrono("", content2)

    assert normalized1 == normalized2
    assert "ts=__TS__" in normalized1
    assert "ts=__TS__" in normalized2


def test_normalize_breizhchrono_does_not_modify_content_without_timestamps() -> None:
    content = "modal.find('.modal-body').load('/somePage.jsp');"

    normalized = normalize_breizhchrono("", content)

    assert normalized == content
