# WorldColony — ETHGlobal NY 2026 Submission (FILLED, copy-paste ready)

> Filled from the actual repo + everything built during the hack. Each section is
> copy-paste ready. **Honesty markers:** ✅ = fully built/working, 🟡 = partial/
> built-but-blocked, 📝 = narrated/planned. Don't claim 🟡/📝 as done to judges.
> Pick the framing you want — the simpler "dashboard" story (your original draft)
> is a subset of this; this version reflects the full system.

---

## Project basics

- **Project name:** WorldColony
- **Category:** Data/Analytics (also fits: AI/Agents, DeFi/Prediction Markets)
- **Emoji:** 🐜  (alt: 🌎 / ⚽)
- **Demo link:** https://worldcolony.nyc
- **GitHub:** https://github.com/Vainglorious/ethglobalnyc  (Monorepo)

---

## Short description  (form max 100 chars)

**Use this (84 chars):**
```
A colony of forecasting agent "ants" placing real World Cup prediction-market trades.
```
Alternates:
- `Evolutionary agent colony that bets real money on the World Cup, gated by World ID.` (82)
- `World Cup forecasting swarm: agent ants make real Polymarket trades.` (67)

---

## Full description  (form min 280 chars)

```
WorldColony is an evolutionary ecosystem of forecasting agent "ants" that earn or
die by the quality of their World Cup predictions. Each ant has a heritable genome,
its own wallet, and an ENS identity; human-verified lineages (World ID) are born
with privileges. Ants debate in rooms, reach a consensus, and place REAL
prediction-market trades on Polymarket — executed via PolyGun because Polymarket's
order book geoblocks the US. Thinking literally costs money: ants pay (an x402-style
402→pay→query handshake) to query a ~1TB ClickHouse corpus of prediction-market odds
history and UMA resolution events, behind a strict replay timestamp gate so the
backtest can never see the future. A 3D dashboard renders the swarm, and the ENS
name worldcolony.eth (Ethereum mainnet) resolves to the live trades wallet so anyone
can independently verify the colony is tied to real on-chain market activity — not a
mockup. Verified-human lineages get a bigger bankroll and a premium data tier,
turning the demo into a live question: do privileged human-backed ants out-survive
lean anonymous ones?
```

---

## How it's made  (form min 280 chars)

```
The colony core is a Python harness: each ant has a genome (risk appetite, edge
threshold, source weights, query budget), debates in bounded rooms, makes a cheap
parametric forecast, and commits a sealed bet. 200 agents are generated with Dynamic
wallets and ENS subnames (root-*.colonny.eth, published on Sepolia ENSv2).

Identity & privilege: Worldcoin World ID via AgentKit verifies lineage ROOTS on
World Chain — one human = one humanId across all their wallets (proven live; 5 ants
registered). Verified lineages unlock a bigger birth bankroll + a premium data tier.

Knowledge plane: a FastAPI service (clickhouse_api) fronts ClickHouse (~2.84M
Polymarket markets, an odds time-series, and UMA Optimistic-Oracle events). It
enforces a real replay TIMESTAMP GATE (queries only return rows <= as_of, re-checked
per row, with a leak test) and meters access with an x402 402→pay→200 handshake;
World-ID-verified lineages get a discounted/premium tier.

Execution: real Polymarket bets are placed through PolyGun (a Telegram trading bot)
driven by a Telethon userbot we wrote — this is the geoblock workaround, since the
direct Polymarket CLOB returns HTTP 403 in the US. Positions land as real
ConditionalToken (ERC-1155) outcomes on Polygon; 7 real trades are logged in
predictions.json and verified on-chain. We also built the direct py-clob-client path
(works up to the geoblock).

Frontend & API: colony_api (FastAPI, on Railway) streams runs/agents/KG/scouting over
SSE to a Vite + React + Three.js / react-three-fiber 3D dashboard (worldcolony.nyc).

The hacky parts: (1) PolyGun-as-geoblock-bypass to actually trade from the US;
(2) ENS as a verification + narrative layer — resolve worldcolony.eth → the trades
wallet → Polygonscan; (3) x402 + a timestamp gate so agent "thinking" costs USDC and
the replay stays honest.
```

---

## Sponsor / track integrations  (use these to pick prize tracks)

- **ENS** ✅ — `worldcolony.eth` (mainnet) resolves to the live trades wallet
  `0xe9E3…3AA9`, with text records (url=worldcolony.nyc, description, notice→Polygonscan,
  com.github) + a Polygon multichain address record. Plus 200 per-agent subnames
  `root-*.colonny.eth` on Sepolia ENSv2 (each ant has its own ENS identity).
  📝 offchain CCIP-Read resolver is the planned next step.
