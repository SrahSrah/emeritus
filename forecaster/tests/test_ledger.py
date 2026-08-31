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


def test_a_row_records_the_beats_declared_checkable_facts(tmp_path: Path) -> None:
    """Since 2026-08-31 the stored `checkable_fields` merges the beat's declared facts
    with the item's `fields` — FR-19's disjoint-key clause reads a missing key as "the
    reader was never told this", so a row that stored `fields` alone would make every
    later night's counts look new forever (the measured wsb suppression)."""
    db = tmp_path / "ledger.db"
    record_delivered_items(_digest(tmp_path, "run-1"), "run-1", path=db)

    rows = rows_for_run("run-1", path=db)
    assert all(
        row.fields["final_score"] == "Houston Astros 3, Chicago White Sox 12"
        for row in rows
    )


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
# The guardrail, revised 2026-08-02 when §9 Q3 was answered
#
# These tests used to enforce "the ledger is write-only because item identity is an
# open question". Q3 is now answered — *identity is a read-time relation, not a stored
# property* — so the guard changes shape rather than going away. What must still hold:
# no identity is ever written down, and nothing outside the retrieval layer queries this
# table to make a decision.
# --------------------------------------------------------------------------- #


LEDGER_SOURCE = (
    Path(__file__).resolve().parent.parent / "forecaster" / "memory" / "ledger.py"
).read_text(encoding="utf-8")


def test_the_schema_still_has_no_semantic_identity_column(tmp_path: Path) -> None:
    """`checkable_fields` is the *observed values*, not a "same story" key.

    The distinction is the whole answer to §9 Q3. Storing what a line claimed is a
    record. Storing "this is story #47" would be a frozen judgment, and that is still
    forbidden.
    """
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
        "checkable_fields",
    }
    for forbidden in ("item_identity", "fingerprint", "content_hash", "story_id", "dedup_key"):
        assert forbidden not in columns


def test_the_module_computes_no_hash_and_stores_no_verdict() -> None:
    """Checked against the code, not the prose.

    The ledger may *index* a vector (an accelerator for a read-time search) but it may
    never compute a content hash or persist a dedup verdict — either would turn identity
    back into a stored property.
    """
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
    for forbidden in ("hashlib", "sha256", "md5", "difflib", "dedup", "suppress"):
        assert forbidden not in haystack


def test_the_migration_adds_the_column_to_an_existing_ledger(tmp_path: Path) -> None:
    """A ledger written before 2026-08-02 must open, not crash. Real ones exist."""
    db = tmp_path / "old.db"
    legacy = sqlite3.connect(db)
    legacy.executescript(
        """
        CREATE TABLE sent_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            beat TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            rendered_text TEXT NOT NULL,
            source_observation_id TEXT
        );
        """
    )
    legacy.execute(
        "INSERT INTO sent_items (run_id, beat, sent_at, rendered_text, "
        "source_observation_id) VALUES ('old-run', 'astros', '2026-07-01T00:00:00', "
        "'Astros won.', NULL)"
    )
    legacy.commit()
    legacy.close()

    with connect(db) as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(sent_items)")
        }
        surviving = connection.execute("SELECT COUNT(*) FROM sent_items").fetchone()[0]

    assert "checkable_fields" in columns
    assert surviving == 1


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
        "only the runner may import the ledger module; FR-9b reads the table through a "
        f"connection handed to `retrieval.py`, not by importing it, got {importers}"
    )
