from __future__ import annotations

import io
import stat
import zipfile
from pathlib import Path

import pytest

from automd.security import (
    ArchiveBudget,
    SecurityError,
    extract_archive,
    resolve_inside,
    safe_filename,
    safe_relative_path,
)


@pytest.mark.parametrize(
    "value", ["../secret", "/etc/passwd", "C:\\Windows\\system.ini", "a/../../b"]
)
def test_rejects_unsafe_relative_paths(value: str) -> None:
    with pytest.raises(SecurityError):
        safe_relative_path(value)


def test_resolve_inside_and_filename(tmp_path: Path) -> None:
    assert resolve_inside(tmp_path, "folder/file.txt") == (tmp_path / "folder/file.txt").resolve()
    assert safe_filename("../../My output?.md") == "My-output-.md"
    assert len((safe_filename("世" * 120) + "-rag.zip").encode()) <= 255


def test_zip_traversal_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../outside.txt", "nope")
    with pytest.raises(SecurityError):
        extract_archive(archive, tmp_path / "out")
    assert not (tmp_path / "outside.txt").exists()


def test_zip_symlink_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "link.zip"
    info = zipfile.ZipInfo("link")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr(info, "target")
    with pytest.raises(SecurityError):
        extract_archive(archive, tmp_path / "out")


def test_normal_zip_extracts(tmp_path: Path) -> None:
    archive = tmp_path / "ok.zip"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as handle:
        handle.writestr("project/readme.md", "hello")
    archive.write_bytes(buffer.getvalue())
    budget = ArchiveBudget(4, 100)
    extract_archive(archive, tmp_path / "out", budget=budget)
    assert (budget.entries_left, budget.bytes_left) == (3, 95)
    assert (tmp_path / "out/project/readme.md").read_text() == "hello"


@pytest.mark.parametrize("name", ["CON.txt", "file.txt:stream", "name.", "folder/Trailing "])
def test_paths_are_portable_and_regular(name: str) -> None:
    with pytest.raises(SecurityError):
        safe_relative_path(name)


def test_archive_failure_cleans_partial_files_and_charges_shared_budget(tmp_path: Path) -> None:
    good = tmp_path / "good.zip"
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(good, "w") as handle:
        handle.writestr("notes.txt", "1234")
    with zipfile.ZipFile(bad, "w") as handle:
        handle.writestr("more.txt", "1234")
    budget = ArchiveBudget(2, 6)
    extract_archive(good, tmp_path / "first", budget=budget)
    with pytest.raises(SecurityError):
        extract_archive(bad, tmp_path / "second", budget=budget)
    assert not (tmp_path / "second").exists()
    assert (tmp_path / "first" / "notes.txt").read_text() == "1234"


def test_archive_rejects_case_collisions(tmp_path: Path) -> None:
    archive = tmp_path / "files.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("README.md", "first")
        handle.writestr("Readme.md", "second")
    with pytest.raises(SecurityError, match="conflicting"):
        extract_archive(archive, tmp_path / "out")
    assert not (tmp_path / "out").exists()
