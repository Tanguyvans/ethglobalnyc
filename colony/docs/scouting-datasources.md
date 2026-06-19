# Scouting Datasources

This is the working shortlist for KG scouting sources. The executable source
modules live in `colony/config/scouting_source_catalog.json`; this document is
the human-readable map of what each source should contribute.

## Implemented Now

| Source | Access | Useful KG Claims | Notes |
| --- | --- | --- | --- |
| OpenFootball World Cup | bundled JSON/dataset | `match_schedule`, `team_profile` | Good base schedule and country/team layer. Not a scouting source by itself. |
| Existing KG | local JSON | prior `context`, prior claims/entities | Lets a run reuse older graph context or merge entities from a previous KG. |
| Public web/news scout | `public`, `url`, cached web/search | `recent_form`, `player_form`, `squad_roster`, `injury_availability`, `lineup`, `match_history`, `tactical` | Highest coverage, highest noise. Prefer official federation, competition, league, or reputable news URLs. |
| Polymarket market context | API, CLI, MCP stdio | `market_snapshot`, `market_price`, `market_liquidity` | Dashboard plugin: `polymarket_market_context`. It expands to Gamma discovery plus public CLOB midpoint/spread/orderbook enrichment. Keep it as market context, not player/tactical scouting. |
| TXLINE match feed | authenticated API | `match_schedule`, `team_profile`, `market_snapshot`, `coverage_status`, `live_score_event` | Dashboard plugin: `txline_full`. Best tested live World Cup backbone. Wallet activation stays outside KG/scouting; runs only need HTTP tokens. |
| Wikidata | no-key Action API + SPARQL | `team_profile`, `player_profile` | Entity/profile resolver for teams and players. Action API gives resilient team profiles; SPARQL can enrich linked players when WDQS is available. Not a live roster, injury, or lineup source. |
| ScrapeCreators X search | external API/search connector | `social_signal`, `injury_availability`, `lineup` leads | Dashboard plugin: `public_x` / “ScrapeCreators X search”. Get an API key at `https://app.scrapecreators.com/billing`, then set `SCRAPECREATORS_API_KEY` and `SCRAPECREATORS_X_SEARCH_URL=https://api.scrapecreators.com/v1/google/search?query={query}`. It uses Google Search filtered to `x.com`/`twitter.com`; do not scrape X directly from the runner. `public_x` includes the normal public scout, so cold runs may still take 1-3 minutes; use `stage_metrics` to see whether time went to web/news, ScrapeCreators, CAMEL, or claim extraction. |
| CAMEL deep research | DDGS/news/CAMEL native agents when enabled, fallback search otherwise | `recent_form`, `player_form`, `key_players`, `squad_roster`, `injury_availability`, `injury_return`, `lineup`, `match_history`, `coach_form`, `player_ratings`, `attacking_profile`, `defensive_profile`, `tactical`, `social_signal` | Dashboard plugin: `camel_deep_research`. Runs role-scoped research agents, asks CAMEL/OpenRouter for source-grounded structured claims when native mode is enabled, then applies the local critic before KG ingestion. |

## Dashboard Plugins

The dashboard hides low-level aliases and implementation modules so the run
picker stays readable. These are the user-facing plugins:

| Plugin | Expands To | Use |
| --- | --- | --- |
| `fixture` | `fixture` | Base match schedule/team profile. |
| `polymarket_market_context` | `polymarket_clob` | Market probability, price, spread, orderbook/liquidity context. |
| `public` | `public` | Broad public web scouting. |
| `camel_deep_research` | `camel_deep_research` | Deeper role-based scouting for missing sports intelligence. |
| `wikidata_profiles` | `wikidata_profiles` | Team/player identity enrichment. |
| `public_x` | `public` + ScrapeCreators X connector flags | Low-confidence social/injury/lineup leads when ScrapeCreators is configured. |
| `txline_full` | `txline_fixture`, `txline_scores`, `txline_odds_historical` | TXLINE fixture, score/status, and odds snapshots. |
| `existing_kg` | `existing_kg` | Reuse prior KG context. |

CLI-only compatibility modules remain available for targeted debugging:
`polymarket_api`, `polymarket_gamma`, `polymarket_clob`, `public_camel`,
`txline_fixture`, `txline_scores`, `txline_odds_historical`, and
`deep_fixture`.

## Candidate Sources To Add

