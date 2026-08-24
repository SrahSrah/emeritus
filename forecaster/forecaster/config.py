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
    #: FR-44. Beats whose items bypass the dedup pass entirely — no retrieval, no
    #: judgment, an explicit `dedup_exempt` record instead. Config-owned rather than
    #: beat-declared, so the opt-out is visible every time this file is opened and
    #: reversible with a one-line edit. Ships as ["venues"]: a standing listing should
    #: repeat nightly while Sarah decides (her call, 2026-08-16).
    exempt_beats: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ChunkingConfig:
    """FR-22. Character counts, not tokens — the PRD specifies characters."""

    target_chars: int
    max_chars: int
    overlap_chars: int


@dataclass(frozen=True)
class CorpusConfig:
    """FR-23. A **separate** file from `ledger.db`; see the PRD's rationale."""

    path: str
    ttl_days: int


@dataclass(frozen=True)
class NewsRetrievalConfig:
    """FR-24. Deliberately **not** the same numbers as :class:`RetrievalConfig`.

    Matching a topic query against an article chunk is a different retrieval problem from
    comparing a candidate line against past lines, so it has a different natural floor.
    Both sets are reasoned rather than measured — parent PRD §9 Q5 and child §9 Q6.
    """

    k: int
    similarity_floor: float
    window_days: int
    max_chunks_per_article: int


@dataclass(frozen=True)
class FeedConfig:
    name: str
    url: str


@dataclass(frozen=True)
class TopicConfig:
    """One retrieval query. Nothing in the code knows any particular `id`."""

    id: str
    query: str


@dataclass(frozen=True)
class NewsConfig:
    user_agent: str
    fetch_delay_seconds: float
    timeout_seconds: float
    min_body_chars: int
    feeds: list[FeedConfig]
    chunking: ChunkingConfig
    corpus: CorpusConfig
    retrieval: NewsRetrievalConfig
    topics: list[TopicConfig]


@dataclass(frozen=True)
class CorroborationConfig:
    """FR-33. A third retrieval problem with a third natural floor.

    `floor` is the project's first **measured** threshold (0.35, sweep of 2026-08-20 —
    see the config.toml comment and §9 Q7). `window_days` and `min_sources` remain
    reasoned; `min_sources` is FR-36's mechanical gate, alive at the measured floor.
    """

    window_days: int
    floor: float
    min_sources: int


@dataclass(frozen=True)
class BarConfig:
    """FR-36. Sarah's definition of "need to know", in plain language, in config.

    Taste is config, not code — the same reasoning as the news topics. `deliver` and
    `exclude` are interpolated into the judgment prompt; `exclude` exists because her
    2026-08-14 interview named deliberate exclusions (election outcomes, deaths of
    public figures), and naming them beats leaving them to inference.
    """

    deliver: list[str]
    exclude: list[str]


@dataclass(frozen=True)
class NeedToKnowConfig:
    """FR-31. The news beat's shape minus topics — this beat has no queries.

    Its candidate set is every in-window article from its own sources, and its only
    v4 computation is the corroboration count. Deliberately **no** `min_sources`,
    `watchlist`, or `bar` key: those are v5 (FR-36, FR-38), and shipping a knob nothing
    consumes would be inventing the bar through config.
    """

    user_agent: str
    fetch_delay_seconds: float
    timeout_seconds: float
    min_body_chars: int
    feeds: list[FeedConfig]
    chunking: ChunkingConfig
    corpus: CorpusConfig
    corroboration: CorroborationConfig
    #: FR-38. Terms whose presence in a candidate's headline or lead bypasses the gate
    #: and the judgment and escalates deterministically. Sarah's list, seeded 2026-08-14.
    watchlist: list[str]
    bar: BarConfig


@dataclass(frozen=True)
class VenueConfig:
    """One venue calendar. `kind` names the parser; config stays ignorant of code."""

    name: str
    kind: str
    url: str


@dataclass(frozen=True)
class VenuesConfig:
    """FR-43. Named-venue listings — deliberately no taste, ranking, or discovery knobs.

    The 2026-08-16 re-scope is the design: what's playing at venues Sarah named, for
    `window_days`, repeated nightly. Anything resembling a preference belongs in
    `preferences.toml`, not here, and v1 has none.
    """

    user_agent: str
    timeout_seconds: float
    window_days: int
    venues: list[VenueConfig]


