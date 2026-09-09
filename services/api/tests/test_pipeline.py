from __future__ import annotations

import io
import sys
import types
import zipfile
from pathlib import Path

import pytest
from defusedxml.ElementTree import fromstring

from app.epub import EpubError
from app.pipeline import (
    SMIL_NS,
    PassageMatch,
    Sentence,
    SentenceTiming,
    TranscriptionOptions,
    TranscriptSegment,
    WordTiming,
    align_sentences,
    build_overlays,
    extract_sentences,
    locate_passages,
    overlay_archive_path,
    package_epub,
    review_alignment,
    transcribe_audio,
)

XHTML_NS = "http://www.w3.org/1999/xhtml"
OPF_NS = "http://www.idpf.org/2007/opf"


def book(tmp_path: Path, *, href: str = "Text/ch1.xhtml", xhtml: str | None = None) -> Path:
    container = """<container><rootfiles>
      <rootfile full-path="OEBPS/content.opf"/>
    </rootfiles></container>"""
    opf = f"""<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
      <manifest><item id="one" href="{href}" media-type="application/xhtml+xml"/></manifest>
      <spine><itemref idref="one"/></spine>
    </package>"""
    xhtml = xhtml or """<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Chapter</title></head>
      <body><h1>Chapter One</h1><p id="ra-sentence-1">Hello <em>world</em>. Again!</p>
      <nav><p>Skip this.</p></nav><p>Last line.</p></body></html>"""
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", opf)
        archive.writestr("OEBPS/Text/ch1.xhtml", xhtml)
    path = tmp_path / "book.epub"
    path.write_bytes(data.getvalue())
    return path


def test_extract_preserves_order_markup_offsets_and_original(tmp_path: Path) -> None:
    path = book(tmp_path)
    before = path.read_bytes()

    sentences = extract_sentences(path)

    assert [s.text for s in sentences] == ["Chapter One", "Hello world.", "Again!", "Last line."]
    assert all(s.document == "OEBPS/Text/ch1.xhtml" for s in sentences)
    assert len({s.anchor_id for s in sentences}) == len(sentences)
    assert "ra-sentence-1" not in {s.anchor_id for s in sentences}
    with zipfile.ZipFile(path) as archive:
        from defusedxml.ElementTree import fromstring

        root = fromstring(archive.read(sentences[0].document))
        source = "".join(root.itertext())
    for sentence in sentences:
        assert source[sentence.text_start : sentence.text_end] == sentence.text
    assert extract_sentences(path) == sentences
    assert path.read_bytes() == before


def test_extract_rejects_escaped_manifest_path(tmp_path: Path) -> None:
    with pytest.raises(EpubError, match="escapes"):
        extract_sentences(book(tmp_path, href="../../other.xhtml"))


def test_extract_rejects_epub2_until_conversion_is_supported(tmp_path: Path) -> None:
    path = book(tmp_path)
    with zipfile.ZipFile(path) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    parts["OEBPS/content.opf"] = parts["OEBPS/content.opf"].replace(
        b'version="3.0"', b'version="2.0"'
    )
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    with pytest.raises(EpubError, match="EPUB 3"):
        extract_sentences(path)


def test_extract_rejects_missing_xhtml(tmp_path: Path) -> None:
    with pytest.raises(EpubError, match="missing"):
        extract_sentences(book(tmp_path, href="Text/absent.xhtml"))


def test_extract_keeps_nested_blocks_separate(tmp_path: Path) -> None:
    xhtml = """<html xmlns="http://www.w3.org/1999/xhtml"><body>
      <div><p>First. Second!</p><p>Third?</p></div>
      <p>Before <em>the end</em>.</p>
      <script>Not narration.</script>
    </body></html>"""
    path = book(tmp_path, xhtml=xhtml)
    assert [s.text for s in extract_sentences(path)] == [
        "First.", "Second!", "Third?", "Before the end.",
    ]


