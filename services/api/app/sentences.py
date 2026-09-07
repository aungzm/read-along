"""Sentence boundaries in original EPUB text, without normalizing its contents."""

from __future__ import annotations

import re

import pysbd
from pysbd.languages import LANGUAGE_CODES

from .epub import EpubError

# Supplement pySBD's English rules for titles borrowed from French. Only veto
# a boundary directly after the title, never punctuation after a closing quote.
_TITLE_END = re.compile(r"\b(?:Mme|Mmes|Mlle|Mlles)\.\s*$", re.IGNORECASE)


class SentenceSegmenter:
    def __init__(self, language: str | None) -> None:
        # Missing language preserves the application's historical English default.
        code = (language or "en").strip().lower().replace("_", "-").split("-")[0]
        self.language = code
        self.engine = (
            pysbd.Segmenter(language=code, clean=False, char_span=True)
            if code in LANGUAGE_CODES
            else None
        )

    def spans(self, text: str) -> list[tuple[int, int]]:
        """Return trimmed, ordered spans. Unsupported languages retain whole blocks."""
        spans: list[tuple[int, int]] = []
        candidates = (
            [(span.start, span.end) for span in self.engine.segment(text)]
            if self.engine is not None
            else [(0, len(text))]
        )
        previous_end = 0
        for start, end in candidates:
            if not previous_end <= start <= end <= len(text) or text[previous_end:start].strip():
                raise EpubError("Sentence segmentation lost or reordered source text.")
            previous_end = end
            part = text[start:end]
            beginning = start + len(part) - len(part.lstrip())
            finish = end - (len(part) - len(part.rstrip()))
            if beginning >= finish:
                continue
            if (
                spans
                and self.language == "en"
                and _TITLE_END.search(text[spans[-1][0] : spans[-1][1]])
                and text[beginning].isalpha()
            ):
                spans[-1] = (spans[-1][0], finish)
            else:
                spans.append((beginning, finish))
        if text[previous_end:].strip():
            raise EpubError("Sentence segmentation lost source text.")
        return spans
