from __future__ import annotations

import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import click
import structlog

from ranking.core.cache import CachePolicy
from ranking.core.cache_httpx import HttpxClientWithCache
from ranking.core.errors import ExternalRedirectError
from ranking.plugins.breizhchrono.eventdetail import (
    RaceItem,
    build_event_detail_no_info,
    extract_event_detail,
)
from ranking.plugins.breizhchrono.eventlist import (
    EVENTS_LIST_URL,
    EventListItem,
    extract_events_list,
)
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


def is_valid_url(url: str) -> bool:
    return url.startswith("http")


@click.group()
@click.option("--debug", is_flag=True, help="Enable debug logging", default=False)
@click.pass_context
def cli(ctx, debug) -> None:
    setup_logging(debug)
    ctx.obj = {
        "log": structlog.get_logger().bind(component="cli"),
        "cache": HttpxClientWithCache(
            PLUGIN_NAME,
            normalize_for_comparison=normalize_breizhchrono,
            save_extracted=True,
            base_url=EVENTS_LIST_URL,
        ),
    }


@cli.command()
@click.pass_context
def list(ctx) -> None:
    log = ctx.obj["log"]
    cache = ctx.obj["cache"]

    log.info("mode_selected", mode="event_list")
    try:
        html = cache.fetch(EVENTS_LIST_URL, CachePolicy.REFRESH_AND_CACHE)
    except RuntimeError as exc:
        log.error("fetch_error", error=str(exc))
        return

    events = extract_events_list(html)
    cache.save_extracted_json(EVENTS_LIST_URL, events)
    log.info("event_list_processed", url=EVENTS_LIST_URL)
    if not events:
        return

    # first_event_url = "https://resultats.breizhchrono.com/resultats-courses/triathlon-de-la-cote-de-granit-rose-tregastel-2026-1295405190290-19/triathlon-m"

    for event in events:
        process_event(event, cache, log)


@cli.command()
@click.option("--url", type=str, required=True, help="Process a single event by URL")
@click.pass_context
def event(ctx, url) -> None:
    log = ctx.obj["log"]
    cache = ctx.obj["cache"]

    if not is_valid_url(url):
        log.error("invalid_event_url", url=url)
        raise click.BadParameter("Invalid event URL")

    log.info("mode_selected", mode="single_event", url=url)

    event: EventListItem = {
        "name": "manual",
        "url": url.replace(EVENTS_LIST_URL, ""),
        "date_raw": "",
        "location_raw": "",
    }

    process_event(event, cache, log)


def process_event(
    event: EventListItem, cache: HttpxClientWithCache, log: structlog.BoundLogger
) -> None:
    event_url = EVENTS_LIST_URL + event["url"]
    log.info("event_processing", url=event_url, name=event["name"])
    try:
        time.sleep(1)  # be nice to the server
        event_html = cache.fetch(event_url, CachePolicy.CACHE_IF_PRESENT)
    except RuntimeError as exc:
        log.error("fetch_error", error=str(exc), event_url=event_url)
        return
    except ExternalRedirectError as exc:
        log.info(
            "event_skipped",
            reason="external_redirect",
            from_url=exc.requested_url,
            to_url=exc.final_url,
        )
        no_event_detail = build_event_detail_no_info(status="external_redirect")
        cache.save_extracted_json(event_url, no_event_detail)
        return

    event_detail = extract_event_detail(event_html)
    cache.save_extracted_json(event_url, event_detail)
    if not event_detail or "races" not in event_detail or not event_detail["races"]:
        log.warning("no_event_detail_or_races_found", event_url=event_url)
        return
    else:
        log.info("event_processed", event_url=event_url, event_name=event_detail["event_race_raw"])
        log.debug(
            "event_detail_race_sample",
            event_url=event_url,
            sample=event_detail["races"][:1],
        )

    for race in event_detail["races"]:
        process_race(race, cache, log)


def process_race(race: RaceItem, cache: HttpxClientWithCache, log: structlog.BoundLogger) -> None:
    race_url = EVENTS_LIST_URL + race["url"]

    try:
        time.sleep(1)  # be nice to the server
        race_html = cache.fetch(race_url, CachePolicy.CACHE_IF_PRESENT)
    except RuntimeError as exc:
        log.error("fetch_error", error=str(exc), race_url=race_url)
        return

    race_information = {
        "ref_computed": race["ref_computed"],
        "heat_computed": race["heat_computed"],
    }
    results = extract_race_results(race_html, race_information)
    cache.save_extracted_json(race_url, results)
    log.info("race_processed", race_url=race_url)

    if results:
        log.debug(
            "race_results_sample",
            race_url=race_url,
            sample=results[:1],
        )
    else:
        return

    result_detail_url = results[0].get("result_detail_url_computed")
    if not isinstance(result_detail_url, str) or not result_detail_url:
        log.info(
            "partial_data_available",
            missing="result_detail",
            race_url=race_url,
        )
        return

    full_result_detail_url = EVENTS_LIST_URL + result_detail_url
    try:
        time.sleep(1)  # be nice to the server
        detail_html = cache.fetch(full_result_detail_url, CachePolicy.CACHE_IF_PRESENT)
    except RuntimeError as exc:
        log.error("fetch_error", error=str(exc), result_detail_url=full_result_detail_url)
        return

    detail = extract_result_detail(detail_html)
    cache.save_extracted_json(full_result_detail_url, detail)
    log.info("result_detail_processed", url=full_result_detail_url)
