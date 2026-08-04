"""Shared test harness.

Two jobs:

1. **Fixtures over the wire.** ``load_fixture`` reads a recorded JSON payload from
   ``tests/fixtures/``; ``load_text_fixture`` reads a recorded XML/HTML/text one;
   ``mock_transport`` turns a list of routes into an ``httpx.MockTransport`` so an
   adapter under test sees a real ``httpx.Client`` serving recorded bytes.
2. **No live network, ever.** An ``autouse`` fixture patches ``socket.socket.connect``
   so a test that reaches for the network fails loudly and immediately.

## Why there are two loaders

Through Steps 1–22 every adapter spoke JSON, so the harness did too: ``load_fixture``
parsed JSON, and ``mock_transport`` built ``httpx.Response(json=...)``. The news beat's
sources are **RSS/Atom (XML), article pages (HTML), and robots.txt (plain text)**, none
of which survive a round trip through ``json.loads``. Without the text path, Step 25's
adapter could not have a recorded fixture at all, and the no-live-network rule would have
to bend for it. It does not bend.

The two loaders are kept separate rather than merged so the distinction stays explicit:
``load_fixture`` takes a bare name and adds ``.json``; ``load_text_fixture`` **requires**
the extension, because that extension is what picks the response's content type.
"""

from __future__ import annotations

import json
import re
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import httpx
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


class NetworkAccessError(RuntimeError):
    """Raised when test code tries to open a real socket."""


def load_fixture(name: str) -> Any:
    """Load ``tests/fixtures/<name>.json``. The ``.json`` suffix is optional."""
    filename = name if name.endswith(".json") else f"{name}.json"
    path = FIXTURE_DIR / filename
    if not path.exists():
        raise FileNotFoundError(
            f"No fixture {filename!r} in {FIXTURE_DIR}. "
            "Record it with scripts/capture_fixture.py."
        )
    return json.loads(path.read_text(encoding="utf-8"))


#: Extension → content type, for text fixtures. The extension is the whole signal.
CONTENT_TYPES = {
    ".xml": "application/xml",
    ".html": "text/html",
    ".txt": "text/plain",
}


def load_text_fixture(name: str) -> str:
    """Load ``tests/fixtures/<name>`` verbatim as UTF-8. The extension is **required**.

    Unlike :func:`load_fixture`, nothing is parsed — an RSS feed, an article page, and a
    ``robots.txt`` are all served exactly as recorded, because the adapter under test is
    the thing that is supposed to do the parsing.
    """
    suffix = Path(name).suffix
    if suffix not in CONTENT_TYPES:
        raise ValueError(
            f"Text fixture {name!r} needs one of {sorted(CONTENT_TYPES)} — the extension "
            "is what selects the response content type. For JSON use load_fixture()."
        )
    path = FIXTURE_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"No fixture {name!r} in {FIXTURE_DIR}. "
            "Record it with scripts/capture_fixture.py --raw."
        )
    return path.read_text(encoding="utf-8")


@dataclass
class Route:
    """One URL pattern → canned response.

    ``pattern`` is a regex matched against the full request URL. ``status`` defaults to
    200. The payload comes from exactly one of:

    - ``fixture`` naming a ``.json`` file (or no extension) → a JSON response;
    - ``fixture`` naming a ``.xml`` / ``.html`` / ``.txt`` file → a text response;
    - ``json_body`` → a JSON response built inline;
    - ``text`` → a text response built inline (``content_type`` defaults to
      ``text/plain``).
    """

    pattern: str
    fixture: str | None = None
    json_body: Any = None
    status: int = 200
    exc: Exception | None = None
    text: str | None = None
    content_type: str | None = None

    @property
    def is_text(self) -> bool:
        if self.text is not None:
            return True
        return bool(self.fixture) and Path(self.fixture or "").suffix in CONTENT_TYPES

    def payload(self) -> Any:
        if self.fixture is not None:
            return load_fixture(self.fixture)
        return self.json_body

    def text_payload(self) -> str:
        if self.text is not None:
            return self.text
        return load_text_fixture(self.fixture or "")

    def resolved_content_type(self) -> str:
        if self.content_type is not None:
            return self.content_type
        suffix = Path(self.fixture or "").suffix
        return CONTENT_TYPES.get(suffix, "text/plain")


