from __future__ import annotations

import posixpath
import zipfile
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import pytest
from defusedxml.ElementTree import fromstring
from support import create_job, make_client, multi_document_transcriber, wait_for_terminal

from app.epub import EpubError
from app.pipeline import (
    OPF_NS,
    SMIL_NS,
    Overlay,
    SentenceTiming,
    build_overlays,
    extract_sentences,
    package_epub,
)


def book(tmp_path: Path, documents: tuple[str, ...], package: str = "OPS/package.opf") -> Path:
    base = posixpath.dirname(package) or "."
    items = "".join(
        f'<item id="doc-{index}" href="{quote(posixpath.relpath(document, base), safe="/")}" '
        'media-type="application/xhtml+xml"/>'
        for index, document in enumerate(documents)
    )
    spine = "".join(f'<itemref idref="doc-{index}"/>' for index in range(len(documents)))
    source = tmp_path / "book.epub"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            f'<container><rootfiles><rootfile full-path="{escape(package)}"/>'
            "</rootfiles></container>",
        )
        archive.writestr(
            package,
            f'<package xmlns="{OPF_NS}" version="3.0"><manifest>{items}</manifest>'
            f"<spine>{spine}</spine></package>",
        )
        for index, document in enumerate(documents):
            archive.writestr(
                document,
                '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
                f"<p>Document {index}. Final line.</p></body></html>",
            )
    return source


def prepare(tmp_path: Path, documents: tuple[str, ...], package: str = "OPS/package.opf"):
    source = book(tmp_path, documents, package)
    sentences = extract_sentences(source)
    timings = tuple(
        SentenceTiming(sentence, i * 2, i * 2 + 1) for i, sentence in enumerate(sentences)
    )
    overlays = build_overlays(timings, "OEBPS/audio/book #1%.mp3", tmp_path / "stage")
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"ID3-audio")
    return source, sentences, overlays, audio


@pytest.mark.parametrize(
    "package, documents",
    [
        ("OPS/package.opf", ("OPS/Part2/chapter.xhtml", "OPS/Part1/chapter.xhtml")),
        ("OPS/package.opf", ("OPS/chapter.html", "OPS/chapter.xhtml")),
        ("package.opf", ("Part1/chapter.xhtml", "Part2/chapter.xhtml")),
        (
            "EPUB/Metadata/package.opf",
            ("EPUB/Books/Vol1/chapter.xhtml", "EPUB/Books/Vol2/chapter.xhtml"),
        ),
        (
            "OPS/package.opf",
            ("OPS/Part #1/chapter %draft.xhtml", "OPS/Part #2/chapter %draft.xhtml"),
        ),
        (
            "OPS/package.opf",
            ("OPS/A/chapter%20one.xhtml", "OPS/B/chapter%20one.xhtml"),
        ),
        ("OPS/package.opf", ("OPS/第一/chapter.xhtml", "OPS/第二/chapter.xhtml")),
    ],
)
def test_full_paths_keep_overlays_and_manifest_associations_distinct(
    tmp_path: Path, package: str, documents: tuple[str, ...]
) -> None:
    source, sentences, overlays, audio = prepare(tmp_path, documents, package)
    before = source.read_bytes()
    assert len({overlay.path for overlay in overlays}) == len(documents)
    assert {overlay.document for overlay in overlays} == set(documents)
    result = package_epub(source, audio, sentences, overlays, tmp_path / "result.epub")
    with zipfile.ZipFile(result) as archive:
        opf = fromstring(archive.read(package))
        items = {
            item.get("id"): item for item in opf.findall(f"{{{OPF_NS}}}manifest/{{{OPF_NS}}}item")
        }
        associations = []
        for index, document in enumerate(documents):
            overlay_id = items[f"doc-{index}"].get("media-overlay")
            associations.append(overlay_id)
            href = items[overlay_id].get("href")
            smil_path = posixpath.normpath(
                posixpath.join(posixpath.dirname(package), unquote(href))
            )
            assert smil_path == f"{document}.smil"
            smil = fromstring(archive.read(smil_path))
            targets = []
            for text in smil.findall(f".//{{{SMIL_NS}}}text"):
                reference = urlsplit(text.get("src"))
                target = posixpath.normpath(
                    posixpath.join(posixpath.dirname(smil_path), unquote(reference.path))
                )
                assert target == document
                targets.append(unquote(reference.fragment))
            assert targets == [s.anchor_id for s in sentences if s.document == document]
            for node in smil.findall(f".//{{{SMIL_NS}}}audio"):
                target = posixpath.normpath(
                    posixpath.join(
                        posixpath.dirname(smil_path), unquote(urlsplit(node.get("src")).path)
                    )
                )
                assert archive.read(target) == b"ID3-audio"
        assert len(set(associations)) == len(documents)
    assert source.read_bytes() == before


