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

from typing import Any

from forecaster.beats.base import (
    BeatContext,
    BeatItem,
    BeatResult,
    register_beat,
)
from forecaster.memory import corpus as corpus_module
from forecaster.tools import feeds

ADAPTER_FEED = "feeds.fetch_feed"
ADAPTER_ARTICLE = "feeds.fetch_article"
ADAPTER_CORROBORATE = "corpus.corroborating_sources"


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

        candidates = self._index(context, settings, entries)
        self._observe(context, settings, candidates)

        return BeatResult(
            beat=self.name,
            items=self._unavailability_items(context, failed_sources),
            # Empty on both axes, on purpose: v4 states no fact for FR-11 to copy and
            # writes no synthesized text for FR-26 to police. The beat's output is the
            # trace, and FR-35's checker is what reads it.
            checkable_fields={},
            available=True,
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
    ) -> None:
        """FR-34 — the accounting that makes silence provable.

        One `corroboration_observed` decision per candidate, each pointing at the
        observation holding its contributing chunks — or exactly one `no_candidates`
        when the night is genuinely quiet. A run with neither (and no failure) is what
        FR-35's condition (a) fails.
        """
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
            return

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


__all__ = ["NeedToKnowBeat"]
