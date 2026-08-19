from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from support import epub_bytes

from app.epub import EpubError, inspect_epub


def _write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def test_inspect_reads_the_package_metadata(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "dune.epub",
        epub_bytes(title="Dune", author="Frank Herbert", language="en", chapters=5),
    )

    info = inspect_epub(path)

    assert info.title == "Dune"
    assert info.author == "Frank Herbert"
    assert info.language == "en"
    assert info.chapters == 5
    assert info.identifier == "urn:uuid:test"


def test_inspect_falls_back_to_the_file_name(tmp_path: Path) -> None:
    path = _write(tmp_path / "Untitled Book.epub", epub_bytes(title=""))

    info = inspect_epub(path)

    assert info.title == "Untitled Book"


def test_inspect_rejects_a_non_zip(tmp_path: Path) -> None:
    path = _write(tmp_path / "not-a-book.epub", b"plain text, not an archive")

    with pytest.raises(EpubError):
        inspect_epub(path)


def test_inspect_rejects_a_zip_without_a_container(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "no container here")
    path = _write(tmp_path / "empty.epub", buffer.getvalue())

    with pytest.raises(EpubError):
        inspect_epub(path)


def test_inspect_rejects_a_missing_package_document(tmp_path: Path) -> None:
    container = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/missing.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("META-INF/container.xml", container)
    path = _write(tmp_path / "broken.epub", buffer.getvalue())

    with pytest.raises(EpubError):
        inspect_epub(path)
