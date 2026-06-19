# Scouting Source Contract

`colony/scout_to_kg.py` builds a scouting KG without running the full Colony app.
It selects one match, runs source adapters, extracts evidence claims, writes run
artifacts, and validates them with the same ingestion checks used by
`export_scouting_kg.py`.

## Source Specs

Use `--source` repeatedly to plug multiple sources into one run.

- `fixture` - OpenFootball fixture row for schedule and team context.
- `public` or `public:/cache/dir` - existing public-data scout using cached or live public web/news sources.
- `url:https://...` or a plain `https://...` - fetch one URL, strip HTML, extract claims.
- `api:https://...` - fetch an API URL. JSON payloads can be structured claims or raw documents; text/HTML responses are scraped.
- `{ "kind": "api", "url": "...", "headers": {...}, "adapter": "..." }` - fetch an authenticated or structured API source from a manifest. Header/body/query values can reference environment variables with `${VAR_NAME}` or `env:VAR_NAME`.
- `cli:command --args` - run a local command. Stdout can be JSON or plain text.
- `json:/path/file.json` - load local JSON claims, findings, documents, items, or text.
- `mcp:/path/export.json` - load a local MCP export shaped like JSON claims, findings, documents, items, or text.
- `mcp-stdio:/path/config.json` - start an MCP stdio server, call one tool, and extract the tool result into KG claims.
- `deep-fixture` - deterministic local fixture data for structural KG tests only. Do not use it as real scouting evidence.

You can also put sources in a manifest:

```json
{
  "sources": [
    "fixture",
    "url:https://example.test/brazil-morocco-preview",
    "cli:python3 scouts/my_scout.py --match 'Brazil vs Morocco'",
    {
      "kind": "mcp_stdio",
      "command": ["python3", "scouts/mcp_server.py"],
      "tool": "scout_match",
      "arguments": {"match": "Brazil vs Morocco"}
    },
    {
      "kind": "api",
      "url": "https://txline.txodds.com/api/fixtures/snapshot",
      "adapter": "txline_fixtures",
      "title": "TXLINE fixtures snapshot",
      "headers": {
        "Authorization": "Bearer ${TXLINE_JWT}",
        "X-Api-Token": "${TXLINE_API_TOKEN}"
      },
      "query": {"competitionId": 123}
    }
  ],
  "existing_kg": ["colony/data/world_cup_kg.json"],
  "scout_focus": ["Brazil:lineup", "Morocco:recent_form"],
  "rescout_from_audit": ["colony/runs/scouting_kg/latest/scouting_audit.json"]
}
```

Run it with:

```bash
python3 colony/scout_to_kg.py --source-manifest scout_sources.json
```

## Source Module Catalog

`colony/scouting_matrix.py` reads reusable modules from
`colony/config/scouting_source_catalog.json`. This keeps the matrix runner
provider-neutral: adding a new module should usually mean adding a catalog entry
whose `sources` are normal `fixture`, `api`, `cli`, `mcp_stdio`, `json`, or
`url` specs.

The candidate/source map is documented in
`colony/docs/scouting-datasources.md`.

List runnable modules. The `Surface` column shows whether a module is exposed
as a dashboard plugin or kept as a CLI-only alias/debug implementation:

```bash
python3 colony/scouting_matrix.py --list-modules
```

List implemented and candidate datasources:

```bash
python3 colony/scouting_matrix.py --list-datasources
```

Run a matrix with catalog modules:

```bash
python3 colony/scouting_matrix.py \
  --from-date 2026-06-19 \
  --limit 3 \
  --module fixture \
  --module polymarket_market_context \
  --module txline_full
```

For CAMEL deep research, use:

```bash
python3 colony/scouting_matrix.py \
  --match "Brazil vs Haiti" \
  --module fixture \
  --module camel_deep_research \
  --camel-agents 6
```

Open the local HTML dashboard:

```bash
python3 colony/scouting_dashboard.py
```

