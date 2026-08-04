"""Structured per-run trace, and the checker that reads it (FR-13).

Every run writes JSON-lines to ``data/runs/<run_id>.jsonl``: the plan, every tool call
and the observation it returned, every decision with its reason, each beat's result, the
escalation ordering, the rendered digest, delivery, and closing timings and token usage.
It deliberately records **more than v1 consumes** so a later evaluation module has data
to work with. Nothing here decides anything.

The second half of this module is what makes PRD §2's load-bearing metric — zero
checkable claims without a matching tool observation — *machine-checkable* rather than a
matter of opinion. :func:`check_provenance` needs the trace file and the digest the trace
itself recorded, and nothing else.

## What the checker actually checks

Scoped to declared `checkable_fields`, per FR-11 — inning counts, dates, and "6 am" are
prose, not claims.

1. **Support.** Every declared checkable value must be findable in one of the
   observations the beat pointed at. A value with no backing observation is an
   `unsupported_claim` — the fabricated-box-score failure mode, caught mechanically.
2. **Fidelity.** Each observation-backed rendering (a string checkable value, or a
   `BeatItem`'s own text) becomes a numeric template: the literal text with each run of
   digits replaced by a wildcard. Any passage in the digest that matches the template but
   carries *different* numbers is an `altered_claim`. That is what catches "a score
   changed by one".
3. **Honest degradation.** An unavailable beat must have contributed no checkable field,
   and the digest must name it. A failed beat that vanished from the digest is a
   `missing_unavailability_line` (FR-18 / §2c).

A declared value the digest simply doesn't mention is **not** a violation — FR-11 says
"appears only if it matches", not "must appear". Those are reported as notes.

## The fourth case, added by FR-26

Checks 1 and 2 above are computed over declared `checkable_fields` and over renderings
the beat assembled itself. Neither can catch a number the model **invented into a
sentence**, because both shipped beats build their item text from typed API fields in
code — the failure could not previously occur. A summary written from a retrieved passage
is the first place it can.

So a fourth check runs, scoped to items declaring ``fields["text_origin"] ==
"synthesized"``: every number and every quoted phrase in such an item's text must appear
in one of the observations **that item** points at. Items without the flag are untouched,
which is why the Astros and weather beats see no change.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, Iterable, Iterator, Mapping, Sequence

DEFAULT_RUN_DIR = Path(__file__).resolve().parent.parent / "data" / "runs"

#: Env vars whose values must never appear in a trace record.
SECRET_VARS = ("CLAUDE_CODE_OAUTH_TOKEN", "SMTP_PASSWORD")

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


class TraceError(RuntimeError):
    """Something went wrong writing or reading a trace."""


class SecretInTraceError(TraceError):
    """A record was about to be written that contains a secret. Refused."""


def new_run_id(now: datetime | None = None) -> str:
    """A sortable, unique run id."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


