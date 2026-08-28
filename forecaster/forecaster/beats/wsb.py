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


__all__ = ["count_mentions"]
