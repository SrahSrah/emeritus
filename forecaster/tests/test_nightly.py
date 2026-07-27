"""Step 19 — missed-run honesty, and the shape of the nightly job script.

FR-14's actual acceptance (three consecutive scheduled nights) is human-gated: registering
a scheduled task changes system settings, and three nights is three nights. What is
testable here is the missed-run accounting and the script's guarantees.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from pathlib import Path

import pytest

from forecaster.agent import FakeAgentClient
from forecaster.beats.base import load_builtin_beats
from forecaster.cli import last_run_at, missed_slots, run_pipeline
from forecaster.delivery.base import FakeDeliverer
from forecaster.memory.preferences import parse_preferences
from forecaster.trace import Trace, read_trace, records_of
from tests.conftest import Route, fixture_client
from tests.helpers import HOURLY_URL, NOW, POINTS_URL, make_config

load_builtin_beats()

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run_nightly.ps1"
SCRIPT_SOURCE = SCRIPT.read_text(encoding="utf-8")
#: The script with its comment-based help block removed, so "first statement" means it.
SCRIPT_CODE = re.sub(r"<#.*?#>", "", SCRIPT_SOURCE, flags=re.DOTALL)

PREFS = parse_preferences({"topics": {"astros": 1.0, "weather": 1.0}})
SEND_TIME = time(19, 0)

ROUTES = [
    Route(r"date=2026-07-27", fixture="mlb_final"),
    Route(r"startDate=", fixture="mlb_preview"),
    Route(POINTS_URL, fixture="nws_points_austin"),
    Route(HOURLY_URL, fixture="nws_hourly_austin"),
]


# --------------------------------------------------------------------------- #
# Missed-run accounting (PRD §8 / §2b)
# --------------------------------------------------------------------------- #


def test_no_previous_run_means_nothing_is_counted_as_missed() -> None:
    assert missed_slots(None, NOW, SEND_TIME) == []


def test_a_run_last_night_means_nothing_missed() -> None:
    yesterday = datetime(2026, 7, 26, 19, 0)
    assert missed_slots(yesterday, NOW, SEND_TIME) == []


def test_three_dark_nights_produce_three_missed_slots() -> None:
    last = datetime(2026, 7, 23, 19, 5)

    slots = missed_slots(last, datetime(2026, 7, 27, 19, 0), SEND_TIME)

    assert [slot.date() for slot in slots] == [
        date(2026, 7, 24),
        date(2026, 7, 25),
        date(2026, 7, 26),
    ]
    assert all(slot.time() == SEND_TIME for slot in slots)


def test_a_slot_in_the_future_is_not_counted() -> None:
    last = datetime(2026, 7, 26, 19, 0)
    # It is 6 pm — tonight's slot hasn't happened yet, so it isn't missed.
    assert missed_slots(last, datetime(2026, 7, 27, 18, 0), SEND_TIME) == []


def test_the_slot_list_is_bounded() -> None:
    slots = missed_slots(datetime(2020, 1, 1, 19, 0), NOW, SEND_TIME, limit=5)
    assert len(slots) == 5


def test_last_run_at_reads_the_newest_trace(tmp_path: Path) -> None:
    assert last_run_at(tmp_path) is None

    with Trace("older", directory=tmp_path) as trace:
        trace.run_start(auth_mode="subscription_oauth", config_digest="x")
    with Trace("zzz-newer", directory=tmp_path) as trace:
        trace.run_start(auth_mode="subscription_oauth", config_digest="x")

    found = last_run_at(tmp_path)
    assert isinstance(found, datetime)


def test_a_corrupt_old_trace_does_not_block_tonight(tmp_path: Path) -> None:
    (tmp_path / "aaa-broken.jsonl").write_text("not json at all\n", encoding="utf-8")
    with Trace("zzz-good", directory=tmp_path) as trace:
        trace.run_start(auth_mode="subscription_oauth", config_digest="x")

    assert isinstance(last_run_at(tmp_path), datetime)


def test_missed_slots_are_written_into_tonights_trace(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    with Trace("20260723T190000-old", directory=runs) as trace:
        trace.run_start(auth_mode="subscription_oauth", config_digest="x")
        # Backdate it so three nights look dark.
    lines = (runs / "20260723T190000-old.jsonl").read_text(encoding="utf-8")
    (runs / "20260723T190000-old.jsonl").write_text(
        lines.replace(
            re.search(r'"at": "([^"]+)"', lines).group(1), "2026-07-23T19:05:00"
        ),
        encoding="utf-8",
    )

    client, _ = fixture_client(ROUTES)
    with client:
        report = run_pipeline(
            make_config(),
            PREFS,
            agent_client=FakeAgentClient(),
            deliverer=FakeDeliverer(),
            http_client=client,
            now=NOW,
            trace_dir=runs,
            ledger_path=tmp_path / "ledger.db",
        )

    missed = list(records_of(read_trace(report.trace_path), "missed_run"))
    assert report.missed_runs == 3
    assert len(missed) == 3
    assert all("counted as missed" in record["reason"] for record in missed)
    assert [record["expected_at"][:10] for record in missed] == [
        "2026-07-24",
        "2026-07-25",
        "2026-07-26",
    ]


def test_missed_runs_are_separate_records_from_failures(tmp_path: Path) -> None:
    """§2(b) counts missed runs separately from delivery failures."""
    client, _ = fixture_client(ROUTES)
    with client:
        report = run_pipeline(
            make_config(),
            PREFS,
            agent_client=FakeAgentClient(),
            deliverer=FakeDeliverer(),
            http_client=client,
            now=NOW,
            trace_dir=tmp_path / "runs",
            ledger_path=tmp_path / "ledger.db",
        )

    records = read_trace(report.trace_path)
    assert list(records_of(records, "missed_run")) == []
    assert next(records_of(records, "delivery"))["success"] is True


# --------------------------------------------------------------------------- #
# The job script's guarantees, read off the script itself
# --------------------------------------------------------------------------- #


def test_the_script_strips_the_api_key_before_anything_else() -> None:
    body = [
        line.strip()
        for line in SCRIPT_CODE.splitlines()
        if line.strip()
        and not line.strip().startswith(("#", "[", "param", ")", "$ErrorAction"))
    ]
    # First executable statement after the param block and the strictness setting.
    assert body[0].startswith("Remove-Item Env:ANTHROPIC_API_KEY")


def test_the_script_never_re_adds_the_api_key_from_the_env_file() -> None:
    assert "if ($name -eq 'ANTHROPIC_API_KEY') { continue }" in SCRIPT_SOURCE


def test_the_script_accepts_a_dry_run_switch_and_passes_it_through() -> None:
    assert "[switch]$DryRun" in SCRIPT_SOURCE
    assert "$CliArgs += '--dry-run'" in SCRIPT_SOURCE


def test_the_script_logs_under_the_gitignored_data_directory() -> None:
    assert "'data\\logs'" in SCRIPT_SOURCE
    assert "nightly-$Stamp.log" in SCRIPT_SOURCE


def test_the_script_exits_with_the_cli_exit_code() -> None:
    assert "$ExitCode = $Process.ExitCode" in SCRIPT_SOURCE
    assert SCRIPT_SOURCE.rstrip().endswith("exit $ExitCode")


def test_the_script_logs_only_the_presence_of_secrets_never_their_values() -> None:
    """It may say a token is present. It may not say what it is."""
    for line in SCRIPT_SOURCE.splitlines():
        if "Out-File" in line and "TOKEN" in line.upper():
            assert "[bool]" in line, f"log line may reveal a value: {line.strip()}"
        assert "$env:CLAUDE_CODE_OAUTH_TOKEN\"" not in line
        assert "$env:SMTP_PASSWORD" not in line


def test_the_script_does_not_register_the_scheduled_task() -> None:
    """Registering it changes system settings — that is Sarah's action, not the agent's."""
    assert "schtasks" not in SCRIPT_SOURCE.lower()
    assert "Register-ScheduledTask" not in SCRIPT_SOURCE


def test_the_script_adds_no_wake_hack_retry_daemon_or_api_key_fallback() -> None:
    lowered = SCRIPT_SOURCE.lower()
    for forbidden in ("powercfg", "start-sleep", "while (", "-retry", "anthropic_api_key ="):
        assert forbidden not in lowered
