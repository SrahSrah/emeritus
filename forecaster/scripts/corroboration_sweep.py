"""Corroboration floor sweep over the live corpus — the Q7 tuning instrument.

Re-runs the shipped FR-33 counter at several floors and windows over whatever the
corpus currently holds, and histograms the counts. This is how `floor` moved from a
reasoned 0.55 to a measured 0.35 on 2026-08-20 (three nights, 162 articles: nothing
reached two sources above 0.40; 0.35 yielded ~2 gate-passing candidates per night).

Read-only, offline, no model calls. Run it again before ever moving the floor:

    uv run python scripts/corroboration_sweep.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forecaster.config import load_config
from forecaster.memory import corpus as corpus_module
from forecaster.memory.retrieval import load_vec

FLOORS = [0.35, 0.40, 0.45, 0.50, 0.55]
WINDOWS = [2, 3]


def main() -> int:
    config = load_config()
    settings = config.need_to_know
    if settings is None:
        print("no [need_to_know] section in config.toml; nothing to sweep")
        return 1
    sources = [feed.name for feed in settings.feeds]
    now = datetime.now(timezone.utc)

    connection = corpus_module.connect(settings.corpus.path)
    load_vec(connection)

    placeholders = ",".join("?" for _ in sources)
    rows = connection.execute(
        f"SELECT url, source, published FROM articles WHERE source IN ({placeholders}) "
        "ORDER BY published DESC",
        tuple(sources),
    ).fetchall()
    print(f"corpus holds {len(rows)} need-to-know articles across {len(sources)} sources")
    print(f"shipped: floor={settings.corroboration.floor}, "
          f"window_days={settings.corroboration.window_days}")

    for window in WINDOWS:
        cutoff = (now - timedelta(days=window)).isoformat()
        candidates = [row for row in rows if str(row[2]) >= cutoff]
        print(f"\n=== window_days = {window}: {len(candidates)} candidates ===")
        print(f"{'floor':>6} | {'>=1 src':>8} | {'>=2 src':>8} | {'>=3 src':>8} | {'max':>4}")
        for floor in FLOORS:
            counts = [
                len(
                    corpus_module.corroborating_sources(
                        connection,
                        str(url),
                        sources=sources,
                        floor=floor,
                        window_days=window,
                        now=now,
                    )
                )
                for url, _, _ in candidates
            ]
            print(
                f"{floor:>6} | {sum(1 for c in counts if c >= 1):>8} | "
                f"{sum(1 for c in counts if c >= 2):>8} | "
                f"{sum(1 for c in counts if c >= 3):>8} | "
                f"{max(counts) if counts else 0:>4}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
