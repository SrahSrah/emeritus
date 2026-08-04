"""Step 27 — FR-22: chunking that loses nothing.

The load-bearing case is `reconstruct`. Everything else about chunking can look right in
a spot check while an off-by-one in the overlap quietly drops or duplicates text, and
that only shows up much later as retrieval that misses things for no visible reason.
"""

from __future__ import annotations

import pytest

from forecaster.memory.corpus import Chunk, chunk_article, reconstruct
from forecaster.tools.feeds import extract_body
from tests.conftest import load_text_fixture

TARGET = 900
MAX = 1200
OVERLAP = 150

HEADLINE = "A headline that says what the article is about"


def _body(paragraphs: int, sentence: str = "This is a sentence of a reasonable length. ") -> str:
    return "\n\n".join((sentence * 5).strip() for _ in range(paragraphs))


def _chunk(body: str, **overrides) -> list[Chunk]:
    settings = {"target_chars": TARGET, "max_chars": MAX, "overlap_chars": OVERLAP}
    settings.update(overrides)
    return chunk_article(HEADLINE, body, **settings)


# --------------------------------------------------------------------------- #
# The invariant that matters
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("paragraphs", [1, 2, 3, 7, 20, 50])
def test_chunks_reconstruct_the_body_byte_for_byte(paragraphs: int) -> None:
    """The assertion that catches an off-by-one in the overlap arithmetic."""
    body = _body(paragraphs)
    chunks = _chunk(body)

    assert reconstruct(body, chunks) == body


def test_a_real_article_reconstructs_byte_for_byte() -> None:
    """Same invariant, over prose nobody wrote to be convenient."""
    body = extract_body(load_text_fixture("article_arstechnica.html"))
    chunks = _chunk(body)

    assert len(chunks) > 1, f"a {len(body)}-char body should not be one chunk"
    assert reconstruct(body, chunks) == body


def test_a_single_paragraph_longer_than_max_still_reconstructs() -> None:
    """The hard-cut path is ugly, but it may not lose a character."""
    body = "word " * 2000  # one paragraph, ~10,000 chars, no blank lines
    chunks = _chunk(body)

    assert len(chunks) > 5
    assert all(len(c.body_text) <= MAX for c in chunks)
    assert reconstruct(body, chunks) == body


# --------------------------------------------------------------------------- #
# Size and overlap
# --------------------------------------------------------------------------- #


def test_no_chunk_exceeds_max_chars() -> None:
    body = extract_body(load_text_fixture("article_arstechnica.html"))
    for chunk in _chunk(body):
        assert len(chunk.body_text) <= MAX, f"chunk {chunk.ordinal} is {len(chunk.body_text)}"


def test_every_chunk_after_the_first_carries_the_previous_tail() -> None:
    """The overlap is what keeps a sentence split across a boundary retrievable."""
    body = _body(20)
    chunks = _chunk(body)
    assert len(chunks) > 2

    for previous, current in zip(chunks, chunks[1:]):
        carried = current.char_start
        assert carried < previous.char_end, "chunks must overlap, not abut"
        assert previous.char_end - carried <= OVERLAP


def test_a_short_body_yields_exactly_one_chunk() -> None:
    """The feed-summary case. It needs no special handling downstream because of this."""
    chunks = _chunk("A four hundred character summary. " * 12)

    assert len(chunks) == 1
    assert chunks[0].ordinal == 0
    assert chunks[0].char_start == 0


def test_an_empty_body_yields_no_chunks() -> None:
    assert _chunk("") == []


def test_ordinals_are_dense_and_ordered() -> None:
    chunks = _chunk(_body(20))
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


# --------------------------------------------------------------------------- #
# The headline prefix
# --------------------------------------------------------------------------- #


def test_every_chunk_text_starts_with_the_headline() -> None:
    """A mid-article chunk carries no subject on its own, and the embedder infers little."""
    for chunk in _chunk(_body(20)):
        assert chunk.text.startswith(HEADLINE + "\n")


def test_the_headline_is_not_counted_in_the_offsets() -> None:
    """Offsets index the body alone — this is what makes reconstruction possible."""
    body = _body(10)
    for chunk in _chunk(body):
        assert body[chunk.char_start : chunk.char_end] == chunk.body_text
        assert HEADLINE not in chunk.body_text


def test_a_chunk_with_no_headline_is_just_its_body() -> None:
    chunk = Chunk(ordinal=0, body_text="text", char_start=0, char_end=4)
    assert chunk.text == "text"


# --------------------------------------------------------------------------- #
# Splitting behaviour
# --------------------------------------------------------------------------- #


def test_splits_prefer_paragraph_boundaries() -> None:
    """A chunk should end where a paragraph ends, when it can."""
    body = _body(20)
    boundaries = {0}
    position = 0
    for paragraph in body.split("\n\n"):
        position += len(paragraph) + 2
        boundaries.add(min(position, len(body)))

    chunks = _chunk(body)
    aligned = sum(1 for c in chunks if c.char_end in boundaries)
    assert aligned == len(chunks), "every chunk of a clean paragraph body should align"


def test_a_long_paragraph_prefers_a_sentence_boundary() -> None:
    body = "Sentence one is here. " * 200
    chunks = _chunk(body)

    ends_mid_word = [
        c for c in chunks[:-1] if not c.body_text.rstrip().endswith((".", "!", "?"))
    ]
    assert ends_mid_word == [], "a sentence boundary was available and should have been used"


def test_invalid_settings_raise_rather_than_looping_forever() -> None:
    with pytest.raises(ValueError, match="never advances"):
        _chunk(_body(5), overlap_chars=TARGET)
    with pytest.raises(ValueError, match="at least target_chars"):
        _chunk(_body(5), max_chars=TARGET - 1)
