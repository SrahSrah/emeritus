"""Article chunks: the corpus, and the chunking that fills it (FR-22, FR-23, FR-24).

This is the first place in the project where retrieval runs over documents Sarah did not
write. FR-9b's corpus is the sent-item ledger, whose records are single delivered
sentences — one line is one atomic record, so it needed no chunking at all, and
Checkpoint 3 said as much ("How did I chunk it? I didn't"). Articles are different, and
this module is the difference.

## The three parts

1. **Chunking** (FR-22) — pure functions, no I/O. Paragraph-aware, with overlap, and a
   headline prefix on every chunk.
2. **The corpus** (FR-23) — a **separate** SQLite file from `ledger.db`, with its own
   lifecycle.
3. **Topic retrieval** (FR-24) — a query goes in, passages come out.

## Why the corpus is a separate file

The two corpora have opposite lifecycles. `sent_items` is the permanent record of what
was actually delivered and **cannot be rebuilt** if it is lost. Article chunks are
disposable and reconstructible from the feeds in a single run. At roughly 40 articles a
night times 5 chunks times a 7-day TTL, the chunk corpus is ~1,400 vectors against the
ledger's ~35 a week — sharing the file would have the disposable corpus dwarfing the
durable one. A corpus you can delete without losing anything does not belong in the file
holding the record you cannot rebuild.

Both use the **same `Embedder` instance**, passed in, so the model loads once per run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

#: Sentence-ish boundaries, used only when a single paragraph exceeds `max_chars`.
_SENTENCE_END = re.compile(r"[.!?][\"')\]]?\s")


@dataclass(frozen=True)
class Chunk:
    """One retrievable passage of an article.

    ``body_text`` is the raw slice of the article body; ``char_start`` and ``char_end``
    index into that body and **exclude** the headline prefix. Keeping the two apart is
    what makes the round-trip assertion in the tests possible — an off-by-one in the
    overlap arithmetic is otherwise invisible until retrieval quality quietly degrades.

    ``text`` is what gets embedded and stored: the headline on its own line, then the
    body slice. The prefix matters because a mid-article chunk carries no subject on its
    own, and the shipped embedder is close to a bag of words — the parent build measured
    cosine 0.9859 between two different Astros scores, so it is not a model that infers
    much from context.
    """

    ordinal: int
    body_text: str
    char_start: int
    char_end: int
    headline: str = ""

    @property
    def text(self) -> str:
        if not self.headline:
            return self.body_text
        return f"{self.headline}\n{self.body_text}"


def _paragraph_spans(body: str) -> list[tuple[int, int]]:
    """Contiguous ``(start, end)`` spans, one per paragraph.

    Contiguous on purpose: the separator between two paragraphs belongs to the one before
    it, so the spans tile the body with no gaps and
    ``"".join(body[s:e] for s, e in spans) == body``. Reconstruction depends on that.
    """
    if not body:
        return []
    boundaries = [match.end() for match in re.finditer(r"\n\s*\n", body)]
    spans: list[tuple[int, int]] = []
    cursor = 0
    for boundary in boundaries:
        spans.append((cursor, boundary))
        cursor = boundary
    spans.append((cursor, len(body)))
    return [(start, end) for start, end in spans if end > start]


def _split_long_paragraph(body: str, start: int, limit: int) -> int:
    """Where to cut a single paragraph that is longer than ``max_chars`` on its own.

    Prefers a sentence boundary, falls back to whitespace, and hard-cuts only when the
    text offers neither. A hard cut is ugly but honest — it never drops or reorders a
    character, which is what the reconstruction assertion checks.
    """
    ceiling = min(start + limit, len(body))
    window = body[start:ceiling]

    sentence_ends = [match.end() for match in _SENTENCE_END.finditer(window)]
    if sentence_ends:
        return start + sentence_ends[-1]

    space = window.rfind(" ")
    if space > 0:
        return start + space + 1

    return ceiling


def chunk_article(
    headline: str,
    body: str,
    *,
    target_chars: int,
    max_chars: int,
    overlap_chars: int,
) -> list[Chunk]:
    """Split an article body into overlapping, paragraph-aligned chunks.

    A body at or under ``target_chars`` comes back as exactly one chunk — which is the
    normal case for an entry that fell back to its feed summary, and the reason the
    summary path needs no special handling downstream.
    """
    if not body:
        return []
    if max_chars < target_chars:
        raise ValueError("max_chars must be at least target_chars")
    if overlap_chars >= target_chars:
        raise ValueError(
            "overlap_chars must be less than target_chars, or chunking never advances"
        )

    spans = _paragraph_spans(body)
    chunks: list[Chunk] = []
    cursor = 0
    ordinal = 0

    while cursor < len(body):
        end = cursor
        for span_start, span_end in spans:
            if span_end <= cursor:
                continue
            candidate = span_end
            if candidate - cursor > max_chars:
                break
            end = candidate
            if end - cursor >= target_chars:
                break

        if end <= cursor:
            # One paragraph is longer than max_chars all by itself.
            end = _split_long_paragraph(body, cursor, max_chars)

        chunks.append(
            Chunk(
                ordinal=ordinal,
                body_text=body[cursor:end],
                char_start=cursor,
                char_end=end,
                headline=headline,
            )
        )
        ordinal += 1

        if end >= len(body):
            break
        cursor = max(end - overlap_chars, cursor + 1)

    return chunks


def reconstruct(body: str, chunks: Sequence[Chunk]) -> str:
    """Rebuild the source body from chunk offsets, counting overlaps once.

    Lives here rather than only in the tests because it *is* the definition of a correct
    chunking: whatever the overlap arithmetic does, no character may be lost, duplicated
    into the wrong place, or reordered.
    """
    parts: list[str] = []
    covered_to = 0
    for chunk in sorted(chunks, key=lambda c: c.ordinal):
        if chunk.char_end <= covered_to:
            continue
        parts.append(body[max(chunk.char_start, covered_to) : chunk.char_end])
        covered_to = chunk.char_end
    return "".join(parts)


__all__ = [
    "Chunk",
    "chunk_article",
    "reconstruct",
]