def test_source_identity_does_not_depend_on_local_staging_paths(tmp_path: Path) -> None:
    source, sentences, overlays, audio = prepare(
        tmp_path, ("OPS/Part1/chapter.xhtml", "OPS/Part2/chapter.xhtml")
    )
    relocated = []
    for index, overlay in enumerate(overlays):
        destination = tmp_path / f"detached-{index}.smil"
        overlay.path.rename(destination)
        relocated.append(replace(overlay, path=destination))
    package_epub(source, audio, sentences, tuple(relocated), tmp_path / "result.epub")


@pytest.mark.parametrize("index", [0, 1])
def test_every_text_reference_is_checked_against_full_document_path(
    tmp_path: Path, index: int
) -> None:
    source, sentences, overlays, audio = prepare(
        tmp_path, ("OPS/Part1/chapter.xhtml", "OPS/Part2/chapter.xhtml")
    )
    root = fromstring(overlays[0].path.read_bytes())
    text = root.findall(f".//{{{SMIL_NS}}}text")[index]
    fragment = urlsplit(text.get("src")).fragment
    text.set("src", f"../Part2/chapter.xhtml#{fragment}")
    overlays[0].path.write_bytes(ET.tostring(root))
    with pytest.raises(EpubError, match="full source path"):
        package_epub(source, audio, sentences, overlays, tmp_path / "result.epub")
    assert not (tmp_path / "result.epub").exists()


@pytest.mark.parametrize("problem", ["missing", "duplicate", "unknown", "anchor"])
def test_overlay_identity_and_sentence_coverage_are_validated(tmp_path: Path, problem: str) -> None:
    source, sentences, overlays, audio = prepare(
        tmp_path, ("OPS/Part1/chapter.xhtml", "OPS/Part2/chapter.xhtml")
    )
    if problem == "missing":
        overlays = overlays[:1]
    elif problem == "duplicate":
        overlays = (*overlays, overlays[0])
    elif problem == "unknown":
        overlays = (Overlay("OPS/Unknown/chapter.xhtml", overlays[0].path), overlays[1])
    else:
        root = fromstring(overlays[0].path.read_bytes())
        root.find(f".//{{{SMIL_NS}}}text").set("src", "chapter.xhtml#missing")
        overlays[0].path.write_bytes(ET.tostring(root))
    with pytest.raises(EpubError):
        package_epub(source, audio, sentences, overlays, tmp_path / "result.epub")


@pytest.mark.anyio
async def test_repeated_chapter_filenames_complete_the_real_job_pipeline(tmp_path: Path) -> None:
    source = book(tmp_path, ("OPS/Part1/chapter.xhtml", "OPS/Part2/chapter.xhtml"))
    async with make_client(tmp_path / "jobs", transcriber=multi_document_transcriber) as client:
        response = await create_job(client, epub=source.read_bytes())
        job_id = response.json()["jobId"]
        job = await wait_for_terminal(client, job_id)
        assert job["status"] == "succeeded", job["error"]
        assert (await client.get(f"/api/jobs/{job_id}/download")).status_code == 200
    with zipfile.ZipFile(tmp_path / "jobs" / job_id / "result.epub") as archive:
        assert "OPS/Part1/chapter.xhtml.smil" in archive.namelist()
        assert "OPS/Part2/chapter.xhtml.smil" in archive.namelist()
