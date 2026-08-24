"""Need-to-know news beat, v4 (FR-31, FR-34) — the beat that deliberately says nothing.

Every other beat exists to put lines in the digest. This one, in its observation
increment, exists to put **evidence in the trace**: for every in-window article from its
general-news sources, how many *other* configured sources are carrying the same story
(FR-33's corroboration count), recorded with full provenance. The bar that will one day
consume those counts (FR-36) is decided but not built here, and its numbers are meant to
be tuned from this beat's accumulated distribution — not guessed.

Two deliberate absences, both load-bearing:

- **No digest items** beyond FR-28-style source-unavailability status lines. A quiet
  night is the designed norm, and in v4 the digest simply doesn't mention this beat.
  Silence is instead **provable from the trace**: every run records either per-candidate
  `corroboration_observed` decisions or one explicit `no_candidates` — which is how the
  metric (FR-35) tells "quiet" from "broken", the failure Checkpoint 3 named.
- **No model calls.** The whole beat is mechanical, so `context.agent_client` is never
  touched, FR-26/FR-27 never engage, and the increment's token cost is zero. A test
  asserts this by handing the beat a client that explodes on contact.

The run: purge → fetch feeds → (all-sources-down check, against the **configured feed
count**, not the entry count — three healthy feeds on a quiet day are not an outage) →
window-filter and fetch bodies → chunk → index into the **shared** corpus → one
corroboration count per candidate, each traced as its own tool call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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
ADAPTER_CORROBORATE = "corpus.corroborating_sources"

#: FR-36/FR-38. The news beat's writing contract, reused rather than paraphrased: the
#: model phrases; the passages own every figure and every quoted word.
SYSTEM_PROMPT = (
    "You write one or two sentences of a nightly news digest from passages that were "
    "retrieved from articles. Use only what the passages say. "
    "Reuse every figure exactly as it appears; never round, estimate, derive, or infer a "
    "number. Name the publication. "
    "Quotation marks are a promise that the words between them are copied character for "
    "character from a passage. If you quote, copy an unbroken run of words and do not "
    "add, drop, or change punctuation inside it — not even a final period. Prefer not "
    "quoting at all to quoting loosely. "
    "If the passages do not support a claim, leave it out. "
    "Write only the digest sentences: no preamble, no heading, and no trailing note."
)

WRITE_PROMPT = (
    "Write one or two sentences reporting this story, using only the passages below. "
    "Reuse their figures exactly and name the source publication. Output only those "
    "sentences."
)


@dataclass
class _Candidate:
    """One in-window article, with everything the bar phase needs about it."""

    entry: feeds.FeedEntry
    count: int
    sources: list[str]
    observation_id: str
    watchlist_term: str | None = None
    chunk_refs: list[ObservationRef] = field(default_factory=list)


@register_beat
class NeedToKnowBeat:
    """`name = "need_to_know"`. One class plus one config entry, per FR-2."""

    name = "need_to_know"
    completion_criterion = (
        "every in-window candidate carries a corroboration_observed decision with "
        "resolvable observations, or the run records no_candidates; no digest item "
        "beyond source-unavailability lines"
    )

    def should_run(self, context: BeatContext) -> bool:
        return bool(context.config.beats.get(self.name, False))

    # -- the run ------------------------------------------------------------ #

    def run(self, context: BeatContext) -> BeatResult:
        settings = context.config.need_to_know
        if settings is None:
            return BeatResult.unavailable(
                self.name,
                "the need_to_know beat is enabled but [need_to_know] is not configured",
            )
        if context.embedder is None or context.corpus is None:
            return BeatResult.unavailable(
                self.name,
                "the need_to_know beat needs an embedder and a corpus connection; the "
                "runner supplies both and neither was injected",
            )

        corpus_module.purge_expired(
            context.corpus, ttl_days=settings.corpus.ttl_days, now=context.now
        )

        entries, failed_sources = self._collect(context, settings)

        if failed_sources and len(failed_sources) == len(settings.feeds):
            return BeatResult.unavailable(
                self.name,
                "every configured need-to-know source failed: "
                + "; ".join(f"{name} ({error})" for name, error in failed_sources),
            )

        fetched = self._index(context, settings, entries)
        candidates = self._observe(context, settings, fetched)

        # v5 — the bar. Watchlist first (FR-38): a hit bypasses the gate and the
        # judgment entirely and escalates via the deterministic rule.
        story_items = self._watchlist_pass(context, settings, candidates)
        hits = [c.watchlist_term for c in candidates if c.watchlist_term]

        return BeatResult(
            beat=self.name,
            items=self._unavailability_items(context, failed_sources) + story_items,
            # Still empty: delivered items are model-written, so their claims are
            # policed by FR-26 over linked chunk observations, not by typed fields.
            checkable_fields={},
            available=True,
            escalation_candidate=bool(hits),
            escalation_reason=(
                f"watchlist term(s) matched: {', '.join(hits)}" if hits else None
            ),
            escalation_signals={"watchlist": hits} if hits else {},
            observations=[ref for c in candidates for ref in c.chunk_refs],
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

    def _unavailability_items(
        self, context: BeatContext, failed: list[tuple[str, str]]
    ) -> list[BeatItem]:
        """One dated status line per dead source — the only items v4 may ever emit.

        Same shape as the news beat's: the `as_of` date puts them under FR-19's original
        invariant, so a feed down for a week says so on the seventh night as loudly as
        the first. Going quiet about a failure is the failure (FR-18/FR-28).
        """
        stamp = context.now.date().isoformat()
        return [
            BeatItem(
                beat=self.name,
                text=f"Couldn't reach {source} tonight ({error}).",
                fields={"source": source, "as_of": stamp},
            )
            for source, error in failed
        ]

    def _index(
        self, context: BeatContext, settings: Any, entries: list[feeds.FeedEntry]
    ) -> list[feeds.FeedEntry]:
        """Fetch bodies for in-window entries, chunk and index them, return the candidates.

        The window is the **corroboration** window: an article too old to corroborate or
        be corroborated is not a candidate, so fetching its body would be a wasted
        (im)polite request. Summary fallbacks are expected here far more often than on
        the AI beat — general-news publishers gate fetchers hard (NPR timed out the
        fixture capture on 2026-08-14; the Guardian blocked it outright at spec time).
        """
        if not entries:
            return []

        arguments = {
            "entries": len(entries),
            "window_days": settings.corroboration.window_days,
        }
        observation_id = context.trace.tool_call(
            beat=self.name, adapter=ADAPTER_ARTICLE, arguments=arguments
        )
        fetched = feeds.fetch_article_bodies(
            entries,
            client=context.http_client,
            user_agent=settings.user_agent,
            now=context.now,
            window_days=settings.corroboration.window_days,
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
        return fetched

    def _observe(
        self, context: BeatContext, settings: Any, candidates: list[feeds.FeedEntry]
    ) -> list[_Candidate]:
        """FR-34 — the accounting that makes silence provable.

        One `corroboration_observed` decision per candidate, each pointing at the
        observation holding its contributing chunks — or exactly one `no_candidates`
        when the night is genuinely quiet. A run with neither (and no failure) is what
        FR-35's condition (a) fails. Returns the observed candidates so the v5 bar
        phase runs on exactly what was accounted — the bar sits on top of observation,
        never instead of it.
        """
        observed: list[_Candidate] = []
        if not candidates:
            context.trace.decision(
                beat=self.name,
                decision="no_candidates",
                reason=(
                    f"no article from the configured sources was published within "
                    f"{settings.corroboration.window_days} day(s); a quiet night, "
                    "recorded rather than filled"
                ),
            )
            return observed

        source_names = [feed.name for feed in settings.feeds]
        for entry in candidates:
            observation_id = context.trace.tool_call(
                beat=self.name,
                adapter=ADAPTER_CORROBORATE,
                arguments={"url": entry.url, "source": entry.source},
            )
            corroborators = corpus_module.corroborating_sources(
                context.corpus,
                entry.url,
                sources=source_names,
                floor=settings.corroboration.floor,
                window_days=settings.corroboration.window_days,
                now=context.now,
            )
            context.trace.observation(
                observation_id,
                payload={
                    "url": entry.url,
                    "source": entry.source,
                    # Which text the count ran over — §8 expects the report to surface
                    # the per-source article-vs-summary split, and this is where it
                    # can come from without a second bookkeeping path.
                    "text_source": entry.text_source,
                    "corroborators": {
                        source: [hit.as_record() for hit in hits]
                        for source, hits in corroborators.items()
                    },
                },
            )
            context.trace.decision(
                beat=self.name,
                decision="corroboration_observed",
                reason=(
                    f"{entry.url}: carried by {len(corroborators)} other configured "
                    f"source(s) within {settings.corroboration.window_days} day(s) at "
                    f"or above cosine {settings.corroboration.floor}"
                ),
                url=entry.url,
                source=entry.source,
                count=len(corroborators),
                sources=sorted(corroborators),
                observation=observation_id,
            )
            observed.append(
                _Candidate(
                    entry=entry,
                    count=len(corroborators),
                    sources=sorted(corroborators),
                    observation_id=observation_id,
                )
            )
        return observed

    # -- v5: the bar --------------------------------------------------------- #

    def _watchlist_pass(
        self, context: BeatContext, settings: Any, candidates: list[_Candidate]
    ) -> list[BeatItem]:
        """FR-38 — the mechanical carve-out that bounds suppress-when-unsure.

        Whole-word, case-insensitive match over headline + first stored chunk. A hit
        bypasses the corroboration gate and the FR-36 judgment: it always delivers,
        no model opinion consulted about *whether* — the model only phrases it.
        """
        items: list[BeatItem] = []
        for candidate in candidates:
            term = self._watchlist_match(context, settings, candidate.entry)
            if term is None:
                continue
            candidate.watchlist_term = term
            context.trace.decision(
                beat=self.name,
                decision="watchlist_hit",
                reason=(
                    f"{candidate.entry.url}: matched watchlist term {term!r}; bypassing "
                    "the gate and the judgment — the carve-out may never be suppressed"
                ),
                url=candidate.entry.url,
                term=term,
            )
            items.append(self._write_item(context, candidate, via="watchlist"))
        return items

    def _watchlist_match(
        self, context: BeatContext, settings: Any, entry: feeds.FeedEntry
    ) -> str | None:
        chunks = corpus_module.chunks_for(context.corpus, entry.url)
        haystack = entry.headline + "\n" + (chunks[0][1] if chunks else "")
        for term in settings.watchlist:
            if re.search(rf"\b{re.escape(term)}\b", haystack, re.IGNORECASE):
                return term
        return None

    def _write_item(
        self, context: BeatContext, candidate: _Candidate, *, via: str
    ) -> BeatItem:
        """Model-written from the candidate's own chunks, the news beat's FR-26 shape:
        each chunk is its own observation, and the item points at every one."""
        client = context.agent_client
        if client is None:
            raise RuntimeError(
                "the need-to-know bar needs an agent client to phrase a delivered item"
            )
        chunks = corpus_module.chunks_for(context.corpus, candidate.entry.url)
        chunk_refs: list[ObservationRef] = []
        passages: list[dict[str, str]] = []
        for chunk_id, text in chunks:
            chunk_observation = context.trace.tool_call(
                beat=self.name,
                adapter=ADAPTER_CORROBORATE,
                arguments={"url": candidate.entry.url, "chunk_id": chunk_id},
            )
            context.trace.observation(chunk_observation, payload=text)
            chunk_refs.append(ObservationRef(chunk_observation, ADAPTER_CORROBORATE))
            passages.append(
                {
                    "source": candidate.entry.source,
                    "headline": candidate.entry.headline,
                    "text": text,
                }
            )
        candidate.chunk_refs = chunk_refs

        response = client.complete(
            WRITE_PROMPT,
            structured={"headline": candidate.entry.headline, "passages": passages},
            system=SYSTEM_PROMPT,
            effort=DEFAULT_EFFORT,
        )
        return BeatItem(
            beat=self.name,
            text=response.text.strip(),
            # FR-27 shape: origin plus routing only — no date, url, or source, because
            # each of those differs between two articles about one story.
            fields={"text_origin": SYNTHESIZED, "via": via},
            observations=chunk_refs,
        )


__all__ = ["NeedToKnowBeat"]
