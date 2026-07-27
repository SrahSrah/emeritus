"""Step 7 — an identical call inside one run hits the adapter exactly once."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from forecaster.beats.base import ScratchpadLike
from forecaster.memory.scratchpad import Scratchpad, call_key
from forecaster.trace import Trace, read_trace, records_of


class CountingAdapter:
    """Counts how many times it was actually invoked."""

    def __init__(self) -> None:
        self.call_count = 0

    def fetch(self, **kwargs: Any) -> dict[str, Any]:
        self.call_count += 1
        return {"invocation": self.call_count, **kwargs}


class StubWorker:
    """A beat-shaped caller that always goes through the scratchpad."""

    def __init__(self, scratchpad: ScratchpadLike, adapter: CountingAdapter) -> None:
        self.scratchpad = scratchpad
        self.adapter = adapter

    def schedule(self, date: str) -> dict[str, Any]:
        return self.scratchpad.get_or_call(
            lambda: self.adapter.fetch(team_id=117, date=date),
            beat="astros",
            adapter="mlb.fetch_schedule",
            arguments={"team_id": 117, "date": date},
        )


def test_repeated_identical_call_invokes_the_adapter_once() -> None:
    adapter = CountingAdapter()
    worker = StubWorker(Scratchpad(), adapter)

    first = worker.schedule("2026-07-26")
    second = worker.schedule("2026-07-26")

    assert adapter.call_count == 1
    assert first == second
    assert first["invocation"] == 1


def test_two_different_calls_invoke_the_adapter_twice() -> None:
    adapter = CountingAdapter()
    worker = StubWorker(Scratchpad(), adapter)

    worker.schedule("2026-07-26")
    worker.schedule("2026-07-27")

    assert adapter.call_count == 2


def test_the_key_is_the_normalized_signature_not_object_identity() -> None:
    adapter = CountingAdapter()
    pad = Scratchpad()

    pad.get_or_call(
        lambda: adapter.fetch(),
        beat="astros",
        adapter="mlb.fetch_schedule",
        arguments={"team_id": 117, "date": "2026-07-26"},
    )
    pad.get_or_call(
        lambda: adapter.fetch(),
        beat="astros",
        adapter="mlb.fetch_schedule",
        arguments={"date": "2026-07-26", "team_id": 117},  # same call, keys reordered
    )

    assert adapter.call_count == 1
    assert call_key("a", {"x": 1, "y": 2}) == call_key("a", {"y": 2, "x": 1})
    assert call_key("a", {"x": 1}) != call_key("b", {"x": 1})


def test_scratchpad_reports_counts_and_still_missing() -> None:
    adapter = CountingAdapter()
    pad = Scratchpad()
    worker = StubWorker(pad, adapter)

    worker.schedule("2026-07-26")
    worker.schedule("2026-07-26")
    pad.note("astros", "found last night's final")
    pad.note_missing("astros", "no injury feed exists in v1")

    assert pad.call_count == 1
    assert pad.hit_count == 1
    assert pad.still_missing("astros") == ["no injury feed exists in v1"]
    assert pad.still_missing() == ["no injury feed exists in v1"]
    assert pad.summary()["adapter_calls"] == 1
    assert pad.notes["astros"] == ["found last night's final"]


def test_both_the_hit_and_the_miss_land_in_the_trace(tmp_path: Path) -> None:
    adapter = CountingAdapter()
    with Trace("scratchpad-run", directory=tmp_path) as trace:
        worker = StubWorker(Scratchpad(trace=trace), adapter)
        worker.schedule("2026-07-26")
        worker.schedule("2026-07-26")

    decisions = list(records_of(read_trace(trace.path), "decision"))
    kinds = [record["decision"] for record in decisions]

    assert kinds == ["scratchpad_miss", "scratchpad_hit"]
    assert "not re-invoking" in decisions[1]["reason"]
    assert decisions[1]["beat"] == "astros"


def test_nothing_is_written_to_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Short-term means short-term: no file, no db, no cross-run reuse."""
    monkeypatch.chdir(tmp_path)
    adapter = CountingAdapter()
    worker = StubWorker(Scratchpad(), adapter)
    worker.schedule("2026-07-26")
    worker.schedule("2026-07-26")

    assert list(Path(tmp_path).iterdir()) == []


def test_a_fresh_scratchpad_shares_nothing_with_the_previous_one() -> None:
    adapter = CountingAdapter()

    StubWorker(Scratchpad(), adapter).schedule("2026-07-26")
    StubWorker(Scratchpad(), adapter).schedule("2026-07-26")

    assert adapter.call_count == 2, "a new run must not reuse the previous run's cache"


def test_scratchpad_satisfies_the_protocol_beats_are_written_against() -> None:
    assert isinstance(Scratchpad(), ScratchpadLike)


def test_cached_reports_membership_without_invoking() -> None:
    adapter = CountingAdapter()
    pad = Scratchpad()
    args = {"team_id": 117}

    assert not pad.cached("mlb.fetch_schedule", args)
    pad.get_or_call(
        lambda: adapter.fetch(), beat="astros", adapter="mlb.fetch_schedule", arguments=args
    )
    assert pad.cached("mlb.fetch_schedule", args)
    assert adapter.call_count == 1
