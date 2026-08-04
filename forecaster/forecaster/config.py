"""Run configuration loaded from ``config.toml`` (FR-1).

Everything that changes what a run does — which beats fire, where "here" is, who the
digest goes to, when it sends, what escalates — lives in the TOML file. Nothing in this
module supplies a default that would change behavior if a key went missing; a malformed
or incomplete config fails loudly instead.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from typing import Any, Mapping

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.toml"


class ConfigError(ValueError):
    """A config file is missing, malformed, or missing a key that matters."""


def _require(table: Mapping[str, Any], key: str, section: str) -> Any:
    if key not in table:
        raise ConfigError(f"config.toml: [{section}] is missing required key {key!r}")
    return table[key]


def _require_table(data: Mapping[str, Any], section: str) -> Mapping[str, Any]:
    if section not in data:
        raise ConfigError(f"config.toml: missing required section [{section}]")
    value = data[section]
    if not isinstance(value, Mapping):
        raise ConfigError(
            f"config.toml: [{section}] must be a table, got {type(value).__name__}"
        )
    return value


def _parse_time(raw: Any, section: str, key: str) -> time:
    if not isinstance(raw, str):
        raise ConfigError(f'config.toml: [{section}].{key} must be an "HH:MM" string')
    try:
        hours, _, minutes = raw.partition(":")
        return time(hour=int(hours), minute=int(minutes))
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f'config.toml: [{section}].{key} = {raw!r} is not a valid "HH:MM" time'
        ) from exc


def _require_float(table: Mapping[str, Any], key: str, section: str) -> float:
    value = _require(table, key, section)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"config.toml: [{section}].{key} must be a number, got {value!r}")
    return float(value)


def _require_int(table: Mapping[str, Any], key: str, section: str) -> int:
    value = _require(table, key, section)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"config.toml: [{section}].{key} must be an integer, got {value!r}")
    return value


def _require_str(table: Mapping[str, Any], key: str, section: str) -> str:
    value = _require(table, key, section)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"config.toml: [{section}].{key} must be a non-empty string")
    return value


def _require_str_list(table: Mapping[str, Any], key: str, section: str) -> list[str]:
    value = _require(table, key, section)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"config.toml: [{section}].{key} must be a list of strings")
    return list(value)


@dataclass(frozen=True)
class RunConfig:
    send_time: time
    timezone: str
    run_window_start: time
    run_window_end: time


@dataclass(frozen=True)
class LocationConfig:
    city: str
    state: str
    latitude: float
    longitude: float
    timezone: str


@dataclass(frozen=True)
class DeliveryConfig:
    kind: str
    target: str


@dataclass(frozen=True)
class EscalationConfig:
    """Rule order is priority order — Step 13 reads it to break ties deterministically."""

    rules: list[str]
    freeze_threshold_f: float
    freeze_horizon_days: int
    watched_players: list[str]


@dataclass(frozen=True)
class TeamConfig:
    mlb_team_id: int
    name: str


@dataclass(frozen=True)
class RetrievalConfig:
    """FR-9b's retrieval layer. `enabled = false` restores exact v1 behaviour."""

    enabled: bool
    model: str
    k: int
    similarity_floor: float
    window_days: int


@dataclass(frozen=True)
class Config:
    run: RunConfig
    beats: dict[str, bool]
    location: LocationConfig
    delivery: DeliveryConfig
    escalation: EscalationConfig
    team: TeamConfig
    retrieval: RetrievalConfig
    source_path: Path | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)


