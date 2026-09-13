"""Contracts for the planned sentence-level read-along pipeline.

This module is not wired into the running job worker. Sentence extraction,
passage location, sentence timing, alignment review, Media Overlay generation,
and EPUB packaging are implemented here. ``transcribe_audio`` calls
faster-whisper when that optional dependency is installed. Keeping the
intermediate data independent of SMIL lets us change the transcription or
alignment backend without changing the EPUB writer.
"""

from __future__ import annotations

import difflib
import math
import os
import posixpath
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET
from xml.etree.ElementTree import Element

from .epub import EpubError, _package_document_path, _read_xml, validate_archive
from .sentences import SentenceSegmenter

OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
XHTML_NS = "http://www.w3.org/1999/xhtml"
SMIL_NS = "http://www.w3.org/ns/SMIL"
EPUB_NS = "http://www.idpf.org/2007/ops"
MEDIA_NS = "http://www.idpf.org/epub/vocab/overlays/#"

_BLOCKS = {
    "body", "main", "section", "article", "header", "footer", "aside", "address",
    "p", "li", "blockquote", "div", "pre", "figure", "figcaption", "dl", "dt", "dd",
    "ul", "ol", "table", "caption", "thead", "tbody", "tfoot", "tr", "td", "th",
    *(f"h{i}" for i in range(1, 7)),
}
_IGNORED = {"head", "script", "style", "nav", "svg", "math", "template"}
_WORD = re.compile(r"[0-9a-z']+")
_AUDIO_TYPES = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".m4b": "audio/mp4",
    ".mp4": "audio/mp4",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".wav": "audio/wav",
}


@dataclass(frozen=True)
class Sentence:
    """Narratable text in spine order, tied to a future XHTML element ID.

    ``document`` is the path inside the EPUB, not an extracted filesystem path.
    ``anchor_id`` must be unique within that XHTML document. ``text_start``
    and ``text_end`` locate the sentence in the document's concatenated text
    nodes, using character offsets before any markup is changed. The packaging
    stage must add an element with this ID without losing inline markup.
    """

    document: str
    anchor_id: str
    text: str
    text_start: int
    text_end: int


@dataclass(frozen=True)
class WordTiming:
    """One spoken word with seconds relative to the source audio file."""

    text: str
    start: float
    end: float


@dataclass(frozen=True)
class TranscriptSegment:
    """A rough audio transcription with seconds relative to the source file."""

    text: str
    start: float
    end: float
    words: tuple[WordTiming, ...] = ()


@dataclass(frozen=True)
class TranscriptionOptions:
    """Proposed faster-whisper settings for English, CPU-only v1 jobs.

    Use the EPUB language only after checking that it matches the narration.
    A non-English book needs a multilingual model, not ``small.en``.
    """

    model: str = "small.en"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str = "en"
    vad_filter: bool = True


@dataclass(frozen=True)
class PassageMatch:
    """A candidate sentence-to-audio window, before precise timing.

    ``start`` and ``end`` are rough bounds in seconds. ``words`` holds the
    transcript words in that window, which :func:`align_sentences` refines. An
    unmatched sentence has no match rather than an invented position.
    """

    sentence: Sentence
    start: float
    end: float
    words: tuple[WordTiming, ...] = ()


@dataclass(frozen=True)
class SentenceTiming:
    """A sentence anchored to a measured interval in the source audio."""

    sentence: Sentence
    start: float
    end: float


@dataclass(frozen=True)
class AlignmentReport:
    """Coverage and problems to show before deciding whether to export.

    ``partial`` records useful timings but does not permit packaging by
    default. ``rejected`` means the timings are too unreliable to ship.
    """

    status: Literal["ready", "partial", "rejected"]
    matched_sentences: int
    total_sentences: int
    issues: tuple[str, ...]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _namespace(tag: str) -> str | None:
    if tag.startswith("{"):
        return tag[1:].split("}", 1)[0]
    return None