def test_abbreviations_across_markup_preserve_packaged_text(tmp_path: Path) -> None:
    xhtml = """<html xmlns="http://www.w3.org/1999/xhtml"><body>
      <p>  Mme. <em>Sofronie</em> sold hair. “No!” she said.  </p>
      <p>Dr. <a href="#end">Watson</a> left.</p><p id="end">No!</p>
    </body></html>"""
    path = book(tmp_path, xhtml=xhtml)
    sentences = extract_sentences(path)
    assert [s.text for s in sentences] == [
        "Mme. Sofronie sold hair.", "“No!” she said.", "Dr. Watson left.", "No!",
    ]
    source = "".join(fromstring(xhtml).itertext())
    for sentence in sentences:
        assert source[sentence.text_start:sentence.text_end] == sentence.text
    assert extract_sentences(path) == sentences
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"ID3-audio")
    overlays = build_overlays(_timings(sentences), "OEBPS/audio/book.mp3", tmp_path / "stage")
    output = package_epub(path, audio, sentences, overlays, tmp_path / "result.epub")
    with zipfile.ZipFile(output) as epub:
        root = fromstring(epub.read("OEBPS/Text/ch1.xhtml"))
    assert "".join(root.itertext()) == source
    assert root.find(f".//{{{XHTML_NS}}}em") is not None
    assert root.find(f".//{{{XHTML_NS}}}a").get("href") == "#end"
    anchors = {
        node.get("id"): "".join(node.itertext())
        for node in root.iter(f"{{{XHTML_NS}}}span")
    }
    assert all(anchors[s.anchor_id] == s.text for s in sentences)


@pytest.mark.parametrize(
    "body",
    [
        '<em id="style">First sentence. Second sentence.</em>',
        'First <em id="style">sentence. Second</em> sentence.',
        'First <em id="style"><strong>sentence. Second</strong></em> sentence.',
        '<a id="link" href="#end" class="note">First sentence. Second sentence.</a>',
        'First <a id="link" href="#end" class="note">sentence. Second</a> sentence.',
        'First <em id="style">sentence. Second sentence. Third</em> sentence.',
        'First sentence.<br/><img id="image" src="image.png"/> Second sentence.',
    ],
)
def test_packaged_highlights_are_exact_across_inline_boundaries(
    tmp_path: Path, body: str
) -> None:
    xhtml = f'<html xmlns="{XHTML_NS}"><body><p id="end">{body}</p></body></html>'
    path = book(tmp_path, xhtml=xhtml)
    original = path.read_bytes()
    source = fromstring(xhtml)
    sentences = extract_sentences(path)
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"ID3-audio")
    overlays = build_overlays(_timings(sentences), "OEBPS/audio/book.mp3", tmp_path / "stage")
    output = package_epub(path, audio, sentences, overlays, tmp_path / "result.epub")
    with zipfile.ZipFile(output) as archive:
        root = fromstring(archive.read("OEBPS/Text/ch1.xhtml"))
    assert "".join(root.itertext()) == "".join(source.itertext())
    assert path.read_bytes() == original
    identifiers = [node.get("id") for node in root.iter() if node.get("id")]
    assert len(identifiers) == len(set(identifiers))
    for node in source.iter():
        if node.get("id"):
            assert identifiers.count(node.get("id")) == 1
    generated_ids = {s.anchor_id for s in sentences}
    for sentence in sentences:
        target = next(node for node in root.iter() if node.get("id") == sentence.anchor_id)
        assert "".join(target.itertext()) == sentence.text
        assert not any(node.get("id") in generated_ids for node in list(target.iter())[1:])
    for link in root.iter(f"{{{XHTML_NS}}}a"):
        assert link.get("href") == "#end"
        assert link.get("class") == "note"
    assert len(list(root.iter(f"{{{XHTML_NS}}}img"))) == len(
        list(source.iter(f"{{{XHTML_NS}}}img"))
    )


@pytest.mark.parametrize(
    "language, text, expected",
    [
        ("ja-JP", "これは文です。次の文です！", ["これは文です。", "次の文です！"]),
        ("xx", "First. Second!", ["First. Second!"]),
    ],
)
def test_extract_uses_package_language(
    tmp_path: Path, language: str, text: str, expected: list[str]
) -> None:
    path = book(tmp_path, xhtml=f'<html xmlns="{XHTML_NS}"><body><p>{text}</p></body></html>')
    with zipfile.ZipFile(path) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    metadata = f'<metadata><dc:language xmlns:dc="http://purl.org/dc/elements/1.1/">{language}'
    metadata += '</dc:language></metadata><manifest>'
    parts["OEBPS/content.opf"] = parts["OEBPS/content.opf"].replace(
        b"<manifest>", metadata.encode()
    )
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    assert [sentence.text for sentence in extract_sentences(path)] == expected


def test_review_ready_partial_and_empty() -> None:
    a = Sentence("chapter.xhtml", "a", "One.", 0, 4)
    b = Sentence("chapter.xhtml", "b", "Two.", 5, 9)
    timings = (SentenceTiming(a, 0, 1), SentenceTiming(b, 2, 3))
    assert review_alignment((a, b), timings).status == "ready"
    partial = review_alignment((a, b), (SentenceTiming(a, 0, 1),))
    assert (partial.status, partial.matched_sentences, partial.total_sentences) == ("partial", 1, 2)
    assert review_alignment((), ()).status == "rejected"


