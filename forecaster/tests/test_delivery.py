"""Step 17 — delivery, with zero SMTP socket activity anywhere in the suite.

The real send is human-gated (FR-12) and is **not** exercised here. `smtplib.SMTP` is
mocked; the socket guard would fail the test if it weren't.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from forecaster.agent import FakeAgentClient
from forecaster.beats.base import BeatItem, BeatResult, ObservationRef
from forecaster.delivery import email as email_mod
from forecaster.delivery.base import Deliverer, DeliveryResult, FakeDeliverer
from forecaster.delivery.email import (
    DeliveryConfigError,
    EmailDeliverer,
    SmtpSettings,
    build_message,
    load_smtp_settings,
    make_deliverer,
)
from forecaster.memory.preferences import parse_preferences
from forecaster.synthesizer import synthesize
from forecaster.trace import read_trace, records_of
from tests.helpers import make_config, trace_in

CONFIG = make_config()
PREFS = parse_preferences({"topics": {"astros": 1.0}})

ENV = {
    "SMTP_HOST": "smtp.example.test",
    "SMTP_PORT": "587",
    "SMTP_USER": "sender@example.test",
    "SMTP_PASSWORD": "app-password-not-a-login-password",
    "SMTP_FROM": "sender@example.test",
    "SMTP_TO": "sarah@example.test",
}


def _synthesized_digest(tmp_path: Path, run_id: str = "delivery-run"):
    """Call the synthesizer directly — the CLI does not exist until Step 18."""
    trace = trace_in(tmp_path, run_id)
    with trace:
        obs = trace.tool_call(beat="astros", adapter="mlb.fetch_schedule", arguments={})
        trace.observation(obs, payload=[{"away_score": 3, "home_score": 12}])
        result = BeatResult(
            beat="astros",
            items=[
                BeatItem(
                    beat="astros",
                    text="Final: Houston Astros 3, Chicago White Sox 12.",
                    observations=[ObservationRef(obs, "mlb.fetch_schedule")],
                )
            ],
            checkable_fields={"final_score": "Houston Astros 3, Chicago White Sox 12"},
            observations=[ObservationRef(obs, "mlb.fetch_schedule")],
        )
        trace.beat_result(result)
        digest = synthesize([result], CONFIG, PREFS, trace, agent_client=FakeAgentClient())
    return digest, trace


class MockSMTP:
    """Stands in for `smtplib.SMTP`. Opens no socket."""

    instances: list["MockSMTP"] = []

    def __init__(self, host: str, port: int, timeout: float = 0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.login_args: tuple[str, str] | None = None
        self.messages: list[Any] = []
        MockSMTP.instances.append(self)

    def __enter__(self) -> "MockSMTP":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, user: str, password: str) -> None:
        self.login_args = (user, password)

    def send_message(self, message: Any) -> None:
        self.messages.append(message)


@pytest.fixture(autouse=True)
def _reset_mock() -> None:
    MockSMTP.instances = []


# --------------------------------------------------------------------------- #
# FakeDeliverer captures a real synthesized digest, no SMTP involved
# --------------------------------------------------------------------------- #


def test_fake_deliverer_captures_a_synthesized_digest(tmp_path: Path) -> None:
    digest, _ = _synthesized_digest(tmp_path)
    deliverer = FakeDeliverer(target="nobody@example.test")

    result = deliverer.send(digest)

    assert isinstance(deliverer, Deliverer)
    assert isinstance(result, DeliveryResult)
    assert result.success is True
    assert deliverer.sent == [digest]
    assert "Houston Astros 3, Chicago White Sox 12" in (deliverer.last_text or "")
    assert MockSMTP.instances == [], "the fake deliverer must not touch SMTP"


# --------------------------------------------------------------------------- #
# EmailDeliverer composes correctly against a mocked smtplib
# --------------------------------------------------------------------------- #


def test_email_deliverer_composes_the_right_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(email_mod.smtplib, "SMTP", MockSMTP)
    digest, _ = _synthesized_digest(tmp_path)

    result = EmailDeliverer(env=ENV).send(digest)

    assert result.success is True
    assert result.target == "sarah@example.test"

    assert len(MockSMTP.instances) == 1
    smtp = MockSMTP.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.example.test", 587)
    assert smtp.started_tls is True
    assert smtp.login_args == ("sender@example.test", ENV["SMTP_PASSWORD"])

    message = smtp.messages[0]
    assert message["To"] == "sarah@example.test"
    assert message["From"] == "sender@example.test"
    assert message["Subject"]
    assert "Houston Astros 3, Chicago White Sox 12" in message.get_content()


def test_an_smtp_failure_returns_an_unsuccessful_result_rather_than_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class ExplodingSMTP(MockSMTP):
        def send_message(self, message: Any) -> None:
            raise OSError("connection reset")

    monkeypatch.setattr(email_mod.smtplib, "SMTP", ExplodingSMTP)
    digest, _ = _synthesized_digest(tmp_path)

    result = EmailDeliverer(env=ENV).send(digest)

    assert result.success is False
    assert "connection reset" in (result.error or "")


# --------------------------------------------------------------------------- #
# Missing credentials fail clearly; nothing goes to a default address
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("missing", sorted(ENV))
def test_a_missing_env_var_raises_naming_it(missing: str) -> None:
    env = {key: value for key, value in ENV.items() if key != missing}
    with pytest.raises(DeliveryConfigError, match=missing):
        load_smtp_settings(env)


def test_a_non_integer_port_raises() -> None:
    with pytest.raises(DeliveryConfigError, match="SMTP_PORT"):
        load_smtp_settings({**ENV, "SMTP_PORT": "not-a-port"})


def test_it_never_falls_back_to_a_default_address() -> None:
    with pytest.raises(DeliveryConfigError):
        load_smtp_settings({})


# --------------------------------------------------------------------------- #
# No credential anywhere it could leak
# --------------------------------------------------------------------------- #


def test_the_trace_delivery_record_carries_the_target_and_no_credential(
    tmp_path: Path,
) -> None:
    _, trace = _synthesized_digest(tmp_path)
    with trace_in(tmp_path, "delivery-record") as trace2:
        trace2.delivery(
            deliverer="EmailDeliverer", target="sarah@example.test", success=True
        )
    record = next(records_of(read_trace(trace2.path), "delivery"))

    assert record["target"] == "sarah@example.test"
    assert record["success"] is True
    blob = trace2.path.read_text(encoding="utf-8")
    assert ENV["SMTP_PASSWORD"] not in blob


def test_the_password_is_redacted_in_repr_and_absent_from_the_deliverer_repr() -> None:
    settings = load_smtp_settings(ENV)
    assert ENV["SMTP_PASSWORD"] not in repr(settings)
    assert "<redacted>" in repr(settings)

    deliverer = EmailDeliverer(env=ENV)
    assert ENV["SMTP_PASSWORD"] not in repr(deliverer)


def test_the_message_body_contains_no_credential(tmp_path: Path) -> None:
    digest, _ = _synthesized_digest(tmp_path)
    message = build_message(digest.text, load_smtp_settings(ENV))
    assert ENV["SMTP_PASSWORD"] not in message.get_content()
    assert ENV["SMTP_PASSWORD"] not in str(message)


# --------------------------------------------------------------------------- #
# Config selects the deliverer
# --------------------------------------------------------------------------- #


def test_config_kind_fake_selects_the_fake_deliverer() -> None:
    deliverer = make_deliverer(make_config(delivery={"kind": "fake", "target": "x@y.test"}))
    assert isinstance(deliverer, FakeDeliverer)
    assert deliverer.target == "x@y.test"


def test_config_kind_email_selects_the_email_deliverer() -> None:
    deliverer = make_deliverer(
        make_config(delivery={"kind": "email", "target": "x@y.test"}), env=ENV
    )
    assert isinstance(deliverer, EmailDeliverer)
    assert deliverer.target == "sarah@example.test"


def test_an_unknown_kind_raises() -> None:
    with pytest.raises(DeliveryConfigError, match="not a known"):
        make_deliverer(make_config(delivery={"kind": "sms", "target": "+15125550123"}))


def test_v1_ships_no_sms_push_or_webhook() -> None:
    source = (
        Path(__file__).resolve().parent.parent / "forecaster" / "delivery" / "email.py"
    ).read_text(encoding="utf-8")
    for channel in ("twilio", "webhook", "requests.post", "pushover"):
        assert channel not in source.lower()
