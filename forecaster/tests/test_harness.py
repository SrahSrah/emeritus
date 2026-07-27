"""Step 1 — the harness itself: fixtures serve, and the socket guard bites."""

from __future__ import annotations

import httpx
import pytest

from tests.conftest import NetworkAccessError, Route, fixture_client, load_fixture


def test_load_fixture_and_mock_transport_serve_a_recorded_payload() -> None:
    client, recorder = fixture_client([Route(r"example\.test/sample", fixture="sample")])
    with client:
        response = client.get("https://example.test/sample")

    assert response.status_code == 200
    assert response.json() == load_fixture("sample")
    assert response.json()["harness"] == "ok"
    assert len(recorder.requests) == 1


def test_mock_transport_can_serve_an_error_status() -> None:
    client, _ = fixture_client(
        [Route(r"example\.test/boom", json_body={"detail": "nope"}, status=500)]
    )
    with client:
        response = client.get("https://example.test/boom")
    assert response.status_code == 500


def test_missing_fixture_fails_loudly() -> None:
    with pytest.raises(FileNotFoundError, match="capture_fixture"):
        load_fixture("definitely_not_recorded")


def test_real_network_call_raises() -> None:
    """The socket guard must fire — fast and loud, not slow and quiet."""
    with pytest.raises((NetworkAccessError, httpx.ConnectError, httpx.TransportError)):
        with httpx.Client(timeout=2.0) as client:
            client.get("https://statsapi.mlb.com/api/v1/schedule?sportId=1")