@dataclass(frozen=True)
class Config:
    run: RunConfig
    beats: dict[str, bool]
    location: LocationConfig
    delivery: DeliveryConfig
    escalation: EscalationConfig
    team: TeamConfig
    retrieval: RetrievalConfig
    news: NewsConfig | None = None
    need_to_know: NeedToKnowConfig | None = None
    venues: VenuesConfig | None = None
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
    raw_exempt = retrieval_table.get("exempt_beats", [])
    if not isinstance(raw_exempt, list) or not all(
        isinstance(item, str) and item for item in raw_exempt
    ):
        raise ConfigError(
            "config.toml: [retrieval].exempt_beats must be a list of beat names"
        )
    retrieval = RetrievalConfig(
        enabled=enabled,
        model=_require_str(retrieval_table, "model", "retrieval"),
        k=_require_int(retrieval_table, "k", "retrieval"),
        similarity_floor=_require_float(retrieval_table, "similarity_floor", "retrieval"),
        window_days=_require_int(retrieval_table, "window_days", "retrieval"),
        exempt_beats=list(raw_exempt),
    )
    if retrieval.k < 1:
        raise ConfigError("config.toml: [retrieval].k must be at least 1")
    if not 0.0 <= retrieval.similarity_floor <= 1.0:
        raise ConfigError("config.toml: [retrieval].similarity_floor must be within 0.0–1.0")

    news = _parse_news(data, news_enabled=beats.get("news", False))
    need_to_know = _parse_need_to_know(
        data, enabled=beats.get("need_to_know", False)
    )
    _reject_corpus_ttl_conflict(news, need_to_know)
    venues = _parse_venues(data, enabled=beats.get("venues", False))

    return Config(
        run=run,
        beats=beats,
        location=location,
        delivery=delivery,
        escalation=escalation,
        team=team,
        retrieval=retrieval,
        news=news,
        need_to_know=need_to_know,
        venues=venues,
        source_path=source_path,
        raw=dict(data),
    )


def _parse_news(data: Mapping[str, Any], *, news_enabled: bool) -> NewsConfig | None:
    """Parse `[news]` if present. Absent is fine **unless** `[beats].news` is on.

    Optional rather than required because every config that predates the news beat — the
    test builders included — is still a valid config. What is not valid is enabling the
    beat with nothing to configure it from, and that fails loudly here rather than at
    2 am inside a nightly run.
    """
    if "news" not in data:
        if news_enabled:
            raise ConfigError(
                "config.toml: [beats].news is true but there is no [news] section. "
                "The beat has no feeds, no topics, and no corpus settings to run with."
            )
        return None

    news_table = _require_table(data, "news")

    chunking = _parse_chunking(news_table, "news")
    corpus = _parse_corpus(news_table, "news")

    retrieval_table = _require_table(news_table, "retrieval")
    news_retrieval = NewsRetrievalConfig(
        k=_require_int(retrieval_table, "k", "news.retrieval"),
        similarity_floor=_require_float(
            retrieval_table, "similarity_floor", "news.retrieval"
        ),
        window_days=_require_int(retrieval_table, "window_days", "news.retrieval"),
        max_chunks_per_article=_require_int(
            retrieval_table, "max_chunks_per_article", "news.retrieval"
        ),
    )
    if news_retrieval.k < 1:
        raise ConfigError("config.toml: [news.retrieval].k must be at least 1")
    if not 0.0 <= news_retrieval.similarity_floor <= 1.0:
        raise ConfigError(
            "config.toml: [news.retrieval].similarity_floor must be within 0.0–1.0"
        )
    if news_retrieval.window_days < 1:
        raise ConfigError("config.toml: [news.retrieval].window_days must be at least 1")
    if news_retrieval.max_chunks_per_article < 1:
        raise ConfigError(
            "config.toml: [news.retrieval].max_chunks_per_article must be at least 1"
        )
    if news_retrieval.window_days > corpus.ttl_days:
        raise ConfigError(
            f"config.toml: [news.retrieval].window_days ({news_retrieval.window_days}) "
            f"exceeds [news.corpus].ttl_days ({corpus.ttl_days}) — the run would retrieve "
            "over articles the purge has already deleted"
        )

    feeds = _parse_feeds(news_table, "news")

    topics: list[TopicConfig] = []
    raw_topics = news_table.get("topics", [])
    if not isinstance(raw_topics, list):
        raise ConfigError("config.toml: [[news.topics]] must be a list of tables")
    for index, raw in enumerate(raw_topics):
        if not isinstance(raw, Mapping):
            raise ConfigError(f"config.toml: [[news.topics]] #{index} must be a table")
        topics.append(
            TopicConfig(
                id=_require_str(raw, "id", f"news.topics#{index}"),
                query=_require_str(raw, "query", f"news.topics#{index}"),
            )
        )
    _reject_duplicates([topic.id for topic in topics], "news.topics", "id")

    if news_enabled and not feeds:
        raise ConfigError(
            "config.toml: [beats].news is true but [news].feeds is empty — there is "
            "nothing to read"
        )
    if news_enabled and not topics:
        raise ConfigError(
            "config.toml: [beats].news is true but [[news.topics]] is empty — retrieval "
            "has no query, so the beat would produce nothing"
        )

    return NewsConfig(
        user_agent=_require_str(news_table, "user_agent", "news"),
        fetch_delay_seconds=_require_float(
            news_table, "fetch_delay_seconds", "news"
        ),
        timeout_seconds=_require_float(news_table, "timeout_seconds", "news"),
        min_body_chars=_require_int(news_table, "min_body_chars", "news"),
        feeds=feeds,
        chunking=chunking,
        corpus=corpus,
        retrieval=news_retrieval,
        topics=topics,
    )


