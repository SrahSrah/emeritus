"""The ``Beat`` contract everything else is written against (FR-2).

This is the extensibility seam. The planner and the synthesizer know **only** what is in
this module — never a concrete beat — so FR-17's four future beats land as one class plus
one config entry, with no edit to `planner.py`, `synthesizer.py`, or `delivery/`.

Three things are load-bearing beyond the obvious:

- **`checkable_fields`** is the set of values the synthesizer is allowed to state as
  fact. FR-11's provenance check is computed over exactly this set, so widening it to
  "every number" would defeat the point — inning counts, dates, and "6 am" are prose.
- **`available` / `error`** is the FR-18 shape. A beat whose adapter failed says so; it
  never silently drops out of the digest.
- **`escalation_signals`** is a beat-agnostic bag the rules engine may read. Sport- and
  domain-specific data goes here or in an item's `fields`, never as a named column on
  the universal contract.

`TraceWriter` and `ScratchpadLike` are declared here as `Protocol`s so nothing
forward-references a module that does not exist yet. Steps 6 and 7 implement them; this
module never imports them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping, Protocol, TypeVar, runtime_checkable

from forecaster.config import Config, enabled_beats
from forecaster.memory.preferences import Preferences

T = TypeVar("T")


# --------------------------------------------------------------------------- #
# Collaborator interfaces (implemented in Steps 6 and 7)
# --------------------------------------------------------------------------- #


@runtime_checkable
class TraceWriter(Protocol):
    """What a beat may record. See `forecaster.trace` for the implementation."""

    def tool_call(
        self, *, beat: str, adapter: str, arguments: Mapping[str, Any]
    ) -> str:
        """Record an outgoing call and return the observation id it will resolve to."""
        ...

    def observation(
        self,
        observation_id: str,
        *,
        payload: Any = None,
        error: str | None = None,
    ) -> None:
        """Record what the call returned — or the error it raised."""
        ...

    def decision(self, *, beat: str, decision: str, reason: str, **extra: Any) -> None:
        """Record a branch that was taken and why."""
        ...


@runtime_checkable
class ScratchpadLike(Protocol):
    """Per-run short-term memory. See `forecaster.memory.scratchpad`."""

    def get_or_call(
        self,
        fn: Callable[[], T],
        *,
        beat: str,
        adapter: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> T:
        """Serve an identical call from memory rather than re-invoking the adapter."""
        ...

    def note(self, beat: str, note: str) -> None:
        """Record something learned."""
        ...

    def note_missing(self, beat: str, note: str) -> None:
        """Record something still missing."""
        ...


# --------------------------------------------------------------------------- #
# Result shape
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ObservationRef:
    """A pointer from a stated value back to the trace record it came from."""

    observation_id: str
    adapter: str
    note: str = ""


@dataclass
class BeatItem:
    """One line of the digest, plus the structured values behind it."""

    beat: str
    text: str
    fields: dict[str, Any] = field(default_factory=dict)
    observations: list[ObservationRef] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.beat:
            raise ValueError("BeatItem.beat must be set")


@dataclass
class BeatResult:
    """Everything one beat produced this run.

    ``available=False`` requires a populated ``error``: FR-18 turns a failed adapter into
    an explicit "couldn't reach X tonight" line, and an unavailable result with no reason
    could not render one.
    """

    beat: str
    items: list[BeatItem] = field(default_factory=list)
    checkable_fields: dict[str, Any] = field(default_factory=dict)
    available: bool = True
    error: str | None = None
    escalation_candidate: bool = False
    escalation_reason: str | None = None
    escalation_signals: dict[str, Any] = field(default_factory=dict)
    observations: list[ObservationRef] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.beat:
            raise ValueError("BeatResult.beat must be set")
        if not self.available and not self.error:
            raise ValueError(
                f"BeatResult({self.beat!r}) is unavailable but carries no error. FR-18 "
                "requires the digest to say what could not be reached."
            )
        if self.available and self.error:
            raise ValueError(
                f"BeatResult({self.beat!r}) is available but carries an error — pick one."
            )
        if self.escalation_candidate and not self.escalation_reason:
            raise ValueError(
                f"BeatResult({self.beat!r}) is an escalation candidate with no reason. "
                "An unexplained promotion is not auditable."
            )
        if not self.available and self.checkable_fields:
            raise ValueError(
                f"BeatResult({self.beat!r}) is unavailable but declares checkable_fields. "
                "There is nothing to state as fact when the source could not be reached."
            )

    @classmethod
    def unavailable(cls, beat: str, error: str, **kwargs: Any) -> "BeatResult":
        """The FR-18 shape, built so it cannot be built wrong."""
        return cls(beat=beat, available=False, error=error, checkable_fields={}, **kwargs)


# --------------------------------------------------------------------------- #
# Context and protocol
# --------------------------------------------------------------------------- #


@dataclass
class BeatContext:
    """Everything a beat is handed. Nothing is reached for globally.

    ``embedder``, ``corpus``, and ``agent_client`` are optional and only a document-shaped
    beat uses them (FR-23/FR-24/FR-25). They are handed *in* rather than constructed by the
    beat, for the reason this project always injects: the real embedder fetches model
    weights on first use and the real agent client makes a model call, so a beat that built
    its own would reach for the network inside the test suite — and would load the model a
    second time in production when the run already has one.

    ``agent_client`` is the first crack in "beats do not talk to the model". Through FR-25
    every beat turned a typed API response into a sentence *in code*, so only the
    synthesizer needed a client. A beat that summarizes retrieved passages cannot. FR-11's
    guarantee is unchanged and is what makes this safe: the model phrases, and
    :func:`forecaster.trace.check_provenance` fails the run if a figure it wrote is not in
    a passage the item points at.

    Adding these here is not an FR-2 seam violation. FR-2's zero-edit clause names
    `planner.py`, `synthesizer.py`, and `delivery/`; this module *is* the contract, and a
    new optional field on it breaks no existing beat.
    """

    config: Config
    preferences: Preferences
    now: datetime
    scratchpad: ScratchpadLike
    trace: TraceWriter
    http_client: Any = None
    embedder: Any = None
    corpus: Any = None
    agent_client: Any = None


@runtime_checkable
class Beat(Protocol):
    """The one interface every beat implements."""

    name: str

    def should_run(self, context: BeatContext) -> bool: ...

    def run(self, context: BeatContext) -> BeatResult: ...


# --------------------------------------------------------------------------- #
# Registry — one class + one config entry is the whole cost of a new beat
# --------------------------------------------------------------------------- #

_REGISTRY: dict[str, type] = {}


def register_beat(cls: type) -> type:
    """Register a beat class. Usable as a decorator."""
    name = getattr(cls, "name", None)
    if not isinstance(name, str) or not name:
        raise ValueError(f"{cls.__name__} must define a non-empty class-level `name`")
    existing = _REGISTRY.get(name)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"A different beat is already registered as {name!r}: {existing.__name__}"
        )
    _REGISTRY[name] = cls
    return cls


def unregister_beat(name: str) -> None:
    """Remove a beat from the registry. Mostly for tests that register a dummy."""
    _REGISTRY.pop(name, None)


def registered_beats() -> dict[str, type]:
    """A copy of the registry, so callers cannot mutate it by accident."""
    return dict(_REGISTRY)


def get_beats(config: Config) -> list[Beat]:
    """Instantiate the beats this config enables, in config declaration order.

    A config that enables a beat nobody registered is a config error, not a silent skip —
    a typo in `[beats]` should not quietly shrink the digest.
    """
    instances: list[Beat] = []
    missing: list[str] = []
    for name in enabled_beats(config):
        cls = _REGISTRY.get(name)
        if cls is None:
            missing.append(name)
            continue
        instances.append(cls())
    if missing:
        known = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise LookupError(
            f"config.toml enables beat(s) {missing} that are not registered. "
            f"Registered: {known}."
        )
    return instances


# --------------------------------------------------------------------------- #
# Failure handling (FR-18) — no beat may crash the run, none may vanish from it
# --------------------------------------------------------------------------- #


def run_beat_safely(beat: Beat, context: BeatContext) -> BeatResult:
    """Run a beat, turning any failure into an honest unavailable result.

    An adapter error, a timeout, a parse failure, or an outright bug all become a
    `BeatResult` with ``available=False``, a populated ``error``, and empty
    ``checkable_fields`` — never a substituted value and never a silent disappearance.
    The error is recorded in the trace as an observation, because PRD §8's instruction is
    to *fail loudly into the trace rather than emit a plausible score*.

    Catching bare `Exception` is deliberate. Narrowing it to `AdapterError` would let an
    unrelated bug in one beat take down a run that could still have delivered the other
    beat's content.
    """
    try:
        return beat.run(context)
    except Exception as exc:  # noqa: BLE001 - a beat must not be able to kill the run
        detail = f"{type(exc).__name__}: {exc}"
        trace = getattr(context, "trace", None)
        if trace is not None:
            observation_id = trace.tool_call(
                beat=beat.name, adapter="beat.run", arguments={}
            )
            trace.observation(observation_id, error=detail)
            trace.decision(
                beat=beat.name,
                decision="beat_unavailable",
                reason=(
                    f"{beat.name} failed with {detail}; reporting it as unavailable "
                    "rather than substituting a value"
                ),
            )
        return BeatResult.unavailable(beat.name, detail)


def load_builtin_beats() -> None:
    """Import the shipped beats so importing them registers them.

    Kept as a function rather than an import at module scope: `base.py` must not depend
    on any concrete beat, or the seam this module exists to protect stops being a seam.
    """
    from forecaster.beats import astros, need_to_know, news, venues, weather  # noqa: F401


__all__ = [
    "Beat",
    "BeatContext",
    "BeatItem",
    "BeatResult",
    "ObservationRef",
    "ScratchpadLike",
    "TraceWriter",
    "get_beats",
    "load_builtin_beats",
    "register_beat",
    "registered_beats",
    "run_beat_safely",
    "unregister_beat",
]