def _resolve(base_dir: str, href: str) -> str:
    """Resolve a relative reference without escaping the archive root."""

    url = urlsplit(href)
    if url.scheme or url.netloc or url.query or url.fragment:
        raise EpubError(f"Invalid EPUB reference: {href}.")
    name = unquote(url.path)
    if not name or name.startswith("/") or "\\" in name:
        raise EpubError(f"Invalid EPUB reference: {href}.")
    path = posixpath.normpath(posixpath.join(base_dir, name))
    if path == ".." or path.startswith("../"):
        raise EpubError(f"EPUB reference escapes the archive: {href}.")
    return path


def _archive_path(package_path: str, href: str) -> str:
    return _resolve(posixpath.dirname(package_path) or ".", href)


def _text_runs(root: Element) -> list[tuple[int, str]]:
    """Collect all eligible body text, retaining offsets into all document text.

    Every body text node belongs to its nearest structural block, or the body
    itself. Inline markup joins within a run; block boundaries, line breaks and
    explicitly excluded subtrees separate runs, even when they contain no text.
    """

    runs: list[tuple[Element, int, str]] = []
    offset = 0
    can_merge = False

    def add(text: str | None, block: Element | None, ignored: bool) -> None:
        nonlocal offset, can_merge
        if not text:
            return
        if block is not None and not ignored:
            if can_merge and runs and runs[-1][0] is block:
                owner, start, previous = runs[-1]
                runs[-1] = (owner, start, previous + text)
            else:
                runs.append((block, offset, text))
            can_merge = True
        else:
            can_merge = False
        offset += len(text)

    def walk(node: Element, block: Element | None = None, ignored: bool = False) -> None:
        nonlocal can_merge
        name = _local_name(node.tag)
        ignored = ignored or name in _IGNORED
        boundary = name in _BLOCKS or name in {"br", "hr"} or ignored
        if boundary:
            can_merge = False
        if name == "body" or (block is not None and name in _BLOCKS and not ignored):
            block = node
        add(node.text, block, ignored)
        for child in node:
            walk(child, block, ignored)
            # Tails belong to the parent, not the child.
            add(child.tail, block, ignored)
        if boundary:
            can_merge = False

    walk(root)
    return [(start, text) for _, start, text in runs]