def _parse_chunking(table: Mapping[str, Any], section: str) -> ChunkingConfig:
    """FR-22's knobs, shared by every document-shaped beat's config section."""
    chunk_table = _require_table(table, "chunking")
    chunking = ChunkingConfig(
        target_chars=_require_int(chunk_table, "target_chars", f"{section}.chunking"),
        max_chars=_require_int(chunk_table, "max_chars", f"{section}.chunking"),
        overlap_chars=_require_int(chunk_table, "overlap_chars", f"{section}.chunking"),
    )
    if chunking.overlap_chars < 0:
        raise ConfigError(
            f"config.toml: [{section}.chunking].overlap_chars must not be negative"
        )
    if chunking.overlap_chars >= chunking.target_chars:
        raise ConfigError(
            f"config.toml: [{section}.chunking].overlap_chars must be less than "
            "target_chars — an overlap at or above the target never advances and "
            "chunking would not terminate"
        )
    if chunking.target_chars > chunking.max_chars:
        raise ConfigError(
            f"config.toml: [{section}.chunking].target_chars must not exceed max_chars"
        )
    if chunking.target_chars < 1:
        raise ConfigError(
            f"config.toml: [{section}.chunking].target_chars must be at least 1"
        )
    return chunking


def _parse_corpus(table: Mapping[str, Any], section: str) -> CorpusConfig:
    corpus_table = _require_table(table, "corpus")
    corpus = CorpusConfig(
        path=_require_str(corpus_table, "path", f"{section}.corpus"),
        ttl_days=_require_int(corpus_table, "ttl_days", f"{section}.corpus"),
    )
    if corpus.ttl_days < 1:
        raise ConfigError(f"config.toml: [{section}.corpus].ttl_days must be at least 1")
    return corpus


def _parse_feeds(table: Mapping[str, Any], section: str) -> list[FeedConfig]:
    feeds: list[FeedConfig] = []
    raw_feeds = table.get("feeds", [])
    if not isinstance(raw_feeds, list):
        raise ConfigError(f"config.toml: [{section}].feeds must be a list of tables")
    for index, raw in enumerate(raw_feeds):
        if not isinstance(raw, Mapping):
            raise ConfigError(f"config.toml: [{section}].feeds #{index} must be a table")
        feeds.append(
            FeedConfig(
                name=_require_str(raw, "name", f"{section}.feeds#{index}"),
                url=_require_str(raw, "url", f"{section}.feeds#{index}"),
            )
        )
    _reject_duplicates([feed.name for feed in feeds], f"{section}.feeds", "name")
    return feeds