| Source | Access | Best Use | Adapter Shape |
| --- | --- | --- | --- |
| The Odds API | authenticated API | multi-bookmaker odds, live/upcoming events, scores, historical odds | Small `the_odds_api` adapter is better than pure `row_claims` because payloads are nested event -> bookmaker -> market -> outcome. |
| Betfair Exchange API | authenticated API | exchange back/lay prices, liquidity, in-play market movement | Provider adapter mapping market catalogue + runners into `market_snapshot` and `liquidity_signal`. |
| Pinnacle API | authenticated API | sharp-book prices, line movement, betting limits if available | Provider adapter or API manifest after access is verified. |
| OddsJam API | authenticated API | aggregated odds, consensus, movement, bookmaker comparison | Provider adapter for `market_consensus`, `line_movement`, and `market_snapshot`. |
| StatsBomb Open Data | open JSON dataset | historical event data, lineups, player profiles, tactical context | `json`/`api` source that maps matches, lineups, and events into `player_form`, `lineup`, `tactical`, `match_history`. |
| Sportmonks Football API | authenticated API | fixtures, livescores, teams, players, standings, odds | Start with `row_claims` manifests; add provider adapters once payloads are stable. |
| API-FOOTBALL | authenticated API | fixtures, teams, players, standings, player stats, odds | Same pattern as Sportmonks: first manifests, then structured adapters for high-value endpoints. |
| TheSportsDB | JSON API | media/team/player enrichment, event metadata | Good context/display enrichment; weaker for fresh scouting unless endpoint coverage fits. |
| Open-Meteo | unauthenticated API | venue weather context | Low priority. Only useful after venue coordinates exist and core player/lineup/injury/market modules are already working. |

## Priority Read

Core sources are the ones we should keep testing in regular matrix suites:
fixtures, existing KG, TXLINE, Polymarket, and public web/news scouting. The
dashboard defaults stay intentionally light (`fixture` +
`polymarket_market_context`) so a quick local run is fast; broader quality runs
should add public, CAMEL, Wikidata, TXLINE, and existing KG as needed.
High-priority next integrations are X/social as low-confidence leads, and
betting/odds APIs that add market consensus or line movement. Medium-priority
sources enrich entity linking and historical analytics. Low-priority sources
such as Open-Meteo and display/media metadata should not distract from missing
player, lineup, injury, tactical, and odds movement evidence.

External source failures are isolated per source. A rate-limited API should
produce a `source_error` log and a zero-claim source summary, not abort the
whole KG run.

Performance diagnostics are part of the source contract. Public-scout runs emit
`public_stage_complete` events and store them as `stage_metrics` in
`source_summaries`; inspect those before assuming ScrapeCreators or another
single plugin is slow. In practice, ScrapeCreators search is usually only one
stage inside a broader `public_x` run.

## Integration Rule

Add a provider in this order:

1. Add a catalog datasource entry with `status: "candidate"` or `"implemented"`.
2. If the source can be expressed declaratively, add a module using `adapter: "row_claims"`.
3. If it needs provider-specific normalization, add a small adapter in the scouting pipeline.
4. Verify with `scouting_matrix.py` across several matches and inspect `findings.json`, `world_graph.json`, and `scouting_audit.json`.

Do not add private keys or wallet secrets to manifests. Use environment
variables for API tokens and keep wallet-signing helpers outside the KG run.

## Keyword Search Packs

The catalog now has `keyword_packs` for repeatable search intent:

- `betting_odds`: odds, bookmaker, line movement, implied probability queries.
- `sports_news`: team news, injuries, lineups, squad context.
- `x_social`: X/social search strings for lineup and injury leads.
- `official_sources`: constrained searches against official sources.

These should feed a search connector or the public scout. Treat social/search
hits as leads until another source confirms them. A rumor from X can enter the
KG as `social_signal`; it should become `injury_availability` or `lineup` only
when the extractor has a named source and enough confidence.

## Betting/Scraping Boundary

Prefer official APIs and aggregators first: TXLINE, Polymarket, The Odds API,
Betfair, OddsJam, Sportmonks, API-FOOTBALL. Direct HTML scraping of betting
sites is brittle and may violate terms or geography restrictions. If we need a
scraper, wire it as `api`, `cli`, or `mcp_stdio` behind a connector that returns
normalized `findings`, `documents`, or `items`; the KG runner should not contain
site-specific scraping logic.
