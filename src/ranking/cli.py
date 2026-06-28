from __future__ import annotations

import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import click
import structlog

from ranking.core.cache import CachePolicy
from ranking.core.cache_httpx import CacheHttpx
from ranking.plugins.breizhchrono.eventdetail import extract_event_detail
from ranking.plugins.breizhchrono.eventlist import EVENTS_LIST_URL, extract_events_list
from ranking.plugins.breizhchrono.plugin import normalize_breizhchrono
from ranking.plugins.breizhchrono.raceresults import extract_race_results
from ranking.plugins.breizhchrono.resultdetail import extract_result_detail

PLUGIN_NAME = "breizhchrono"


def setup_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO

    # Créer dossier .log
    log_dir = Path(".log")
    log_dir.mkdir(exist_ok=True)

    # Nom fichier avec timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = log_dir / f"run-{timestamp}.log"

    # --- Handlers ---

    # Console handler (avec couleurs)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    # File handler (sans couleurs)
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(level)

    # Root logger
    logging.basicConfig(
        level=level,
        handlers=[console_handler, file_handler],
        format="%(message)s",
    )

    # --- Structlog config ---
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.format_exc_info,
            # Différenciation console / fichier
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
    )

    # --- Formatters ---

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(colors=True)
    )

    file_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(colors=False)
    )

    console_handler.setFormatter(formatter)
    file_handler.setFormatter(file_formatter)


@click.command()
@click.option("--debug", is_flag=True, help="Enable debug logging", default=False)
def main(debug: bool) -> None:
    setup_logging(debug)
    log = structlog.get_logger().bind(component="cli")
    cache = CacheHttpx(
        PLUGIN_NAME, normalize_for_comparison=normalize_breizhchrono, save_extracted=True
    )

    try:
        html = cache.fetch(EVENTS_LIST_URL, CachePolicy.REFRESH_AND_CACHE)
    except RuntimeError as exc:
        log.error("fetch_error", error=str(exc))
        return

    events = extract_events_list(html)
    cache.save_extracted_json(EVENTS_LIST_URL, events)
    log.info("extracted_events", count=len(events), events=events)
    if not events:
        return

    # first_event_url = "https://resultats.breizhchrono.com/resultats-courses/triathlon-de-la-cote-de-granit-rose-tregastel-2026-1295405190290-19/triathlon-m"

    for event in events:
        event_url = EVENTS_LIST_URL + event["url"]
        log.info("event_processing", url=event_url, name=event["name"])
        try:
            time.sleep(1)  # be nice to the server
            event_html = cache.fetch(event_url, CachePolicy.CACHE_IF_PRESENT)
        except RuntimeError as exc:
            log.error("fetch_error", error=str(exc), event_url=event_url)
            continue

        event_detail = extract_event_detail(event_html)
        cache.save_extracted_json(event_url, event_detail)
        log.info("extracted_event_detail", event_url=event_url, event_detail=event_detail)

        if not event_detail or "races" not in event_detail or not event_detail["races"]:
            log.warning("no_event_detail_or_races_found", event_url=event_url)
            continue

        first_race_url = EVENTS_LIST_URL + event_detail["races"][0]["url"]

        try:
            time.sleep(1)  # be nice to the server
            race_html = cache.fetch(first_race_url, CachePolicy.CACHE_IF_PRESENT)
        except RuntimeError as exc:
            log.error("fetch_error", error=str(exc))
            return

        first_race = event_detail["races"][0]
        race_information = {
            "ref_computed": first_race["ref_computed"],
            "heat_computed": first_race["heat_computed"],
        }
        results = extract_race_results(race_html, race_information)
        cache.save_extracted_json(first_race_url, results)
        log.info("extracted_race_results", results=results)

        if not results:
            return

        result_detail_url = results[0].get("result_detail_url_computed")
        if not isinstance(result_detail_url, str) or not result_detail_url:
            log.error("no_computed_result_detail_url_found")
            return

        full_result_detail_url = EVENTS_LIST_URL + result_detail_url
        try:
            time.sleep(1)  # be nice to the server
            detail_html = cache.fetch(full_result_detail_url, CachePolicy.CACHE_IF_PRESENT)
        except RuntimeError as exc:
            log.error("fetch_error", error=str(exc))
            return

        detail = extract_result_detail(detail_html)
        cache.save_extracted_json(full_result_detail_url, detail)
        log.info("extracted_result_detail", result_detail=detail)


if __name__ == "__main__":
    main()