def _parse_need_to_know(
    data: Mapping[str, Any], *, enabled: bool
) -> NeedToKnowConfig | None:
    """Parse `[need_to_know]` if present. Absent is fine **unless** the beat is on.

    Same contract as `_parse_news`: every config that predates this beat stays valid,
    and enabling the beat with nothing to configure it from fails at load, not at 7 pm.
    """
    if "need_to_know" not in data:
        if enabled:
            raise ConfigError(
                "config.toml: [beats].need_to_know is true but there is no "
                "[need_to_know] section. The beat has no feeds and no corroboration "
                "settings to run with."
            )
        return None

    table = _require_table(data, "need_to_know")

    chunking = _parse_chunking(table, "need_to_know")
    corpus = _parse_corpus(table, "need_to_know")
    feeds = _parse_feeds(table, "need_to_know")

    corroboration_table = _require_table(table, "corroboration")
    corroboration = CorroborationConfig(
        window_days=_require_int(
            corroboration_table, "window_days", "need_to_know.corroboration"
        ),
        floor=_require_float(corroboration_table, "floor", "need_to_know.corroboration"),
        min_sources=_require_int(
            corroboration_table, "min_sources", "need_to_know.corroboration"
        ),
    )
    if corroboration.window_days < 1:
        raise ConfigError(
            "config.toml: [need_to_know.corroboration].window_days must be at least 1"
        )
    if not 0.0 <= corroboration.floor <= 1.0:
        raise ConfigError(
            "config.toml: [need_to_know.corroboration].floor must be within 0.0–1.0"
        )
    if corroboration.min_sources < 1:
        raise ConfigError(
            "config.toml: [need_to_know.corroboration].min_sources must be at least 1"
        )
    if corroboration.window_days > corpus.ttl_days:
        raise ConfigError(
            f"config.toml: [need_to_know.corroboration].window_days "
            f"({corroboration.window_days}) exceeds [need_to_know.corpus].ttl_days "
            f"({corpus.ttl_days}) — the run would corroborate over articles the purge "
            "has already deleted"
        )

    # FR-38. Required as of v5: the bar is part of the beat's definition, so a section
    # without its watchlist or bar blocks fails at load, naming what is missing.
    watchlist_table = _require_table(table, "watchlist")
    watchlist = _require_str_list(watchlist_table, "terms", "need_to_know.watchlist")
    if not watchlist:
        raise ConfigError(
            "config.toml: [need_to_know.watchlist].terms must name at least one term — "
            "an empty carve-out leaves the suppress-when-unsure judgment unbounded"
        )
    seen_terms: set[str] = set()
    for term in watchlist:
        folded = term.casefold()
        if folded in seen_terms:
            raise ConfigError(
                f"config.toml: duplicate watchlist term {term!r} (matching is "
                "case-insensitive, so duplicates only blur the trace)"
            )
        seen_terms.add(folded)

    bar_table = _require_table(table, "bar")
    bar = BarConfig(
        deliver=_require_str_list(bar_table, "deliver", "need_to_know.bar"),
        exclude=_require_str_list(bar_table, "exclude", "need_to_know.bar"),
    )
    if not bar.deliver:
        raise ConfigError(
            "config.toml: [need_to_know.bar].deliver must name at least one category — "
            "a bar that delivers nothing by definition is not a bar"
        )
    if not bar.exclude:
        raise ConfigError(
            "config.toml: [need_to_know.bar].exclude must name at least one category — "
            "the deliberate exclusions are part of the definition (PRD §9 Q2)"
        )

    if enabled and not feeds:
        raise ConfigError(
            "config.toml: [beats].need_to_know is true but [need_to_know].feeds is "
            "empty — there is nothing to read"
        )

    return NeedToKnowConfig(
        user_agent=_require_str(table, "user_agent", "need_to_know"),
        fetch_delay_seconds=_require_float(table, "fetch_delay_seconds", "need_to_know"),
        timeout_seconds=_require_float(table, "timeout_seconds", "need_to_know"),
        min_body_chars=_require_int(table, "min_body_chars", "need_to_know"),
        feeds=feeds,
        chunking=chunking,
        corpus=corpus,
        corroboration=corroboration,
        watchlist=watchlist,
        bar=bar,
    )