class Trace:
    """One run's JSON-lines trace. Recording only — it changes no behavior."""

    def __init__(
        self,
        run_id: str | None = None,
        *,
        directory: str | Path | None = None,
        now: datetime | None = None,
    ) -> None:
        self.run_id = run_id or new_run_id(now)
        self.directory = Path(directory) if directory is not None else DEFAULT_RUN_DIR
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / f"{self.run_id}.jsonl"
        self._handle = self.path.open("a", encoding="utf-8")
        self._observation_seq = 0
        self._closed = False

    # -- lifecycle ---------------------------------------------------------- #

    def __enter__(self) -> "Trace":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._handle.close()
            self._closed = True

    # -- writing ------------------------------------------------------------ #

    def _write(self, record_type: str, **payload: Any) -> dict[str, Any]:
        if self._closed:
            raise TraceError(f"trace {self.run_id} is already closed")
        record = {
            "type": record_type,
            "run_id": self.run_id,
            "at": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        line = json.dumps(record, default=str)
        _assert_no_secret(line)
        self._handle.write(line + "\n")
        self._handle.flush()
        return record

    def run_start(
        self,
        *,
        auth_mode: str,
        config_digest: str,
        config_path: str | None = None,
        preferences_path: str | None = None,
        **extra: Any,
    ) -> None:
        """Opens the run. `auth_mode` is FR-14's evidence that subscription auth was used."""
        self._write(
            "run_start",
            auth_mode=auth_mode,
            config_digest=config_digest,
            config_path=config_path,
            preferences_path=preferences_path,
            **extra,
        )

    def plan(self, entries: Sequence[Mapping[str, Any]]) -> None:
        """One entry per beat: its name and its completion criterion (FR-7)."""
        self._write("plan", beats=[dict(entry) for entry in entries])

    def tool_call(
        self, *, beat: str, adapter: str, arguments: Mapping[str, Any]
    ) -> str:
        """Record an outgoing call; return the observation id it will resolve to."""
        self._observation_seq += 1
        observation_id = f"obs-{self._observation_seq:04d}"
        self._write(
            "tool_call",
            beat=beat,
            adapter=adapter,
            arguments=dict(arguments),
            observation_id=observation_id,
        )
        return observation_id

    def observation(
        self,
        observation_id: str,
        *,
        payload: Any = None,
        error: str | None = None,
    ) -> None:
        """Record what came back — or the error. Failures belong in the trace."""
        self._write(
            "observation", observation_id=observation_id, payload=payload, error=error
        )

    def decision(self, *, beat: str, decision: str, reason: str, **extra: Any) -> None:
        self._write("decision", beat=beat, decision=decision, reason=reason, **extra)

    def beat_result(self, result: Any) -> None:
        """Record a `BeatResult`. Structural access keeps `trace` free of `beats.base`."""
        self._write("beat_result", **serialize_beat_result(result))

    def escalation(
        self,
        *,
        rule: str,
        fired: bool,
        reason: str,
        beat: str | None = None,
        **extra: Any,
    ) -> None:
        self._write(
            "escalation", rule=rule, fired=fired, reason=reason, beat=beat, **extra
        )

    def digest(self, text: str, *, order: Sequence[str] | None = None) -> None:
        """Record the rendered digest so the provenance check needs no other input."""
        self._write("digest", text=text, order=list(order or []))

    def delivery(
        self, *, deliverer: str, target: str, success: bool, error: str | None = None
    ) -> None:
        """Target address is fine here. The password never is."""
        self._write(
            "delivery",
            deliverer=deliverer,
            target=target,
            success=success,
            error=error,
        )

    def missed_run(self, *, expected_at: str, reason: str) -> None:
        """A 7 pm slot that produced no run (PRD §8 / §2b). Counted separately."""
        self._write("missed_run", expected_at=expected_at, reason=reason)

    def run_end(
        self,
        *,
        duration_ms: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
        status: str = "ok",
        error: str | None = None,
        **extra: Any,
    ) -> None:
        self._write(
            "run_end",
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            status=status,
            error=error,
            **extra,
        )


def _assert_no_secret(line: str) -> None:
    for var in SECRET_VARS:
        value = os.environ.get(var)
        if value and len(value) >= 8 and value in line:
            raise SecretInTraceError(
                f"Refusing to write a trace record containing the value of {var}."
            )


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {
        key: getattr(value, key)
        for key in dir(value)
        if not key.startswith("_") and not callable(getattr(value, key))
    }


def serialize_beat_result(result: Any) -> dict[str, Any]:
    """Flatten a `BeatResult` into plain JSON-able data."""

    def get(name: str, default: Any) -> Any:
        if isinstance(result, Mapping):
            return result.get(name, default)
        return getattr(result, name, default)

    items = []
    for item in get("items", []) or []:
        items.append(
            {
                "beat": (item.get("beat") if isinstance(item, Mapping) else item.beat),
                "text": (item.get("text") if isinstance(item, Mapping) else item.text),
                "fields": dict(
                    item.get("fields", {}) if isinstance(item, Mapping) else item.fields
                ),
                "observations": [
                    _observation_id(ref)
                    for ref in (
                        item.get("observations", [])
                        if isinstance(item, Mapping)
                        else item.observations
                    )
                ],
            }
        )

    return {
        "beat": get("beat", ""),
        "items": items,
        "checkable_fields": dict(get("checkable_fields", {}) or {}),
        "available": bool(get("available", True)),
        "error": get("error", None),
        "escalation_candidate": bool(get("escalation_candidate", False)),
        "escalation_reason": get("escalation_reason", None),
        "escalation_signals": dict(get("escalation_signals", {}) or {}),
        "observations": [
            _observation_id(ref) for ref in (get("observations", []) or [])
        ],
    }


def _observation_id(ref: Any) -> str:
    if isinstance(ref, str):
        return ref
    if isinstance(ref, Mapping):
        return str(ref.get("observation_id", ""))
    return str(getattr(ref, "observation_id", ""))


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #


def read_trace(path: str | Path) -> list[dict[str, Any]]:
    """Parse a trace file. A malformed line is an error, not something to skip."""
    trace_path = Path(path)
    if not trace_path.exists():
        raise TraceError(f"No trace file at {trace_path}")
    records: list[dict[str, Any]] = []
    for lineno, line in enumerate(
        trace_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise TraceError(f"{trace_path}:{lineno} is not valid JSON: {exc}") from exc
    return records


def records_of(records: Iterable[Mapping[str, Any]], record_type: str) -> Iterator[dict[str, Any]]:
    for record in records:
        if record.get("type") == record_type:
            yield dict(record)


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ProvenanceViolation:
    kind: str
    beat: str
    field_name: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.kind}] {self.beat}.{self.field_name}: {self.detail}"


