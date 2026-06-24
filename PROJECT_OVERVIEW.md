# WorldColony — Project Overview (2026-06-24)

*The single front-door summary of the whole project: what it is, how the pieces fit, what's
actually built, and the links anyone can verify. WorldColony is now treated as a long-term agent
society project, not a hackathon-only demo. Honesty markers: ✅ built/working · 🟡 partial or
built-but-blocked · 📝 narrated/planned. Don't claim 🟡/📝 as done.*

## What it is
**WorldColony** is an evolutionary ecosystem of forecasting agent "ants" that **survive or fail by
the quality of their World Cup decisions and risk sizing.** Each ant has a persona, a heritable
genome, an identity record, memory, reputation, and a scarce bankroll. The current Survival Thesis
V1 strategy asks ants to read reliable match context, form a qualitative thesis, choose a team or
draw, size the risk (`micro`, `small`, `medium`, or `high`), debate, revise, and learn after the
match resolves.

The important shift: this is no longer "many agents wrapped around one probability equation." A
`stats_purist`, `form_hunter`, `tactical_scout`, `market_reader`, and `contrarian_risk` should be
able to look at the same match and defend different decisions for legible reasons. Market data can
be one signal, but not the whole product.

On-chain rails, Polymarket experiments, Arc settlement, x402, ENS, and World ID remain valuable
integrations. The default colony economy now uses fake credits first so the society can become
coherent before real capital is attached by default.

**The headline long-term question:** over many matches, which agent personalities and lineages
survive: cautious stats readers, form hunters, tactical scouts, market readers, contrarians, or
human-verified founders?

## The core loop
```
Birth → Reliable match context → Persona thesis → Pick + risk read → Sized fake-credit stake
→ Debate + revision → Match resolves → Settle bankroll/reputation
→ survive & reproduce (mutate genome, mint child identity)  |  or die
```

## Architecture — three planes + execution
- **Identity plane (ENS).** `worldcolony.eth` on Ethereum mainnet ✅; 200 per-agent subnames
  `root-*.colonny.eth` on Sepolia ENSv2 ✅. Offchain CCIP-Read resolver 📝 (planned).
- **Economic plane (fake credits first, Arc + Circle as rails).** The active society loop uses
  fake credits for survival pressure ✅. Real ant-to-ant **x402** payments via Circle Gateway
  (EIP-3009 sign → 402 → pay → 200) exist as an integration rail ✅; a
  **`ColonyForecastMarket`** betting contract is deployed to Arc testnet (`0xc40a8f2e…ada87`) for
  optional on-chain settlement experiments ✅. Buyer-side x402 from Dynamic MPC wallets is the open
  seam 🟡 (Circle GatewayClient needs an EOA key; MPC wallets have none).
- **Knowledge plane (ClickHouse).** ~2.84M Polymarket markets + an odds time-series + UMA
  Optimistic-Oracle events, fronted by **`clickhouse_api`** (FastAPI) that enforces a real
  **timestamp gate** (`ts <= as_of`, enforced in SQL *and* re-checked per row, with a leak test)
  ✅ and meters access with an x402 handshake (verifier currently stubbed → real settlement is
  the next step 🟡). World-ID-verified lineages get a discounted/premium tier ✅.
- **Execution.** Real Polymarket bets placed through **PolyGun** (a Telegram trading bot) driven
  by a Telethon userbot we wrote — the geoblock workaround, since the direct Polymarket CLOB
  returns **HTTP 403 in the US**. Positions land as real ConditionalToken (ERC-1155) outcomes on
  **Polygon**; **7 real trades** logged in `predictions.json` and verified on-chain ✅. The direct
  `py-clob-client` path is also built (works up to the geoblock) 🟡.

## Sponsor integrations
| Track | Status | What's real |
|---|---|---|
| **ENS** | ✅ | `worldcolony.eth` (mainnet) → trades wallet, with text records + Polygon multichain address; 200 `root-*.colonny.eth` subnames on Sepolia. CCIP-Read offchain resolver 📝 next. |
| **Worldcoin / World ID** | ✅ | AgentKit proof-of-personhood at lineage roots; **one human = one humanId across wallets, proven live**; 5 agent wallets verified on World Chain. Verified lineages get bankroll + premium-data privileges. |
| **ClickHouse** | ✅ | Metered knowledge plane: ~2.84M markets + odds time-series + UMA events, via `clickhouse_api` with the timestamp gate + x402 metering. |
| **Polygon** | ✅ | All Polymarket trades + ConditionalTokens settle on Polygon; ENS Polygon multichain record. |
| **Polymarket / UMA** | ✅ | Real markets (CLOB + Gamma); UMA Optimistic-Oracle resolution events ingested + studied (Propose→Settle = the arbitrage window). |
| **Dynamic** | ✅ | Wallet provider for the 200 agent "ant" wallets (V3 MPC/WaaS). |
| **Circle / Arc** | 🟡📝 | x402 `402→pay→query` pattern + real Gateway transfers ✅; deployed betting contract ✅; full Arc-native settlement still partial/narrated — verify before claiming on the Arc track. |

