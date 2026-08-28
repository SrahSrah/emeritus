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

**``--raw`` mode** writes the response body verbatim instead of parsing it, for the news
beat's sources — RSS/Atom is XML, article pages are HTML, and robots.txt is plain text,
and none of those survive ``response.json()``. In raw mode the name carries its own
extension:

    uv run python scripts/capture_fixture.py --raw feed_arstechnica.xml \\
        "https://feeds.arstechnica.com/arstechnica/index"

    uv run python scripts/capture_fixture.py --raw article_arstechnica.html \\
        "https://arstechnica.com/..." \\
        --user-agent "forecaster/0.1 (your.email@example.com)"

Fixtures that were hand-edited afterwards (an in-progress game in the offseason, a
below-freezing Austin morning in July) must be recorded as synthetic in
``tests/fixtures/README.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# Contact string required by api.weather.gov. Not a secret. Set CONTACT_EMAIL in your
# environment (or pass --user-agent) so the header carries a reachable address.
USER_AGENT = "forecaster-capstone ({})".format(
    os.environ.get("CONTACT_EMAIL", "").strip() or "your.email@example.com"
)


def capture(
    name: str,
    url: str,
    *,
    timeout: float = 30.0,
    raw: bool = False,
    user_agent: str | None = None,
) -> Path:
    """Record one response. ``raw=True`` writes the body verbatim, parsing nothing."""
    headers = {
        "User-Agent": user_agent or USER_AGENT,
        "Accept": "*/*" if raw else "application/json",
    }
    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
        response = client.get(url)
    response.raise_for_status()

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    if raw:
        path = FIXTURE_DIR / name
        path.write_text(response.text, encoding="utf-8")
        return path

    path = FIXTURE_DIR / f"{name}.json"
    path.write_text(
        json.dumps(response.json(), indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "name",
        help="fixture name — without .json normally, WITH the extension under --raw",
    )
    parser.add_argument("url", help="full URL to record")
    parser.add_argument(
        "--raw",
        action="store_true",
        help="write the body verbatim (XML/HTML/text) instead of parsing JSON",
    )
    parser.add_argument(
        "--user-agent",
        default=None,
        help="override the User-Agent; use the one the adapter will send",
    )
    args = parser.parse_args(argv)

    path = capture(args.name, args.url, raw=args.raw, user_agent=args.user_agent)
    size = path.stat().st_size
    print(f"wrote {path} ({size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
