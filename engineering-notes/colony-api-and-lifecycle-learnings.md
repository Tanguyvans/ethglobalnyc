# Colony API & Lifecycle — Settlement, Evolution, Identity (2026-06-14)

*Beyond the single-round forecasting brain: the colony now has a deployed API and the full
multi-round lifecycle (settle → evolve → register identity) wired. Engineering record
(paths `colony/`, `colony_api/`). Supersedes the "stubbed" notes in the earlier Colony Harness doc.*

## colony_api — FastAPI backend, DEPLOYED on Railway
- **Prod:** `https://ethglobalnyc-production.up.railway.app` · `colony_api/main.py` (~2,350 lines).
- Wraps the harness as managed background processes; the frontend starts real runs and **streams
  status/events over SSE**, then loads the JSONL artifacts. ~33 endpoints, grouped:
  - **Health/config:** `/health`, `/config`
  - **Runs:** `POST /runs/demo`, `GET /runs`, `GET /runs/{id}/events`, `GET /runs/{id}/stream` (SSE)
  - **Scouting:** `POST /scouting/run` (public-data KG + scouts), `GET /runs/{id}/kg`, `/kg/manifest`
  - **Agents:** `GET /ants`, `POST /ants/reproduce`, `POST /ants/{id}/kill`, `GET /ants/{id}/avatar.svg`
  - **Forecast (Arc):** `POST /forecast/demo-setup`, `POST /forecast/settle`, `POST /forecast/market`, `GET /forecast/games`
  - **x402:** `POST /x402/demo-payment`, `GET /x402/config`
- **Demo defaults:** 200 agents, 12 debate rooms, seed 205, Dynamic wallet provider, LLM voice.
  Wallet store `colony/data/agent-wallets.dynamic.200.public.json` (public addresses only).

## Settlement — WIRED
`settle_population.py` reads forecast artifacts, updates each agent's **accuracy via Brier
scoring**, and adjusts **bankrolls** per match result (`--winner home|away`, `--accuracy-alpha`
default 0.2, `--payout-multiple`). Emits a settled population state + settlement summary.

## Evolution — WIRED
`evolve_population.py` scores agents from recent `conversation_memory.json`
(fitness = memory_score×1.8 + bankroll×0.4 + accuracy×0.8), keeps the top `--survival-rate`
(default 55%), and replaces weaker slots with **mutated children** — recording genealogy
(`parent_genome_id`, `previous_genome_id`, evolution role survivor/child). Agent state
(`bankroll`, `accuracy`, `generation`, `parent_agent_id`, `lineage_id`) persists across matches
via `population_state.json`.

## Identity registration — WIRED
- `register_ens_identities.py` — publishes **ENS v2 + classic** resolver records on **Sepolia**
  (dry-run default): per-ant subname + ENSIP-26 text records (`agent-context`, `agent-endpoint`,
  `com.colony.*`, parent/lineage/profile URL). Idempotent.
- `register_world_agent.py` — wraps `@worldcoin/agentkit-cli register`: interactive World ID QR
  flow per agent, stores tx/nullifier receipts.
- `deploy_agents.py` — orchestrator: generate wallets → identity JSON → Worldcoin batch →
  re-tag `world_access_tier=premium_world` → optionally publish ENS (`--ens-broadcast`). Dry-run
  by default; supports local **and** Dynamic WaaS wallets.
- `cleanup_ens_identities.py` — marks deployments inactive / clears resolver records (dry-run default).

## Analysis tooling
- `analyze_memory.py` — aggregates `conversation_memory.json` into debater usefulness scores +
  genome performance trends (the input signal for evolution).
- `export_scouting_kg.py` — validates `world_graph.json` + `kg_manifest.json`, reports entity/
  relationship counts, flags duplicate evidence, emits an ingestion bundle.

## Still not wired
- **Explicit per-round agent death/culling event** — evolution replaces weak agents offline, but
  there's no live death event yet (`POST /ants/{id}/kill` exists at the API level).
- **Automatic on-chain settlement reveal/claim** — sealed bets are computed locally; claiming from
  the Arc contract is still a manual call.
- **Real bookmaker odds feed** — odds remain a low-confidence stub in the KG.