def parse_config(data: Mapping[str, Any], source_path: Path | None = None) -> Config:
    """Build a typed :class:`Config` from an already-parsed TOML mapping."""
    run_table = _require_table(data, "run")
    run = RunConfig(
        send_time=_parse_time(_require(run_table, "send_time", "run"), "run", "send_time"),
        timezone=_require_str(run_table, "timezone", "run"),
        run_window_start=_parse_time(
            _require(run_table, "run_window_start", "run"), "run", "run_window_start"
        ),
        run_window_end=_parse_time(
            _require(run_table, "run_window_end", "run"), "run", "run_window_end"
        ),
    )

    beats_table = _require_table(data, "beats")
    beats: dict[str, bool] = {}
    for name, enabled in beats_table.items():
        if not isinstance(enabled, bool):
            raise ConfigError(
                f"config.toml: [beats].{name} must be true or false, got {enabled!r}"
            )
        beats[name] = enabled
    if not beats:
        raise ConfigError("config.toml: [beats] must name at least one beat")

    location_table = _require_table(data, "location")
    location = LocationConfig(
        city=_require_str(location_table, "city", "location"),
        state=_require_str(location_table, "state", "location"),
        latitude=_require_float(location_table, "latitude", "location"),
        longitude=_require_float(location_table, "longitude", "location"),
        timezone=_require_str(location_table, "timezone", "location"),
    )

    delivery_table = _require_table(data, "delivery")
    delivery = DeliveryConfig(
        kind=_require_str(delivery_table, "kind", "delivery"),
        target=_require_str(delivery_table, "target", "delivery"),
    )

    escalation_table = _require_table(data, "escalation")
    escalation = EscalationConfig(
        rules=_require_str_list(escalation_table, "rules", "escalation"),
        freeze_threshold_f=_require_float(escalation_table, "freeze_threshold_f", "escalation"),
        freeze_horizon_days=_require_int(escalation_table, "freeze_horizon_days", "escalation"),
        watched_players=_require_str_list(escalation_table, "watched_players", "escalation"),
    )
    if not escalation.rules:
        raise ConfigError("config.toml: [escalation].rules must name at least one rule")

    team_table = _require_table(data, "team")
    team = TeamConfig(
        mlb_team_id=_require_int(team_table, "mlb_team_id", "team"),
        name=_require_str(team_table, "name", "team"),
    )

    retrieval_table = _require_table(data, "retrieval")
    enabled = _require(retrieval_table, "enabled", "retrieval")
    if not isinstance(enabled, bool):
        raise ConfigError("config.toml: [retrieval].enabled must be true or false")
    retrieval = RetrievalConfig(
        enabled=enabled,
        model=_require_str(retrieval_table, "model", "retrieval"),
        k=_require_int(retrieval_table, "k", "retrieval"),
        similarity_floor=_require_float(retrieval_table, "similarity_floor", "retrieval"),
        window_days=_require_int(retrieval_table, "window_days", "retrieval"),
    )
    if retrieval.k < 1:
        raise ConfigError("config.toml: [retrieval].k must be at least 1")
    if not 0.0 <= retrieval.similarity_floor <= 1.0:
        raise ConfigError("config.toml: [retrieval].similarity_floor must be within 0.0–1.0")

    return Config(
        run=run,
        beats=beats,
        location=location,
        delivery=delivery,
        escalation=escalation,
        team=team,
        retrieval=retrieval,
        source_path=source_path,
        raw=dict(data),
    )


def load_config(path: str | Path | None = None) -> Config:
    """Read and validate ``config.toml``."""
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise ConfigError(f"No config file at {config_path}")
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{config_path} is not valid TOML: {exc}") from exc
    return parse_config(data, source_path=config_path)


def enabled_beats(config: Config) -> list[str]:
    """Beat names this config turns on, in declaration order."""
    return [name for name, enabled in config.beats.items() if enabled]


def config_digest(config: Config) -> str:
    """A short, stable fingerprint of the run parameters, for the trace's `run_start`."""
    payload = json.dumps(config.raw, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "Config",
    "ConfigError",
    "DeliveryConfig",
    "EscalationConfig",
    "LocationConfig",
    "RetrievalConfig",
    "RunConfig",
    "TeamConfig",
    "config_digest",
    "enabled_beats",
    "load_config",
    "parse_config",
]
