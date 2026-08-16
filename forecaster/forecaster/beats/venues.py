"""Venue listings beat (FR-43, FR-45) — what's playing, in the venue's own words.

The 2026-08-16 re-scope is the design: named venues, a 14-day window, repeated nightly on
purpose (`[retrieval] exempt_beats` — FR-44 — is what honors the repetition; this module
just produces the listings). No corpus, no embedder, no model call: a listing is a
template over typed fields, and every date the digest states is the **page's own text,
verbatim** — quoting the venue's words is a stronger provenance posture than paraphrasing
them, and it makes the FR-11 support check exact rather than approximate.

Parsers are dispatched by the config entry's ``kind``, so FR-47 (Bass via Ticketmaster,
gated on an account that does not yet exist) lands as a new kind plus a config entry —
not a new beat, and not a stub here.

Quiet vs broken, per FR-45: a parsed-but-empty calendar is a *fact* and renders as one
("Nothing on the calendar…"); a fetch or parse failure is a named outage line; every
venue failing is the standard FR-18 unavailable shape. No third state.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable

from forecaster.beats.base import (
    BeatContext,
    BeatItem,
    BeatResult,
    ObservationRef,
    register_beat,
)
from forecaster.tools import venues as venues_tool

ADAPTER_LISTINGS = "venues.fetch_listings"

#: kind → fetcher. Config deliberately does not validate against this mapping (config
#: stays ignorant of code); an unknown kind becomes a named failed venue at run time.
PARSERS: dict[str, Callable[..., list[venues_tool.Production]]] = {
    "zach_shows": venues_tool.fetch_listings,
}


@register_beat
class VenueListingsBeat:
    """`name = "venues"`. One class plus one config entry, per FR-2."""

    name = "venues"
    completion_criterion = (
        "every configured venue yields in-window listings, an explicit quiet line, or a "
        "named outage line; listings quote the venue's own dates text"
    )

    def should_run(self, context: BeatContext) -> bool:
        return bool(context.config.beats.get(self.name, False))

    def run(self, context: BeatContext) -> BeatResult:
        settings = context.config.venues
        if settings is None:
            return BeatResult.unavailable(
                self.name, "the venues beat is enabled but [venues] is not configured"
            )

        items: list[BeatItem] = []
        checkable: dict[str, Any] = {}
        refs: list[ObservationRef] = []
        failed: list[tuple[str, str]] = []

        for venue in settings.venues:
            outcome = self._venue(context, settings, venue)
            if outcome.error is not None:
                failed.append((venue.name, outcome.error))
                items.append(self._outage_item(context, venue.name, outcome.error))
                continue
            items.extend(outcome.items)
            checkable.update(outcome.checkable)
            if outcome.ref is not None:
                refs.append(outcome.ref)

        if failed and len(failed) == len(settings.venues):
            return BeatResult.unavailable(
                self.name,
                "every configured venue failed: "
                + "; ".join(f"{name} ({error})" for name, error in failed),
            )

        return BeatResult(
            beat=self.name,
            items=items,
            checkable_fields=checkable,
            available=True,
            observations=refs,
        )

    # -- one venue ---------------------------------------------------------- #

    class _VenueOutcome:
        def __init__(self) -> None:
            self.items: list[BeatItem] = []
            self.checkable: dict[str, Any] = {}
            self.ref: ObservationRef | None = None
            self.error: str | None = None

    def _venue(self, context: BeatContext, settings: Any, venue: Any) -> "_VenueOutcome":
        outcome = self._VenueOutcome()

        observation_id = context.trace.tool_call(
            beat=self.name,
            adapter=ADAPTER_LISTINGS,
            arguments={"venue": venue.name, "kind": venue.kind, "url": venue.url},
        )

        fetcher = PARSERS.get(venue.kind)
        if fetcher is None:
            detail = f"no parser registered for kind {venue.kind!r}"
            context.trace.observation(observation_id, error=detail)
            context.trace.decision(
                beat=self.name,
                decision="venue_unavailable",
                reason=f"{venue.name}: {detail}",
                venue=venue.name,
            )
            outcome.error = detail
            return outcome

        try:
            productions = fetcher(
                venue.url,
                client=context.http_client,
                user_agent=settings.user_agent,
                timeout=settings.timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - one dark venue is not a dead beat
            detail = f"{type(exc).__name__}: {exc}"
            context.trace.observation(observation_id, error=detail)
            context.trace.decision(
                beat=self.name,
                decision="venue_unavailable",
                reason=f"{venue.name}: {detail}",
                venue=venue.name,
            )
            outcome.error = detail
            return outcome

        context.trace.observation(
            observation_id,
            payload={
                "venue": venue.name,
                "productions": [production.as_record() for production in productions],
            },
        )
        ref = ObservationRef(observation_id, ADAPTER_LISTINGS)
        outcome.ref = ref

        in_window = self._in_window(context, settings, productions)
        stamp = context.now.date().isoformat()

        if not in_window:
            context.trace.decision(
                beat=self.name,
                decision="venue_quiet",
                reason=(
                    f"{venue.name}: parsed {len(productions)} production(s), none "
                    f"inside the next {settings.window_days} day(s); saying so rather "
                    "than saying nothing"
                ),
                venue=venue.name,
            )
            outcome.items.append(
                BeatItem(
                    beat=self.name,
                    text=(
                        f"Nothing on the calendar at {venue.name} in the next "
                        f"{settings.window_days} days."
                    ),
                    fields={"venue": venue.name, "as_of": stamp},
                    observations=[ref],
                )
            )
            return outcome

        for index, production in enumerate(in_window):
            dates = production.raw_dates or "dates: see site"
            outcome.items.append(
                BeatItem(
                    beat=self.name,
                    # The venue's own dates text, verbatim — never a paraphrase.
                    text=f'At {venue.name}: "{production.title}" — {dates} {production.url}',
                    fields={
                        "venue": venue.name,
                        "title": production.title,
                        "start_date": (
                            production.start_date.isoformat()
                            if production.start_date
                            else None
                        ),
                        "end_date": (
                            production.end_date.isoformat()
                            if production.end_date
                            else None
                        ),
                        "raw_dates": production.raw_dates,
                        "as_of": stamp,
                    },
                    observations=[ref],
                )
            )
            outcome.checkable[f"{venue.name}:{index}:title"] = production.title
            if production.raw_dates:
                outcome.checkable[f"{venue.name}:{index}:dates"] = production.raw_dates

        context.trace.decision(
            beat=self.name,
            decision="venue_listed",
            reason=(
                f"{venue.name}: {len(in_window)} of {len(productions)} parsed "
                f"production(s) intersect the next {settings.window_days} day(s)"
            ),
            venue=venue.name,
            listed=len(in_window),
            parsed=len(productions),
        )
        return outcome

    def _in_window(
        self, context: BeatContext, settings: Any, productions: list[Any]
    ) -> list[Any]:
        """Runs intersecting [today, today + window]. Unparsed dates are included —
        a listing with "dates: see site" is honest; silently dropping it is not."""
        today = context.now.date()
        horizon = today + timedelta(days=settings.window_days)
        kept = []
        for production in productions:
            if production.start_date is None or production.end_date is None:
                kept.append(production)
                continue
            if production.start_date <= horizon and production.end_date >= today:
                kept.append(production)
        return kept

    def _outage_item(self, context: BeatContext, venue_name: str, error: str) -> BeatItem:
        """FR-28 shape: a dark venue is named nightly, as loudly on day seven as day one."""
        return BeatItem(
            beat=self.name,
            text=f"Couldn't read {venue_name}'s calendar tonight ({error}).",
            fields={"venue": venue_name, "as_of": context.now.date().isoformat()},
        )


__all__ = ["PARSERS", "VenueListingsBeat"]