Then open `http://127.0.0.1:8765` to choose a match, select plugins, launch a
run, watch logs, and inspect the generated KG categories.

Catalog source templates can use match placeholders such as `{match_name}`,
`{team1}`, `{team2}`, `{match_date}`, and `{epoch_day}`. Two-pass modules can
declare `requires_context: ["txline_fixture"]`; the matrix first resolves the
TXLINE fixture id, then renders `{txline_fixture_id}` and `{txline_start_time}`
for score/odds modules.

Modules can also declare `pipeline_flags`, for example `public_x` enables the
optional X/social search path and `camel_deep_research` enables the deeper
role-scoped CAMEL/DDGS research path. Dashboard plugins may declare `includes`
to hide implementation modules behind one user-facing choice; for example
`polymarket_market_context` expands to `polymarket_clob`, and `txline_full`
expands to the TXLINE fixture, score, and odds modules. Candidate keyword packs
such as `betting_odds`, `sports_news`, and `x_social` live in the same catalog
so search connectors can reuse them.

For the dashboard plugin “ScrapeCreators X search”, set these in `colony/.env`:

```bash
SCRAPECREATORS_API_KEY=...
SCRAPECREATORS_X_SEARCH_URL=https://api.scrapecreators.com/v1/google/search?query={query}
```

The recommended ScrapeCreators path uses their Google Search API with
`site:x.com` / `site:twitter.com` query filters, because their Twitter endpoints
are profile/tweet/community lookups rather than open keyword search. The URL can
also be a POST endpoint accepting JSON `{"query": "..."}`. Get or manage the key
from `https://app.scrapecreators.com/billing`. X/social claims enter the KG as
low-confidence `social_signal` leads unless corroborated by a stronger source.

Each source is isolated. Network/API/timeout/config failures are logged as
`source_error` events and represented in `source_summaries` with
`error_type`/`error`, while the remaining sources still build and validate a KG.

The public scout also emits `public_stage_complete` events while it runs. These
events are copied into the public source summary as `stage_metrics`, so a slow
run can be diagnosed without reading every raw log line. Typical stages include
`team_profiles`, `squad_rosters`, `match_news_search`, `team_scout_searches`,
`scrapecreators_x_search`, `x_social_claim_mapping`, and the
`*_claim_extraction` stages that fetch/parse articles. A warm-cache run can
finish in seconds; a cold `public` or `public_x` run can reasonably take 1-3
minutes because many public web/news URLs are read and normalized before the KG
is built.

## Accepted Payloads

Sources can return fully normalized findings:

```json
{
  "findings": [
    {
      "scout_name": "my_roster_scout",
      "source_type": "lineup",
      "finding_name": "roster_read",
      "confidence": 0.7,
      "evidence_claims": [
        {
          "claim_type": "squad_roster",
          "team": "Brazil",
          "player": "Neymar",
          "claim": "Neymar is listed in Brazil's squad.",
          "impact": "context_home",
          "confidence": 0.7,
          "source_title": "Example roster",
          "source_url": "https://example.test/brazil-roster",
          "source_kind": "official",
          "source_quality": "strong",
          "metrics": {"position": "Forward"}
        }
      ]
    }
  ]
}
```

They can also return raw documents:

```json
{
  "documents": [
    {
      "title": "Brazil vs Morocco team news",
      "url": "https://example.test/team-news",
      "published": "2026-06-13",
      "text": "Brazil won 4 of their last 6 matches. Neymar has 18 goals and 9 assists in 42 appearances."
    }
  ]
}
```

Search-like payloads also work:

```json
{
  "items": [
    {
      "title": "Brazil 2026 results - ESPN",
      "link": "https://example.test/results",
      "snippet": "Brazil won 4 of their last 6 matches and scored 11 goals."
    }
  ]
}
```

Plain text stdout from `cli:` is treated as one source document.

