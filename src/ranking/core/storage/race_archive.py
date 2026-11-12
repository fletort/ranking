from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

import structlog

from ranking.core.storage.local import LocalStorageProvider

if TYPE_CHECKING:
    from ranking.core.storage.provider import (
        DownloadedDocument,
        HealthCheckResult,
        StorageProvider,
    )

log = structlog.get_logger().bind(component="storage")

RACE_SESSION_DIR_ENV = "RANKING_RACE_SESSION_DIR"


class ArchiveArea(str, Enum):
    """Logical layer packaged into a per-race archive."""

    HTTP = "http"
    EXTRACTED = "extracted"


# Local sub-directories bundled into each archive, relative to the plugin cache root.
_AREA_SUBDIRS: dict[ArchiveArea, tuple[str, ...]] = {
    ArchiveArea.HTTP: ("http", "redirects"),
    ArchiveArea.EXTRACTED: ("extracted",),
}


class RaceScopedStorage(LocalStorageProvider):
    """Storage overlay scoping a race crawl.

    The archived layers (HTTP cache bodies, redirect pointers and extracted data) are buffered
    locally under the session working directory. The non-archived area (downloaded documents) is
    delegated to the base provider and therefore never leaves the flat layout.
    """

    def __init__(self, base: StorageProvider, workdir: Path) -> None:
        super().__init__(
            base.plugin_name,
            cache_root=workdir / "cache",
            document_root=workdir / "documents",
        )
        self.base = base

    def save_document(self, document: DownloadedDocument) -> None:
        self.base.save_document(document)

    def get_document(self, url: str) -> DownloadedDocument | None:
        return self.base.get_document(url)

    def document_exists(self, url: str) -> bool:
        return self.base.document_exists(url)

    def healthcheck(self) -> HealthCheckResult:
        return self.base.healthcheck()


def _pack(subdirs: tuple[str, ...], base_dir: Path, archive: Path) -> None:
    """Zip every file under ``base_dir/<subdir>`` using paths relative to ``base_dir``."""
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for subdir in subdirs:
            root = base_dir / subdir
            if not root.exists():
                continue
            for file in sorted(root.rglob("*")):
                if file.is_file():
                    zf.write(file, file.relative_to(base_dir).as_posix())


def _extract(archive: Path, target: Path) -> None:
    """Extract ``archive`` into ``target``, restoring the archived subtrees."""
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "r") as zf:
        zf.extractall(target)


def _resolve_session_root(workdir_root: Path | str | None) -> str | None:
    """Resolve the root directory hosting race session working directories."""
    root: Path | None
    if workdir_root is not None:
        root = Path(workdir_root)
    else:
        env_root = os.environ.get(RACE_SESSION_DIR_ENV)
        root = Path(env_root) if env_root else None
    if root is None:
        return None
    root.mkdir(parents=True, exist_ok=True)
    return str(root)


@contextmanager
def race_session(
    base: StorageProvider,
    race_url: str,
    workdir_root: Path | str | None = None,
) -> Iterator[StorageProvider]:
    """Scope the crawl of one race and package its artifacts into per-layer archives.

    On enter, every layer archive is downloaded from ``base`` and extracted into a local working
    directory (cache-hit verification). During the block, the returned scoped provider reads and
    writes locally. On exit, each layer is packed and uploaded back through ``base``; an upload
    failure is logged but never masks the crawl result.
    """
    resource_id = base.compute_resource_id(race_url)
    session_dir = Path(
        tempfile.mkdtemp(prefix=f"race-{resource_id[:8]}-", dir=_resolve_session_root(workdir_root))
    )
    workdir = session_dir / "work"
    cache_plugin_root = workdir / "cache" / base.plugin_name
    scoped = RaceScopedStorage(base, workdir)
    initialized = False
    try:
        for area in ArchiveArea:
            archive = session_dir / f"{area.value}.zip"
            found = base.download_area_archive(race_url, area, archive)
            if found:
                _extract(archive, cache_plugin_root)
            log.info(
                "race_area_archive_synced",
                race_url=race_url,
                resource_id=resource_id,
                area=area.value,
                cache_hit=found,
            )
        initialized = True
        yield scoped
    finally:
        for area in (ArchiveArea if initialized else ()):
            archive = session_dir / f"{area.value}.zip"
            try:
                _pack(_AREA_SUBDIRS[area], cache_plugin_root, archive)
                base.upload_area_archive(race_url, area, archive)
                log.info(
                    "race_area_archive_saved",
                    race_url=race_url,
                    resource_id=resource_id,
                    area=area.value,
                )
            except Exception:
                log.exception(
                    "race_area_archive_failed",
                    race_url=race_url,
                    resource_id=resource_id,
                    area=area.value,
                )
        shutil.rmtree(session_dir, ignore_errors=True)


__all__ = [
    "RACE_SESSION_DIR_ENV",
    "ArchiveArea",
    "RaceScopedStorage",
    "race_session",
]
