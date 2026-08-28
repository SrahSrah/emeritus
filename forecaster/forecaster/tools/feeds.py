"""RSS/Atom feed adapter (FR-20).

Normalizes a publisher's feed into typed :class:`FeedEntry` objects. Same contract as
`tools/mlb.py` and `tools/weather.py`: an injectable ``httpx.Client``, a typed result, and
:class:`AdapterError` on any failure rather than a partial or guessed entry.

Free, no key, no signup — which is the whole reason the source is RSS. Measured live
2026-08-04 across five publishers: all returned HTTP 200 with no credential.

## What a feed does and does not give you

Feed summary bodies are **short**. Measured the same day:

    Ars Technica   median 975 chars      The Verge   median 730
    OpenAI news    median 154            TechCrunch  median 124
    DeepMind blog  median 111

That is one chunk, not a document. This adapter therefore only does **discovery** — it
answers "what was published, when, and where does it live". FR-21 fetches the article
page itself, which measured 3,233–6,838 characters and is what makes chunking mean
anything. Keeping the two separate is deliberate: a feed that parses is not the same
event as an article that fetches, and they fail independently.

## Why stdlib XML rather than feedparser

The whole project's dependency list is short on purpose. RSS 2.0 and Atom differ in three
places that matter here — the item element, where the link lives, and the date format —
and all three are a few lines with ``xml.etree``. `feedparser` would be a dependency
earning its keep on feeds far stranger than these five.
"""

from __future__ import annotations

import html
import re
import time as _time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Iterable, Mapping
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from forecaster.tools.mlb import AdapterError

ADAPTER_NAME = "feeds.fetch_feed"
ARTICLE_ADAPTER_NAME = "feeds.fetch_article"
DEFAULT_TIMEOUT = 15.0

#: Text sources an entry's body can have. Never "invented" — that is the point.
SOURCE_UNFETCHED = "unfetched"
SOURCE_ARTICLE = "article"
SOURCE_SUMMARY = "summary"

#: Namespaces the two shapes use. `content:encoded` is where RSS puts a fuller body.
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class FeedEntry:
    """One published article, as the feed describes it.

    ``body`` and ``text_source`` are populated by FR-21, not here. An entry straight out
    of a feed carries ``text_source = "unfetched"``, which is honest: nothing has looked
    at the article itself yet.
    """

    url: str
    source: str
    headline: str
    published: datetime
    summary: str
    body: str = ""
    text_source: str = SOURCE_UNFETCHED

    def with_body(self, body: str, text_source: str) -> "FeedEntry":
        """Return a copy carrying a fetched body. Frozen, so this replaces rather than mutates."""
        return FeedEntry(
            url=self.url,
            source=self.source,
            headline=self.headline,
            published=self.published,
            summary=self.summary,
            body=body,
            text_source=text_source,
        )


