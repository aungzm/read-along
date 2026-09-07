from __future__ import annotations

import pytest

from app.sentences import SentenceSegmenter


@pytest.mark.parametrize(
    "expected",
    [
        ["Mme. Sofronie sold hair.", "Mlle. Dupont left."],
        ["Dr. Watson met Mr. Holmes.", "They left."],
        ["J. R. R. Tolkien wrote books.", "Read them."],
        ["He paid 3.50 dollars.", "Then left."],
        ["He bought bread, etc.", "Then he left."],
        ["Wait... what happened?", "Stop!"],
        ['“No!” she said.', '“Go.”'],
        ["No!", "Go!", "No!"],
        ["Same sentence.", "Same sentence."],
        [
            'Where she stopped the sign read: “Mme. Sofronie. Hair Goods of All Kinds.”',
            "One flight up Della ran.",
        ],
    ],
)
def test_book_passages_preserve_boundaries_and_offsets(expected: list[str]) -> None:
    text = "  " + " \n\t".join(expected) + "  "
    spans = SentenceSegmenter("en-US").spans(text)
    assert [text[start:end] for start, end in spans] == expected
    assert all(left[1] <= right[0] for left, right in zip(spans, spans[1:], strict=False))
    # Every character outside a returned span must be whitespace.
    covered = {index for start, end in spans for index in range(start, end)}
    assert all(char.isspace() or index in covered for index, char in enumerate(text))


def test_language_specific_boundaries() -> None:
    text = "これは文です。次の文です！"
    spans = SentenceSegmenter("ja-JP").spans(text)
    assert [text[start:end] for start, end in spans] == ["これは文です。", "次の文です！"]


def test_unknown_language_keeps_block_and_missing_language_defaults_to_english() -> None:
    text = "  Dr. Watson left. Holmes stayed.  "
    assert SentenceSegmenter("xx").spans(text) == [(2, len(text) - 2)]
    spans = SentenceSegmenter(None).spans(text)
    assert [text[start:end] for start, end in spans] == ["Dr. Watson left.", "Holmes stayed."]
    assert SentenceSegmenter("en").spans(" \n ") == []