def extract_sentences(epub_path: Path) -> tuple[Sentence, ...]:
    """Read spine XHTML in order and assign stable sentence anchors.

    Resolve OPF manifest entries relative to the package document. Skip
    non-linear or non-XHTML spine items and known non-narrative markup. Retain
    enough location information to insert sentence IDs in the packaged EPUB.
    Do not rewrite the uploaded EPUB. Keep each sentence inside one block
    element; handle inline elements such as ``em`` and ``a`` without dropping
    their markup. This extends ``epub.inspect_epub`` beyond metadata.
    """

    try:
        archive = zipfile.ZipFile(epub_path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise EpubError("The EPUB file is not a readable zip archive.") from exc

    sentences: list[Sentence] = []
    with archive:
        validate_archive(archive)
        package_path = _package_document_path(archive)
        package = _read_xml(archive, package_path)
        language = package.findtext(f"{{{OPF_NS}}}metadata/{{{DC_NS}}}language")
        segmenter = SentenceSegmenter(language)
        if not (package.get("version") or "").startswith("3."):
            raise EpubError("Read-along currently requires an EPUB 3 source book.")
        manifest = package.find("{*}manifest")
        spine = package.find("{*}spine")
        if manifest is None or spine is None:
            raise EpubError("The EPUB is missing a manifest or spine.")
        items = {item.get("id"): item for item in manifest.findall("{*}item")}
        for ref in spine.findall("{*}itemref"):
            if ref.get("linear") == "no":
                continue
            item = items.get(ref.get("idref"))
            if item is None:
                raise EpubError(f"Missing spine item: {ref.get('idref')}.")
            if item.get("media-type") != "application/xhtml+xml":
                continue
            href = item.get("href")
            if not href:
                raise EpubError("A spine XHTML item has no href.")
            document = _archive_path(package_path, href)
            root = _read_xml(archive, document)
            if root.find(".//{*}body") is None:
                raise EpubError(f"{document} has no XHTML body.")

            # Offsets count *all* document text nodes, including head and skipped
            # markup. This lets the eventual writer find the same source spans.
            used_ids = {node.get("id") for node in root.iter() if node.get("id")}
            sentence_number = 0
            for start, text in _text_runs(root):
                for beginning, end in segmenter.spans(text):
                    anchor = f"ra-sentence-{sentence_number + 1}"
                    while anchor in used_ids:
                        anchor += "-new"
                    used_ids.add(anchor)
                    sentence_number += 1
                    sentences.append(
                        Sentence(
                            document, anchor, text[beginning:end], start + beginning, start + end
                        )
                    )
    return tuple(sentences)


def transcribe_audio(
    audio_path: Path, *, options: TranscriptionOptions | None = None
) -> tuple[TranscriptSegment, ...]:
    """Transcribe one audiobook file into rough timestamped speech segments.

    Backend: faster-whisper (CTranslate2), with PyAV for decoding and optional
    voice activity detection. Word timestamps are requested so the aligner can
    refine sentence boundaries later. Offsets stay relative to the original
    file, and intros or other unmatched speech remain in the transcript. These
    rough timestamps locate passages; they are not final highlight times.
    """

    opts = options or TranscriptionOptions()
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - depends on the local env
        raise RuntimeError(
            "Transcription needs the optional 'transcribe' dependency; "
            "install read-along-api[transcribe]."
        ) from exc

    model = WhisperModel(opts.model, device=opts.device, compute_type=opts.compute_type)
    segments, _info = model.transcribe(
        str(audio_path),
        language=opts.language,
        vad_filter=opts.vad_filter,
        word_timestamps=True,
    )
    result: list[TranscriptSegment] = []
    for segment in segments:
        words = tuple(
            WordTiming(word.word.strip(), float(word.start), float(word.end))
            for word in (segment.words or ())
            if word.word and word.word.strip()
        )
        result.append(
            TranscriptSegment(
                segment.text.strip(), float(segment.start), float(segment.end), words
            )
        )
    return tuple(result)


def _tokens(text: str) -> list[str]:
    return [token for token in (part.strip("'") for part in _WORD.findall(text.lower())) if token]


def _needed(count: int) -> int:
    return 1 if count <= 1 else max(2, math.ceil(count * 0.5))


def _transcript_words(
    transcript: tuple[TranscriptSegment, ...],
) -> tuple[list[str], list[WordTiming]]:
    tokens: list[str] = []
    words: list[WordTiming] = []
    for segment in transcript:
        source = segment.words or (
            WordTiming(segment.text, segment.start, segment.end),
        )
        for word in source:
            for token in _tokens(word.text):
                tokens.append(token)
                words.append(WordTiming(token, word.start, word.end))
    return tokens, words


def locate_passages(
    sentences: tuple[Sentence, ...],
    transcript: tuple[TranscriptSegment, ...],
) -> tuple[PassageMatch, ...]:
    """Find rough audio windows for book sentences despite edition differences.

    Match normalized words in reading order using difflib's longest-matching
    blocks, which tolerate skipped text, editions with extra lines, and
    audio-only speech. Each spine document is matched against the transcript
    from the previous document's end, keeping the result monotonic. Return only
    matches backed by enough matched words; leave weak sentences out so the
    review stage can report missing coverage. Cost grows with transcript size,
    so very large single documents want chunking.
    """

    tokens, words = _transcript_words(transcript)
    passages: list[PassageMatch] = []
    cursor = 0
    for document in dict.fromkeys(sentence.document for sentence in sentences):
        group = [sentence for sentence in sentences if sentence.document == document]
        source: list[str] = []
        owners: list[Sentence] = []
        for sentence in group:
            for token in _tokens(sentence.text):
                source.append(token)
                owners.append(sentence)
        if not source:
            continue
        window = tokens[cursor:]
        matcher = difflib.SequenceMatcher(None, source, window, autojunk=False)
        matched: dict[Sentence, list[WordTiming]] = {}
        furthest = 0
        for block in matcher.get_matching_blocks():
            if not block.size:
                continue
            furthest = max(furthest, block.b + block.size)
            for offset in range(block.size):
                matched.setdefault(owners[block.a + offset], []).append(
                    words[cursor + block.b + offset]
                )
        cursor += furthest

        for sentence in group:
            found = matched.get(sentence)
            if not found:
                continue
            if len(found) < _needed(len(_tokens(sentence.text))):
                continue
            passages.append(
                PassageMatch(
                    sentence,
                    min(word.start for word in found),
                    max(word.end for word in found),
                    tuple(found),
                )
            )
    return tuple(passages)


def align_sentences(
    audio_path: Path, matches: tuple[PassageMatch, ...]
) -> tuple[SentenceTiming, ...]:
    """Refine matched windows to sentence start and end times.

    Align each sentence's words to the transcript words carried by its passage
    with the same longest-matching-block search, then take the first and last
    matched word times. Sentences with too few matched words are dropped rather
    than interpolated. ``audio_path`` is checked for existence now; a future
    acoustic backend can read it directly. Keeping timestamps relative to the
    original single audio file is the caller's contract.
    """

    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    timings: list[SentenceTiming] = []
    for match in matches:
        tokens = _tokens(match.sentence.text)
        words = list(match.words)
        if not tokens or not words:
            continue
        matcher = difflib.SequenceMatcher(
            None, tokens, [word.text for word in words], autojunk=False
        )
        chosen: list[WordTiming] = []
        for block in matcher.get_matching_blocks():
            for offset in range(block.size):
                chosen.append(words[block.b + offset])
        if len(chosen) < _needed(len(tokens)):
            continue
        start = min(word.start for word in chosen)
        end = max(word.end for word in chosen)
        if not math.isfinite(start) or not math.isfinite(end) or end <= start:
            continue
        timings.append(SentenceTiming(match.sentence, start, end))
    return tuple(timings)


def review_alignment(
    sentences: tuple[Sentence, ...], timings: tuple[SentenceTiming, ...]
) -> AlignmentReport:
    """Check coverage, order, gaps, and durations before building an EPUB.

    Reject invalid intervals, duplicates, or out-of-order timestamps. Report
    missing sentences as partial even if the available timings are valid. Gaps
    are not scored yet: there is no audio duration or calibrated quality threshold.
    """

    if not sentences:
        return AlignmentReport("rejected", 0, 0, ("No narratable sentences.",))

    positions = {sentence: i for i, sentence in enumerate(sentences)}
    issues: list[str] = []
    if len(positions) != len(sentences):
        issues.append("Duplicate sentences in source text.")
    seen: set[Sentence] = set()
    previous_index = -1
    previous_end = 0.0
    for timing in timings:
        index = positions.get(timing.sentence)
        if index is None:
            issues.append("Timing references a sentence outside the source text.")
        elif timing.sentence in seen:
            issues.append(f"Duplicate timing for sentence {index + 1}.")
        else:
            seen.add(timing.sentence)
        if not math.isfinite(timing.start) or not math.isfinite(timing.end):
            issues.append("Timing has a non-finite timestamp.")
        elif timing.start < 0 or timing.end <= timing.start:
            issues.append("Timing has an invalid interval.")
        elif timing.start < previous_end:
            issues.append("Timing intervals overlap or run backwards.")
        if index is not None and index <= previous_index:
            issues.append("Sentence timings are out of reading order.")
        if index is not None:
            previous_index = index
        previous_end = timing.end

    if issues:
        return AlignmentReport("rejected", len(seen), len(sentences), tuple(issues))
    if len(seen) != len(sentences):
        return AlignmentReport(
            "partial",
            len(seen),
            len(sentences),
            (f"{len(sentences) - len(seen)} sentences have no timing.",),
        )
    return AlignmentReport("ready", len(seen), len(sentences), ())


def overlay_archive_path(document: str) -> str:
    """The archive path of the SMIL file built next to a content document."""

    directory, _, name = document.rpartition("/")
    stem = name.rsplit(".", 1)[0]
    return f"{directory}/{stem}.smil" if directory else f"{stem}.smil"


def _clock(seconds: float) -> str:
    hours, remainder = divmod(max(seconds, 0.0), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{secs:06.3f}"


def _parse_clock(value: str) -> float:
    parts = value.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(value)


def _xml_bytes(root: Element, default_ns: str | None = None) -> bytes:
    if default_ns:
        ET.register_namespace("", default_ns)
    ET.register_namespace("epub", EPUB_NS)
    ET.register_namespace("dc", DC_NS)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def build_overlays(
    timings: tuple[SentenceTiming, ...], audio_name: str, output_dir: Path
) -> tuple[Path, ...]:
    """Write SMIL documents mapping XHTML sentence IDs to audio clip ranges.

    ``audio_name`` is the audio's archive path; each SMIL references it relative
    to its own directory. Files are grouped by content document, placed under
    ``output_dir`` at the archive path from :func:`overlay_archive_path`, and
    returned in sorted document order. Use EPUB Media Overlay ``par`` elements
    to pair text references with audio clipBegin/clipEnd.
    """

    grouped: dict[str, list[SentenceTiming]] = {}
    for timing in timings:
        grouped.setdefault(timing.sentence.document, []).append(timing)

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for document in sorted(grouped):
        archive = overlay_archive_path(document)
        base = posixpath.dirname(archive) or "."
        text_ref = posixpath.relpath(document, base)
        audio_ref = posixpath.relpath(audio_name, base)

        smil = Element(f"{{{SMIL_NS}}}smil")
        smil.set("version", "3.0")
        body = ET.SubElement(smil, f"{{{SMIL_NS}}}body")
        seq = ET.SubElement(body, f"{{{SMIL_NS}}}seq")
        for timing in grouped[document]:
            par = ET.SubElement(seq, f"{{{SMIL_NS}}}par")
            par.set("id", f"par-{timing.sentence.anchor_id}")
            text = ET.SubElement(par, f"{{{SMIL_NS}}}text")
            text.set("src", f"{text_ref}#{timing.sentence.anchor_id}")
            audio = ET.SubElement(par, f"{{{SMIL_NS}}}audio")
            audio.set("src", audio_ref)
            audio.set("clipBegin", _clock(timing.start))
            audio.set("clipEnd", _clock(timing.end))

        path = output_dir / Path(*archive.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_xml_bytes(smil, SMIL_NS))
        written.append(path)
    return tuple(written)


def _content_len(element: Element) -> int:
    total = len(element.text or "")
    for child in element:
        total += _content_len(child) + len(child.tail or "")
    return total


def _detach(element: Element) -> list[Element | str]:
    """Flatten an element's direct content into text strings and child elements."""

    items: list[Element | str] = []
    if element.text:
        items.append(element.text)
    element.text = None
    for child in list(element):
        items.append(child)
        if child.tail:
            items.append(child.tail)
            child.tail = None
        element.remove(child)
    return items


def _rebuild(element: Element, items: list[Element | str]) -> None:
    element.text = None
    for child in list(element):
        element.remove(child)
    previous: Element | None = None
    for item in items:
        if isinstance(item, str):
            if previous is None:
                element.text = (element.text or "") + item
            else:
                previous.tail = (previous.tail or "") + item
        else:
            element.append(item)
            previous = item


def _split_content(
    items: list[Element | str], offset: int
) -> tuple[list[Element | str], list[Element | str]]:
    """Split mixed content exactly, splitting inline ancestors when necessary.

    The first fragment retains the original element and its ID. Continuations
    copy formatting and link attributes but never duplicate IDs.
    """
    before: list[Element | str] = []
    after: list[Element | str] = []
    cursor = 0
    for item in items:
        length = len(item) if isinstance(item, str) else _content_len(item)
        start, end = cursor, cursor + length
        cursor = end
        if end <= offset:
            before.append(item)
        elif start >= offset:
            after.append(item)
        elif isinstance(item, str):
            before.append(item[: offset - start])
            after.append(item[offset - start :])
        else:
            continuation = Element(item.tag, {
                key: value for key, value in item.attrib.items()
                if key not in {"id", "{http://www.w3.org/XML/1998/namespace}id"}
            })
            left, right = _split_content(_detach(item), offset - start)
            _rebuild(item, left)
            _rebuild(continuation, right)
            before.append(item)
            after.append(continuation)
    return before, after


def _wrap_content(element: Element, lo: int, hi: int, span: Element) -> None:
    """Wrap exactly [lo, hi), without pulling adjacent sentences into the span."""
    if not 0 <= lo < hi <= _content_len(element):
        raise EpubError("Sentence anchor is outside its source element.")
    # Keep original inline ancestors intact when the range lies wholly within
    # one. This preserves their identity and ID-based styling where possible.
    offset = len(element.text or "")
    for child in element:
        end = offset + _content_len(child)
        if offset <= lo and hi <= end:
            _wrap_content(child, lo - offset, hi - offset, span)
            return
        offset = end + len(child.tail or "")

    before, rest = _split_content(_detach(element), lo)
    inside, after = _split_content(rest, hi - lo)
    _rebuild(element, before + [span] + after)
    _rebuild(span, inside)


def _block_spans(root: Element) -> list[tuple[Element, int]]:
    spans: list[tuple[Element, int]] = []
    offset = 0

    def walk(node: Element, block: Element | None) -> None:
        nonlocal offset
        if _local_name(node.tag) in _BLOCKS:
            block = node
            spans.append((node, offset))
        if node.text:
            offset += len(node.text)
        for child in node:
            walk(child, block)
            if child.tail:
                offset += len(child.tail)

    walk(root, None)
    return spans


def _find_block(spans: list[tuple[Element, int]], sentence: Sentence) -> tuple[Element, int]:
    best: tuple[Element, int] | None = None
    for block, start in spans:
        if start <= sentence.text_start and sentence.text_end <= start + _content_len(block):
            if best is None or _content_len(block) < _content_len(best[0]):
                best = (block, start)
    if best is None:
        raise EpubError(f"Sentence {sentence.anchor_id} is not inside a single block.")
    return best


def _anchor_document(root: Element, sentences: tuple[Sentence, ...]) -> None:
    original_text = "".join(root.itertext())
    spans = _block_spans(root)
    groups: dict[int, tuple[Element, int, list[Sentence]]] = {}
    for sentence in sentences:
        block, start = _find_block(spans, sentence)
        groups.setdefault(id(block), (block, start, []))[2].append(sentence)

    for block, start, items in groups.values():
        namespace = _namespace(block.tag)
        # Right-to-left insertion keeps later anchors outside subsequent cuts.
        for sentence in sorted(items, key=lambda item: item.text_start, reverse=True):
            span = Element(f"{{{namespace}}}span") if namespace else Element("span")
            span.set("id", sentence.anchor_id)
            _wrap_content(block, sentence.text_start - start, sentence.text_end - start, span)

    if "".join(root.itertext()) != original_text:
        raise EpubError("Sentence anchoring changed the source text.")
    by_id: dict[str, list[Element]] = {}
    for node in root.iter():
        if identifier := node.get("id"):
            by_id.setdefault(identifier, []).append(node)
    for sentence in sentences:
        targets = by_id.get(sentence.anchor_id, [])
        if len(targets) != 1 or "".join(targets[0].itertext()) != sentence.text:
            raise EpubError(f"Sentence anchor {sentence.anchor_id} does not match its source text.")


def _audio_media_type(name: str) -> str:
    return _AUDIO_TYPES.get(posixpath.splitext(name)[1].lower(), "audio/mpeg")


def _match_document(sentences: tuple[Sentence, ...], text_src: str) -> str:
    target = unquote(urlsplit(text_src).path).rsplit("/", 1)[-1]
    candidates = list(
        dict.fromkeys(s.document for s in sentences if s.document.rsplit("/", 1)[-1] == target)
    )
    if len(candidates) != 1:
        raise EpubError(f"Cannot match overlay text reference {text_src!r} to a document.")
    return candidates[0]


def _first_src(root: Element, tag: str) -> str | None:
    element = root.find(f".//{{{SMIL_NS}}}{tag}")
    return element.get("src") if element is not None else None


def _update_package(
    package: Element,
    package_path: str,
    overlay_entries: list[tuple[str, str, float]],
    audio_archive: str,
) -> None:
    namespace = _namespace(package.tag) or OPF_NS
    qa = lambda tag: f"{{{namespace}}}{tag}"  # noqa: E731
    manifest = package.find(qa("manifest"))
    spine = package.find(qa("spine"))
    if manifest is None or spine is None:
        raise EpubError("The EPUB is missing a manifest or spine.")
    base = posixpath.dirname(package_path) or "."

    ids = {item.get("id") for item in manifest.findall(qa("item"))}

    def unique(prefix: str) -> str:
        number = 1
        while f"{prefix}-{number}" in ids:
            number += 1
        identifier = f"{prefix}-{number}"
        ids.add(identifier)
        return identifier

    audio_id = unique("ra-audio")
    audio_item = ET.SubElement(manifest, qa("item"))
    audio_item.set("id", audio_id)
    audio_item.set("href", posixpath.relpath(audio_archive, base))
    audio_item.set("media-type", _audio_media_type(audio_archive))

    overlay_ids: dict[str, str] = {}
    for archive, document, _duration in overlay_entries:
        identifier = unique("ra-overlay")
        overlay_ids[document] = identifier
        item = ET.SubElement(manifest, qa("item"))
        item.set("id", identifier)
        item.set("href", posixpath.relpath(archive, base))
        item.set("media-type", "application/smil+xml")

    for item in manifest.findall(qa("item")):
        href = item.get("href")
        if not href:
            continue
        document = _resolve(base, href.split("#", 1)[0])
        if document in overlay_ids:
            item.set("media-overlay", overlay_ids[document])

    metadata = package.find(qa("metadata"))
    if metadata is None:
        metadata = Element(qa("metadata"))
        package.insert(0, metadata)
    prefix = package.get("prefix") or ""
    if MEDIA_NS not in prefix:
        package.set("prefix", f"{prefix} media: {MEDIA_NS}".strip())

    total = 0.0
    for _archive, document, duration in overlay_entries:
        total += duration
        meta = ET.SubElement(metadata, qa("meta"))
        meta.set("property", "media:duration")
        meta.set("refines", f"#{overlay_ids[document]}")
        meta.text = _clock(duration)
    total_meta = ET.SubElement(metadata, qa("meta"))
    total_meta.set("property", "media:duration")
    total_meta.text = _clock(total)


def _write_epub(
    source: Path,
    output_path: Path,
    replacements: dict[str, bytes],
    additions: dict[str, bytes | Path],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        zipfile.ZipFile(source) as src,
        zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as dst,
    ):
        validate_archive(src)
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        dst.writestr(info, b"application/epub+zip")
        for item in src.infolist():
            name = item.filename
            if name == "mimetype" or name in additions:
                continue
            data = replacements.get(name)
            if data is not None:
                dst.writestr(item, data)
            else:
                with src.open(item) as source_file, dst.open(item, "w") as target:
                    shutil.copyfileobj(source_file, target, length=1 << 20)
        for name, data in additions.items():
            if isinstance(data, Path):
                with data.open("rb") as source_file, dst.open(name, "w") as target:
                    shutil.copyfileobj(source_file, target, length=1 << 20)
            else:
                dst.writestr(name, data)


def _run_epubcheck(path: Path) -> None:
    jar = os.environ.get("EPUBCHECK_JAR")
    executable = shutil.which("epubcheck")
    if jar and Path(jar).exists():
        command = ["java", "-jar", jar, str(path)]
    elif executable:
        command = [executable, str(path)]
    else:
        return
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stdout or result.stderr).strip()
        raise EpubError(f"EPUBCheck rejected the packaged EPUB: {detail}")


def _validate_output(output_path: Path) -> None:
    with zipfile.ZipFile(output_path) as archive:
        infos = archive.infolist()
        if not infos or infos[0].filename != "mimetype":
            raise EpubError("Packaged EPUB does not store the mimetype first.")
        if infos[0].compress_type != zipfile.ZIP_STORED:
            raise EpubError("Packaged EPUB does not store the mimetype uncompressed.")
        names = {info.filename for info in infos}
        if "META-INF/container.xml" not in names:
            raise EpubError("Packaged EPUB is missing META-INF/container.xml.")
    _run_epubcheck(output_path)


def package_epub(
    epub_path: Path,
    audio_path: Path,
    sentences: tuple[Sentence, ...],
    overlays: tuple[Path, ...],
    output_path: Path,
) -> Path:
    """Copy the original EPUB, add sentence anchors, audio, and SMIL, then validate.

    Anchors every extracted sentence, adds each overlay at the archive path from
    :func:`overlay_archive_path`, and places the audio where the overlays point.
    Update the OPF manifest, Media Overlay associations, and duration metadata.
    Preserve other book resources and never change the uploaded original. The
    result is checked structurally and with EPUBCheck when it is installed.
    """

    try:
        source = zipfile.ZipFile(epub_path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise EpubError("The EPUB file is not a readable zip archive.") from exc

    overlay_entries: list[tuple[str, str, float]] = []
    overlay_bytes: dict[str, bytes] = {}
    audio_archives: set[str] = set()
    for overlay in overlays:
        root = ET.fromstring(overlay.read_bytes())
        text_src = _first_src(root, "text")
        audio_src = _first_src(root, "audio")
        if not text_src or not audio_src:
            raise EpubError(f"Overlay {overlay.name} is missing a text or audio reference.")
        document = _match_document(sentences, text_src)
        archive = overlay_archive_path(document)
        audio_archives.add(_resolve(posixpath.dirname(archive) or ".", audio_src))
        duration = sum(
            _parse_clock(audio.get("clipEnd", "0"))
            - _parse_clock(audio.get("clipBegin", "0"))
            for audio in root.findall(f".//{{{SMIL_NS}}}audio")
        )
        overlay_entries.append((archive, document, duration))
        overlay_bytes[archive] = overlay.read_bytes()

    if len(audio_archives) != 1:
        raise EpubError("Overlays do not agree on a single audio file.")
    audio_archive = audio_archives.pop()
    if not audio_path.exists():
        raise EpubError(f"Audio file not found: {audio_path}")

    with source:
        validate_archive(source)
        package_path = _package_document_path(source)
        collisions = (set(overlay_bytes) | {audio_archive}) & set(source.namelist())
        if collisions:
            name = sorted(collisions)[0]
            raise EpubError(f"Generated resource already exists in the EPUB: {name}")
        documents = list(dict.fromkeys(sentence.document for sentence in sentences))
        replacements: dict[str, bytes] = {}
        for document in documents:
            root = _read_xml(source, document)
            _anchor_document(
                root, tuple(sentence for sentence in sentences if sentence.document == document)
            )
            replacements[document] = _xml_bytes(root, _namespace(root.tag))

        package = _read_xml(source, package_path)
        _update_package(package, package_path, overlay_entries, audio_archive)
        replacements[package_path] = _xml_bytes(package, _namespace(package.tag) or OPF_NS)

    additions = dict(overlay_bytes)
    additions[audio_archive] = audio_path
    temporary = output_path.with_name(f".{output_path.stem}.partial{output_path.suffix}")
    try:
        _write_epub(epub_path, temporary, replacements, additions)
        _validate_output(temporary)
        temporary.replace(output_path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return output_path
