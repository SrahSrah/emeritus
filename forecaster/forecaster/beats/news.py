"""AI news beat (FR-25) — the first beat whose items are written, not assembled.

Every other beat in this project turns a typed API response into a sentence in code. This
one retrieves passages out of a multi-day corpus of article text and asks the model to
phrase them. That difference is the whole point of the increment, and it is also what
required two safety mechanisms to grow:

- **FR-26** — `check_provenance` gained a case, because neither the support check (which
  reads declared `checkable_fields`) nor the fidelity check (which catches an *altered*
  number) can see a number the model **invented** into a sentence. Every number and quote
  in this beat's item text must trace to a chunk observation.
- **FR-27** — FR-19's first invariant inverts here. For a status beat, identical wording
  on a different day means a different fact; for news, the same story on a different day
  *is* the repeat. The veto reads the prose instead of typed fields.

## Why retrieval is necessary here, and was not for the other beats

One night's articles could be handed to the model directly. It is the **multi-day** corpus
that forces retrieval: at roughly 40 articles a night over a 7-day TTL, ~1,400 chunks is
on the order of 350k tokens, and the nightly run shares subscription rolling-window limits
with interactive Claude Code use. The vector index is not decoration on a single night's
fetch; it is what makes a week of context affordable.

## The run

purge → fetch feeds → filter to the window → fetch article bodies → chunk → index → one
retrieval per configured topic → one item per topic that found anything.

Each retrieved chunk is written to the trace as **its own observation**, and the item
points at every chunk it was grounded in. That is what makes FR-26 computable and the
§2(b) attribution metric non-vacuous.
"""

from __future__ import annotations

from typing import Any

from forecaster.agent import DEFAULT_EFFORT
from forecaster.beats.base import (
    BeatContext,
    BeatItem,
    BeatResult,
    ObservationRef,
    register_beat,
)
from forecaster.memory import corpus as corpus_module
from forecaster.tools import feeds
from forecaster.trace import SYNTHESIZED

ADAPTER_FEED = "feeds.fetch_feed"
ADAPTER_ARTICLE = "feeds.fetch_article"
ADAPTER_RETRIEVE = "corpus.retrieve_for_topic"

SYSTEM_PROMPT = (
    "You write one sentence of a nightly news digest from passages that were retrieved "
    "from articles. Use only what the passages say. "
    "Reuse every figure exactly as it appears; never round, estimate, derive, or infer a "
    "number. Quote at most a short phrase, verbatim. Name the publication. "
    "If the passages do not support a claim, leave it out."
)

PROMPT = (
    "Write one or two sentences summarizing what is new on this topic, using only the "
    "passages below. Reuse their figures exactly and name the source publication."
)