@dataclass
class ProvenanceReport:
    """The §2(a) metric, computed. `ok` is False if a single violation exists."""

    run_id: str
    checked_fields: int = 0
    violations: list[ProvenanceViolation] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def __bool__(self) -> bool:
        return self.ok

    def summary(self) -> str:
        if self.ok:
            return (
                f"provenance OK — {self.checked_fields} checkable field(s), "
                f"0 violations ({len(self.notes)} note(s))"
            )
        lines = [f"provenance FAILED — {len(self.violations)} violation(s):"]
        lines.extend(f"  {violation}" for violation in self.violations)
        return "\n".join(lines)


def _flatten_payload(payload: Any) -> Iterator[Any]:
    if isinstance(payload, Mapping):
        for value in payload.values():
            yield from _flatten_payload(value)
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            yield from _flatten_payload(value)
    else:
        yield payload


def _supports(payload: Any, value: Any) -> bool:
    """Is `value` present in this observation payload?

    Either as a leaf (so `28` is backed by a `temperature: 28`) or as a substring of the
    payload's serialization (so `"Astros 3, White Sox 12"`, assembled from two leaves, is
    backed by the numbers that built it).
    """
    leaves = list(_flatten_payload(payload))
    for leaf in leaves:
        if leaf == value:
            return True
        if str(leaf) == str(value):
            return True

    if isinstance(value, str):
        blob = json.dumps(payload, default=str)
        numbers = _NUMBER.findall(value)
        if numbers and all(number in blob for number in numbers):
            return True
        if value and value in blob:
            return True
    return False


def _template(text: str) -> re.Pattern[str] | None:
    """Turn an observation-backed rendering into a numbers-are-wildcards pattern."""
    if not text or not _NUMBER.search(text):
        return None
    parts: list[str] = []
    cursor = 0
    for match in _NUMBER.finditer(text):
        parts.append(re.escape(text[cursor : match.start()]))
        parts.append(r"(\d+(?:\.\d+)?)")
        cursor = match.end()
    parts.append(re.escape(text[cursor:]))
    try:
        # Case-insensitive: the model is allowed to recase a sentence it was handed.
        # It is not allowed to change the numbers inside one.
        return re.compile("".join(parts), re.IGNORECASE)
    except re.error:  # pragma: no cover - templates are built from literals
        return None


def _numbers(text: str) -> list[str]:
    return _NUMBER.findall(text)


# --------------------------------------------------------------------------- #
# FR-26 — grounded text, for items the model wrote rather than assembled
# --------------------------------------------------------------------------- #

#: The flag that opts an item into the grounded-text check. Set by the news beat.
SYNTHESIZED = "synthesized"

