# KG Run Frontend Contract

The frontend should treat KG construction as its own action, separate from the
full agent pipeline.

## Flow

1. User selects a match and source modules.
2. Frontend loads available source modules from `GET /kg/modules`.
3. Frontend calls `POST /kg/run` with selected modules.
4. Frontend streams `/runs/{run_id}/stream` or polls `/runs/{run_id}`.
5. On success, frontend loads:
   - `GET /runs/{run_id}/kg`
   - `GET /runs/{run_id}/kg/manifest`
   - `GET /runs/{run_id}/scouting-audit`
5. The result tab renders those artifacts. Do not replace the result with
   `GET /kg/world-cup`; that endpoint is only the static tournament fixture KG.

## Start A KG Run

```http
POST /kg/run
Content-Type: application/json
```

```json
{
  "match": "Portugal vs Uzbekistan",
  "match_id": "match:world_cup_2026:063:2026_06_23_portugal_uzbekistan",
  "mode": "fast",
  "modules": ["fixture", "public_x", "polymarket_market_context", "wikidata_profiles"],
  "timeout": 120,
  "camel_agents": 4
}
```

Response:

```json
{
  "id": "kg_20260620_101500_ab12cd34",
  "status": "queued",
  "run_dir": "...",
  "events_path": ".../events.jsonl",
  "compact_runs_dir": ".../compact"
}
```

## List Selectable Plugins

```http
GET /kg/modules
```

The response contains visible, implemented modules from
`colony/config/scouting_source_catalog.json`. Modules that need missing
environment variables are returned with `configured: false`; the UI should show
them disabled with the setup hint.

## Recommended Result Tab

Show these panes:

- Graph: `/runs/{run_id}/kg`
- Quality: `/runs/{run_id}/kg/manifest`
- Gaps and provenance: `/runs/{run_id}/scouting-audit`
- Logs: `/runs/{run_id}/events`

The current static frontend button uses `DN.databridge.startKgRun()` and renders
the completed graph via `DN.kgview`. That is intentionally minimal; a product UI
can replace it with module checkboxes and a richer result tab.

## Module Notes

Good default modules:

- `fixture`: baseline match/team schedule.
- `public_x`: public scouting plus ScrapeCreators X/social search if keys exist.
- `polymarket_market_context`: market probability, liquidity, and price context.
- `wikidata_profiles`: no-key team/player profile enrichment.

Optional heavier modules:

- `camel_deep_research`: deeper multi-role research. Slower, useful when quality
  matters more than latency.
- `txline_full`: fixture, score/status, and odds snapshots. Requires TxLINE API
  token setup.
