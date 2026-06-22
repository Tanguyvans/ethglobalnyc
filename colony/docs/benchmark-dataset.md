# Benchmark Dataset Format

Colony benchmarks are resolved-event replays. Agents must predict from a
time-bounded evidence snapshot, then the runner scores their frozen forecasts
against a resolution that was not visible during prediction.

## Core Rule

For every event:

```text
evidence_item.available_at_utc <= prediction_cutoff_utc
resolution.available_at_utc > prediction_cutoff_utc
```

The runner converts each event into a prediction-only `MatchContext` with an
empty `score`. Result facts stay in `resolution` until scoring.

## Dataset Shape

```json
{
  "schema_version": 1,
  "dataset_id": "worldcup_2026_pilot_v0",
  "title": "World Cup 2026 pilot benchmark dataset",
  "created_at_utc": "2026-06-22T00:00:00Z",
  "sources": [],
  "events": []
}
```

Each event keeps generic classification fields so the same benchmark layer can
support football, prediction markets, finance events, tech launches, culture,
or geopolitics later:

```json
{
  "event_id": "wc26_group_a_mexico_south_africa",
  "category": "sports",
  "sub_category": "football",
  "event_type": "three_way_match_result",
  "title": "Mexico vs South Africa",
  "starts_at_utc": "2026-06-11T19:00:00Z",
  "prediction_cutoff_utc": "2026-06-11T14:00:00Z",
  "outcome_space": ["home", "draw", "away"],
  "baseline_probabilities": {
    "home": 0.58,
    "draw": 0.24,
    "away": 0.18
  },
  "evidence_items": [],
  "resolution": {}
}
```

## Evidence Items

An evidence item is one pre-cutoff source-derived signal.

Required:

```json
{
  "evidence_id": "odds_snapshot",
  "source_name": "market_odds_snapshot",
  "source_type": "odds",
  "access_level": "shared",
  "available_at_utc": "2026-06-11T12:15:00Z",
  "home_probability": 0.61,
  "confidence": 0.78,
  "summary": "Odds snapshot slightly strengthens Mexico.",
  "citations": ["benchmark://odds/..."]
}
```

Recommended for real collected sources:

```json
{
  "source_snapshot_id": "gdelt_doc_20260611T130000Z_mexico_south_africa",
  "published_at_utc": "2026-06-11T11:55:00Z",
  "seen_at_utc": "2026-06-11T12:10:00Z",
  "collected_at_utc": "2026-06-11T13:00:00Z",
  "content_hash": "sha256:...",
  "metadata": {
    "source_quality": "strong",
    "source_kind": "bookmaker|official|news|social|model|manual",
    "raw_snapshot_file": "..."
  }
}
```

For live sources, prefer:

```text
available_at_utc = max(published_at_utc, seen_at_utc, collected_at_utc)
```

If only one timestamp is trustworthy, use it explicitly and document the source
contract in `metadata.timestamp_basis`.

## Resolution

Resolution is post-cutoff and never becomes an evidence item for the same event.

```json
{
  "result_side": "home",
  "score": "2-0",
  "resolved_at_utc": "2026-06-11T21:05:00Z",
  "available_at_utc": "2026-06-11T21:15:00Z",
  "source_name": "official_result_snapshot",
  "citations": ["benchmark://results/..."]
}
```

## Settling Prematch Scrapes

For match-specific pre-match scrapes, resolve scores in a separate post-match
step:

```bash
python3 colony/resolve_settled_games.py \
  --prematch-root colony/runs/prematch_scrape \
  --out colony/runs/settled_games/worldcup_20260622/settled_games.json
```

The resolver scans `normalized/prematch_documents.json`, fetches or loads an
ESPN World Cup scoreboard snapshot, and writes three lists:

```text
settled_games    completed matches with score/result_side
pending_games    matched ESPN event, but not safely resolved yet
unmatched_games  prematch scrape could not be matched to one ESPN event
```

This preserves the no-leak contract: prematch KG files remain unchanged, while
scores are stored only in the settled-games artifact. The resolver also saves
the raw ESPN scoreboard snapshot under the output directory so the score source
can be audited later.

## Raw Collection

Raw source snapshots should be collected before being turned into benchmark
events. The collector writes exact bytes plus a manifest:

```bash
python3 colony/collect_benchmark_data.py \
  --worldcup-openfootball colony/data/openfootball/worldcup_2026.json \
  --football-data 2425/E0 \
  --espn-worldcup-dates 20260611-20260622 \
  --url google_news_worldcup_rss="https://news.google.com/rss/search?q=FIFA%20World%20Cup%202026%20football&hl=en-US&gl=US&ceid=US:en"
```

Output:

```text
collection_manifest.json
openfootball_worldcup_2026.json
football_data_2425_E0.csv
espn_worldcup_scoreboard_20260611_20260622.json
google_news_worldcup_rss.raw
```

Each manifest row contains:

```json
{
  "source_id": "football_data_2425_E0",
  "source_type": "historical_results_odds",
  "locator": "https://www.football-data.co.uk/mmz4281/2425/E0.csv",
  "collected_at_utc": "...",
  "bytes": 12345,
  "sha256": "..."
}
```

This raw collection step proves what bytes were saved and when. A later builder
should convert those raw files into `BenchmarkEvent` records with event cutoffs,
evidence timestamps, baseline probabilities, and resolutions.

## First Source Priorities

1. `OpenFootball` or official fixture data for schedule and known resolutions.
2. Football-Data CSVs for historical results and bookmaker odds backtests.
3. GDELT DOC/GKG for timestamped news and sentiment snapshots.
4. A real odds provider for live pre-match odds and closing-line comparison.

## Current Pilot

The committed pilot dataset is:

```text
colony/data/benchmarks/worldcup_pilot.json
```

It is useful for validating the benchmark loop and temporal contract. It is not
yet a real externally collected benchmark because its evidence is curated.

## World Cup 2026 Latest Resolved Builder

For the first broad World Cup 2026 benchmark path, prefer the ESPN snapshot
because the local OpenFootball fixture file may lag on scores:

```bash
python3 colony/build_worldcup_benchmark.py \
  --collection-dir colony/runs/benchmark_collection/worldcup_20260611_20260622 \
  --out colony/data/benchmarks/worldcup_2026_latest_resolved.json
```

When an ESPN scoreboard snapshot is present, the builder selects completed
events, sorts them chronologically, injects fixture context plus opening
DraftKings/ESPN moneyline probabilities, and writes scores only under
`resolution`.

The raw ESPN summaries contain many useful but dangerous post-match fields.
The builder does not inject `boxscore`, `leaders`, `keyEvents`, `commentary`,
`article`, `news`, `rosters`, `standings`, or closing moneyline odds into
pre-prediction evidence. Those raw bytes remain in the collection snapshot for
later audit and richer builders.

Current limitations:

- ESPN exposes opening moneyline odds but not exact opening timestamps. The
  dataset records this in `metadata.timestamp_basis` and treats opening odds as
  available by the benchmark cutoff.
- Google News RSS snapshots collected after resolved matches are not injected
  because they can include post-match facts.
- Closing odds are useful for later market comparison, but are not injected with
  a six-hour pre-kickoff cutoff.

Then run the ants:

```bash
python3 colony/run_benchmark.py \
  --dataset colony/data/benchmarks/worldcup_2026_latest_resolved.json \
  --agents 24 \
  --rooms 5
```

## Reusing KG Sources Before The Match

The benchmark builder can also reuse the same source modules as the scouting KG
instead of maintaining a separate benchmark-only source path:

```bash
python3 colony/build_worldcup_benchmark.py \
  --collection-dir colony/runs/benchmark_collection/worldcup_20260611_20260622 \
  --kg-module fixture \
  --out colony/data/benchmarks/worldcup_2026_latest_resolved_kg_sources.json
```

Every KG-sourced finding is generated with:

```text
as_of_utc = prediction_cutoff_utc
```

That temporal gate keeps only claims available before the match cutoff. Durable
undated fixture/profile claims are retained; live scores and match-result
claims are always rejected as pre-match evidence.

For historical providers, use source modules that support an explicit `asOf`.
For example, `txline_odds_historical` now renders:

```json
{
  "asOf": "{txline_prediction_cutoff_utc}"
}
```

That means the odds request is anchored before kickoff rather than at kickoff.
Modules that only expose current web/search data should be treated as unsafe
for already-resolved matches unless they provide trustworthy publish timestamps
that pass the temporal gate.