`mcp-stdio` tool results are read from the MCP `tools/call` response. If the
tool returns JSON text or structured content, the pipeline treats it as a normal
payload. Otherwise text content is treated as raw scout documents and passed
through the heuristic claim extractor.

## Generic Plugin Contract

The preferred integration contract is provider-neutral:

- MCP and CLI plugins should return normalized `findings`, `claims`, `documents`, or `items`.
- API sources can either return the same normalized payloads or use `adapter: row_claims` to map raw JSON rows into KG claims from the manifest.
- Provider-specific scripts are examples only. They are not required for the pipeline and should not be added for every new plugin.

Minimal normalized plugin output:

```json
{
  "findings": [
    {
      "scout_name": "my_plugin_scout",
      "source_type": "market",
      "finding_name": "market_snapshot",
      "evidence_claims": [
        {
          "claim_type": "market_snapshot",
          "team": "Brazil",
          "claim": "Example market says Brazil outcome is priced at 0.58.",
          "impact": "context_home",
          "source_title": "My plugin",
          "source_url": "plugin://market/123",
          "source_kind": "mcp",
          "source_quality": "strong"
        }
      ]
    }
  ]
}
```

Generic raw API mapping:

```json
{
  "kind": "api",
  "url": "https://example.test/markets/search",
  "adapter": "row_claims",
  "rows_path": "events[].markets[]",
  "row_filter": {"field": "question", "match_teams": true},
  "finding": {
    "scout_name": "example_market_api_scout",
    "source_type": "market",
    "finding_name": "example_market_snapshot"
  },
  "claim": {
    "for_each": "outcomes",
    "claim_type": "market_snapshot",
    "team": "{home_team}",
    "claim": "Market '{question}' lists outcome '{item}' at price {prices[item_index]}.",
    "source_url": "https://example.test/event/{slug}",
    "source_quality": "strong",
    "metrics": {
      "market_id": "{id}",
      "outcome": "{item}",
      "price": "{prices[item_index]}"
    }
  }
}
```

Supported `row_claims` fields:

- `rows_path` - dot path with `[]` expansion, for example `events[].markets[]`.
- `row_filter` - optional guardrail, usually `{"field": "question", "match_teams": true}`. It also supports `contains_any`, `contains_all`, and `exclude_contains_any` for noisy public-search rows.
- `finding` - finding metadata such as `scout_name`, `source_type`, and `finding_name`.
- `claim` or `claims` - one or more claim templates.
- Template variables - row fields like `{question}`, indexed list fields like `{prices[item_index]}`, plus `{home_team}`, `{away_team}`, `{item}`, `{item_index}`, and `{request_url}`.

### Polymarket Example

`polymarket/mcp_server.py` is a read-only MCP stdio server for market scouting.
It exposes `scout_match_market`, which returns normalized `market_snapshot`
claims for the KG. It does not load private keys, sign orders, or place trades.
The same data path can be tested through MCP, CLI, or direct API.

Offline local test:

```json
{
  "sources": [
    "fixture",
    {
      "kind": "mcp_stdio",
      "command": ["python3", "polymarket/mcp_server.py", "--offline"],
      "tool": "scout_match_market",
      "arguments": {
        "match": "Brazil vs Morocco",
        "home_team": "Brazil",
        "away_team": "Morocco",
        "limit": 5
      }
    }
  ]
}
```

Live read-only Gamma lookup:

```json
{
  "sources": [
    {
      "kind": "mcp_stdio",
      "command": ["python3", "polymarket/mcp_server.py"],
      "tool": "scout_match_market",
      "arguments": {
        "match": "Brazil vs Morocco",
        "home_team": "Brazil",
        "away_team": "Morocco",
        "query": "Brazil Morocco",
        "limit": 10,
        "allow_offline_fallback": true
      }
    }
  ]
}
```

The live MCP is strict: if it cannot find a market whose question directly
matches the requested teams/query, it returns zero market claims instead of
admitting unrelated high-volume Polymarket markets into the KG. Use
`colony/config/example.polymarket-mcp-source.json` for deterministic offline
testing and `colony/config/example.polymarket-mcp-live-source.json` for live
read-only Gamma lookup.

