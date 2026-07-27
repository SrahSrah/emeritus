"""Step 2 — the auth guard, the secret-leak guarantee, and the shared interface.

No test here makes a model call. The real client's SDK call is stubbed; the fake never
had one to begin with.
"""

from __future__ import annotations

import io
import logging
from typing import Any

import pytest

from forecaster import agent as agent_mod
from forecaster.agent import (
    API_KEY_VAR,
    OAUTH_TOKEN_VAR,
    SUBSCRIPTION_OAUTH,
    AgentClientLike,
    AgentResponse,
    ApiKeyShadowError,
    ClaudeAgentClient,
    FakeAgentClient,
    MissingOAuthTokenError,
    assert_subscription_auth,
    build_prompt,
)

SENTINEL = "sk-ant-oat01-SENTINEL-DO-NOT-LEAK-4a91f2"


# --------------------------------------------------------------------------- #
# The three auth cases
# --------------------------------------------------------------------------- #


def test_api_key_present_raises_and_names_the_shadowing_problem() -> None:
    env = {API_KEY_VAR: "sk-ant-whatever", OAUTH_TOKEN_VAR: SENTINEL}
    with pytest.raises(ApiKeyShadowError) as excinfo:
        assert_subscription_auth(env)
    message = str(excinfo.value)
    assert API_KEY_VAR in message
    assert "shadow" in message.lower()
    assert SENTINEL not in message


def test_empty_api_key_still_raises() -> None:
    """An empty string occupies the precedence slot — it is not "unset"."""
    with pytest.raises(ApiKeyShadowError):
        assert_subscription_auth({API_KEY_VAR: "", OAUTH_TOKEN_VAR: SENTINEL})


def test_neither_var_set_raises_the_distinct_missing_token_error() -> None:
    with pytest.raises(MissingOAuthTokenError) as excinfo:
        assert_subscription_auth({})
    assert OAUTH_TOKEN_VAR in str(excinfo.value)


def test_only_oauth_token_set_reports_subscription_auth() -> None:
    assert assert_subscription_auth({OAUTH_TOKEN_VAR: SENTINEL}) == SUBSCRIPTION_OAUTH


def test_real_client_constructs_and_reports_auth_mode() -> None:
    client = ClaudeAgentClient(env={OAUTH_TOKEN_VAR: SENTINEL})
    assert client.auth_mode == SUBSCRIPTION_OAUTH


def test_real_client_refuses_when_api_key_is_set() -> None:
    with pytest.raises(ApiKeyShadowError):
        ClaudeAgentClient(env={API_KEY_VAR: "sk-ant-x", OAUTH_TOKEN_VAR: SENTINEL})


# --------------------------------------------------------------------------- #
# Secret-leak guarantee
# --------------------------------------------------------------------------- #


def test_sentinel_token_appears_nowhere_in_captured_output(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Construct with a sentinel token, exercise the layer, capture everything."""
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)

    try:
        monkeypatch.setenv(OAUTH_TOKEN_VAR, SENTINEL)
        monkeypatch.delenv(API_KEY_VAR, raising=False)

        real = ClaudeAgentClient(load_dotenv_file=False)
        fake = FakeAgentClient()
        response = fake.complete(
            "Phrase these values.", structured={"score": "Astros 5, Rangers 3"}
        )

        # Anything a caller might plausibly print or trace.
        print(repr(real))
        print(repr(fake))
        print(response.text)
        print(build_prompt("Phrase these values.", {"score": "Astros 5, Rangers 3"}))
        print(repr(fake.calls))
    finally:
        root.removeHandler(handler)

    captured = capsys.readouterr()
    haystack = captured.out + captured.err + log_stream.getvalue()

    assert haystack, "nothing was captured — the test would pass vacuously"
    assert SENTINEL not in haystack
    assert "SENTINEL" not in haystack


# --------------------------------------------------------------------------- #
# Shared interface, parametrized over both clients
# --------------------------------------------------------------------------- #


class _StubResult:
    """Stands in for the SDK's ResultMessage."""

    usage = {"input_tokens": 120, "output_tokens": 45}
    duration_ms = 1234
    duration_api_ms = 1000


async def _stub_run_query(full_prompt: str, options: Any) -> AgentResponse:
    """Replaces the SDK call entirely — no subprocess, no network, no model."""
    assert "<data>" in full_prompt
    return AgentResponse(
        text="Astros 5, Rangers 3",
        input_tokens=_StubResult.usage["input_tokens"],
        output_tokens=_StubResult.usage["output_tokens"],
        duration_ms=_StubResult.duration_ms,
        duration_api_ms=_StubResult.duration_api_ms,
    )


def _make_real(monkeypatch: pytest.MonkeyPatch) -> ClaudeAgentClient:
    monkeypatch.setattr(agent_mod, "_run_query", _stub_run_query)
    return ClaudeAgentClient(env={OAUTH_TOKEN_VAR: SENTINEL})


def _make_fake(monkeypatch: pytest.MonkeyPatch) -> FakeAgentClient:
    return FakeAgentClient()


@pytest.mark.parametrize("factory", [_make_real, _make_fake], ids=["real", "fake"])
def test_both_clients_satisfy_the_same_interface(
    factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = factory(monkeypatch)

    assert isinstance(client, AgentClientLike)
    assert client.auth_mode == SUBSCRIPTION_OAUTH

    response = client.complete(
        "Phrase these values; do not invent any.",
        structured={"score": "Astros 5, Rangers 3"},
        system="You phrase; you never originate.",
        effort="low",
    )

    assert isinstance(response, AgentResponse)
    assert "Astros 5, Rangers 3" in response.text
    assert response.input_tokens >= 0
    assert response.output_tokens >= 0


def test_real_client_defaults_to_low_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def capture(full_prompt: str, options: Any) -> AgentResponse:
        seen["effort"] = options.effort
        seen["allowed_tools"] = options.allowed_tools
        return AgentResponse(text="ok")

    monkeypatch.setattr(agent_mod, "_run_query", capture)
    client = ClaudeAgentClient(env={OAUTH_TOKEN_VAR: SENTINEL})
    client.complete("hello")

    assert seen["effort"] == "low"
    assert seen["allowed_tools"] == []


# --------------------------------------------------------------------------- #
# FakeAgentClient specifics
# --------------------------------------------------------------------------- #


def test_fake_records_every_call_and_reports_zero_usage() -> None:
    fake = FakeAgentClient()
    fake.complete("first", structured={"a": "one"})
    fake.complete("second", structured={"b": "two"}, effort="high")

    assert fake.call_count == 2
    assert [call.prompt for call in fake.calls] == ["first", "second"]
    assert fake.calls[1].effort == "high"
    assert all(
        call_response.input_tokens == 0
        for call_response in [fake.complete("third", structured={"c": "3"})]
    )


def test_fake_phrases_rather_than_originates() -> None:
    """Every value in the response came from the caller's structured payload."""
    fake = FakeAgentClient()
    structured = {
        "weather": {"low_f": 41, "precip_pct": 20},
        "astros": ["Final: Astros 5, Rangers 3"],
    }
    text = fake.complete("Phrase these.", structured=structured).text

    assert "41" in text
    assert "20" in text
    assert "Final: Astros 5, Rangers 3" in text
