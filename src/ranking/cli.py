from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import click
import structlog

from ranking.core.crawler import CachePolicy, HttpxCrawlerRuntime
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
from ranking.plugins.breizhchrono.extractors import EXTRACTORS
from ranking.plugins.breizhchrono.plugin import normalize_breizhchrono
from ranking.plugins.breizhchrono.raceresults import extract_race_results
from ranking.plugins.breizhchrono.resultdetail import extract_result_detail

PLUGIN_NAME = "breizhchrono"


@dataclass
class CrawlSummary:
    started_at: float
    sleep_duration_seconds: float = 0
    events_processed_count: int = 0
    events_failed_count: int = 0
    events_document_downloaded_count: int = 0
    events_document_failed_count: int = 0
    races_processed_count: int = 0
    races_document_downloaded_count: int = 0
    races_document_failed_count: int = 0
    races_external_count: int = 0
    races_failed_count: int = 0
    results_processed_count: int = 0
    results_failed_count: int = 0


def sleep(seconds: int | float, summary: CrawlSummary | None = None) -> None:
    time.sleep(seconds)
    if summary is not None:
        summary.sleep_duration_seconds += seconds


def log_crawl_summary(
    log: structlog.BoundLogger, summary: CrawlSummary, cache: HttpxCrawlerRuntime
) -> None:
    wall_duration_seconds = int(time.monotonic() - summary.started_at)
    sleep_duration_seconds = int(summary.sleep_duration_seconds)
    processing_duration_seconds = max(0, wall_duration_seconds - sleep_duration_seconds)
    log.info(
        "crawl_summary",
        wall_duration_seconds=wall_duration_seconds,
        sleep_duration_seconds=sleep_duration_seconds,
        processing_duration_seconds=processing_duration_seconds,
        events_processed_count=summary.events_processed_count,
        events_failed_count=summary.events_failed_count,
        events_document_downloaded_count=summary.events_document_downloaded_count,
        events_document_failed_count=summary.events_document_failed_count,
        races_processed_count=summary.races_processed_count,
        races_external_count=summary.races_external_count,
        races_failed_count=summary.races_failed_count,
        races_document_downloaded_count=summary.races_document_downloaded_count,
        races_document_failed_count=summary.races_document_failed_count,
        results_processed_count=summary.results_processed_count,
        results_failed_count=summary.results_failed_count,
        cache_hits_count=cache.cache_hits,
        cache_misses_count=cache.cache_misses,
    )


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
        "cache": HttpxCrawlerRuntime(
            PLUGIN_NAME,
            normalize_for_comparison=normalize_breizhchrono,
            save_extracted=True,
            base_url=EVENTS_LIST_URL,
        ),
    }


@cli.command()
@click.option(
    "--page-event-max",
    type=int,
    default=None,
    help="Maximum number of event list pages to process",
)
@click.option(
    "--page-race-max",
    type=int,
    default=None,
    help="Maximum number of race result pages to process per race",
)
@click.pass_context
def list(ctx, page_event_max, page_race_max) -> None:
    log = ctx.obj["log"]
    cache = ctx.obj["cache"]
    summary = CrawlSummary(started_at=time.monotonic())

    log.info("mode_selected", mode="event_list")

    current_url = EVENTS_LIST_URL
    pages_processed = 0

    try:
        while True:
            try:
                html = cache.fetch(current_url, CachePolicy.REFRESH_AND_CACHE)
            except RuntimeError as exc:
                log.error("fetch_error", error=str(exc))
                return

            result = extract_events_list(html)
            events = result["events"]
            cache.save_extracted_json(current_url, result)
            log.info("event_list_processed", url=current_url)
            pages_processed += 1

            for event in events:
                process_event(event, cache, log, page_race_max, summary=summary)

            next_url = result["next_url"]
            if not next_url:
                break
            if page_event_max is not None and pages_processed >= page_event_max:
                log.info("event_list_max_pages_reached", pages=pages_processed)
                break

            current_url = urljoin(EVENTS_LIST_URL, next_url)
    finally:
        log_crawl_summary(log, summary, cache)


@cli.command()
@click.option("--url", type=str, required=True, help="Process a single event by URL")
@click.option(
    "--page-race-max",
    type=int,
    default=None,
    help="Maximum number of race result pages to process per race",
)
@click.pass_context
def event(ctx, url, page_race_max) -> None:
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

    process_event(event, cache, log, page_race_max)


