"""The single seam through which the pipeline talks to the model.

Two rules this module exists to enforce:

1. **Auth is Sarah's Claude subscription, never a per-token API key.** The agent layer
   authenticates with ``CLAUDE_CODE_OAUTH_TOKEN``. If ``ANTHROPIC_API_KEY`` is present
   it *shadows* the OAuth token and silently bills per token, so the guard refuses to
   start rather than let that happen. There is no fallback and no override flag.
2. **The token never leaves this module.** Its presence is recorded; its value is not
   logged, printed, traced, or repr'd.

Which client a run uses is injected. Production code never constructs one inline, so a
test can hand any caller a :class:`FakeAgentClient` and be certain no model call — and
no subscription usage — happens.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal, Mapping, Protocol, Sequence, runtime_checkable

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

#: Effort level passed through to the agent SDK. PRD §6: routine beats run "low".
EffortLevel = Literal["low", "medium", "high", "xhigh", "max"]
DEFAULT_EFFORT: EffortLevel = "low"

#: The only auth mode this project supports. Stamped into every trace (FR-13/FR-14).
SUBSCRIPTION_OAUTH = "subscription_oauth"

OAUTH_TOKEN_VAR = "CLAUDE_CODE_OAUTH_TOKEN"
API_KEY_VAR = "ANTHROPIC_API_KEY"

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


class AuthError(RuntimeError):
    """Base class for the two ways auth can be wrong."""


class ApiKeyShadowError(AuthError):
    """`ANTHROPIC_API_KEY` is set and would shadow the subscription OAuth token."""


class MissingOAuthTokenError(AuthError):
    """`CLAUDE_CODE_OAUTH_TOKEN` is absent, so there is nothing to authenticate with."""


def load_env(path: Path | None = None) -> None:
    """Load the gitignored ``.env`` if it exists. Never overrides a real env var."""
    env_path = path if path is not None else ENV_PATH
    if env_path.exists():
        load_dotenv(env_path, override=False)


def assert_subscription_auth(env: Mapping[str, str] | None = None) -> str:
    """Verify the process is set up for subscription OAuth and return the auth mode.

    Raises :class:`ApiKeyShadowError` if ``ANTHROPIC_API_KEY`` is present — including
    when it is set to an empty string, which still occupies the precedence slot — and
    :class:`MissingOAuthTokenError` if the OAuth token is absent. Never falls back.
    """
    environ = os.environ if env is None else env

    if API_KEY_VAR in environ:
        raise ApiKeyShadowError(
            f"{API_KEY_VAR} is set in this environment. It shadows "
            f"{OAUTH_TOKEN_VAR} and would bill per token instead of drawing on the "
            "Claude subscription. Unset it before running the pipeline:\n"
            f"    Remove-Item Env:{API_KEY_VAR} -ErrorAction SilentlyContinue\n"
            "This is not overridable — there is no API-key fallback by design."
        )

    if not environ.get(OAUTH_TOKEN_VAR):
        raise MissingOAuthTokenError(
            f"{OAUTH_TOKEN_VAR} is missing or empty. Mint one with `claude setup-token` "
            f"and put it in the gitignored {ENV_PATH.name}. The pipeline cannot run "
            "without it, and it will not fall back to an API key."
        )

    return SUBSCRIPTION_OAUTH


@dataclass(frozen=True)
class AgentResponse:
    """What a completion returns: the text, plus what it cost and how long it took."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    duration_api_ms: int = 0
    model: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@runtime_checkable
class AgentClientLike(Protocol):
    """The interface the rest of the pipeline codes against.

    ``structured`` carries the values the caller wants *phrased*. The model is never
    asked to supply one — see FR-11 and :func:`forecaster.trace.check_provenance`.
    """

    auth_mode: str

    def complete(
        self,
        prompt: str,
        *,
        structured: Mapping[str, Any] | None = None,
        system: str | None = None,
        effort: EffortLevel = DEFAULT_EFFORT,
    ) -> AgentResponse: ...


def build_prompt(prompt: str, structured: Mapping[str, Any] | None) -> str:
    """Render the prompt handed to the model, with the structured values fenced off."""
    if not structured:
        return prompt
    payload = json.dumps(structured, indent=2, sort_keys=False, default=str)
    return f"{prompt}\n\n<data>\n{payload}\n</data>"


# --------------------------------------------------------------------------- #
# Real client
# --------------------------------------------------------------------------- #


