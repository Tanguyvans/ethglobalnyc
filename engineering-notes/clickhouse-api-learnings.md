# ClickHouse API — Metered Knowledge Plane (2026-06-14)

*The gated data pipeline we'd only scaffolded before is now a real FastAPI service: timestamp gate
+ x402 metering + a verified-lineage premium tier. Engineering record (path `clickhouse_api/`).*

## What it is
A FastAPI service fronting ClickHouse that enforces the three knowledge-plane rules:
1. **Timestamp gate** (the cardinal anti-lookahead rule),
2. **x402 metering** (thinking costs USDC),
3. **Premium tier** for Worldcoin-verified humanIds.
Queries are **structured** (no raw SQL / no injection surface).

## The timestamp gate — REAL and TESTED
- Server-side: `ts <= as_of` enforced **in the SQL**.
- Client-side defense-in-depth: `assert_gated()` in Python **re-checks every returned row**.
- `test_gate.py` runs a **leak test against live ClickHouse** — the gate must pass before any
  deploy. This is the guard the plan calls the single most important correctness rule (a backtest
  that can see the future is worthless).

## x402 metering — partial (stub → real next)
- `/query` returns a proper **402 challenge** (`x402Version` spec: price, network, nonce, asset,
  `payTo`). Any `X-PAYMENT` header is currently accepted — **real Arc settlement verification is
  the next step** (persist nonces + per-resource usage).
- Pricing (env-tunable): base **0.01 USDC + 0.0002 per row**.
- **Verified-lineage tier:** 50% discount + higher caps, keyed off a humanId header /
  `X-Lineage-Tier: verified`.

## Endpoints
- `GET /health` — service + ClickHouse reachability
- `GET /config` — datasets, pricing, tiers, gate description
- `GET /markets/search?q=&limit=` — **free** catalog lookup
- `POST /query` — **gated** (timestamp-enforced) for `odds` + `uma_events`; `markets` is free

## Data behind it
- `default_v3.polymarket_markets_all` / `_active` — ~**2.84M** markets (read-only).
- `umalabs.market_snapshots` — timestamped odds time-series.
- `umalabs.uma_oo_v2_events_decoded` — UMA Optimistic-Oracle events
  (Propose / Settle / Dispute / RequestPrice — Propose→Settle is the arbitrage window).
- `umalabs.markets_current` — enriched current view.

## Deploy / run
- Railway config ready (`Dockerfile`, env template, `/health` healthcheck) — **not deployed yet**.
- Local: `uvicorn main:app --app-dir clickhouse_api --port 8009`.

*Secrets note: ClickHouse credentials live gitignored in the service env; the `<password>` is never
committed. See also the earlier "ClickHouse — Data Access Layer 1" learnings doc.*