@pytest.mark.parametrize(
    "timings",
    [
        ((0, 2), (1, 3)),  # overlap
        ((0, 1), (-1, 2)),  # negative start
        ((0, 1), (2, 2)),  # zero duration
        ((0, 1), (float("nan"), 3)),
    ],
)
def test_review_rejects_bad_intervals(timings: tuple[tuple[float, float], ...]) -> None:
    a = Sentence("ch", "a", "One", 0, 3)
    b = Sentence("ch", "b", "Two", 4, 7)
    result = review_alignment(
        (a, b), (SentenceTiming(a, *timings[0]), SentenceTiming(b, *timings[1]))
    )
    assert result.status == "rejected"
    assert result.issues


def test_review_rejects_duplicate_unknown_and_reordered_sentences() -> None:
    a = Sentence("ch", "a", "One", 0, 3)
    b = Sentence("ch", "b", "Two", 4, 7)
    outsider = Sentence("ch", "c", "Three", 8, 13)
    for timings in (
        (SentenceTiming(a, 0, 1), SentenceTiming(a, 2, 3)),
        (SentenceTiming(a, 0, 1), SentenceTiming(outsider, 2, 3)),
        (SentenceTiming(b, 0, 1), SentenceTiming(a, 2, 3)),
    ):
        assert review_alignment((a, b), timings).status == "rejected"


def _spoken(text: str, start: float, end: float) -> TranscriptSegment:
    step = (end - start) / max(len(text.split()), 1)
    words = tuple(
        WordTiming(word, start + i * step, start + (i + 1) * step)
        for i, word in enumerate(text.split())
    )
    return TranscriptSegment(text, start, end, words)


def test_locate_skips_intro_and_keeps_reading_order() -> None:
    sentences = (
        Sentence("ch.xhtml", "a", "The wind blew.", 0, 13),
        Sentence("ch.xhtml", "b", "It was cold.", 14, 26),
    )
    transcript = (
        _spoken("this is a publisher introduction", 0.0, 2.0),
        _spoken("the wind blew", 2.0, 3.0),
        _spoken("it was cold", 3.0, 4.0),
    )

    passages = locate_passages(sentences, transcript)

    assert [passage.sentence for passage in passages] == list(sentences)
    assert passages[0].start == pytest.approx(2.0)
    assert passages[1].end == pytest.approx(4.0)
    assert review_alignment(sentences, ()).status == "partial"


def test_locate_drops_words_that_do_not_appear() -> None:
    sentence = Sentence("ch.xhtml", "a", "A completely different passage.", 0, 30)
    transcript = (_spoken("the wind blew", 0.0, 1.0),)
    assert locate_passages((sentence,), transcript) == ()


def test_align_refines_to_matched_words_and_drops_weak(tmp_path: Path) -> None:
    audio = tmp_path / "book.mp3"
    audio.write_bytes(b"audio")
    good = Sentence("ch.xhtml", "a", "The wind blew.", 0, 13)
    weak = Sentence("ch.xhtml", "b", "It was cold.", 14, 26)
    matches = (
        PassageMatch(
            good,
            1.7,
            3.1,
            (
                WordTiming("noise", 1.7, 1.8),
                WordTiming("the", 2.0, 2.2),
                WordTiming("wind", 2.2, 2.5),
                WordTiming("blew", 2.5, 2.9),
            ),
        ),
        PassageMatch(weak, 3.0, 4.0, (WordTiming("cold", 3.5, 3.8),)),
    )

    timings = align_sentences(audio, matches)

    assert [timing.sentence for timing in timings] == [good]
    assert (timings[0].start, timings[0].end) == (2.0, 2.9)


def test_align_requires_an_audio_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        align_sentences(tmp_path / "missing.mp3", ())


def test_transcribe_maps_faster_whisper_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: dict[str, object] = {}

    class FakeWord:
        def __init__(self, word: str, start: float, end: float) -> None:
            self.word, self.start, self.end = word, start, end

    class FakeSegment:
        text = "Hello world"
        start = 0.0
        end = 1.0
        words = [FakeWord("Hello", 0.0, 0.4), FakeWord("world", 0.4, 1.0)]

    class FakeModel:
        def __init__(self, model: str, device: str, compute_type: str) -> None:
            calls["init"] = (model, device, compute_type)

        def transcribe(self, path: str, **kwargs: object):
            calls["transcribe"] = (path, kwargs)
            return iter([FakeSegment()]), object()

    module = types.ModuleType("faster_whisper")
    module.WhisperModel = FakeModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", module)

    options = TranscriptionOptions(model="tiny.en")
    segments = transcribe_audio(tmp_path / "book.mp3", options=options)

    assert segments[0].text == "Hello world"
    assert segments[0].words == (WordTiming("Hello", 0.0, 0.4), WordTiming("world", 0.4, 1.0))
    assert calls["init"] == ("tiny.en", "cpu", "int8")
    assert calls["transcribe"][1]["word_timestamps"] is True  # type: ignore[index]