#: A closed mapping, 0 through 20. A model handed "3 papers" may legitimately write
#: "three papers", and without this the check fires constantly on correct output.
_NUMBER_WORDS = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five",
    "6": "six", "7": "seven", "8": "eight", "9": "nine", "10": "ten",
    "11": "eleven", "12": "twelve", "13": "thirteen", "14": "fourteen",
    "15": "fifteen", "16": "sixteen", "17": "seventeen", "18": "eighteen",
    "19": "nineteen", "20": "twenty",
}

#: Quoted spans of four characters or more. Shorter is punctuation, not a quotation.
_QUOTED = re.compile(r'"([^"]{4,})"')


def _payload_text(payload: Any) -> str:
    """Everything in an observation, as one searchable string."""
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, default=str)


def _number_is_grounded(number: str, blob: str) -> bool:
    """Digits, or the English word for them if it is 20 or under."""
    if number in blob:
        return True
    word = _NUMBER_WORDS.get(number)
    if word and re.search(rf"\b{word}\b", blob, re.IGNORECASE):
        return True
    # "4" written where the chunk says "4.0", or vice versa.
    try:
        value = float(number)
    except ValueError:
        return False
    for candidate in _NUMBER.findall(blob):
        try:
            if float(candidate) == value:
                return True
        except ValueError:
            continue
    return False


def _check_failed_sources(
    records: Sequence[Mapping[str, Any]],
    digest_text: str,
    report: "ProvenanceReport",
) -> None:
    """FR-28. A beat that reads many sources can fail *partly*, and FR-18 cannot see that.

    ``missing_unavailability_line`` only fires for a beat that is wholly unavailable. A
    news beat with two of five feeds down is `available=True`, so without this check the
    digest could quietly carry three feeds' worth of news and never mention the two it
    could not reach — which reads exactly like a complete picture.
    """
    lowered = digest_text.lower()
    named: set[str] = set()

    for record in records_of(records, "decision"):
        if record.get("decision") != "source_unavailable":
            continue
        source = str(record.get("source") or "")
        if not source or source in named:
            continue
        named.add(source)
        if source.lower() not in lowered:
            report.violations.append(
                ProvenanceViolation(
                    kind="unnamed_failed_source",
                    beat=str(record.get("beat", "")),
                    field_name=source,
                    detail=(
                        f"{source} could not be reached but the digest never names it; a "
                        "partial outage that reads like a complete picture is the failure "
                        "FR-18 exists to prevent"
                    ),
                )
            )


def _check_grounded_text(
    result: Mapping[str, Any],
    observations: Mapping[str, Mapping[str, Any]],
    report: "ProvenanceReport",
) -> None:
    """FR-26. Every number and quote in a model-written item must trace to a passage."""
    beat = str(result.get("beat", ""))

    for item in result.get("items") or []:
        fields = dict(item.get("fields") or {})
        if fields.get("text_origin") != SYNTHESIZED:
            continue

        text = str(item.get("text", ""))
        linked = [str(oid) for oid in (item.get("observations") or [])]
        blob = "\n".join(
            _payload_text(observations[oid].get("payload"))
            for oid in linked
            if oid in observations and observations[oid].get("error") is None
        )

        if not linked:
            report.violations.append(
                ProvenanceViolation(
                    kind="ungrounded_item",
                    beat=beat,
                    field_name="observations",
                    detail=(
                        "item declares text_origin='synthesized' but points at no "
                        "observation, so nothing it says can be traced to a passage"
                    ),
                )
            )
            continue

        for number in _numbers(text):
            if not _number_is_grounded(number, blob):
                report.violations.append(
                    ProvenanceViolation(
                        kind="ungrounded_number",
                        beat=beat,
                        field_name="text",
                        detail=(
                            f"item text states {number!r}, which appears in none of the "
                            f"passages it was grounded in ({', '.join(linked)})"
                        ),
                    )
                )

        lowered = blob.lower()
        for quoted in _QUOTED.findall(text):
            if quoted.lower() not in lowered:
                report.violations.append(
                    ProvenanceViolation(
                        kind="ungrounded_quote",
                        beat=beat,
                        field_name="text",
                        detail=(
                            f"item text quotes {quoted!r}, which appears verbatim in none "
                            f"of the passages it was grounded in ({', '.join(linked)})"
                        ),
                    )
                )


