"""Step 16 — rows per delivered item, no collisions, and nothing that answers §9 Q3."""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

from forecaster.agent import FakeAgentClient
from forecaster.beats.base import BeatItem, BeatResult, ObservationRef
from forecaster.memory.ledger import (
    all_rows,
    connect,
    create_schema,
    record_delivered_items,
    rows_for_run,
)
from forecaster.memory.preferences import parse_preferences
from forecaster.synthesizer import synthesize
from forecaster.trace import Trace
from tests.helpers import make_config, trace_in

CONFIG = make_config()
PREFS = parse_preferences({"topics": {"astros": 1.0, "weather": 1.0}})


def _digest(tmp_path: Path, run_id: str):
    """A completed synthetic run's digest."""
    trace = trace_in(tmp_path, run_id)
    with trace:
        obs = trace.tool_call(beat="astros", adapter="mlb.fetch_schedule", arguments={})
        trace.observation(obs, payload=[{"away_score": 3, "home_score": 12}])
        astros = BeatResult(
            beat="astros",
            items=[
                BeatItem(
                    beat="astros",
                    text="Final: Houston Astros 3, Chicago White Sox 12.",
                    observations=[ObservationRef(obs, "mlb.fetch_schedule")],
                ),
                BeatItem(
                    beat="astros",
                    text="Next: a game at some point.",
                    observations=[ObservationRef(obs, "mlb.fetch_schedule")],
                ),
            ],
            checkable_fields={"final_score": "Houston Astros 3, Chicago White Sox 12"},
            observations=[ObservationRef(obs, "mlb.fetch_schedule")],
        )
        trace.beat_result(astros)
        return synthesize([astros], CONFIG, PREFS, trace, agent_client=FakeAgentClient())


# --------------------------------------------------------------------------- #
# FR-9's acceptance criterion
# --------------------------------------------------------------------------- #


def test_a_completed_run_appends_one_row_per_delivered_item(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    digest = _digest(tmp_path, "run-1")

    written = record_delivered_items(digest, "run-1", path=db)

    rows = rows_for_run("run-1", path=db)
    assert written == 2
    assert len(rows) == 2
    assert [row.beat for row in rows] == ["astros", "astros"]
    assert rows[0].rendered_text == "Final: Houston Astros 3, Chicago White Sox 12."
    assert rows[0].source_observation_id == "obs-0001"
    assert rows[0].sent_at


def test_a_second_run_appends_its_own_rows_without_collision(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"

    record_delivered_items(_digest(tmp_path, "run-1"), "run-1", path=db)
    record_delivered_items(_digest(tmp_path, "run-2"), "run-2", path=db)

    everything = all_rows(path=db)
    assert len(everything) == 4
    assert len({row.id for row in everything}) == 4, "no id collision"
    assert len(rows_for_run("run-1", path=db)) == 2
    assert len(rows_for_run("run-2", path=db)) == 2

    # The identical text appears twice across runs. That is correct: without an answer
    # to §9 Q3 there is no basis for calling them "the same story".
    texts = [row.rendered_text for row in everything]
    assert texts.count("Final: Houston Astros 3, Chicago White Sox 12.") == 2


def test_re_running_schema_creation_on_an_existing_db_is_a_no_op(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    record_delivered_items(_digest(tmp_path, "run-1"), "run-1", path=db)

    with connect(db) as connection:
        create_schema(connection)
        create_schema(connection)

    assert len(all_rows(path=db)) == 2


def test_the_database_file_is_created_on_demand(tmp_path: Path) -> None:
    db = tmp_path / "nested" / "ledger.db"
    assert not db.exists()

    record_delivered_items(_digest(tmp_path, "run-1"), "run-1", path=db)

    assert db.exists()


# --------------------------------------------------------------------------- #
# The guardrail: nothing here may answer §9 Q3
# --------------------------------------------------------------------------- #


LEDGER_SOURCE = (
    Path(__file__).resolve().parent.parent / "forecaster" / "memory" / "ledger.py"
).read_text(encoding="utf-8")


def test_the_schema_has_no_semantic_identity_column(tmp_path: Path) -> None:
    """A surrogate id plus run_id is fine. A "same story" key is the open question."""
    db = tmp_path / "ledger.db"
    with connect(db) as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(sent_items)")
        }

    assert columns == {
        "id",
        "run_id",
        "beat",
        "sent_at",
        "rendered_text",
        "source_observation_id",
    }
    for forbidden in ("item_identity", "fingerprint", "content_hash", "story_id", "dedup_key"):
        assert forbidden not in columns


def test_the_module_computes_no_hash_and_runs_no_similarity_check() -> None:
    """Checked against the code, not the prose — the docstring explains *why* not."""
    tree = ast.parse(LEDGER_SOURCE)
    identifiers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            identifiers.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            identifiers.add(node.module or "")
            identifiers.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)

    haystack = " ".join(identifiers).lower()
    for forbidden in ("hashlib", "sha256", "md5", "similarity", "difflib", "embedding"):
        assert forbidden not in haystack


def test_no_unique_constraint_implies_an_identity(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    with connect(db) as connection:
        indexes = list(connection.execute("PRAGMA index_list(sent_items)"))
    assert all(index["unique"] == 0 for index in indexes)


def test_the_pipeline_never_reads_the_ledger_to_make_a_decision() -> None:
    """The PowerShell grep, as a test: only the runner touches this module."""
    package = Path(__file__).resolve().parent.parent / "forecaster"
    importers: list[str] = []
    for path in package.rglob("*.py"):
        if path.name == "ledger.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = " ".join(alias.name for alias in node.names)
            if "ledger" in module:
                importers.append(path.name)

    assert set(importers) <= {"cli.py"}, (
        f"the ledger is write-only in v1; only the runner may import it, got {importers}"
    )
