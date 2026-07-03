# ranking/plugins/breizhchrono/extractors.py

from collections.abc import Callable
from typing import Any, TypeAlias

from ranking.plugins.breizhchrono.eventdetail import extract_event_detail
from ranking.plugins.breizhchrono.eventlist import extract_events_list
from ranking.plugins.breizhchrono.raceresults import extract_race_results
from ranking.plugins.breizhchrono.resultdetail import extract_result_detail

Extractor: TypeAlias = Callable[[str], Any]

EXTRACTORS: dict[str, Extractor] = {
    "event_list": extract_events_list,
    "event_detail": extract_event_detail,
    "race_results": extract_race_results,
    "result_detail": extract_result_detail,
}
