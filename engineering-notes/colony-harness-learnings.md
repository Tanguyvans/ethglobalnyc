# Colony Harness — The Forecasting Brain (2026-06-13)

*The Python engine that spawns genome-based predictor "ants," runs a bounded debate, and emits
the forecast stream the frontend replays. Engineering record (path `colony/`).*

## One line
A lightweight, MiroFish-inspired (but independent) **agent-colony debate engine** for World Cup
match forecasting. It spawns many genome-based predictor ants, gives each a private genome and an
access-filtered view of the evidence, runs a bounded multi-room debate, then has every predictor
forecast and produce a **sealed bet commitment**. This is the "forecasting **is** the labor" half
of the thesis.

## Core loop
```
match context
  → predictor genomes (cheap, parametric, reproducible)
  → access-filtered knowledge views
  → bounded debate (rooms → room syntheses → final chamber)
  → herd-adjusted forecasts
  → sealed bet commitments
```
**Design philosophy:** NOT a full LLM call per agent. Decisions are a cheap deterministic function
of `genome + visible findings`, so tens of agents × many rounds stays fast and reproducible. LLMs
are **optional flavor** (genomes = scale + reproducibility; CAMEL scouts = optional tool-using
research; voice = deterministic templates by default).

## Tech stack
Python 3, **core uses only the standard library — runs with no API keys.** Optional: CAMEL AI
(research scout), ddgs/DuckDuckGo (web search), OpenAI-compatible LLM voice
(OpenRouter `deepseek/deepseek-v4-flash` / MiniMax / generic), X/social via ScrapeCreators.

## Package map (`colony_harness/`)
- **models.py** — frozen dataclasses: `Finding` (the universal evidence unit), `WorldGraph`,
  `MatchContext`, `KnowledgeView`, `DebateClaim`, `DebateRoom`, `Forecast`, `BetCommitment`
  (sha256 commit), `RoundResult`.
- **genes.py** — `Genome` (frozen): estimator (poisson|llm), `risk_appetite` (0.02–0.18),
  `edge_threshold` (0.01–0.18), `source_weights {stats,odds,news,debate}`, `herd_bias` (−1..+1),
  `query_budget` (0.1–2.0), persona. Only `genome_hash` is public; plaintext revealed on death.
- **agent.py** — `AntAgent`: baseline probability = weighted blend of visible signals + debate ×
  market; `listen()` adjusts by consensus × herd_bias; `forecast()` always chooses one market
  outcome (`home`, `draw`, or `away`) and records conviction/edge; `commit_bet()` =
  sha256(agent_id | round_id | side | stake | salt).
- **knowledge.py** — access policy by `query_budget`: `<0.75 public | 0.75–1.5 shared | ≥1.5
  private`. **This is the seam for future x402 payment / Worldcoin privilege gating.**
- **scouts.py** — mock findings for offline testing. **live_scouts.py** — real lightweight
  public-data scouts (Wikipedia, Google News RSS, DuckDuckGo, squad/XI, injuries) → normalized
  `Finding`s; optional CAMEL + X/social.
- **world_graph.py / tournament_graph.py** — round subgraph + the World Cup 2026 KG from
  OpenFootball (tournament + stages + venues + 100+ matches).
- **debate.py / voice.py / artifacts.py / harness.py** — debate feed + consensus, voice models
  (Template default, OpenRouter/MiniMax/OpenAI), compact artifact writing (**no raw prompts/
  responses/secrets**), and `ColonyHarness` orchestration (spawn → select debaters → room debates
  → final chamber → forecast → commit → world graph).

## Run artifacts (one round writes)
`colony/runs/<ts>_<round_id>/`: `summary.md`, `debate.md`, `rooms.json`, `forecasts.csv`,
`findings.json`, `knowledge_views.json`, `world_graph.json`, and **`events.compact.jsonl`** —
the streaming event family **the frontend consumes**. (`--debug` adds `debug.md`.)

## State of completeness
**Complete:** predictor loop (genomes, edge/threshold conviction, mandatory three-way choice for
group-stage markets), two-layer debate, KG assembly + access-tier filtering, tournament KG builder,
compact logging, template + LLM voice, public-data scouts, internal settlement accounting, sealed
bet commitments, and the Arc/x402 smoke paths.
**Stubbed / planned:** reproduction/death/mutation across epochs, multi-round persistence,
automatic x402-gated ClickHouse purchases in the harness loop, Dynamic MPC buyer-side x402 signing,
real odds API, real match oracle/UMA, **and the replay clock + strict timestamp gating** (the
lookahead-leak guard the plan calls the cardinal rule) — not built here yet.

## 2026-06-14 France/Senegal correction

The economy-layer bug was that `pass` leaked into the ant side model. That made weak-edge ants
look like they abstained, which broke the project rule that each ant must make its own choice.
`Side` is now only `home | draw | away`; unresolved match settlement uses a separate `pending`
result state.

Latest deterministic KG run:

```text
colony/runs/20260614_002031_roundworld_cup_20260492026_06_16_france_senegal

Opinion distribution:
France/home: 19
Draw: 95
Senegal/away: 86

Bet distribution:
France/home: 19
Draw: 112
Senegal/away: 69
Participation: 200/200
```

This is healthy as a pipeline/debug distribution because it proves the 200 ants no longer collapse
to one side and no longer emit `pass`. It is not yet calibrated as a serious football model:
France probably should not be only 9.5% in a real prior against Senegal. The next calibration task
is to tune synthetic/live priors toward a more realistic France-favored baseline, then let debate
and paid data move the distribution.

## Design notes to remember
- **Genomes, not LLMs, are the substrate** — keeps evolution chartable (a trait sweeps because it
  changes a *number*, not a prompt) and runs cheap/reproducible.
- Access tiers (public/shared/private) are the prototype of the premium data layer; `query_budget`
  stands in for future x402 spend / Worldcoin tier.
- Speech is scarce but interaction scales: rooms → reps → final chamber gives a 100-agent colony
  readable logs.
- **`events.compact.jsonl` is the contract with the frontend** — keep it aligned with the
  frontend's `src/data/schema.ts`.

## Next steps
1. Real datasource adapters emitting `Finding`s (incl. ClickHouse/x402).
2. Settlement + bankroll updates from revealed bets.
3. Reproduction / death / mutation across epochs (the actual evolution).
4. Multi-round persistence + replay clock with strict timestamp gating.
5. Wire ENS / Worldcoin / Arc planes around the now-stable core loop.