@register_beat
class NewsBeat:
    """`name = "news"`. One class plus one config entry, per FR-2."""

    name = "news"
    completion_criterion = (
        "one grounded item per configured topic that retrieved at least one passage, each "
        "item linked to the chunk observations it was written from"
    )

    def should_run(self, context: BeatContext) -> bool:
        return bool(context.config.beats.get(self.name, False))

    # -- the run ------------------------------------------------------------ #

    def run(self, context: BeatContext) -> BeatResult:
        settings = context.config.news
        if settings is None:
            return BeatResult.unavailable(
                self.name, "the news beat is enabled but [news] is not configured"
            )
        if context.embedder is None or context.corpus is None:
            return BeatResult.unavailable(
                self.name,
                "the news beat needs an embedder and a corpus connection; the runner "
                "supplies both and neither was injected",
            )

        corpus_module.purge_expired(
            context.corpus, ttl_days=settings.corpus.ttl_days, now=context.now
        )

        entries, failed_sources = self._collect(context, settings)

        if failed_sources and not entries:
            return BeatResult.unavailable(
                self.name,
                "every configured news source failed: "
                + "; ".join(f"{name} ({error})" for name, error in failed_sources),
            )

        self._index(context, settings, entries)
        items, observations = self._items_for_topics(context, settings)

        return BeatResult(
            beat=self.name,
            items=items,
            # Deliberately empty. A news item states no typed value the synthesizer copies
            # — its prose is policed by FR-26 instead, which is a different mechanism for
            # a different shape of claim.
            checkable_fields={},
            available=True,
            observations=observations,
        )

    # -- stages ------------------------------------------------------------- #

    def _collect(
        self, context: BeatContext, settings: Any
    ) -> tuple[list[feeds.FeedEntry], list[tuple[str, str]]]:
        """Read every configured feed. A failure names its source and does not stop the run."""
        entries: list[feeds.FeedEntry] = []
        failed: list[tuple[str, str]] = []

        for feed in settings.feeds:
            arguments = {"feed": feed.name, "url": feed.url}
            observation_id = context.trace.tool_call(
                beat=self.name, adapter=ADAPTER_FEED, arguments=arguments
            )
            try:
                fetched = context.scratchpad.get_or_call(
                    lambda feed=feed: feeds.fetch_feed(
                        feed.url,
                        feed.name,
                        client=context.http_client,
                        user_agent=settings.user_agent,
                        tz_name=context.config.run.timezone,
                        timeout=settings.timeout_seconds,
                        trace=context.trace,
                    ),
                    beat=self.name,
                    adapter=ADAPTER_FEED,
                    arguments=arguments,
                )
            except Exception as exc:  # noqa: BLE001 - one bad feed is not a dead beat
                detail = f"{type(exc).__name__}: {exc}"
                context.trace.observation(observation_id, error=detail)
                context.trace.decision(
                    beat=self.name,
                    decision="source_unavailable",
                    reason=f"{feed.name}: {detail}",
                    source=feed.name,
                )
                failed.append((feed.name, detail))
                continue

            context.trace.observation(
                observation_id, payload={"feed": feed.name, "entries": len(fetched)}
            )
            entries.extend(fetched)

        return entries, failed

    def _index(
        self, context: BeatContext, settings: Any, entries: list[feeds.FeedEntry]
    ) -> None:
        """Fetch bodies for in-window entries, chunk them, and index them."""
        if not entries:
            return

        arguments = {"entries": len(entries), "window_days": settings.retrieval.window_days}
        observation_id = context.trace.tool_call(
            beat=self.name, adapter=ADAPTER_ARTICLE, arguments=arguments
        )
        fetched = feeds.fetch_article_bodies(
            entries,
            client=context.http_client,
            user_agent=settings.user_agent,
            now=context.now,
            window_days=settings.retrieval.window_days,
            min_body_chars=settings.min_body_chars,
            fetch_delay_seconds=settings.fetch_delay_seconds,
            timeout=settings.timeout_seconds,
            trace=context.trace,
        )
        context.trace.observation(
            observation_id,
            payload={
                "fetched": len(fetched),
                "article_bodies": sum(
                    1 for e in fetched if e.text_source == feeds.SOURCE_ARTICLE
                ),
                "summary_fallbacks": sum(
                    1 for e in fetched if e.text_source == feeds.SOURCE_SUMMARY
                ),
            },
        )

        for entry in fetched:
            chunks = corpus_module.chunk_article(
                entry.headline,
                entry.body,
                target_chars=settings.chunking.target_chars,
                max_chars=settings.chunking.max_chars,
                overlap_chars=settings.chunking.overlap_chars,
            )
            corpus_module.index_article(
                context.corpus, entry, chunks, context.embedder, fetched_at=context.now
            )

    def _items_for_topics(
        self, context: BeatContext, settings: Any
    ) -> tuple[list[BeatItem], list[ObservationRef]]:
        """One item per topic that retrieved something. A quiet topic is recorded, not filled."""
        items: list[BeatItem] = []
        refs: list[ObservationRef] = []

        for topic in settings.topics:
            arguments = {"topic": topic.id, "query": topic.query}
            observation_id = context.trace.tool_call(
                beat=self.name, adapter=ADAPTER_RETRIEVE, arguments=arguments
            )
            vector = context.embedder.encode([topic.query])[0]
            retrieved = corpus_module.retrieve_for_topic(
                context.corpus,
                vector,
                k=settings.retrieval.k,
                similarity_floor=settings.retrieval.similarity_floor,
                window_days=settings.retrieval.window_days,
                max_chunks_per_article=settings.retrieval.max_chunks_per_article,
                now=context.now,
            )
            context.trace.observation(
                observation_id,
                payload={
                    "topic": topic.id,
                    "chunks": [chunk.as_record() for chunk in retrieved],
                },
            )

            if not retrieved:
                context.trace.decision(
                    beat=self.name,
                    decision="topic_empty",
                    reason=(
                        f"{topic.id}: no passage within {settings.retrieval.window_days} "
                        f"days scored at or above {settings.retrieval.similarity_floor}; "
                        "emitting no item rather than filling the gap"
                    ),
                    topic=topic.id,
                )
                continue

            # Each chunk becomes its own observation, so FR-26 can check the sentence
            # against exactly the passages it was written from — not against a blob of
            # everything the beat happened to see tonight.
            chunk_refs: list[ObservationRef] = []
            for chunk in retrieved:
                chunk_observation = context.trace.tool_call(
                    beat=self.name,
                    adapter=ADAPTER_RETRIEVE,
                    arguments={"topic": topic.id, "chunk_id": chunk.chunk_id},
                )
                context.trace.observation(chunk_observation, payload=chunk.text)
                chunk_refs.append(ObservationRef(chunk_observation, ADAPTER_RETRIEVE))

            text = self._write(context, topic, retrieved)
            items.append(
                BeatItem(
                    beat=self.name,
                    text=text,
                    # Topic and origin only. No date, url, or source: each of those
                    # differs between two articles about the same story, and FR-27's
                    # veto reads the prose instead.
                    fields={"topic": topic.id, "text_origin": SYNTHESIZED},
                    observations=chunk_refs,
                )
            )
            refs.extend(chunk_refs)

        return items, refs

    def _write(self, context: BeatContext, topic: Any, retrieved: list[Any]) -> str:
        """Ask the model to phrase the passages. It supplies no figure of its own."""
        client = context.agent_client
        if client is None:
            raise RuntimeError(
                "the news beat needs an agent client to phrase its retrieved passages"
            )
        response = client.complete(
            PROMPT,
            structured={
                "topic": topic.query,
                "passages": [
                    {
                        "source": chunk.source,
                        "headline": chunk.headline,
                        "text": chunk.text,
                    }
                    for chunk in retrieved
                ],
            },
            system=SYSTEM_PROMPT,
            effort=DEFAULT_EFFORT,
        )
        return response.text.strip()


__all__ = ["NewsBeat", "PROMPT", "SYSTEM_PROMPT"]
