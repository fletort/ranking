from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from ranking.core.storage.local import LocalStorageProvider
from ranking.core.storage.provider import DownloadedDocument
from ranking.core.storage.race_archive import (
    _AREA_SUBDIRS,
    RACE_SESSION_DIR_ENV,
    ArchiveArea,
    RaceScopedStorage,
    _extract,
    _pack,
    race_session,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RACE_URL = "https://example.com/events/2025/race-10km"
BODY_URL = "https://example.com/events/2025/race-10km?page=1"
REDIRECT_URL = "https://example.com/events/2025/race-10km-legacy"
DOCUMENT_URL = "https://example.com/events/2025/race-10km/results.pdf"


class FakeStorageProvider(LocalStorageProvider):
    """In-memory archive backend used as the base provider in tests.

    Archives are kept in memory while the inherited local filesystem behavior backs the
    non-archived areas (downloaded documents).
    """

    def __init__(self, plugin_name: str = "demo", root: Path = Path(".")) -> None:
        super().__init__(
            plugin_name,
            cache_root=root / "base-cache",
            document_root=root / "base-documents",
        )
        self.archives: dict[tuple[str, ArchiveArea], bytes] = {}
        self.document_saves: list[str] = []

    def download_area_archive(self, race_url: str, area: ArchiveArea, target: Path) -> bool:
        data = self.archives.get((race_url, area))
        if data is None:
            return False
        target.write_bytes(data)
        return True

    def upload_area_archive(self, race_url: str, area: ArchiveArea, source: Path) -> None:
        self.archives[(race_url, area)] = source.read_bytes()

    def save_document(self, document: DownloadedDocument) -> None:
        self.document_saves.append(document.url)
        super().save_document(document)


def _download_document(url: str = DOCUMENT_URL) -> DownloadedDocument:
    content = b"%PDF-1.7"
    return DownloadedDocument(
        url=url,
        content=content,
        original_filename="results.pdf",
        content_type="application/pdf",
        content_length=len(content),
        downloaded_at=datetime.now(timezone.utc),
    )


def _zip_names(data: bytes) -> set[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return set(zf.namelist())


# ---------------------------------------------------------------------------
# _pack / _extract
# ---------------------------------------------------------------------------


def test_pack_and_extract_round_trip(tmp_path: Path) -> None:
    base_dir = tmp_path / "plugin"
    body = base_dir / "http" / "current" / "ab" / "abc.html"
    pointer = base_dir / "redirects" / "ab" / "abc.json"
    extracted = base_dir / "extracted" / "ab" / "abc.json"
    for file in (body, pointer, extracted):
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(f"content of {file.name}", encoding="utf-8")

    archive = tmp_path / "http.zip"
    _pack(_AREA_SUBDIRS[ArchiveArea.HTTP], base_dir, archive)

    names = _zip_names(archive.read_bytes())
    assert "http/current/ab/abc.html" in names
    assert "redirects/ab/abc.json" in names
    assert "extracted/ab/abc.json" not in names

    target = tmp_path / "restored"
    _extract(archive, target)
    assert (target / "http" / "current" / "ab" / "abc.html").read_text() == "content of abc.html"
    assert (target / "redirects" / "ab" / "abc.json").read_text() == "content of abc.json"


def test_pack_ignores_missing_subdirs(tmp_path: Path) -> None:
    archive = tmp_path / "empty.zip"
    _pack(_AREA_SUBDIRS[ArchiveArea.EXTRACTED], tmp_path / "missing", archive)
    assert _zip_names(archive.read_bytes()) == set()


# ---------------------------------------------------------------------------
# race_session lifecycle
# ---------------------------------------------------------------------------


def test_race_session_first_run_is_cache_miss(tmp_path: Path) -> None:
    base = FakeStorageProvider(root=tmp_path)
    with race_session(base, RACE_URL, workdir_root=tmp_path) as scoped:
        assert isinstance(scoped, RaceScopedStorage)
        assert scoped.get_http_cache(BODY_URL) is None
        assert scoped.get_redirect(REDIRECT_URL) is None
        assert scoped.get_extracted(BODY_URL) is None


def test_race_session_packages_layers_on_close(tmp_path: Path) -> None:
    base = FakeStorageProvider(root=tmp_path)
    with race_session(base, RACE_URL, workdir_root=tmp_path) as scoped:
        scoped.save_http_cache(BODY_URL, "<html>body</html>")
        scoped.save_redirect(REDIRECT_URL, BODY_URL)
        scoped.save_extracted(BODY_URL, {"rank": 1})

    assert set(base.archives) == {
        (RACE_URL, ArchiveArea.HTTP),
        (RACE_URL, ArchiveArea.EXTRACTED),
    }

    body_rid = base.compute_resource_id(BODY_URL)
    redirect_rid = base.compute_resource_id(REDIRECT_URL)
    http_names = _zip_names(base.archives[(RACE_URL, ArchiveArea.HTTP)])
    assert f"http/current/{body_rid[:2]}/{body_rid}.html" in http_names
    assert f"redirects/{redirect_rid[:2]}/{redirect_rid}.json" in http_names

    extracted_rid = base.compute_resource_id(BODY_URL)
    extracted_names = _zip_names(base.archives[(RACE_URL, ArchiveArea.EXTRACTED)])
    assert extracted_names == {f"extracted/{extracted_rid[:2]}/{extracted_rid}.json"}


def test_race_session_restores_layers_on_reopen(tmp_path: Path) -> None:
    base = FakeStorageProvider(root=tmp_path)
    with race_session(base, RACE_URL, workdir_root=tmp_path) as scoped:
        scoped.save_http_cache(BODY_URL, "<html>body</html>")
        scoped.save_redirect(REDIRECT_URL, BODY_URL)
        scoped.save_extracted(BODY_URL, {"rank": 1})

    with race_session(base, RACE_URL, workdir_root=tmp_path) as scoped:
        assert scoped.exists_http_cache(BODY_URL)
        assert scoped.get_http_cache(BODY_URL) == "<html>body</html>"
        assert scoped.get_redirect(REDIRECT_URL) == BODY_URL
        assert scoped.get_extracted(BODY_URL) == {"rank": 1}


def test_race_session_removes_session_directory(tmp_path: Path) -> None:
    base = FakeStorageProvider(root=tmp_path)
    with race_session(base, RACE_URL, workdir_root=tmp_path) as scoped:
        assert isinstance(scoped, RaceScopedStorage)
        session_dir = scoped.cache_root.parent.parent
        assert session_dir.exists()
    assert not session_dir.exists()


def test_race_session_upload_failure_is_non_fatal(tmp_path: Path) -> None:
    class BrokenProvider(FakeStorageProvider):
        def upload_area_archive(self, race_url: str, area: ArchiveArea, source: Path) -> None:
            raise RuntimeError("boom")

    base = BrokenProvider(root=tmp_path)
    with race_session(base, RACE_URL, workdir_root=tmp_path) as scoped:
        scoped.save_http_cache(BODY_URL, "<html>body</html>")

    assert base.archives == {}
    assert list(tmp_path.glob("race-*")) == []


def test_race_session_uses_env_root(tmp_path: Path, monkeypatch) -> None:
    sessions_root = tmp_path / "sessions"
    monkeypatch.setenv(RACE_SESSION_DIR_ENV, str(sessions_root))

    base = FakeStorageProvider(root=tmp_path)
    with race_session(base, RACE_URL) as scoped:
        assert isinstance(scoped, RaceScopedStorage)
        session_dir = scoped.cache_root.parent.parent
        assert sessions_root in session_dir.parents

    assert sessions_root.exists()


# ---------------------------------------------------------------------------
# RaceScopedStorage routing
# ---------------------------------------------------------------------------


def test_race_scoped_storage_buffers_archived_layers(tmp_path: Path) -> None:
    base = FakeStorageProvider(root=tmp_path)
    scoped = RaceScopedStorage(base, tmp_path / "work")

    scoped.save_http_cache(BODY_URL, "x")
    scoped.save_redirect(REDIRECT_URL, BODY_URL)
    scoped.save_extracted(BODY_URL, {"k": "v"})

    body_rid = base.compute_resource_id(BODY_URL)
    cache_root = scoped.cache_root / "demo"
    assert (cache_root / "http" / "current" / body_rid[:2] / f"{body_rid}.html").exists()
    redirect_rid = base.compute_resource_id(REDIRECT_URL)
    assert (cache_root / "redirects" / redirect_rid[:2] / f"{redirect_rid}.json").exists()
    assert (cache_root / "extracted" / body_rid[:2] / f"{body_rid}.json").exists()

    # The archivable layers never touch the base provider.
    assert base.get_http_cache(BODY_URL) is None
    assert base.get_redirect(REDIRECT_URL) is None
    assert base.get_extracted(BODY_URL) is None


def test_race_scoped_storage_delegates_documents(tmp_path: Path) -> None:
    base = FakeStorageProvider(root=tmp_path)
    scoped = RaceScopedStorage(base, tmp_path / "work")
    document = _download_document()

    scoped.save_document(document)

    assert base.document_saves == [document.url]
    assert scoped.document_exists(document.url)
    retrieved = scoped.get_document(document.url)
    assert retrieved is not None
    assert retrieved.content == document.content
    assert scoped.healthcheck().backend == "local"

    # Documents are never buffered locally.
    assert not scoped.document_root.exists()
