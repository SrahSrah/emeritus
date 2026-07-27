"""Record an HTTP fixture from a live endpoint.

This is the **only** code in the project allowed to touch the network outside a real
run. It is never imported by the package or the test suite — run it by hand when a new
adapter needs fixtures:

    uv run python scripts/capture_fixture.py mlb_final \\
        "https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=117&date=2026-07-26"

    uv run python scripts/capture_fixture.py nws_points_austin \\
        "https://api.weather.gov/points/30.2672,-97.7431"

Writes a pretty-printed JSON file to ``tests/fixtures/<name>.json``. Every NWS request
carries a User-Agent, because api.weather.gov answers 403 without one.

Fixtures that were hand-edited afterwards (an in-progress game in the offseason, a
below-freezing Austin morning in July) must be recorded as synthetic in
``tests/fixtures/README.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# Contact string required by api.weather.gov. Not a secret.
USER_AGENT = "forecaster-capstone (sarah.rachel.hernandez@gmail.com)"


def capture(name: str, url: str, *, timeout: float = 30.0) -> Path:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
        response = client.get(url)
    response.raise_for_status()
    payload = response.json()

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURE_DIR / f"{name}.json"
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="fixture name, without the .json suffix")
    parser.add_argument("url", help="full URL to record")
    args = parser.parse_args(argv)

    path = capture(args.name, args.url)
    size = path.stat().st_size
    print(f"wrote {path} ({size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