def process_event(
    event: EventListItem,
    cache: HttpxCrawlerRuntime,
    log: structlog.BoundLogger,
    page_race_max: int | None = None,
    summary: CrawlSummary | None = None,
) -> None:
    event_url = EVENTS_LIST_URL + event["url"]
    log.info("event_processing", url=event_url, name=event["name"])
    try:
        sleep(1, summary)  # be nice to the server
        event_html = cache.fetch(event_url, CachePolicy.CACHE_IF_PRESENT)
    except RuntimeError as exc:
        if summary is not None:
            summary.events_failed_count += 1
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
        if summary is not None:
            summary.events_processed_count += 1
        log.info("event_processed", event_url=event_url, event_name=event_detail["event_race_raw"])
        log.debug(
            "event_detail_race_sample",
            event_url=event_url,
            sample=event_detail["races"][:1],
        )

    # Download optionals event documents
    if "documents" in event_detail and event_detail["documents"]:
        for document in event_detail["documents"]:
            document_url = document["url"]
            try:
                sleep(1, summary)  # be nice to the server
                cache.download(document_url)
                if summary is not None:
                    summary.events_document_downloaded_count += 1
                log.info("document_downloaded", event_document_url=document_url)
            except RuntimeError as exc:
                if summary is not None:
                    summary.events_document_failed_count += 1
                log.error("download_error", error=str(exc), event_document_url=document_url)

    for race in event_detail["races"]:
        process_race(race, cache, log, page_race_max, summary=summary)


def process_race(
    race: RaceItem,
    cache: HttpxCrawlerRuntime,
    log: structlog.BoundLogger,
    page_race_max: int | None = None,
    summary: CrawlSummary | None = None,
) -> None:
    base_race_url = EVENTS_LIST_URL + race["technical_url"]
    current_url = base_race_url
    pages_processed = 0

    while True:
        try:
            sleep(1, summary)  # be nice to the server
            race_html = cache.fetch(current_url, CachePolicy.CACHE_IF_PRESENT)
        except RuntimeError as exc:
            if summary is not None:
                summary.races_failed_count += 1
            log.error("fetch_error", error=str(exc), race_url=current_url)
            return
        except ExternalRedirectError as exc:
            if summary is not None:
                summary.races_external_count += 1
            log.info(
                "race_skipped",
                reason="external_redirect",
                from_url=exc.requested_url,
                to_url=exc.final_url,
            )
            return

        race_result = extract_race_results(race_html, race)

        # Download the results document
        if pages_processed == 0:
            race_document_url = race_result["document"]
            if race_document_url:
                full_document_url = EVENTS_LIST_URL + race_document_url
                try:
                    sleep(1, summary)  # be nice to the server
                    cache.download(full_document_url)
                    log.info("document_downloaded", race_document_url=full_document_url)
                    if summary is not None:
                        summary.races_document_downloaded_count += 1
                except RuntimeError as exc:
                    if summary is not None:
                        summary.races_document_failed_count += 1
                    log.error("download_error", error=str(exc), race_document_url=full_document_url)

        results = race_result["results"]
        if summary is not None:
            summary.races_processed_count += 1
            summary.results_processed_count += len(results)
        cache.save_extracted_json(current_url, race_result)
        log.info("race_processed", race_url=current_url)
        pages_processed += 1

        if results:
            log.debug(
                "race_results_sample",
                race_url=current_url,
                sample=results[:1],
            )

            result_detail_url = results[0].get("result_detail_url_computed")
            if not isinstance(result_detail_url, str) or not result_detail_url:
                log.info(
                    "partial_data_available",
                    missing="result_detail",
                    race_url=current_url,
                )
            else:
                full_result_detail_url = EVENTS_LIST_URL + result_detail_url
                try:
                    sleep(1, summary)  # be nice to the server
                    detail_html = cache.fetch(full_result_detail_url, CachePolicy.CACHE_IF_PRESENT)
                    detail = extract_result_detail(detail_html)
                    cache.save_extracted_json(full_result_detail_url, detail)
                    log.info("result_detail_processed", url=full_result_detail_url)
                except ExternalRedirectError as exc:
                    if summary is not None:
                        summary.results_failed_count += 1
                    log.info(
                        "result_detail_skipped",
                        reason="external_redirect",
                        from_url=exc.requested_url,
                        to_url=exc.final_url,
                    )
                except RuntimeError as exc:
                    if summary is not None:
                        summary.results_failed_count += 1
                    log.error(
                        "fetch_error", error=str(exc), result_detail_url=full_result_detail_url
                    )

        next_url = race_result["next_url"]
        if not next_url:
            break
        if page_race_max is not None and pages_processed >= page_race_max:
            log.info("race_max_pages_reached", pages=pages_processed)
            break

        current_url = urljoin(base_race_url, next_url)


@cli.command()
@click.option("--plugin", required=True)
@click.option("--entity", required=True)
@click.option("--input", "input_file", type=click.Path(exists=True), required=True)
@click.option("--output", type=click.Path(), required=False)
def extract(
    plugin: str,
    entity: str,
    input_file: str,
    output: str | None,
) -> None:
    input_path = Path(input_file)

    html = input_path.read_text(encoding="utf-8")

    if plugin != "breizhchrono":
        raise click.ClickException(f"Unsupported plugin: {plugin}")

    extractor = EXTRACTORS.get(entity)
    if extractor is None:
        raise click.ClickException(f"Unknown extractor: {entity}")

    result = extractor(html)

    json_result = json.dumps(
        result,
        indent=2,
        ensure_ascii=False,
    )

    if output:
        Path(output).write_text(
            json_result,
            encoding="utf-8",
        )
    else:
        click.echo(json_result)