- **Worldcoin / World ID** ✅ — AgentKit proof-of-personhood at lineage roots; one
  human = one humanId across wallets (proven live). 5 agent wallets verified on World
  Chain; verified lineages get bankroll + premium-data privileges.
- **Circle / Arc** 🟡📝 — USDC is the economic unit; agents hold wallets; the
  clickhouse_api implements the x402 "402 → pay → query" metering pattern. (Arc-testnet
  settlement is narrated/partial — verify before claiming on the Arc track.)
- **Polygon** ✅ — all Polymarket trades + ConditionalTokens settle on Polygon; ENS
  Polygon multichain address record.
- **ClickHouse** ✅ — the metered knowledge plane: ~2.84M markets + odds time-series +
  UMA events, queried via clickhouse_api with the timestamp gate + x402 metering.
- **Polymarket / UMA** ✅ — real markets (CLOB + Gamma); UMA Optimistic-Oracle
  resolution events ingested + studied (Propose→Settle = the arbitrage window).
- **Dynamic** ✅ — wallet provider for the 200 agent "ant" wallets.

---

## Tech stack form fields  (ACCURATE — replace the generic defaults)

- **Programming languages:** Python, TypeScript, JavaScript, HTML, CSS.
  (No custom Solidity was written — we integrated existing protocol contracts; don't
  select Solidity unless a `.sol` is added.)
- **Web frameworks:** React, Vite, FastAPI, Three.js / react-three-fiber.
  (NOT Next.js, NOT Angular — confirm what worldcolony.nyc's landing uses; the app is Vite+React.)
- **Databases:** **ClickHouse** ✅ (correct the template's "None/MongoDB" — we do use ClickHouse).
- **Blockchain networks:** Ethereum (mainnet — ENS), Ethereum Sepolia (agent ENS
  subnames), Polygon (Polymarket trades), World Chain (Worldcoin AgentKit).
- **Ethereum dev tools:** web3.py, Dynamic, ENS, py-clob-client.
  (NOT Hardhat — no contracts were deployed.)
- **Other tech / libraries / tools:** ENS, World ID / Worldcoin AgentKit, Polymarket
  (CLOB + Gamma), PolyGun, Telethon, ClickHouse, x402, UMA Optimistic Oracle, Dynamic,
  Railway, Vercel, uvicorn, certifi, Claude Code, ChatGPT.

---

## AI tools used  (accurate rewrite)

```
ChatGPT was used to brainstorm the project story, polish this submission copy, and
walk through the ENS record setup on app.ens.domains. Claude Code was used to build
and iterate large parts of the system: the PolyGun Telegram execution layer (a
Telethon userbot that places real Polymarket trades), the clickhouse_api metered
knowledge plane (timestamp gate + x402 handshake + verified-tier pricing, with a
leak test), the direct Polymarket CLOB tooling (py-clob-client), on-chain trade
verification and the predictions.json ledger, the Worldcoin AgentKit verification
flow, and extensive engineering notes/docs. No custom smart contracts were written —
we integrated existing protocols (ENS, World ID/AgentKit, Polymarket, UMA). Final
product decisions, deployment, on-chain transactions, and the demo flow were
directed by the team.
```

---

## Eligibility checklist (before submitting)

- [ ] Demo (https://worldcolony.nyc) opens in incognito.
- [ ] Repo `Vainglorious/ethglobalnyc` is public + marked Monorepo.
- [ ] `worldcolony.eth` resolves on mainnet → trades wallet `0xe9E32Ca24aa1eF725F650b5489281FE621363AA9`.
- [ ] Polygon Polymarket activity visible at that wallet (Polygonscan).
- [ ] Short description < 100 chars; Full + How-it's-made each > 280 chars.
- [ ] Tech stack matches repo: includes Python, FastAPI, ClickHouse, React/Three.js;
      remove Angular.js / MongoDB / Hardhat if present-by-default.
- [ ] Only claim ✅ items as "built"; phrase 🟡/📝 (Arc settlement, CCIP-Read) as planned.
- [ ] For sponsor prizes: ENS, Worldcoin, ClickHouse, Polygon, Dynamic are the strongest (all ✅).

---

## Evidence / verifiable artifacts (for judges)

- ENS: `worldcolony.eth` (mainnet) → `0xe9E32Ca24aa1eF725F650b5489281FE621363AA9`.
- Trades (real, on-chain): `predictions.json` (7 PolyGun trades, tx hashes + blocks);
  counterfactuals in `simulatedtransactions.json`.
- Worldcoin: 5 verified ant wallets (humanId 0x41e49b…608f0) on World Chain AgentBook.
- ClickHouse knowledge plane: `clickhouse_api/` (gate + metering) + `clickhouse/DATA_CATALOG.md`.
- Agent identities: 200 `root-*.colonny.eth` on Sepolia; `colony/data/agent-wallets.dynamic.200.public.json`.