CLI source:

```json
{
  "sources": [
    "fixture",
    {
      "kind": "cli",
      "command": [
        "python3",
        "polymarket/scout_market.py",
        "--offline",
        "--match",
        "Brazil vs Morocco",
        "--home-team",
        "Brazil",
        "--away-team",
        "Morocco",
        "--limit",
        "5"
      ]
    }
  ]
}
```

Direct API source:

```json
{
  "sources": [
    "fixture",
    {
      "kind": "api",
      "url": "https://gamma-api.polymarket.com/public-search",
      "adapter": "row_claims",
      "title": "Polymarket public search",
      "query": {
        "q": "Brazil Morocco",
        "limit_per_type": 10,
        "search_profiles": false,
        "keep_closed_markets": 0
      },
      "rows_path": "events[].markets[]",
      "row_filter": {
        "field": "question",
        "match_teams": true,
        "exclude_contains_any": ["announcers", "broadcast", "sponsor", "visa"]
      },
      "max_rows": 10,
      "finding": {
        "scout_name": "polymarket_gamma_scout",
        "source_type": "market",
        "finding_name": "polymarket_market_snapshot"
      },
      "claim": {
        "for_each": "outcomes",
        "claim_type": "market_snapshot",
        "subject": "Polymarket market: {question}",
        "team": "{home_team}",
        "claim": "Polymarket market '{question}' lists outcome '{item}' at price {outcomePrices[item_index]}.",
        "source_title": "Polymarket public search",
        "source_url": "https://polymarket.com/event/{slug}",
        "source_quality": "strong",
        "metrics": {
          "token_id": "{clobTokenIds[item_index]}",
          "price": "{outcomePrices[item_index]}"
        }
      }
    }
  ]
}
```

This direct API example is still provider-neutral: `row_claims` reads rows from
the configured `rows_path`, filters them, and maps fields into claims using the
templates declared in the manifest. A different API can use the same adapter by
changing the URL, row path, filter, and claim templates.

## Authenticated API Adapters

Manifest object sources support:

- `headers` - request headers, including secrets from environment variables.
- `query` / `params` - query string parameters.
- `method` - defaults to `GET`, or `POST` when `json`/`body` is present.
- `json` / `body` - optional request body.
- `adapter` - optional structured mapper before KG normalization.

Built-in API adapters:

- `row_claims` - provider-neutral row-to-claim mapping declared entirely in the manifest.
- `txline_fixtures` - maps fixture snapshot rows into `match_schedule` and `team_profile` claims.
- `txline_odds` - maps odds snapshot rows into `market_snapshot` claims.
- `txline_scores` - maps score snapshot rows into `live_score_event` claims, or `coverage_status` when TXLINE reports scheduled/pre-match coverage rows.

### TXLINE Auth Boundary

TXLINE's World Cup free tier has two separate steps:

1. Activate API access with a Solana wallet. This one-time activation signs a
   message/transaction and returns a long-lived API token.
2. Run scouting calls with HTTP headers only.

Do not put a Solana private key in a scouting manifest, KG run artifact, or
source adapter. The scouting pipeline only needs:

```bash
export TXLINE_JWT="guest-session-jwt"
export TXLINE_API_TOKEN="txoracle_api_..."
```

The TXLINE fixture, odds, and score endpoints currently require both headers:

```json
{
  "Authorization": "Bearer ${TXLINE_JWT}",
  "X-Api-Token": "${TXLINE_API_TOKEN}"
}
```

Example TXLINE fixtures manifest:

```json
{
  "sources": [
    "fixture",
    {
      "kind": "api",
      "url": "https://txline.txodds.com/api/fixtures/snapshot",
      "adapter": "txline_fixtures",
      "title": "TXLINE World Cup fixtures",
      "headers": {
        "Authorization": "Bearer ${TXLINE_JWT}",
        "X-Api-Token": "${TXLINE_API_TOKEN}"
      },
      "query": {
        "startEpochDay": 20617
      }
    }
  ]
}
```

