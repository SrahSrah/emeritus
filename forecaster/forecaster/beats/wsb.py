"""r/WallStreetBets beat (FR-48 … FR-51) — mention volume, counted, never picked.

The strongest form of the capstone's counts-not-judgments line: there is no model in the
loop to editorialize. One feed fetch per night (the politeness budget is law — a second
request 12 s after the first drew a 429 when measured), a pure counter over post titles
and summaries, and one code-assembled item whose every number is a count.

The counter is deliberately naive — pattern plus stoplist, reasoned rather than measured
(child PRD §9 Q1). All-caps titles make every short uppercase word a candidate, so false
positives are expected; the mitigation is honesty, not cleverness: every match is
post-attributed in the count observation, so a wrong one is findable in minutes and the
stoplist is config Sarah edits the moment one annoys her.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from forecaster.beats.base import (
    BeatContext,
    BeatItem,
    BeatResult,
    ObservationRef,
    register_beat,
)
from forecaster.tools import feeds

ADAPTER_FEED = "feeds.fetch_feed"
ADAPTER_COUNT = "wsb.count_mentions"
SOURCE = "r/wallstreetbets"

#: `$tsla`, `$NVDA` — 1–5 letters, any case, and not a prefix of a longer letter run.
_CASHTAG = re.compile(r"\$([A-Za-z]{1,5})(?![A-Za-z])")
#: Bare `NVDA` — 2–5 chars, all upper, whole word. Single letters are cashtag-only:
#: bare `F` would count every sentence containing "F".
_BARE = re.compile(r"\b([A-Z]{2,5})\b")


def count_mentions(
    entries: Iterable[Any], *, stoplist: Iterable[str]
) -> dict[str, dict[str, Any]]:
    """Per-ticker mention data over the night's entries (FR-48).

    Pure: no network, no trace — recording the result as a tool-call observation is the
    beat's job, because the *beat* owns the trace contract, not the arithmetic.

    A ticker mentioned five times in one title counts once for that post:
    posts-mentioning is the honest unit when snippet lengths vary this much. "Post" is
    identified by ``entry.url`` throughout the spec — ``FeedEntry`` has no separate id.
    """
    stop = {term.upper() for term in stoplist}
    table: dict[str, dict[str, Any]] = {}

    for entry in entries:
        text = f"{entry.headline}\n{entry.summary}"
        tickers = {match.upper() for match in _CASHTAG.findall(text)}
        tickers.update(_BARE.findall(text))
        tickers -= stop
        for ticker in tickers:
            record = table.setdefault(ticker, {"count": 0, "post_urls": []})
            if entry.url not in record["post_urls"]:
                record["post_urls"].append(entry.url)
                record["count"] = len(record["post_urls"])

    return table


def _posts(n: int) -> str:
    return f"{n} post" + ("" if n == 1 else "s")


def ranked_mentions(
    table: dict[str, dict[str, Any]], top_n: int
) -> list[tuple[str, int]]:
    """The only ordering anywhere (FR-51iii): count-descending, alphabetical ties —
    including at the ``top_n`` boundary, so truncation is deterministic."""
    ordered = sorted(table.items(), key=lambda kv: (-kv[1]["count"], kv[0]))
    return [(ticker, record["count"]) for ticker, record in ordered[:top_n]]


def render_counts(reported: list[tuple[str, int]], post_total: int, link: str) -> str:
    """The fixed counts template (FR-49). FR-51's equality test reconstructs this exact
    string from the count observation, so nothing can be appended unnoticed."""
    first_ticker, first_count = reported[0]
    clauses = [f"{first_ticker} mentioned in {_posts(first_count)}"]
    clauses.extend(f"{ticker} in {count}" for ticker, count in reported[1:])
    return (
        f"On {SOURCE}' hot page tonight ({_posts(post_total)}): "
        + ", ".join(clauses)
        + f". {link}"
    )


def render_quiet(post_total: int) -> str:
    """The fixed quiet template (FR-50). ``0 posts scanned`` is honest and stays visible."""
    return (
        f"No ticker mentions counted on {SOURCE}' hot page tonight "
        f"({_posts(post_total)} scanned)."
    )


@register_beat
class WsbMentionsBeat:
    """`name = "wsb"`. One class plus one config entry, per FR-2."""

    name = "wsb"
    completion_criterion = (
        "one nightly item of per-ticker mention counts traced to the night's single "
        "hot-page fetch, or an explicit no-mentions line, or a named outage; never a "
        "second fetch and never a claim beyond a count"
    )

    def should_run(self, context: BeatContext) -> bool:
        return bool(context.config.beats.get(self.name, False))

    def run(self, context: BeatContext) -> BeatResult:
        settings = context.config.wsb
        if settings is None:
            return BeatResult.unavailable(
                self.name, "the wsb beat is enabled but [wsb] is not configured"
            )

        # ONE fetch per night, ever — §2(c). A refused fetch is an honest-failure night:
        # no retry, no cached substitute (a second request 12 s after the first drew a
        # 429 when measured, so a retry would not even work).
        fetch_id = context.trace.tool_call(
            beat=self.name,
            adapter=ADAPTER_FEED,
            arguments={"feed": SOURCE, "url": settings.feed_url},
        )
        try:
            entries = feeds.fetch_feed(
                settings.feed_url,
                SOURCE,
                client=context.http_client,
                user_agent=settings.user_agent,
                tz_name=context.config.run.timezone,
                timeout=settings.timeout_seconds,
                trace=context.trace,
                beat=self.name,
            )
        except Exception as exc:  # noqa: BLE001 - the refused fetch IS the outage mode
            detail = f"{type(exc).__name__}: {exc}"
            context.trace.observation(fetch_id, error=detail)
            context.trace.decision(
                beat=self.name,
                decision="source_unavailable",
                reason=f"{SOURCE}: {detail}; one request is the budget, not retrying",
                source=SOURCE,
            )
            return BeatResult.unavailable(
                self.name, f"couldn't read {SOURCE} tonight ({detail})"
            )

        # §6 trace contract: the fetch observation carries the surviving entries so
        # FR-52's second provenance hop can resolve every contributing url against them.
        context.trace.observation(
            fetch_id,
            payload={
                "feed": SOURCE,
                "entries": [
                    {"url": e.url, "headline": e.headline, "summary": e.summary}
                    for e in entries
                ],
            },
        )
        fetch_ref = ObservationRef(fetch_id, ADAPTER_FEED)

        # The counter is deterministic code traced as a tool call — the point, not a
        # trick: the delivered counts get a recorded observation for FR-11 to check.
        post_total = len(entries)
        count_id = context.trace.tool_call(
            beat=self.name,
            adapter=ADAPTER_COUNT,
            arguments={"posts": post_total, "stoplist_size": len(settings.stoplist)},
        )
        table = count_mentions(entries, stoplist=settings.stoplist)
        context.trace.observation(
            count_id, payload={"tickers": table, "post_total": post_total}
        )
        count_ref = ObservationRef(count_id, ADAPTER_COUNT)

        stamp = context.now.date().isoformat()
        refs = [fetch_ref, count_ref]

        if not table:
            context.trace.decision(
                beat=self.name,
                decision="wsb_no_mentions",
                reason=(
                    f"feed parsed, {post_total} surviving post(s), zero ticker matches "
                    "after the stoplist; saying so rather than saying nothing"
                ),
                post_total=post_total,
            )
            item = BeatItem(
                beat=self.name,
                text=render_quiet(post_total),
                fields={"as_of": stamp, "post_total": post_total},
                observations=refs,
            )
            return BeatResult(
                beat=self.name,
                items=[item],
                checkable_fields={"wsb:post_total": post_total},
                observations=refs,
            )

        reported = ranked_mentions(table, settings.top_n)
        link = settings.feed_url[: -len(".rss")] if settings.feed_url.endswith(".rss") else settings.feed_url
        checkable: dict[str, Any] = {"wsb:post_total": post_total}
        for ticker, count in reported:
            checkable[f"wsb:{ticker}"] = count

        context.trace.decision(
            beat=self.name,
            decision="wsb_counts",
            reason=(
                f"{len(table)} ticker(s) matched across {post_total} post(s); "
                f"reporting the top {len(reported)} by post count"
            ),
            tickers=[ticker for ticker, _ in reported],
            post_total=post_total,
        )
        item = BeatItem(
            beat=self.name,
            text=render_counts(reported, post_total, link),
            fields={"as_of": stamp, "post_total": post_total},
            observations=refs,
        )
        return BeatResult(
            beat=self.name,
            items=[item],
            checkable_fields=checkable,
            observations=refs,
        )


__all__ = [
    "ADAPTER_COUNT",
    "ADAPTER_FEED",
    "WsbMentionsBeat",
    "count_mentions",
    "ranked_mentions",
    "render_counts",
    "render_quiet",
]
