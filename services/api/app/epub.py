"""Read the useful parts of an EPUB's package document.

An EPUB is a zip archive. ``META-INF/container.xml`` points at the package
document (the OPF), which carries the Dublin Core metadata and the spine of
reading-order chapters. That is all the extract stage needs for now.

Uploads are untrusted, so parsing uses ``defusedxml`` and refuses to read an
XML part larger than :data:`MAX_XML_BYTES`.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree.ElementTree import Element

from defusedxml.ElementTree import ParseError, fromstring

from .config import get_settings

CONTAINER_PATH = "META-INF/container.xml"

# Guard against a zip bomb or an absurd package document filling memory.
MAX_XML_BYTES = 5_000_000


class EpubError(Exception):
    """An uploaded file is not a readable EPUB."""


def validate_archive(archive: zipfile.ZipFile) -> None:
    """Bound the entire input archive before reading or copying any members."""
    settings = get_settings()
    entries = archive.infolist()
    if len(entries) > settings.max_archive_entries:
        raise EpubError("The EPUB contains too many archive entries.")
    total = 0
    names: set[str] = set()
    for entry in entries:
        if entry.filename in names:
            raise EpubError("The EPUB contains duplicate archive entries.")
        names.add(entry.filename)
        if entry.file_size > settings.max_archive_entry_bytes:
            raise EpubError("An EPUB archive entry exceeds the expanded-size limit.")
        total += entry.file_size
        if total > settings.max_archive_bytes:
            raise EpubError("The EPUB exceeds the total expanded-size limit.")


@dataclass(frozen=True)
class EpubInfo:
    title: str
    author: str | None
    language: str | None
    chapters: int
    identifier: str | None


def _read_xml(archive: zipfile.ZipFile, name: str) -> Element:
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise EpubError(f"The EPUB is missing {name}.") from exc

    if info.file_size > MAX_XML_BYTES:
        raise EpubError(f"{name} is unexpectedly large.")

    try:
        return fromstring(archive.read(name))
    except ParseError as exc:
        raise EpubError(f"{name} is not valid XML.") from exc


def _first_text(root: Element, tag: str) -> str | None:
    # ``{*}`` matches the tag in any namespace, so the same lookup works for
    # EPUB 2 and EPUB 3 packages without hard-coding their namespace URIs.
    element = root.find(f".//{{*}}{tag}")
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _package_document_path(archive: zipfile.ZipFile) -> str:
    container = _read_xml(archive, CONTAINER_PATH)
    rootfile = container.find(".//{*}rootfile")
    full_path = rootfile.get("full-path") if rootfile is not None else None
    if not full_path:
        raise EpubError("The EPUB container does not name a package document.")
    return full_path


def inspect_epub(path: Path, *, fallback_title: str | None = None) -> EpubInfo:
    """Return the title, author, language, chapter count and identifier.

    Raises :class:`EpubError` when the file is not a usable EPUB. The chapter
    count is the number of spine items, which is the closest thing an EPUB has
    to a chapter list.
    """

    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise EpubError("The EPUB file is not a readable zip archive.") from exc

    with archive:
        validate_archive(archive)
        package = _read_xml(archive, _package_document_path(archive))
        spine = package.find(".//{*}spine")
        chapters = len(spine.findall("{*}itemref")) if spine is not None else 0
        return EpubInfo(
            title=_first_text(package, "title") or fallback_title or path.stem,
            author=_first_text(package, "creator"),
            language=_first_text(package, "language"),
            chapters=chapters,
            identifier=_first_text(package, "identifier"),
        )
