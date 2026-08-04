"""Step 1 — the harness itself: fixtures serve, and the socket guard bites.

Step 23 added the text path. The news beat's sources are XML, HTML, and plain text, so
without it those adapters could not be tested off a recording at all — and the
no-live-network rule would have had to bend. The cases below prove it does not.
"""

from __future__ import annotations

import httpx
import pytest

from tests.conftest import (
    NetworkAccessError,
    Route,
    fixture_client,
    load_fixture,
    load_text_fixture,
)


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


# --------------------------------------------------------------------------- #
# Step 23 — the text path
# --------------------------------------------------------------------------- #


def test_xml_fixture_is_served_verbatim_with_an_xml_content_type() -> None:
    """An RSS feed has to arrive as bytes the adapter parses, not as parsed JSON."""
    client, recorder = fixture_client(
        [Route(r"example\.test/feed", fixture="sample.xml")]
    )
    with client:
        response = client.get("https://example.test/feed")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/xml"
    assert response.text == load_text_fixture("sample.xml")
    assert "<harness>" in response.text
    assert len(recorder.requests) == 1


def test_html_fixture_is_served_verbatim_with_an_html_content_type() -> None:
    client, _ = fixture_client([Route(r"example\.test/article", fixture="sample.html")])
    with client:
        response = client.get("https://example.test/article")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html"
    assert "<p>" in response.text


def test_inline_text_route_defaults_to_plain_text() -> None:
    """robots.txt has no fixture file behind it in most tests — inline is enough."""
    client, _ = fixture_client(
        [Route(r"example\.test/robots\.txt", text="User-agent: *\nDisallow:\n")]
    )
    with client:
        response = client.get("https://example.test/robots.txt")

    assert response.headers["content-type"] == "text/plain"
    assert response.text.startswith("User-agent:")


def test_text_fixture_requires_an_extension() -> None:
    """The extension picks the content type, so a bare name is a mistake, not a default."""
    with pytest.raises(ValueError, match="extension"):
        load_text_fixture("sample")


def test_missing_text_fixture_fails_loudly() -> None:
    with pytest.raises(FileNotFoundError, match="capture_fixture"):
        load_text_fixture("definitely_not_recorded.xml")


def test_json_routes_are_unchanged_by_the_text_path() -> None:
    """The regression guard: a `.json` fixture and an inline json_body still serve JSON."""
    client, _ = fixture_client(
        [
            Route(r"example\.test/a", fixture="sample"),
            Route(r"example\.test/b", fixture="sample.json"),
            Route(r"example\.test/c", json_body={"inline": True}),
        ]
    )
    with client:
        assert client.get("https://example.test/a").json()["harness"] == "ok"
        assert client.get("https://example.test/b").json()["harness"] == "ok"
        assert client.get("https://example.test/c").json() == {"inline": True}


def test_real_network_call_raises() -> None:
    """The socket guard must fire — fast and loud, not slow and quiet."""
    with pytest.raises((NetworkAccessError, httpx.ConnectError, httpx.TransportError)):
        with httpx.Client(timeout=2.0) as client:
            client.get("https://statsapi.mlb.com/api/v1/schedule?sportId=1")