def _tzinfo(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise AdapterError(
            f"Unknown timezone {name!r} from config", adapter=ADAPTER_NAME
        ) from exc


def strip_markup(raw: str | None) -> str:
    """Feed bodies carry HTML. Reduce to plain text without inventing or dropping words."""
    if not raw:
        return ""
    text = html.unescape(raw)
    text = _TAG_RE.sub(" ", text)
    return _WS_RE.sub(" ", html.unescape(text)).strip()


def _text_of(element: Any) -> str:
    """An element's text plus every descendant's, so nested markup survives."""
    if element is None:
        return ""
    return strip_markup("".join(element.itertext()) if len(element) else (element.text or ""))


def _parse_date(raw: str | None) -> datetime | None:
    """RFC 822 (RSS) or ISO 8601 (Atom). ``None`` means the entry gets dropped."""
    if not raw or not raw.strip():
        return None
    candidate = raw.strip()
    try:
        parsed = parsedate_to_datetime(candidate)
    except (TypeError, ValueError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _first_child_text(item: Any, *paths: str) -> str:
    for path in paths:
        found = item.find(path, _NS)
        if found is not None:
            text = _text_of(found)
            if text:
                return text
    return ""


def _rss_link(item: Any) -> str:
    link = item.find("link")
    if link is not None and (link.text or "").strip():
        return (link.text or "").strip()
    guid = item.find("guid")
    if guid is not None and (guid.text or "").strip().startswith("http"):
        return (guid.text or "").strip()
    return ""


def _atom_link(entry: Any) -> str:
    """Atom puts the url in an attribute. Prefer rel="alternate", accept a bare href."""
    fallback = ""
    for link in entry.findall("atom:link", _NS):
        href = (link.get("href") or "").strip()
        if not href:
            continue
        if link.get("rel", "alternate") == "alternate":
            return href
        fallback = fallback or href
    return fallback


def parse_feed(
    body: str, *, source: str, tz_name: str = "UTC"
) -> tuple[list[FeedEntry], list[str]]:
    """Normalize a feed document.

    Returns ``(entries, dropped)``. An entry with no url or no resolvable publication
    date is **dropped** rather than defaulted — a made-up date would place an article in
    the wrong retrieval window, and a made-up url is not a thing that can be fetched.
    Each drop comes back with a reason so the caller can put it in the trace.
    """
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise AdapterError(
            f"{source} returned a body that is not parseable XML: {exc}",
            adapter=ADAPTER_NAME,
        )

    local = _tzinfo(tz_name)
    entries: list[FeedEntry] = []
    dropped: list[str] = []

    items = root.findall(".//item")
    is_atom = not items
    if is_atom:
        items = root.findall(".//atom:entry", _NS)

    for item in items:
        if is_atom:
            headline = _first_child_text(item, "atom:title")
            url = _atom_link(item)
            raw_date = _first_child_text(item, "atom:published", "atom:updated")
            summary = _first_child_text(item, "atom:content", "atom:summary")
        else:
            headline = _first_child_text(item, "title")
            url = _rss_link(item)
            raw_date = _first_child_text(item, "pubDate", "date")
            summary = _first_child_text(item, "content:encoded", "description")

        label = headline or url or "<untitled entry>"

        if not url:
            dropped.append(f"{label!r}: no resolvable link")
            continue
        published = _parse_date(raw_date)
        if published is None:
            dropped.append(f"{label!r}: no resolvable publication date ({raw_date!r})")
            continue

        entries.append(
            FeedEntry(
                url=url,
                source=source,
                headline=headline,
                published=published.astimezone(local),
                summary=summary,
            )
        )

    return entries, dropped


def fetch_feed(
    url: str,
    source: str,
    *,
    client: httpx.Client,
    user_agent: str,
    tz_name: str = "UTC",
    timeout: float = DEFAULT_TIMEOUT,
    trace: Any = None,
    beat: str = "news",
) -> list[FeedEntry]:
    """Fetch and normalize one feed. Raises :class:`AdapterError`; never guesses.

    Dropped entries are recorded on ``trace`` when one is supplied, because "the feed
    parsed but three entries had no date" is exactly the kind of quiet thinning that is
    invisible until the digest goes sparse for no visible reason. ``beat`` labels those
    drop records (FR-49): it defaults to ``"news"`` for the original callers, and a
    non-news beat passes its own name so its drops are never mislabeled or silenced.
    """
    headers = {"User-Agent": user_agent, "Accept": "application/rss+xml, application/xml, text/xml, */*"}
    try:
        response = client.get(url, headers=headers, timeout=timeout)
    except httpx.TimeoutException as exc:
        raise AdapterError(
            f"{source} feed timed out after {timeout}s", adapter=ADAPTER_NAME
        ) from exc
    except httpx.HTTPError as exc:
        raise AdapterError(
            f"{source} feed request failed: {exc}", adapter=ADAPTER_NAME
        ) from exc

    if response.status_code >= 400:
        raise AdapterError(
            f"{source} feed returned {response.status_code}",
            adapter=ADAPTER_NAME,
            status=response.status_code,
        )

    entries, dropped = parse_feed(response.text, source=source, tz_name=tz_name)

    if trace is not None:
        for reason in dropped:
            trace.decision(
                beat=beat,
                decision="feed_entry_dropped",
                reason=(
                    f"{source}: {reason} — dropped rather than defaulted, since a "
                    "substituted date would file the article in the wrong window"
                ),
            )

    return entries


def within_window(
    entries: Iterable[FeedEntry], *, now: datetime, window_days: int
) -> list[FeedEntry]:
    """Entries published inside the retrieval window.

    **This runs before any article is fetched.** One feed returned 1,108 entries in a
    single request on 2026-08-04; filtering afterwards would mean a thousand HTTP calls
    a night. See FR-21.
    """
    from datetime import timedelta

    reference = now
    kept: list[FeedEntry] = []
    for entry in entries:
        published = entry.published
        # Feeds mix aware and naive timestamps; compare on common ground rather than
        # raising, since a TypeError here would fail a whole beat over a formatting quirk.
        if published.tzinfo is not None and reference.tzinfo is None:
            published = published.replace(tzinfo=None)
        elif published.tzinfo is None and reference.tzinfo is not None:
            published = published.replace(tzinfo=reference.tzinfo)
        if published >= reference - timedelta(days=window_days):
            kept.append(entry)
    return kept


# --------------------------------------------------------------------------- #
# FR-21 — the article body. This is what makes the documents document-shaped.
# --------------------------------------------------------------------------- #

#: Blocks that are never article prose. Removed whole, tags and contents alike.
_BOILERPLATE = re.compile(
    r"(?is)<(script|style|nav|header|footer|aside|form|figure|noscript)\b.*?</\1\s*>"
)
_PARAGRAPH = re.compile(r"(?is)<p\b[^>]*>(.*?)</p\s*>")


def extract_body(document: str) -> str:
    """Pull the article prose out of an HTML page.

    Hand-rolled rather than `trafilatura`, which resolves to **16 packages** including
    `lxml`, `babel`, `pytz`, and `dateparser` (measured 2026-08-04). That is a large tree
    for one function, in a project that already chose `model2vec` over
    `sentence-transformers` on exactly this reasoning. This pass produced the 3,233–6,838
    character range the source decision was made on.

    Paragraphs come back **blank-line separated**, because FR-22's chunker splits on
    paragraph boundaries and cannot find them otherwise.
    """
    if not document:
        return ""
    stripped = _BOILERPLATE.sub(" ", document)
    paragraphs = [strip_markup(match) for match in _PARAGRAPH.findall(stripped)]
    return "\n\n".join(paragraph for paragraph in paragraphs if paragraph)


@dataclass
class RobotsCache:
    """Per-run `robots.txt` decisions, fetched **through the injected client**.

    `RobotFileParser.read()` opens its own URL. That bypasses the injected client, which
    means the socket guard kills it in the test suite and it dodges the configured
    `User-Agent` in production — so the file is fetched here and handed to
    :meth:`RobotFileParser.parse` instead.

    Unreachable is treated as **disallowed**, per RFC 9309, and recorded. A 404 means no
    robots file, which means no restriction. The asymmetry is deliberate: "the publisher
    said nothing" and "we could not find out what the publisher said" are different, and
    only one of them is permission.
    """

    client: httpx.Client
    user_agent: str
    timeout: float = DEFAULT_TIMEOUT
    _parsers: dict[str, RobotFileParser | None] = field(default_factory=dict)
    _reasons: dict[str, str] = field(default_factory=dict)

    def _load(self, origin: str) -> RobotFileParser | None:
        try:
            response = self.client.get(
                f"{origin}/robots.txt",
                headers={"User-Agent": self.user_agent},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            self._reasons[origin] = f"robots.txt unreachable ({type(exc).__name__})"
            return None

        if response.status_code in (404, 410):
            parser = RobotFileParser()
            parser.parse([])  # no file means no restriction
            return parser
        if response.status_code >= 400:
            self._reasons[origin] = f"robots.txt returned {response.status_code}"
            return None

        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        return parser

    def allows(self, url: str) -> bool:
        parts = urllib.parse.urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._parsers:
            self._parsers[origin] = self._load(origin)
        parser = self._parsers[origin]
        if parser is None:
            return False
        return parser.can_fetch(self.user_agent, url)

    def reason_for(self, url: str) -> str:
        parts = urllib.parse.urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        return self._reasons.get(origin, "robots.txt disallows this path")


@dataclass
class HostRateLimiter:
    """At least `delay` seconds between requests to the same host.

    `sleep` and `clock` are injected so the suite asserts the wait was *requested*
    without spending it. A test that actually slept one second per fixture article would
    be a test nobody runs.
    """

    delay: float
    sleep: Callable[[float], None] = _time.sleep
    clock: Callable[[], float] = _time.monotonic
    _last: dict[str, float] = field(default_factory=dict)
    waits: list[tuple[str, float]] = field(default_factory=list)

    def wait_for(self, url: str) -> None:
        if self.delay <= 0:
            return
        host = urllib.parse.urlsplit(url).netloc
        previous = self._last.get(host)
        now = self.clock()
        if previous is not None:
            remaining = self.delay - (now - previous)
            if remaining > 0:
                self.waits.append((host, remaining))
                self.sleep(remaining)
                now = self.clock()
        self._last[host] = now


def fetch_article_body(
    entry: FeedEntry,
    *,
    client: httpx.Client,
    user_agent: str,
    robots: RobotsCache,
    limiter: HostRateLimiter,
    min_body_chars: int,
    timeout: float = DEFAULT_TIMEOUT,
    trace: Any = None,
) -> FeedEntry | None:
    """Fetch and extract one article. ``None`` means the entry was skipped entirely.

    Three outcomes, **none of which invents text**:

    - extracted body at or above ``min_body_chars`` → ``text_source="article"``;
    - anything shorter, or a fetch that failed → ``text_source="summary"``, carrying the
      feed's own summary verbatim. The entry survives; it just says less.
    - ``robots.txt`` disallows → skipped, and the caller sees ``None``.
    """

    def _record(decision: str, reason: str) -> None:
        if trace is not None:
            trace.decision(beat="news", decision=decision, reason=reason)

    if not robots.allows(entry.url):
        _record(
            "article_skipped",
            f"{entry.source}: {robots.reason_for(entry.url)} for {entry.url}",
        )
        return None

    limiter.wait_for(entry.url)

    try:
        response = client.get(
            entry.url,
            headers={"User-Agent": user_agent},
            timeout=timeout,
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        _record(
            "article_fetch_failed",
            (
                f"{entry.source}: {entry.url} could not be fetched "
                f"({type(exc).__name__}); falling back to the feed summary rather than "
                "dropping the entry or inventing a body"
            ),
        )
        return entry.with_body(entry.summary, SOURCE_SUMMARY)

    # A redirect chain can rewrite the canonical url. Keep the one actually fetched, so
    # the digest links where the reader would land.
    final_url = str(response.url)
    resolved = entry if final_url == entry.url else FeedEntry(
        url=final_url,
        source=entry.source,
        headline=entry.headline,
        published=entry.published,
        summary=entry.summary,
    )

    body = extract_body(response.text)
    if len(body) < min_body_chars:
        _record(
            "article_body_short",
            (
                f"{entry.source}: extracted {len(body)} chars from {final_url}, under the "
                f"{min_body_chars}-char floor (paywall, truncation, or an extractor miss); "
                "using the feed summary verbatim"
            ),
        )
        return resolved.with_body(resolved.summary, SOURCE_SUMMARY)

    return resolved.with_body(body, SOURCE_ARTICLE)


def fetch_article_bodies(
    entries: Iterable[FeedEntry],
    *,
    client: httpx.Client,
    user_agent: str,
    now: datetime,
    window_days: int,
    min_body_chars: int,
    fetch_delay_seconds: float = 0.0,
    timeout: float = DEFAULT_TIMEOUT,
    robots: RobotsCache | None = None,
    limiter: HostRateLimiter | None = None,
    trace: Any = None,
) -> list[FeedEntry]:
    """Filter to the window, **then** fetch. The order is the whole point.

    One feed returned 1,108 entries in a single request on 2026-08-04. Filtering after
    fetching would mean a thousand HTTP calls a night against publishers who are doing
    us a favour by serving the feed at all.
    """
    in_window = within_window(entries, now=now, window_days=window_days)
    robots = robots or RobotsCache(client=client, user_agent=user_agent, timeout=timeout)
    limiter = limiter or HostRateLimiter(delay=fetch_delay_seconds)

    fetched: list[FeedEntry] = []
    for entry in in_window:
        result = fetch_article_body(
            entry,
            client=client,
            user_agent=user_agent,
            robots=robots,
            limiter=limiter,
            min_body_chars=min_body_chars,
            timeout=timeout,
            trace=trace,
        )
        if result is not None:
            fetched.append(result)
    return fetched


__all__ = [
    "ADAPTER_NAME",
    "ARTICLE_ADAPTER_NAME",
    "SOURCE_ARTICLE",
    "SOURCE_SUMMARY",
    "SOURCE_UNFETCHED",
    "AdapterError",
    "FeedEntry",
    "HostRateLimiter",
    "RobotsCache",
    "extract_body",
    "fetch_article_bodies",
    "fetch_article_body",
    "fetch_feed",
    "parse_feed",
    "strip_markup",
    "within_window",
]
