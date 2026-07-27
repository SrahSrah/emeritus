"""Per-run scratchpad — short-term memory (FR-8).

Each run gets one. It records what each beat searched, what came back, and what is still
missing, and it memoizes calls so an identical adapter call inside a single run is served
from memory instead of hitting the wire twice.

**It dies with the process.** No file, no SQLite, no cross-run reuse, no TTL, no size
limit, no disk spillover — one run is the whole lifetime. The long-term counterpart is
the sent-item ledger (FR-9), and the two are deliberately on opposite sides of the run
boundary (PRD §4).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, TypeVar

T = TypeVar("T")


def call_key(adapter: str, arguments: Mapping[str, Any] | None) -> str:
    """The cache key: a normalized call signature, never object identity.

    Sorted keys and a stable serializer, so ``{"a": 1, "b": 2}`` and ``{"b": 2, "a": 1}``
    are the same call — which is the whole point of memoizing.
    """
    payload = json.dumps(dict(arguments or {}), sort_keys=True, default=str)
    return f"{adapter}({payload})"


@dataclass
class Search:
    """One adapter call this run made."""

    beat: str
    adapter: str
    arguments: dict[str, Any]
    key: str
    served_from_cache: bool = False


@dataclass
class Scratchpad:
    """In-memory notes for one run."""

    searches: list[Search] = field(default_factory=list)
    notes: dict[str, list[str]] = field(default_factory=dict)
    missing: dict[str, list[str]] = field(default_factory=dict)
    trace: Any = None
    _cache: dict[str, Any] = field(default_factory=dict, repr=False)

    # -- memoized calls ----------------------------------------------------- #

    def get_or_call(
        self,
        fn: Callable[[], T],
        *,
        beat: str,
        adapter: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> T:
        """Serve an identical call from the scratchpad rather than re-invoking it.

        Both the hit and the miss are written to the trace as a `decision`, so a
        served-from-cache call is visible rather than looking like a call that never
        happened.
        """
        key = call_key(adapter, arguments)
        hit = key in self._cache

        self.searches.append(
            Search(
                beat=beat,
                adapter=adapter,
                arguments=dict(arguments or {}),
                key=key,
                served_from_cache=hit,
            )
        )

        if hit:
            self._record(
                beat=beat,
                decision="scratchpad_hit",
                reason=f"identical call {key} already made this run; not re-invoking",
                adapter=adapter,
            )
            return self._cache[key]

        self._record(
            beat=beat,
            decision="scratchpad_miss",
            reason=f"first {key} this run; invoking the adapter",
            adapter=adapter,
        )
        value = fn()
        self._cache[key] = value
        return value

    def cached(self, adapter: str, arguments: Mapping[str, Any] | None = None) -> bool:
        return call_key(adapter, arguments) in self._cache

    # -- notes -------------------------------------------------------------- #

    def note(self, beat: str, note: str) -> None:
        """Record something found."""
        self.notes.setdefault(beat, []).append(note)

    def note_missing(self, beat: str, note: str) -> None:
        """Record something still missing, so the run can say what it doesn't know."""
        self.missing.setdefault(beat, []).append(note)

    def still_missing(self, beat: str | None = None) -> list[str]:
        if beat is not None:
            return list(self.missing.get(beat, []))
        return [item for entries in self.missing.values() for item in entries]

    # -- reporting ---------------------------------------------------------- #

    @property
    def call_count(self) -> int:
        """Calls that actually reached an adapter (cache hits excluded)."""
        return sum(1 for search in self.searches if not search.served_from_cache)

    @property
    def hit_count(self) -> int:
        return sum(1 for search in self.searches if search.served_from_cache)

    def summary(self) -> dict[str, Any]:
        return {
            "searches": len(self.searches),
            "adapter_calls": self.call_count,
            "cache_hits": self.hit_count,
            "still_missing": self.still_missing(),
        }

    # -- internals ---------------------------------------------------------- #

    def _record(self, *, beat: str, decision: str, reason: str, **extra: Any) -> None:
        if self.trace is None:
            return
        self.trace.decision(beat=beat, decision=decision, reason=reason, **extra)


__all__ = ["Scratchpad", "Search", "call_key"]