def check_provenance(
    trace_path: str | Path, digest_text: str | None = None
) -> ProvenanceReport:
    """Compute PRD §2(a) over one run.

    ``digest_text`` defaults to the digest the trace recorded, so the check needs the
    trace file and nothing else.
    """
    records = read_trace(trace_path)
    run_id = next((record.get("run_id", "") for record in records), "")

    digests = list(records_of(records, "digest"))
    if digest_text is None:
        if not digests:
            raise TraceError(
                f"{trace_path} records no digest, so provenance cannot be computed "
                "from the trace alone."
            )
        digest_text = str(digests[-1].get("text", ""))

    observations: dict[str, dict[str, Any]] = {}
    for record in records_of(records, "observation"):
        observations[str(record.get("observation_id"))] = record

    report = ProvenanceReport(run_id=run_id)

    _check_failed_sources(records, digest_text, report)

    for result in records_of(records, "beat_result"):
        beat = str(result.get("beat", ""))
        available = bool(result.get("available", True))

        # FR-26. Runs for available beats only: an unavailable one has no items, and its
        # honesty is policed by the unavailability checks below.
        if available:
            _check_grounded_text(result, observations, report)

        checkable = dict(result.get("checkable_fields") or {})
        linked_ids = [str(oid) for oid in (result.get("observations") or [])]
        for item in result.get("items") or []:
            linked_ids.extend(str(oid) for oid in (item.get("observations") or []))

        if not available:
            if checkable:
                report.violations.append(
                    ProvenanceViolation(
                        kind="unavailable_with_claims",
                        beat=beat,
                        field_name="checkable_fields",
                        detail="beat is unavailable but declares checkable values",
                    )
                )
            if beat.lower() not in digest_text.lower():
                report.violations.append(
                    ProvenanceViolation(
                        kind="missing_unavailability_line",
                        beat=beat,
                        field_name="-",
                        detail=(
                            "beat failed but the digest never names it; a failed beat "
                            "must not silently drop out (FR-18)"
                        ),
                    )
                )
            continue

        payloads = [
            observations[oid].get("payload")
            for oid in linked_ids
            if oid in observations and observations[oid].get("error") is None
        ]

        for name, value in checkable.items():
            report.checked_fields += 1

            if not payloads:
                report.violations.append(
                    ProvenanceViolation(
                        kind="unsupported_claim",
                        beat=beat,
                        field_name=name,
                        detail=(
                            f"value {value!r} has no linked observation in this trace"
                        ),
                    )
                )
                continue

            if not any(_supports(payload, value) for payload in payloads):
                report.violations.append(
                    ProvenanceViolation(
                        kind="unsupported_claim",
                        beat=beat,
                        field_name=name,
                        detail=(
                            f"value {value!r} does not appear in any observation it "
                            f"points at ({', '.join(linked_ids)})"
                        ),
                    )
                )
                continue

            if str(value) not in digest_text:
                report.notes.append(
                    f"{beat}.{name}: declared value {value!r} is not stated in the "
                    "digest (allowed — FR-11 scopes the check to values that appear)"
                )

        # Fidelity: an observation-backed rendering must not appear altered.
        renderings = [str(value) for value in checkable.values() if isinstance(value, str)]
        renderings.extend(
            str(item.get("text", "")) for item in (result.get("items") or [])
        )
        for rendering in renderings:
            pattern = _template(rendering)
            if pattern is None:
                continue
            expected = _numbers(rendering)
            for match in pattern.finditer(digest_text):
                if list(match.groups()) != expected:
                    report.violations.append(
                        ProvenanceViolation(
                            kind="altered_claim",
                            beat=beat,
                            field_name="rendered_text",
                            detail=(
                                f"digest states {match.group(0)!r} where the "
                                f"observation-backed value is {rendering!r}"
                            ),
                        )
                    )

    return report


__all__ = [
    "DEFAULT_RUN_DIR",
    "SYNTHESIZED",
    "ProvenanceReport",
    "ProvenanceViolation",
    "SecretInTraceError",
    "Trace",
    "TraceError",
    "check_provenance",
    "new_run_id",
    "read_trace",
    "records_of",
    "serialize_beat_result",
]