def _parse_venues(data: Mapping[str, Any], *, enabled: bool) -> VenuesConfig | None:
    """Parse `[venues]` if present. Absent is fine **unless** the beat is on.

    Same contract as every beat section: pre-existing configs stay valid, and enabling
    the beat with nothing to read fails at load rather than at 7 pm. `kind` is **not**
    validated against a parser registry here — config stays ignorant of code, and an
    unknown kind surfaces at run time as a named failed venue (FR-45), not a load error.
    """
    if "venues" not in data:
        if enabled:
            raise ConfigError(
                "config.toml: [beats].venues is true but there is no [venues] section. "
                "The beat has no venue calendars to read."
            )
        return None

    table = _require_table(data, "venues")

    entries: list[VenueConfig] = []
    raw_venues = table.get("venues", [])
    if not isinstance(raw_venues, list):
        raise ConfigError("config.toml: [venues].venues must be a list of tables")
    for index, raw in enumerate(raw_venues):
        if not isinstance(raw, Mapping):
            raise ConfigError(f"config.toml: [venues].venues #{index} must be a table")
        entries.append(
            VenueConfig(
                name=_require_str(raw, "name", f"venues.venues#{index}"),
                kind=_require_str(raw, "kind", f"venues.venues#{index}"),
                url=_require_str(raw, "url", f"venues.venues#{index}"),
            )
        )
    _reject_duplicates([venue.name for venue in entries], "venues.venues", "name")

    window_days = _require_int(table, "window_days", "venues")
    if window_days < 1:
        raise ConfigError("config.toml: [venues].window_days must be at least 1")

    if enabled and not entries:
        raise ConfigError(
            "config.toml: [beats].venues is true but [venues].venues is empty — there "
            "is nothing to read"
        )

    return VenuesConfig(
        user_agent=_require_str(table, "user_agent", "venues"),
        timeout_seconds=_require_float(table, "timeout_seconds", "venues"),
        window_days=window_days,
        venues=entries,
    )


def _reject_corpus_ttl_conflict(
    news: NewsConfig | None, need_to_know: NeedToKnowConfig | None
) -> None:
    """FR-32. Two beats sharing one corpus file must agree on its lifecycle.

    `purge_expired` deletes by `fetched_at` cutoff regardless of which beat calls it, so
    with unequal TTLs on one path, whichever beat runs first would silently purge the
    other's window. Enforced at load rather than remembered at every purge site.
    """
    if news is None or need_to_know is None:
        return
    if Path(news.corpus.path) != Path(need_to_know.corpus.path):
        return
    if news.corpus.ttl_days != need_to_know.corpus.ttl_days:
        raise ConfigError(
            f"config.toml: [news.corpus] and [need_to_know.corpus] share the path "
            f"{news.corpus.path!r} but disagree on ttl_days "
            f"({news.corpus.ttl_days} vs {need_to_know.corpus.ttl_days}). A shared "
            "corpus file needs one lifecycle — whichever beat purged first would "
            "silently shorten the other's window."
        )


def _reject_duplicates(values: list[str], section: str, key: str) -> None:
    """A duplicate name makes a trace record ambiguous — same reasoning as suppression ids."""
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ConfigError(
                f"config.toml: duplicate {key} {value!r} in [{section}] — {key}s must be "
                "unique so a trace entry is unambiguous"
            )
        seen.add(value)


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
    "BarConfig",
    "ChunkingConfig",
    "Config",
    "ConfigError",
    "CorpusConfig",
    "CorroborationConfig",
    "DeliveryConfig",
    "EscalationConfig",
    "FeedConfig",
    "LocationConfig",
    "NeedToKnowConfig",
    "NewsConfig",
    "NewsRetrievalConfig",
    "RetrievalConfig",
    "RunConfig",
    "TeamConfig",
    "TopicConfig",
    "VenueConfig",
    "VenuesConfig",
    "config_digest",
    "enabled_beats",
    "load_config",
    "parse_config",
]
