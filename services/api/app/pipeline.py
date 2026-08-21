"""Contracts for the planned sentence-level read-along pipeline.

This module is not used by the running job worker yet. Each function raises
``NotImplementedError`` until its stage is built and tested. Keeping the
intermediate data independent of SMIL lets us change alignment backends without
changing the EPUB writer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


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
class TranscriptSegment:
    """A rough audio transcription with seconds relative to the source file."""

    text: str
    start: float
    end: float


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

    ``start`` and ``end`` are rough bounds in seconds. An unmatched sentence
    has no match rather than an invented position in the recording.
    """

    sentence: Sentence
    start: float
    end: float


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


def extract_sentences(epub_path: Path) -> tuple[Sentence, ...]:
    """Read spine XHTML in order and assign stable sentence anchors.

    Resolve OPF manifest entries relative to the package document. Skip
    non-narrative spine items and retain enough location information to insert
    sentence IDs in the packaged EPUB. Do not rewrite the uploaded EPUB. Keep
    each sentence inside one block element; handle inline elements such as
    ``em`` and ``a`` without dropping their markup. This extends
    ``epub.inspect_epub`` beyond metadata.
    """

    raise NotImplementedError("Spine text extraction is not implemented.")


def transcribe_audio(
    audio_path: Path, *, options: TranscriptionOptions = TranscriptionOptions()
) -> tuple[TranscriptSegment, ...]:
    """Transcribe one audiobook file into rough timestamped speech segments.

    Planned backend: faster-whisper (CTranslate2), with PyAV for decoding and
    optional voice activity detection. Iterate its segment generator to run
    inference. Preserve offsets relative to the original file and leave intros
    or other unmatched speech in the transcript. These rough timestamps locate
    passages; they are not final sentence highlight times. Keep the model
    loaded across segments or jobs instead of loading it once per chunk.
    """

    raise NotImplementedError("Audio transcription is not implemented.")


def locate_passages(
    sentences: tuple[Sentence, ...],
    transcript: tuple[TranscriptSegment, ...],
) -> tuple[PassageMatch, ...]:
    """Find rough audio windows for book sentences despite edition differences.

    Match normalized text in reading order while allowing skipped text and
    audio-only speech. Return only matches backed by evidence. Leave weak or
    ambiguous sentences out so the review stage can report missing coverage.
    """

    raise NotImplementedError("Passage location is not implemented.")


def align_sentences(
    audio_path: Path, matches: tuple[PassageMatch, ...]
) -> tuple[SentenceTiming, ...]:
    """Refine matched windows to sentence start and end times.

    Use a replaceable acoustic alignment backend. Keep timestamps relative to
    the original single audio file. Do not assign timings to unmatched text or
    silently interpolate across gaps.
    """

    raise NotImplementedError("Sentence alignment is not implemented.")


def review_alignment(
    sentences: tuple[Sentence, ...], timings: tuple[SentenceTiming, ...]
) -> AlignmentReport:
    """Check coverage, order, gaps, and durations before building an EPUB.

    Report unmatched sentences and suspect intervals. Mark complete, reliable
    work ``ready``; return ``partial`` or ``rejected`` otherwise. Thresholds
    need evaluation on real book/audio pairs before they are set.
    """

    raise NotImplementedError("Alignment review is not implemented.")


def build_overlays(
    timings: tuple[SentenceTiming, ...], audio_name: str, output_dir: Path
) -> tuple[Path, ...]:
    """Write SMIL documents mapping XHTML sentence IDs to audio clip ranges.

    Use EPUB Media Overlay ``par`` elements to pair text references with audio
    clipBegin/clipEnd. Keep paths relative to the eventual EPUB layout. Only
    call this after a ``ready`` review; a partial result needs explicit review.
    """

    raise NotImplementedError("Media Overlay generation is not implemented.")


def package_epub(
    epub_path: Path,
    audio_path: Path,
    sentences: tuple[Sentence, ...],
    overlays: tuple[Path, ...],
    output_path: Path,
) -> Path:
    """Copy the original EPUB, add sentence anchors, audio, and SMIL, then validate.

    Update the OPF manifest, Media Overlay associations, and duration metadata.
    Preserve other book resources and never change the uploaded original. Check
    the result with EPUBCheck before exposing ``output_path`` for download.
    """

    raise NotImplementedError("EPUB packaging is not implemented.")
