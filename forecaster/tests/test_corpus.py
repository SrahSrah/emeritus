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


# --------------------------------------------------------------------------- #
# Step 28 — FR-23: the store, and its separation from the ledger
# --------------------------------------------------------------------------- #


def _entry(url: str, *, published: str = "2026-08-03T14:30:00+00:00", body: str | None = None):
    from datetime import datetime

    from forecaster.tools.feeds import SOURCE_ARTICLE, FeedEntry

    return FeedEntry(
        url=url,
        source="Ars Technica",
        headline=HEADLINE,
        published=datetime.fromisoformat(published),
        summary="short",
        body=body if body is not None else _body(8),
        text_source=SOURCE_ARTICLE,
    )


def _corpus(tmp_path):
    from forecaster.memory.corpus import connect

    return connect(tmp_path / "corpus.db")


def _embedder():
    from forecaster.memory.retrieval import HashingEmbedder

    return HashingEmbedder()


def test_indexing_writes_one_chunk_row_and_one_vector_per_chunk(tmp_path) -> None:
    from forecaster.memory.corpus import (
        article_count,
        chunk_count,
        index_article,
        vector_count,
    )

    conn = _corpus(tmp_path)
    entry = _entry("https://a.test/one")
    chunks = _chunk(entry.body)

    written = index_article(conn, entry, chunks, _embedder())

    assert written == len(chunks) > 1
    assert article_count(conn) == 1
    assert chunk_count(conn) == len(chunks)
    assert vector_count(conn) == len(chunks)


def test_reindexing_the_same_url_replaces_rather_than_duplicates(tmp_path) -> None:
    """An article fetched two nights running is one article, not two."""
    from forecaster.memory.corpus import (
        article_count,
        chunk_count,
        index_article,
        vector_count,
    )

    conn = _corpus(tmp_path)
    entry = _entry("https://a.test/one")
    chunks = _chunk(entry.body)
    embedder = _embedder()

    index_article(conn, entry, chunks, embedder)
    first_chunks = chunk_count(conn)
    index_article(conn, entry, chunks, embedder)

    assert article_count(conn) == 1
    assert chunk_count(conn) == first_chunks
    assert vector_count(conn) == first_chunks


def test_purge_removes_expired_articles_and_their_vectors(tmp_path) -> None:
    from datetime import datetime, timedelta, timezone

    from forecaster.memory.corpus import (
        article_count,
        chunk_count,
        index_article,
        purge_expired,
        vector_count,
    )

    conn = _corpus(tmp_path)
    now = datetime(2026, 8, 4, 19, 0, tzinfo=timezone.utc)
    embedder = _embedder()

    old = _entry("https://a.test/old")
    fresh = _entry("https://a.test/fresh")
    index_article(conn, old, _chunk(old.body), embedder, fetched_at=now - timedelta(days=9))
    index_article(conn, fresh, _chunk(fresh.body), embedder, fetched_at=now)
    total_chunks = chunk_count(conn)

    removed = purge_expired(conn, ttl_days=7, now=now)

    assert removed == 1
    assert article_count(conn) == 1
    assert chunk_count(conn) < total_chunks
    assert vector_count(conn) == chunk_count(conn), "no vector may outlive its chunk row"


def test_purge_on_an_empty_corpus_is_a_no_op(tmp_path) -> None:
    from datetime import datetime, timezone

    from forecaster.memory.corpus import purge_expired

    conn = _corpus(tmp_path)
    assert purge_expired(conn, ttl_days=7, now=datetime(2026, 8, 4, tzinfo=timezone.utc)) == 0


def test_the_corpus_never_touches_the_ledger(tmp_path) -> None:
    """FR-23's separation, asserted rather than asserted-in-prose."""
    from forecaster.memory.corpus import index_article, purge_expired
    from forecaster.memory.ledger import all_rows, connect as connect_ledger

    from datetime import datetime, timezone

    ledger_path = tmp_path / "ledger.db"
    ledger = connect_ledger(ledger_path)
    ledger.execute(
        "INSERT INTO sent_items (run_id, beat, sent_at, rendered_text, "
        "source_observation_id, checkable_fields) VALUES (?,?,?,?,?,?)",
        ("run-1", "astros", "2026-08-03T19:00:00", "Final: 4-2.", "obs-1", "{}"),
    )
    ledger.commit()
    before = len(all_rows(connection=ledger))

    conn = _corpus(tmp_path)
    entry = _entry("https://a.test/one")
    index_article(conn, entry, _chunk(entry.body), _embedder())
    purge_expired(conn, ttl_days=7, now=datetime(2026, 8, 4, tzinfo=timezone.utc))

    assert len(all_rows(connection=ledger)) == before
    assert (tmp_path / "corpus.db").exists()
    assert (tmp_path / "corpus.db") != ledger_path


def test_corpus_module_never_imports_or_opens_the_ledger() -> None:
    """Structural guard, matching the one test_ledger.py already keeps over identity.

    Reads the AST rather than the file text, because the module docstring *should* name
    `ledger.db` — explaining why the two corpora live in separate files is exactly the
    documentation that ought to exist. What may not exist is code that opens it.
    """
    import ast
    from pathlib import Path as _Path

    source = (
        _Path(__file__).resolve().parent.parent / "forecaster" / "memory" / "corpus.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    assert not any("ledger" in module for module in imported), imported

    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]

    offenders = [
        literal
        for literal in literals
        if "ledger.db" in literal or "sent_items" in literal
    ]
    assert offenders == [], f"corpus.py names the ledger in live code: {offenders}"


def test_an_article_with_no_chunks_still_records_the_article(tmp_path) -> None:
    """A body that extracted to nothing is a fact about the article, not a reason to lose it."""
    from forecaster.memory.corpus import article_count, chunk_count, index_article

    conn = _corpus(tmp_path)
    written = index_article(conn, _entry("https://a.test/empty", body=""), [], _embedder())

    assert written == 0
    assert article_count(conn) == 1
    assert chunk_count(conn) == 0
