# Fixture provenance

The test suite runs entirely off these files — no live network (see the socket guard in
`tests/conftest.py`). Every fixture below is either **recorded** verbatim from the live
endpoint or **recorded then hand-edited**. Nobody should have to guess which.

Re-record with `uv run python scripts/capture_fixture.py <name> "<url>"`, or, for the
non-JSON sources the news beat reads (XML feeds, HTML article pages, `robots.txt`):

```
uv run python scripts/capture_fixture.py --raw <name>.<ext> "<url>" --user-agent "<ua>"
```

Under `--raw` the name carries its own extension, and the body is written verbatim —
nothing is parsed. The extension is also what tells the harness which content type to
serve the fixture with.

## Recorded verbatim

| File | Source | Captured |
|---|---|---|
| `mlb_doubleheader.json` | `statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=117&date=2026-04-30` — a real Astros doubleheader | 2026-07-27 |
| `mlb_final.json` | same endpoint, `date=2026-07-26` — one completed game (Astros 3, White Sox 12) | 2026-07-27 |
| `mlb_no_game.json` | same endpoint, `date=2026-07-02` — a real off day; `dates` is empty | 2026-07-27 |
| `nws_points_austin.json` | `api.weather.gov/points/30.2672,-97.7431` — resolves to grid **EWX 156,91** | 2026-07-27 |
| `nws_hourly_austin.json` | `api.weather.gov/gridpoints/EWX/156,91/forecast/hourly` | 2026-07-27 |
| `feed_arstechnica.xml` | `feeds.arstechnica.com/arstechnica/index` — **RSS 2.0**, 20 `<item>`, RFC 822 `<pubDate>`, body in `<content:encoded>` | 2026-08-04 |
| `feed_theverge.xml` | `www.theverge.com/rss/index.xml` — **Atom**, 10 `<entry>`, ISO 8601 `<published>`, url in a `link` href | 2026-08-04 |
| `article_arstechnica.html` | `arstechnica.com/tech-policy/2026/08/senators-demand-crackdown-on-wildfire-prediction-markets/` — extracts to **3,673 chars across 15 paragraphs** | 2026-08-04 |
| `robots_arstechnica.txt` | `arstechnica.com/robots.txt` — the real file, which permits the article path above | 2026-08-04 |

The two feeds are kept as full recordings rather than trimmed, because the point of the
pair is that RSS 2.0 and Atom really do differ in three places — the item element, where
the link lives, and the date format — and a hand-trimmed feed would stop proving that.

`sample.json`, `sample.xml`, and `sample.html` are not recordings — they are tiny files
that exist only to prove the fixture harness itself serves JSON, XML, and HTML through an
`httpx.Client`.

## Recorded, then hand-edited — **synthetic**

Two states cannot be captured live on the day this was built. Both start from a real
payload so the surrounding shape is genuine; only the named fields were changed.

### `mlb_in_progress.json`

Base: `mlb_final.json` (real 2026-07-26 payload, gamePk 824572).

Edited:
- `status` → `abstractGameState: "Live"`, `codedGameState: "I"`, `detailedState: "In Progress"`
- `teams.away.score` 3 → **2**, `teams.home.score` 12 → **1**
- removed `isWinner` from both teams (no winner yet)
- added a minimal `linescore` (`currentInning: 6`, top of the inning)

Why synthetic: no Astros game was in progress at capture time. This is the only way to
exercise FR-5's "tonight in progress" branch off a fixture.

### `feed_malformed.xml`

Hand-built, not derived from a recording — the shape is a minimal RSS 2.0 channel. Four
items on purpose:

- one complete entry (the only one that survives parsing);
- one with **no `<pubDate>`**;
- one with **no `<link>` and no http `<guid>`**;
- one whose `<pubDate>` is `"sometime last Thursday"` — unparseable.

Why synthetic: real publishers mostly emit well-formed entries, so the drop path would
otherwise be untested. FR-20 drops rather than defaults, because a substituted date files
an article in the wrong retrieval window and a substituted url is not a thing that can be
fetched.

### `article_paywalled.html`

Hand-built. One free paragraph, a `div.paywall` telling you to subscribe, and boilerplate
in `nav` / `header` / `aside` / `footer` / `script` / `style`. Extracts to well under the
600-char floor, which is what makes FR-21's summary fallback fire.

Why synthetic: a real paywalled capture would be a copyright problem to check in, and the
shape is what matters, not whose paywall it is.

### `robots_disallow.txt`

Hand-built. `Disallow: /articles/` and `/premium/` for `*`, with a permissive
`Googlebot` block underneath — so the fixture proves the rules are actually *read* rather
than the file's mere presence being noticed. `/blog/` on the same host stays fetchable.

### `nws_hourly_austin_freezing.json`

Base: `nws_hourly_austin.json` (real 2026-07-27 capture).

Edited — **only the three periods covering 05:00–08:00 local on 2026-07-28**:
- `temperature` 77/76/76 °F → **28 °F**
- `probabilityOfPrecipitation.value` 0 → **40**
- `windSpeed` `"5 mph"` → `"12 mph"`, `windDirection` `"S"` → `"N"`
- `shortForecast` → `"Clear"`

Every other period is untouched. Why synthetic: Austin in late July does not produce a
below-freezing morning, and FR-6's acceptance needs one in each direction. The unedited
`nws_hourly_austin.json` is the above-threshold case.
