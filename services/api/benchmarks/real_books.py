"""Download two public-domain pairs and exercise the real API/alignment pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import sys
import time
import urllib.request
import zipfile
from dataclasses import asdict
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.sax.saxutils import escape

from defusedxml.ElementTree import fromstring
from fastapi.testclient import TestClient

from app.main import create_app
from app.pipeline import (
    align_sentences,
    extract_sentences,
    locate_passages,
    review_alignment,
    transcribe_audio,
)

DATA = Path(__file__).parent / "data"
PAIRS = [
    {
        "id": "gift-of-the-magi",
        "title": "The Gift of the Magi",
        "author": "O. Henry",
        "text": "https://www.gutenberg.org/ebooks/7256.txt.utf-8",
        "catalog": "https://librivox.org/the-gift-of-the-magi-by-o-henry/",
        "audio": "https://archive.org/download/giftofmagi/gift_of_the_magi_henry_blb.mp3",
        "reader": "Betsie Bush",
        "start": "One dollar and eighty-seven cents.",
        "end": "*** END OF THE PROJECT GUTENBERG EBOOK",
    },
    {
        "id": "tell-tale-heart",
        "title": "The Tell-Tale Heart",
        "author": "Edgar Allan Poe",
        "text": "https://www.gutenberg.org/ebooks/2148.txt.utf-8",
        "catalog": "https://librivox.org/short-story-collection-001/",
        "audio": "https://archive.org/download/stories_001_librivox/telltale_heart_poe_dm_64kb.mp3",
        "reader": "Don Morgan",
        "start": "THE TELL-TALE HEART.",
        "end": "\nBERENICE",
    },
]


def download(url: str, path: Path) -> None:
    if path.exists():
        return
    print(f"Downloading {url}", flush=True)
    request = urllib.request.Request(url, headers={"User-Agent": "read-along-benchmark/1.0"})
    temporary = path.with_suffix(".partial")
    try:
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as out:
            while chunk := response.read(1024 * 1024):
                out.write(chunk)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(pair: dict[str, str], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    download(pair["text"], directory / "original.txt")
    download(pair["audio"], directory / "audio.mp3")
    text = (directory / "original.txt").read_text(encoding="utf-8")
    # The Poe collection has a table of contents: use the last story heading.
    start = text.rindex(pair["start"])
    if pair["id"] == "tell-tale-heart":
        start += len(pair["start"])
    end = text.index(pair["end"], start)
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text[start:end]) if p.strip()]
    if len(paragraphs) < 10:
        raise ValueError("Source selection is unexpectedly short; inspect the downloaded text.")
    title, author = escape(pair["title"]), escape(pair["author"])
    body = "".join(f"<p>{escape(p)}</p>" for p in paragraphs)
    with zipfile.ZipFile(directory / "book.epub", "w", zipfile.ZIP_DEFLATED) as epub:
        epub.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        epub.writestr(
            "META-INF/container.xml",
            """<container version="1.0"
          xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>
          <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
          </rootfiles></container>""",
        )
        epub.writestr(
            "content.opf",
            f"""<package xmlns="http://www.idpf.org/2007/opf"
          version="3.0" unique-identifier="bookid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
          <dc:identifier id="bookid">urn:read-along:{pair["id"]}</dc:identifier>
          <dc:title>{title}</dc:title><dc:creator>{author}</dc:creator><dc:language>en</dc:language>
          <meta property="dcterms:modified">2026-01-01T00:00:00Z</meta></metadata><manifest>
          <item id="story" href="story.xhtml" media-type="application/xhtml+xml"/>
          <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
          </manifest><spine><itemref idref="story"/></spine></package>""",
        )
        epub.writestr(
            "story.xhtml",
            f"""<html xmlns="http://www.w3.org/1999/xhtml" lang="en">
          <head><title>{title}</title></head><body>{body}</body></html>""",
        )
        epub.writestr(
            "nav.xhtml",
            f"""<html xmlns="http://www.w3.org/1999/xhtml"
          xmlns:epub="http://www.idpf.org/2007/ops" lang="en"><head><title>Contents</title></head>
          <body><nav epub:type="toc"><h1>Contents</h1><ol><li><a href="story.xhtml">{title}</a>
          </li></ol></nav></body></html>""",
        )
    provenance = dict(pair)
    provenance["sha256"] = {
        name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
        for name in ("original.txt", "audio.mp3", "book.epub")
    }
    (directory / "sources.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")


def run(directory: Path, timeout: float) -> dict:
    transcript = ()

    def transcriber(path: Path):
        nonlocal transcript
        transcript = transcribe_audio(path)
        (directory / "transcript.json").write_text(
            json.dumps([asdict(segment) for segment in transcript], indent=2), encoding="utf-8"
        )
        return transcript

    started = time.monotonic()
    app = create_app(data_dir=directory / "jobs", transcriber=transcriber)
    with TestClient(app) as client:
        with (
            (directory / "book.epub").open("rb") as epub,
            (directory / "audio.mp3").open("rb") as audio,
        ):
            response = client.post(
                "/api/jobs",
                files={
                    "epub": ("book.epub", epub, "application/epub+zip"),
                    "audio": ("audio.mp3", audio, "audio/mpeg"),
                },
            )
        response.raise_for_status()
        job_id = response.json()["jobId"]
        previous = None
        while True:
            response = client.get(f"/api/jobs/{job_id}")
            response.raise_for_status()
            job = response.json()
            if job["stage"] != previous:
                print(f"  {job_id}: {job['stage']}", flush=True)
                previous = job["stage"]
            if job["status"] in {"succeeded", "failed", "cancelled"}:
                break
            if time.monotonic() - started > timeout:
                client.post(f"/api/jobs/{job_id}/cancel")
                raise TimeoutError(
                    "Job exceeded timeout (in-flight transcription may still finish)."
                )
            time.sleep(1)
        download_response = client.get(f"/api/jobs/{job_id}/download")
        if job["status"] == "succeeded":
            download_response.raise_for_status()
            (directory / "result.epub").write_bytes(download_response.content)
            validate_result(directory / "result.epub")
        elif download_response.status_code != 409:
            raise AssertionError("Failed job incorrectly offered a download")
    sentences = extract_sentences(directory / "book.epub")
    timings = align_sentences(directory / "audio.mp3", locate_passages(sentences, transcript))
    review = review_alignment(sentences, timings)
    matched = {timing.sentence for timing in timings}
    return {
        "passed": job["status"] == "succeeded",
        "job": job,
        "seconds": round(time.monotonic() - started, 2),
        "alignment": asdict(review),
        "coverage": len(matched) / len(sentences) if sentences else 0,
        "unmatched": [asdict(sentence) for sentence in sentences if sentence not in matched],
        "timings": [asdict(timing) for timing in timings],
    }


def validate_result(path: Path) -> None:
    """Verify every SMIL target, beyond ZIP readability."""
    with zipfile.ZipFile(path) as epub:
        overlays = [name for name in epub.namelist() if name.endswith(".smil")]
        if not overlays:
            raise AssertionError("Result contains no Media Overlays")
        for name in overlays:
            root = fromstring(epub.read(name))
            for text in root.findall(".//{*}text"):
                reference = urlsplit(text.attrib["src"])
                target = posixpath.normpath(
                    posixpath.join(posixpath.dirname(name), unquote(reference.path))
                )
                document = fromstring(epub.read(target))
                if not any(
                    node.get("id") == unquote(reference.fragment) for node in document.iter()
                ):
                    raise AssertionError(f"Missing sentence anchor: {text.attrib['src']}")
            for audio in root.findall(".//{*}audio"):
                target = posixpath.normpath(
                    posixpath.join(posixpath.dirname(name), unquote(audio.attrib["src"]))
                )
                if target not in epub.namelist():
                    raise AssertionError(f"Missing audio: {target}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--pair", choices=[pair["id"] for pair in PAIRS])
    parser.add_argument("--timeout", type=float, default=3600)
    args = parser.parse_args()
    reports = {}
    for pair in PAIRS:
        if args.pair and pair["id"] != args.pair:
            continue
        directory = DATA / pair["id"]
        try:
            prepare(pair, directory)
            if args.prepare_only:
                print(f"Prepared {directory}", flush=True)
                continue
            (directory / "result.epub").unlink(missing_ok=True)
            reports[pair["id"]] = run(directory, args.timeout)
        except Exception as exc:
            reports[pair["id"]] = {"passed": False, "error": str(exc)}
        if pair["id"] in reports:
            DATA.mkdir(parents=True, exist_ok=True)
            (DATA / "report.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
            print(
                json.dumps(
                    {
                        pair["id"]: {
                            k: v
                            for k, v in reports[pair["id"]].items()
                            if k not in {"timings", "unmatched"}
                        }
                    }
                ),
                flush=True,
            )
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "report.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    return int(any(not report["passed"] for report in reports.values()))


if __name__ == "__main__":
    sys.exit(main())