## Subsystem status (by folder)
- **`colony/` + `colony_api/`** ✅ — the Python "brain": Survival Thesis judgments, persona-driven
  debate, team-labeled commitments, fake-credit stake sizing, society decision, memory, and
  FastAPI/SSE backend. Multi-round settlement/evolution, ENS registration (Sepolia), and Worldcoin
  agent registration are present as rails. `colony_api` is deployed on Railway
  (`https://ethglobalnyc-production.up.railway.app`). Explicit per-round "death" is still a stub.
- **`clickhouse_api/`** ✅🟡 — FastAPI gate + metering; timestamp gate tested with a leak test;
  x402 verifier stubbed (accepts any payment header) pending real Arc settlement verification.
- **`arc/`** ✅🟡 — real x402 Circle Gateway services + pay client + treasury funding +
  ledger→transfers mirror + the forecast-market CLI; smoke-tested with real Gateway transfer UUIDs.
- **`polymarket/` + `polygun/`** ✅ — direct CLOB stack (built, US-geoblocked) and the
  PolyGun/Telethon userbot that placed the 7 real trades. `predictions.json` is the on-chain ledger.
- **`dynamic/`** ✅ — bulk MPC wallet creation (200 ant wallets); proven Arc signing + cross-product
  route (treasury → Dynamic MPC → Unlink private).
- **`worldcoin/` / `ens/`** — these top-level folders are now mostly exploration/scaffolding; the
  shipping flows live inside `colony/` (`register_world_agent.py`, `register_ens_identities.py`).
- **`unlink/`** ✅ (exploration) — 1 USDC private transfer proven on Arc testnet; candidate privacy
  layer for ant-to-ant stakes, not on the core demo path.
- **`frontend/`** ✅ — Vite + React + Three.js / react-three-fiber 3D dashboard at
  `worldcolony.nyc`; replays the colony's JSONL event stream (the colony↔frontend contract).

## Live URLs & verifiable artifacts
- **Product preview:** https://worldcolony.nyc
- **API:** https://ethglobalnyc-production.up.railway.app
- **Repo:** https://github.com/Vainglorious/ethglobalnyc (monorepo)
- **ENS:** `worldcolony.eth` (mainnet) → trades wallet `0xe9E32Ca24aa1eF725F650b5489281FE621363AA9`
- **Trades:** `predictions.json` (7 real PolyGun trades, tx hashes + blocks); counterfactuals in
  `simulatedtransactions.json`. Visible on Polygonscan at the trades wallet.
- **Worldcoin:** 5 verified ant wallets (humanId `0x41e49b…608f0`) on World Chain AgentBook.
- **Arc:** `ColonyForecastMarket` at `0xc40a8f2e29fe061cd4c0fe92cc73b9b43f9ada87` (Arc testnet).
- **Knowledge plane:** `clickhouse_api/` + `clickhouse/DATA_CATALOG.md`.
- **Agent identities:** 200 `root-*.colonny.eth` on Sepolia;
  `colony/data/agent-wallets.dynamic.200.public.json` (public addresses only).

## Known seams / next steps
- **x402 buyer-side from Dynamic MPC wallets** — needs a Dynamic-backed signer path, not
  `GatewayClient({privateKey})`. Local-EOA ants already pay for real.
- **clickhouse_api x402 verifier** — replace the stub with real Arc settlement verification;
  persist nonces + per-resource usage.
- **ENS offchain CCIP-Read resolver** — the gasless per-ant resolver is still the planned upgrade
  over the current published subnames.
- **Explicit agent death / culling** — evolution replaces weak agents offline; a per-round death
  event isn't wired yet.

## Tech stack
Python · TypeScript · JavaScript · FastAPI · React + Vite · Three.js / react-three-fiber ·
ClickHouse · web3.py · py-clob-client · Dynamic · ENS · World ID / Worldcoin AgentKit ·
Polymarket (CLOB + Gamma) · PolyGun · Telethon · x402 · UMA Optimistic Oracle · Railway · Vercel.
**No custom Solidity beyond the integrated `ColonyForecastMarket` contract; existing protocols
were integrated, not re-implemented.**

*Secrets note: all private keys, mnemonics, API keys, and passwords live in gitignored `.env`
files (and `polygun/pg.session`) per folder — none are reproduced here. Every address/URL above is
public and meant to be judge-verifiable.*
