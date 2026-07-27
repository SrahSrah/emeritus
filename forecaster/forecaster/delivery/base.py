"""The `Deliverer` interface, and the fake that makes the pipeline testable (FR-12).

One method: ``send(digest)``. Config's ``[delivery].kind`` picks which implementation a
run uses, so the whole pipeline can be exercised end to end without sending anything.

v1 ships **email only** (PRD §4). No SMS, no push, no webhook — the divergence from the
submitted checkpoints is §9 Q1 and is Sarah's framing call, not a build decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class DeliveryResult:
    """What happened. The target address is fine to record; a credential never is."""

    deliverer: str
    target: str
    success: bool
    sent_at: str
    error: str | None = None


@runtime_checkable
class Deliverer(Protocol):
    """One method. That is the whole contract."""

    name: str
    target: str

    def send(self, digest: Any) -> DeliveryResult: ...


def _digest_text(digest: Any) -> str:
    return getattr(digest, "text", str(digest))


@dataclass
class FakeDeliverer:
    """Captures the digest in memory. Sends nothing, ever."""

    target: str = "captured-in-memory"
    name: str = "FakeDeliverer"
    sent: list[Any] = field(default_factory=list)

    @property
    def last_text(self) -> str | None:
        return _digest_text(self.sent[-1]) if self.sent else None

    def send(self, digest: Any) -> DeliveryResult:
        self.sent.append(digest)
        return DeliveryResult(
            deliverer=self.name,
            target=self.target,
            success=True,
            sent_at=datetime.now(timezone.utc).isoformat(),
        )


__all__ = ["Deliverer", "DeliveryResult", "FakeDeliverer"]
