"""ZACH listings parser (FR-42) — a venue calendar into typed productions.

The page (captured 2026-08-16, `tests/fixtures/zach_shows.html`) is server-rendered:
season sections carry `id="onstage"`, and each production is an
`<article class="… contenthighlight-content">` card holding an `<h3>` title, an optional
ticket link, and a `<strong>` line like ``July 22 - August 23, 2026 | The Kleberg``.

Three structural outcomes, kept distinct on purpose (FR-45 depends on the distinction):

- **parsed, with productions** — the normal case;
- **parsed, empty** — the `onstage` landmark is present but holds no cards. A real fact
  ("nothing announced"), returned as ``[]``;
- **unparseable** — the landmark is gone, which is what a site redesign looks like.
  Raises :class:`VenueParseError`, so the beat reports an outage instead of quietly
  showing an empty calendar. A redesign is this beat's 500.

Dates are parsed from the page's informal text, which the capture shows in real variety:
hyphens and en-dashes, non-breaking spaces, cross-year ranges with both years, ranges
whose start inherits the end's year, day-only second halves ("JUNE 2–27, 2027"), and an
all-caps month. Anything the patterns cannot claim confidently keeps its ``raw_dates``
text verbatim with ``None`` dates — **a guessed date is a fabricated fact wearing a
calendar**, and FR-18 applies to calendars too.
"""

from __future__ import annotations

import html as _html
import re
import urllib.parse
from dataclasses import dataclass
from datetime import date

import httpx

from forecaster.tools.feeds import RobotsCache, strip_markup

DEFAULT_TIMEOUT = 15.0

#: The structural landmark. Present on every season section of the captured page; its
#: absence means the page no longer has the shape this parser understands.
LANDMARK = 'id="onstage"'


class VenueParseError(RuntimeError):
    """The page fetched fine but no longer looks like a calendar we can read."""


@dataclass(frozen=True)
class Production:
    """One show on a venue's calendar.

    ``raw_dates`` is always the page's own words; ``start_date``/``end_date`` are filled
    only when the parse is unambiguous. ``None`` dates with non-empty ``raw_dates`` is
    the honest "dates: see site" state, and the beat includes such productions rather
    than silently dropping what it could not parse.
    """

    title: str
    url: str
    raw_dates: str
    start_date: date | None
    end_date: date | None

    def as_record(self) -> dict[str, object]:
        """The shape written into the run trace."""
        return {
            "title": self.title,
            "url": self.url,
            "raw_dates": self.raw_dates,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
        }


_CARD = re.compile(
    r'<article class="[^"]*contenthighlight-content[^"]*">(.*?)</article>', re.S
)
_TITLE = re.compile(r"<h3[^>]*>(.*?)</h3>", re.S)
_STRONG = re.compile(r"<strong>(.*?)</strong>", re.S)
_HREF = re.compile(r'href="([^"]+)"')

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
_MONTH = "|".join(_MONTHS)

#: ``July 22 - August 23, 2026`` · ``October 16, 2026–February 14, 2027`` ·
#: ``JUNE 2–27, 2027`` — the second month and either year are optional.
_RANGE = re.compile(
    rf"(?P<m1>{_MONTH})\s+(?P<d1>\d{{1,2}})(?:,\s*(?P<y1>\d{{4}}))?"
    rf"\s*[-–—]\s*"
    rf"(?:(?P<m2>{_MONTH})\s+)?(?P<d2>\d{{1,2}})(?:,\s*(?P<y2>\d{{4}}))?",
    re.IGNORECASE,
)
_SINGLE = re.compile(
    rf"(?P<m>{_MONTH})\s+(?P<d>\d{{1,2}}),\s*(?P<y>\d{{4}})", re.IGNORECASE
)


def parse_date_range(raw: str) -> tuple[date | None, date | None]:
    """The page's informal date text into ``(start, end)``, or ``(None, None)``.

    Rules, in the order the capture forced them: a start with no year inherits the
    end's; a second half with no month inherits the first's; a start that then lands
    after its end crossed a year boundary, so it backs up one year. No year anywhere,
    or an impossible day, means no claim — never a guess.
    """
    text = raw.replace("\xa0", " ")
    match = _RANGE.search(text)
    if match:
        y1, y2 = match.group("y1"), match.group("y2")
        if y1 is None and y2 is None:
            return None, None
        year_start = int(y1) if y1 else int(y2)
        year_end = int(y2) if y2 else int(y1)
        month_start = _MONTHS[match.group("m1").lower()]
        month_end = (
            _MONTHS[match.group("m2").lower()] if match.group("m2") else month_start
        )
        try:
            start = date(year_start, month_start, int(match.group("d1")))
            end = date(year_end, month_end, int(match.group("d2")))
        except ValueError:
            return None, None
        if start > end and y1 is None:
            start = date(year_start - 1, month_start, int(match.group("d1")))
        if start > end:
            return None, None
        return start, end

    match = _SINGLE.search(text)
    if match:
        try:
            when = date(
                int(match.group("y")),
                _MONTHS[match.group("m").lower()],
                int(match.group("d")),
            )
        except ValueError:
            return None, None
        return when, when

    return None, None


def parse_listings(document: str, *, base_url: str) -> list[Production]:
    """The three-outcome parse. See the module docstring for why it raises."""
    if LANDMARK not in document:
        raise VenueParseError(
            "the listings page has no 'onstage' section — the page shape this parser "
            "was written against (captured 2026-08-16) is gone, which is what a "
            "redesign looks like. Recapture the fixture and update the parser."
        )

    productions: list[Production] = []
    for match in _CARD.finditer(document):
        card = match.group(1)
        title_match = _TITLE.search(card)
        if title_match is None:
            continue
        title = strip_markup(_html.unescape(title_match.group(1))).strip()
        if not title:
            continue

        href_match = _HREF.search(card)
        url = (
            urllib.parse.urljoin(base_url, _html.unescape(href_match.group(1)))
            if href_match
            else base_url
        )

        strong_match = _STRONG.search(card)
        raw_dates = (
            strip_markup(_html.unescape(strong_match.group(1))).replace("\xa0", " ").strip()
            if strong_match
            else ""
        )
        start, end = parse_date_range(raw_dates) if raw_dates else (None, None)

        productions.append(
            Production(
                title=title, url=url, raw_dates=raw_dates, start_date=start, end_date=end
            )
        )
    return productions


def fetch_listings(
    url: str,
    *,
    client: httpx.Client,
    user_agent: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[Production]:
    """Fetch and parse one venue calendar. The FR-21 posture, minus the rate limiter
    (one page per venue per night needs no pacing).

    Raises :class:`VenueParseError` for a robots disallow, a non-200, or an
    unrecognizable page — the beat turns any of those into a named outage (FR-45).
    Follows no cross-host redirect: the captured domain gotcha (``zachtheatre.org``
    bounces through a ticketing session host) is exactly the kind of trip a listings
    fetch should refuse rather than chase.
    """
    robots = RobotsCache(client=client, user_agent=user_agent, timeout=timeout)
    if not robots.allows(url):
        raise VenueParseError(f"robots.txt does not permit {url}: {robots.reason_for(url)}")

    response = client.get(
        url, headers={"User-Agent": user_agent}, timeout=timeout, follow_redirects=False
    )
    if response.status_code != 200:
        raise VenueParseError(f"{url} returned HTTP {response.status_code}")
    return parse_listings(response.text, base_url=url)


__all__ = [
    "DEFAULT_TIMEOUT",
    "LANDMARK",
    "Production",
    "VenueParseError",
    "fetch_listings",
    "parse_date_range",
    "parse_listings",
]