@dataclass
class RecordingTransport:
    """A ``MockTransport`` plus the list of requests it saw."""

    transport: httpx.MockTransport
    requests: list[httpx.Request] = field(default_factory=list)


def mock_transport(routes: Sequence[Route | tuple[str, str]]) -> RecordingTransport:
    """Build an ``httpx.MockTransport`` mapping URL regexes to fixture payloads.

    Accepts ``Route`` objects, or ``(pattern, fixture_name)`` tuples as a shorthand.
    The returned object also records every request, so a test can assert on headers.
    """
    normalized: list[Route] = [
        r if isinstance(r, Route) else Route(pattern=r[0], fixture=r[1]) for r in routes
    ]
    recorder = RecordingTransport(transport=None)  # type: ignore[arg-type]

    def handler(request: httpx.Request) -> httpx.Response:
        recorder.requests.append(request)
        for route in normalized:
            if re.search(route.pattern, str(request.url)):
                if route.exc is not None:
                    raise route.exc
                if route.is_text:
                    return httpx.Response(
                        route.status,
                        text=route.text_payload(),
                        headers={"content-type": route.resolved_content_type()},
                        request=request,
                    )
                return httpx.Response(
                    route.status, json=route.payload(), request=request
                )
        raise AssertionError(
            f"No mock route matched {request.url}. "
            f"Known patterns: {[r.pattern for r in normalized]}"
        )

    recorder.transport = httpx.MockTransport(handler)
    return recorder


def fixture_client(routes: Sequence[Route | tuple[str, str]]) -> tuple[httpx.Client, RecordingTransport]:
    """Convenience: an ``httpx.Client`` wired to a recording mock transport."""
    recorder = mock_transport(routes)
    return httpx.Client(transport=recorder.transport), recorder


# --------------------------------------------------------------------------- #
# Socket guard
# --------------------------------------------------------------------------- #

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex

#: Loopback stays open. On Windows, `asyncio.run()` builds its proactor self-pipe from
#: a `socket.socketpair()` over 127.0.0.1 — blocking that would break every test that
#: touches asyncio without blocking a single outbound request. Nothing in this project
#: serves on loopback, so allowing it does not weaken the no-live-network guarantee:
#: statsapi.mlb.com and api.weather.gov are still unreachable.
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}


def _is_loopback(address: Any) -> bool:
    if isinstance(address, tuple) and address:
        return str(address[0]) in _LOOPBACK_HOSTS
    return False


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> Iterable[None]:
    """Fail loudly on any outbound connection that leaves the machine."""

    def blocked(self: socket.socket, address: Any, *args: Any, **kwargs: Any):
        if _is_loopback(address):
            return _real_connect(self, address, *args, **kwargs)
        raise NetworkAccessError(
            f"Live network access is disabled in the test suite (tried {address!r}). "
            "Use a recorded fixture via tests/conftest.mock_transport."
        )

    def blocked_ex(self: socket.socket, address: Any, *args: Any, **kwargs: Any):
        if _is_loopback(address):
            return _real_connect_ex(self, address, *args, **kwargs)
        raise NetworkAccessError(
            f"Live network access is disabled in the test suite (tried {address!r})."
        )

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked_ex, raising=False)
    yield


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURE_DIR


__all__ = [
    "CONTENT_TYPES",
    "FIXTURE_DIR",
    "NetworkAccessError",
    "Route",
    "RecordingTransport",
    "load_fixture",
    "load_text_fixture",
    "mock_transport",
    "fixture_client",
]