`startEpochDay` is the UTC epoch-day integer. TXLINE defaults fixture snapshots
to the current UTC day, so historical or future match scouting should set it
explicitly. For Brazil vs Morocco on 2026-06-13, `startEpochDay` is `20617`.

Example TXLINE odds manifest, after you know the TXLINE `fixtureId`:

```json
{
  "sources": [
    {
      "kind": "api",
      "url": "https://txline.txodds.com/api/odds/snapshot/987654",
      "adapter": "txline_odds",
      "title": "TXLINE odds snapshot",
      "headers": {
        "Authorization": "Bearer ${TXLINE_JWT}",
        "X-Api-Token": "${TXLINE_API_TOKEN}"
      },
      "max_rows": 20
    }
  ]
}
```

For historical odds, set `asOf` because TXLINE's odds snapshot endpoint returns
only the current live 5-minute snapshot when `asOf` is omitted:

```bash
export TXLINE_FIXTURE_ID="17588386"
export TXLINE_AS_OF="1781388240000"
```

Then run `colony/config/example.txline-odds-historical-api-source.json`.

## KG Admission Rules

Claims are admitted into `evidence_claim` nodes only when they have:

- `claim_type`
- `claim`
- `source_url` or `source_title`
- `impact` that is not `unknown`
- `source_quality` that is not `weak`
- non-weak search aggregate provenance

Required scouting topics are:

- `team_profile`
- `recent_form`
- `player_form`
- `squad_roster`
- `injury_availability`
- `lineup`
- `match_history`
- `tactical`

The run may be `kg_load_ready` while still showing a `scouting_backlog`. That is expected: the KG can be structurally valid while agents still need better/fresher evidence for some topics.

## Focused Re-Scouting

Use a previous run's backlog to drive the next public scout pass:

```bash
python3 colony/scout_to_kg.py \
  --mode deep \
  --match "Brazil vs Morocco" \
  --rescout-from-audit colony/runs/scouting_kg/<run>/scouting_audit.json
```

Or target one gap directly:

```bash
python3 colony/scout_to_kg.py \
  --mode deep \
  --match "Brazil vs Morocco" \
  --scout-focus "Morocco:lineup"
```

Focused targets are passed into the public scout, which runs targeted search
queries and only writes admissible sourced claims into the KG. Empty focus
results stay visible as backlog instead of being filled with placeholders.

## Examples

Fast fixture-only KG:

```bash
python3 colony/scout_to_kg.py --mode fast --match "Brazil vs Morocco"
```

Public scouting plus existing KG enrichment:

```bash
python3 colony/scout_to_kg.py \
  --mode deep \
  --match "Brazil vs Morocco" \
  --existing-kg colony/data/world_cup_kg.json
```

Plug a raw URL:

```bash
python3 colony/scout_to_kg.py \
  --match "Brazil vs Morocco" \
  --source fixture \
  --source url:https://example.test/brazil-morocco-preview
```

Plug a CLI scout:

```bash
python3 colony/scout_to_kg.py \
  --match "Brazil vs Morocco" \
  --source fixture \
  --source "cli:python3 my_scout.py --match 'Brazil vs Morocco'"
```

Plug a live MCP stdio tool:

```json
{
  "sources": [
    {
      "kind": "mcp_stdio",
      "command": ["python3", "my_mcp_server.py"],
      "tool": "scout_match",
      "arguments": {"match": "Brazil vs Morocco"}
    }
  ]
}
```

```bash
python3 colony/scout_to_kg.py --source-manifest scout_sources.json
```

Force fresh public web/news fetches:

```bash
python3 colony/scout_to_kg.py \
  --mode deep \
  --match "Brazil vs Morocco" \
  --refresh-data
```