async def _run_query(full_prompt: str, options: Any) -> AgentResponse:
    """Drive one `claude_agent_sdk.query` turn and collect text + usage.

    Isolated in its own function so tests can stub the SDK call without stubbing the
    client's own behavior.
    """
    from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, query

    chunks: list[str] = []
    input_tokens = output_tokens = duration_ms = duration_api_ms = 0

    async for message in query(prompt=full_prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    chunks.append(block.text)
        elif isinstance(message, ResultMessage):
            usage = message.usage or {}
            input_tokens = int(usage.get("input_tokens", 0) or 0)
            output_tokens = int(usage.get("output_tokens", 0) or 0)
            duration_ms = message.duration_ms
            duration_api_ms = message.duration_api_ms

    return AgentResponse(
        text="".join(chunks).strip(),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=duration_ms,
        duration_api_ms=duration_api_ms,
    )


class ClaudeAgentClient:
    """Thin wrapper over `claude-agent-sdk`, authenticated by subscription OAuth.

    Deliberately thin: beat logic lives in plain functions the agent layer calls, so a
    later module mandating a different framework touches the runner, not the beats
    (PRD §6, framework portability).
    """

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        model: str | None = None,
        load_dotenv_file: bool = True,
    ) -> None:
        if load_dotenv_file and env is None:
            load_env()
        self.auth_mode = assert_subscription_auth(env)
        self.model = model
        logger.info("agent client ready (auth_mode=%s)", self.auth_mode)

    def __repr__(self) -> str:  # never interpolate the token
        return f"ClaudeAgentClient(auth_mode={self.auth_mode!r}, model={self.model!r})"

    def complete(
        self,
        prompt: str,
        *,
        structured: Mapping[str, Any] | None = None,
        system: str | None = None,
        effort: EffortLevel = DEFAULT_EFFORT,
    ) -> AgentResponse:
        from claude_agent_sdk import ClaudeAgentOptions

        options = ClaudeAgentOptions(
            system_prompt=system,
            allowed_tools=[],
            max_turns=1,
            effort=effort,
            model=self.model,
        )
        return asyncio.run(_run_query(build_prompt(prompt, structured), options))


# --------------------------------------------------------------------------- #
# Test double
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RecordedCall:
    """One `complete()` invocation, kept so a test can assert on what was asked."""

    prompt: str
    structured: Mapping[str, Any] | None
    system: str | None
    effort: EffortLevel


def _flatten(value: Any) -> Iterator[str]:
    """Yield every leaf of a structured payload, in order, as text."""
    if value is None:
        return
    if isinstance(value, str):
        if value:
            yield value
    elif isinstance(value, bool):
        yield "yes" if value else "no"
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _flatten(item)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for item in value:
            yield from _flatten(item)
    else:
        yield str(value)


class FakeAgentClient:
    """Deterministic in-memory double. **Never calls a model, ever.**

    The response is derived from the structured payload it was handed, which is what
    makes the FR-11 provenance test meaningful: a digest built this way contains the
    caller's own values, so a test that tampers with one can prove the check catches it.
    Reports zero token usage — nothing was spent.
    """

    def __init__(self, *, auth_mode: str = SUBSCRIPTION_OAUTH) -> None:
        self.auth_mode = auth_mode
        self.calls: list[RecordedCall] = []

    def __repr__(self) -> str:
        return f"FakeAgentClient(auth_mode={self.auth_mode!r}, calls={len(self.calls)})"

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def complete(
        self,
        prompt: str,
        *,
        structured: Mapping[str, Any] | None = None,
        system: str | None = None,
        effort: EffortLevel = DEFAULT_EFFORT,
    ) -> AgentResponse:
        self.calls.append(
            RecordedCall(prompt=prompt, structured=structured, system=system, effort=effort)
        )
        if structured:
            text = "\n".join(_flatten(structured))
        else:
            text = f"[fake] {prompt.strip()}"
        return AgentResponse(text=text, input_tokens=0, output_tokens=0)


__all__ = [
    "API_KEY_VAR",
    "OAUTH_TOKEN_VAR",
    "SUBSCRIPTION_OAUTH",
    "DEFAULT_EFFORT",
    "EffortLevel",
    "AgentResponse",
    "AgentClientLike",
    "AuthError",
    "ApiKeyShadowError",
    "MissingOAuthTokenError",
    "ClaudeAgentClient",
    "FakeAgentClient",
    "RecordedCall",
    "assert_subscription_auth",
    "build_prompt",
    "load_env",
]
