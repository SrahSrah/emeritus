"""SMTP delivery (FR-12).

Credentials come from the **gitignored `.env`** and nowhere else — not `config.toml`, not
a default, not a fallback address. A missing variable raises a clear error naming it,
because sending a personal digest to whatever address happened to be lying around is a
worse failure than not sending at all.

PRD §7: the account needs an **app password** (Gmail will not accept the login password).
That is on Sarah's HUMAN-TODO, not on the build.
"""

from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any, Mapping

from forecaster.delivery.base import DeliveryResult

REQUIRED_VARS = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "SMTP_TO")
DEFAULT_SUBJECT = "Forecaster — tonight's digest"


class DeliveryConfigError(RuntimeError):
    """A required SMTP setting is missing from the environment."""


@dataclass(frozen=True)
class SmtpSettings:
    """Loaded from the environment. `password` is never logged, traced, or repr'd."""

    host: str
    port: int
    user: str
    password: str
    sender: str
    recipient: str

    def __repr__(self) -> str:  # keep the password out of every traceback
        return (
            f"SmtpSettings(host={self.host!r}, port={self.port!r}, user={self.user!r}, "
            f"sender={self.sender!r}, recipient={self.recipient!r}, password=<redacted>)"
        )


def load_smtp_settings(env: Mapping[str, str] | None = None) -> SmtpSettings:
    environ = os.environ if env is None else env
    missing = [name for name in REQUIRED_VARS if not environ.get(name)]
    if missing:
        raise DeliveryConfigError(
            f"Missing SMTP setting(s) {', '.join(missing)} in the environment. They live "
            "in the gitignored .env (see .env.example). Refusing to send rather than "
            "guessing an address or a server."
        )
    raw_port = environ["SMTP_PORT"]
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise DeliveryConfigError(f"SMTP_PORT={raw_port!r} is not an integer") from exc

    return SmtpSettings(
        host=environ["SMTP_HOST"],
        port=port,
        user=environ["SMTP_USER"],
        password=environ["SMTP_PASSWORD"],
        sender=environ["SMTP_FROM"],
        recipient=environ["SMTP_TO"],
    )


def build_message(text: str, settings: SmtpSettings, *, subject: str = DEFAULT_SUBJECT) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.sender
    message["To"] = settings.recipient
    message.set_content(text)
    return message


class EmailDeliverer:
    """SMTP over TLS. Reads its settings from the environment at construction."""

    name = "EmailDeliverer"

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        subject: str = DEFAULT_SUBJECT,
        timeout: float = 30.0,
    ) -> None:
        self.settings = load_smtp_settings(env)
        self.subject = subject
        self.timeout = timeout

    @property
    def target(self) -> str:
        return self.settings.recipient

    def __repr__(self) -> str:
        return f"EmailDeliverer(target={self.target!r})"

    def send(self, digest: Any) -> DeliveryResult:
        text = getattr(digest, "text", str(digest))
        message = build_message(text, self.settings, subject=self.subject)
        sent_at = datetime.now(timezone.utc).isoformat()

        try:
            with smtplib.SMTP(self.settings.host, self.settings.port, timeout=self.timeout) as smtp:
                smtp.starttls()
                smtp.login(self.settings.user, self.settings.password)
                smtp.send_message(message)
        except Exception as exc:  # noqa: BLE001 - the reason belongs in the trace
            return DeliveryResult(
                deliverer=self.name,
                target=self.target,
                success=False,
                sent_at=sent_at,
                error=f"{type(exc).__name__}: {exc}",
            )

        return DeliveryResult(
            deliverer=self.name, target=self.target, success=True, sent_at=sent_at
        )


def make_deliverer(config: Any, *, env: Mapping[str, str] | None = None) -> Any:
    """Pick the deliverer `[delivery].kind` names."""
    from forecaster.delivery.base import FakeDeliverer

    kind = config.delivery.kind.lower()
    if kind == "fake":
        return FakeDeliverer(target=config.delivery.target)
    if kind == "email":
        return EmailDeliverer(env=env)
    raise DeliveryConfigError(
        f"config.toml [delivery].kind = {config.delivery.kind!r} is not a known "
        "deliverer. v1 ships 'email' and 'fake'."
    )


__all__ = [
    "DEFAULT_SUBJECT",
    "REQUIRED_VARS",
    "DeliveryConfigError",
    "EmailDeliverer",
    "SmtpSettings",
    "build_message",
    "load_smtp_settings",
    "make_deliverer",
]