def test_transcribe_without_dependency_explains_the_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    with pytest.raises(RuntimeError, match="transcribe"):
        transcribe_audio(tmp_path / "book.mp3")


def _timings(sentences: tuple[Sentence, ...]) -> tuple[SentenceTiming, ...]:
    return tuple(
        SentenceTiming(sentence, index * 1.0, index * 1.0 + 0.5)
        for index, sentence in enumerate(sentences)
    )


def test_build_overlays_writes_smil(tmp_path: Path) -> None:
    sentences = (Sentence("OEBPS/Text/ch1.xhtml", "s1", "Hello.", 0, 6),)
    overlays = build_overlays(_timings(sentences), "OEBPS/audio/book.mp3", tmp_path / "stage")

    assert len(overlays) == 1
    assert overlays[0] == tmp_path / "stage" / "OEBPS" / "Text" / "ch1.smil"
    root = fromstring(overlays[0].read_bytes())
    text = root.find(f".//{{{SMIL_NS}}}text")
    audio = root.find(f".//{{{SMIL_NS}}}audio")
    assert text is not None and text.get("src") == "ch1.xhtml#s1"
    assert audio is not None and audio.get("src") == "../audio/book.mp3"
    assert audio.get("clipBegin") == "00:00:00.000"
    assert audio.get("clipEnd") == "00:00:00.500"


def test_package_epub_end_to_end(tmp_path: Path) -> None:
    path = book(tmp_path)
    original = path.read_bytes()
    sentences = extract_sentences(path)
    audio_name = "OEBPS/audio/book.mp3"
    overlays = build_overlays(_timings(sentences), audio_name, tmp_path / "stage")
    audio = tmp_path / "book.mp3"
    audio.write_bytes(b"ID3-audio")
    output = tmp_path / "out.epub"

    assert package_epub(path, audio, sentences, overlays, output) == output

    with zipfile.ZipFile(path) as source:
        source_root = fromstring(source.read("OEBPS/Text/ch1.xhtml"))
    source_text = "".join(source_root.itertext())

    with zipfile.ZipFile(output) as archive:
        assert archive.infolist()[0].filename == "mimetype"
        assert archive.infolist()[0].compress_type == zipfile.ZIP_STORED
        names = set(archive.namelist())
        assert {"OEBPS/Text/ch1.smil", audio_name, "OEBPS/content.opf"} <= names

        packaged_root = fromstring(archive.read("OEBPS/Text/ch1.xhtml"))
        assert "".join(packaged_root.itertext()) == source_text
        anchors = {
            element.get("id"): "".join(element.itertext())
            for element in packaged_root.iter(f"{{{XHTML_NS}}}span")
        }
        for sentence in sentences:
            assert anchors[sentence.anchor_id] == sentence.text

        package = fromstring(archive.read("OEBPS/content.opf"))
        items = package.findall(f".//{{{OPF_NS}}}item")
        content_item = next(item for item in items if item.get("href") == "Text/ch1.xhtml")
        overlay_id = content_item.get("media-overlay")
        assert overlay_id
        overlay_item = next(item for item in items if item.get("id") == overlay_id)
        assert overlay_item.get("href") == "Text/ch1.smil"
        assert package.find(f".//{{{OPF_NS}}}itemref").get("media-overlay") is None
        hrefs = {item.get("id"): item.get("href") for item in items}
        assert any(value == "audio/book.mp3" for value in hrefs.values())
        assert package.find(f".//{{{OPF_NS}}}meta[@property='media:duration']") is not None
        smil = fromstring(archive.read("OEBPS/Text/ch1.smil"))
        assert smil.find(f".//{{{SMIL_NS}}}par") is not None

    assert path.read_bytes() == original


def test_overlay_archive_path_keeps_directory() -> None:
    assert overlay_archive_path("OEBPS/Text/ch1.xhtml") == "OEBPS/Text/ch1.smil"
    assert overlay_archive_path("ch1.xhtml") == "ch1.smil"
