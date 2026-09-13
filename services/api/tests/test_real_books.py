from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from support import epub_bytes, saved_transcriber

from benchmarks.real_books import PAIRS, prepare, validate_result


def test_prepare_selects_story_after_contents_and_preserves_original(tmp_path: Path) -> None:
    pair = PAIRS[1]
    original = "THE TELL-TALE HEART.\nBERENICE\n\nTHE TELL-TALE HEART.\n\n"
    original += "\n\n".join(f"Story paragraph {i}." for i in range(12))
    original += "\nBERENICE\nOther story."
    (tmp_path / "original.txt").write_text(original, encoding="utf-8")
    (tmp_path / "audio.mp3").write_bytes(b"cached audio")

    prepare(pair, tmp_path)

    assert (tmp_path / "original.txt").read_text(encoding="utf-8") == original
    with zipfile.ZipFile(tmp_path / "book.epub") as epub:
        story = epub.read("story.xhtml").decode()
        assert "Story paragraph 0." in story
        assert "Story paragraph 11." in story
        assert "Other story" not in story
        assert "BERENICE" not in story
        assert epub.infolist()[0].filename == "mimetype"


@pytest.mark.parametrize("anchor", ["sentence", "missing"])
def test_validate_download_resolves_sentence_anchors(tmp_path: Path, anchor: str) -> None:
    path = tmp_path / "result.epub"
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("story.xhtml", '<html><body><p id="sentence">Hello.</p></body></html>')
        epub.writestr("audio.mp3", b"audio")
        epub.writestr("story.smil", f'''<smil><body><seq><par>
          <text src="story.xhtml#{anchor}"/>
          <audio src="audio.mp3" clipBegin="00:00:00.000" clipEnd="00:00:01.000"/>
          </par></seq></body></smil>''')
    if anchor == "missing":
        with pytest.raises(AssertionError, match="Missing sentence anchor"):
            validate_result(path)
    else:
        validate_result(path)


def test_benchmark_collects_transcript_from_worker_process(tmp_path: Path, monkeypatch) -> None:
    from benchmarks import real_books

    (tmp_path / "book.epub").write_bytes(epub_bytes())
    (tmp_path / "audio.mp3").write_bytes(b"audio")
    monkeypatch.setattr(real_books, "transcribe_fixture", saved_transcriber)
    report = real_books.run(tmp_path, timeout=15)
    assert report["passed"]
    assert report["coverage"] == 1
    assert len(report["timings"]) == 3
    assert (tmp_path / "transcript.json").exists()
    validate_result(tmp_path / "result.epub")
