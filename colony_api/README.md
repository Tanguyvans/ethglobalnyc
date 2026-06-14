# Colony API

Railway deploys this FastAPI wrapper around the Colony harness. The frontend can
use it to start a real agent run, stream status/events, and load the generated
JSONL artifacts.

Production API:

```text
https://ethglobalnyc-production.up.railway.app
```

## Health Check

```bash
curl https://ethglobalnyc-production.up.railway.app/health
```

Expected shape:

```json
{
  "ok": true,
  "service": "colony-api",
  "runs_root": "/data/runs",
  "run_demo_exists": true
}
```

## API Config

The frontend can inspect the backend contract with `GET /config`.

```bash
curl https://ethglobalnyc-production.up.railway.app/config
```

Important fields:

```json
{
  "defaults": {
    "agents": 200,
    "rooms": 12,
    "seed": 205,
    "voice_mode": "llm",
    "agent_wallets": true,
    "wallet_provider": "dynamic",
    "wallet_store": "colony/data/agent-wallets.dynamic.200.public.json"
  },
  "identity_fields": [
    "agent_id",
    "name",
    "ens_name",
    "wallet_address",
    "world_status",
    "world_access_tier",
    "genome_id",
    "lineage_id"
  ]
}
```

## Start A Demo Run

The frontend can create a run with `POST /runs/demo`.

```bash
curl -X POST https://ethglobalnyc-production.up.railway.app/runs/demo \
  -H "Content-Type: application/json" \
  -d '{"agents":200,"rooms":12,"seed":205,"voice_mode":"llm","agent_wallets":true,"wallet_provider":"dynamic","wallet_store":"colony/data/agent-wallets.dynamic.200.public.json"}'
```

Response:

```json
{
  "id": "run_20260613_232524_c0ac4d80",
  "status": "queued",
  "events_path": "/data/runs/run_.../events.jsonl"
}
```

Use `voice_mode: "llm"` for the deployed frontend interaction. Use
`voice_mode: "template"` only for cheap smoke tests or when OpenRouter/DeepSeek
variables are not configured in Railway.

The committed wallet store is sanitized:

```text
colony/data/agent-wallets.dynamic.200.public.json
```

It contains the 200 already-published Dynamic/ENS public addresses, but no raw
private keys and no Dynamic user metadata. It lets Railway reuse the same
`ant_0000` ... `ant_0199` wallet addresses and ENS names instead of minting new
wallets during a frontend demo click.

## Poll Run Status

```bash
curl https://ethglobalnyc-production.up.railway.app/runs/run_20260613_232524_c0ac4d80
```

When complete, the response includes links such as:

```json
{
  "status": "succeeded",
  "artifacts": {
    "events": "/runs/run_.../events",
    "stream": "/runs/run_.../stream",
    "summary": "/runs/run_.../artifacts/compact/.../summary.md",
    "decision": "/runs/run_.../artifacts/compact/.../decision.compact.json"
  }
}
```

## Stream Live Events

`GET /runs/{run_id}/stream` uses Server-Sent Events.

```js
const apiUrl = 'https://ethglobalnyc-production.up.railway.app'
const source = new EventSource(`${apiUrl}/runs/${runId}/stream`)

source.addEventListener('status', (event) => {
  const run = JSON.parse(event.data)
  console.log('run status', run.status)
})

source.addEventListener('colony_event', (event) => {
  const colonyEvent = JSON.parse(event.data)
  console.log('colony event', colonyEvent.event_type, colonyEvent)
})

source.addEventListener('done', () => {
  source.close()
})
```

The current first integration streams transport/status immediately. Most domain
events arrive when `run_demo.py` writes `events.jsonl` at the end of the harness
run. A later harness refactor can emit room/forecast events during `run_round()`.

## Agents And Rooms

The frontend can fetch ant identity and debate-room structure directly without
parsing raw JSONL.

```bash
curl https://ethglobalnyc-production.up.railway.app/runs/{run_id}/agents
curl https://ethglobalnyc-production.up.railway.app/runs/{run_id}/rooms
```

`GET /runs/{run_id}/agents` returns every `agent_record`, including ENS and
wallet identity fields:

```json
{
  "run_id": "run_...",
  "count": 200,
  "agents": [
    {
      "agent_id": "ant_0000",
      "name": "ant-0000",
      "ens_name": "root-fable-0.colonny.eth",
      "wallet_address": "0x3fB467e269e4C0BfdeAA99086f7854d3590A078D",
      "genome_id": "genome_...",
      "world_status": "unverified",
      "world_access_tier": "standard",
      "latest_forecast": {
        "side": "draw",
        "stake": 2.4
      }
    }
  ]
}
```

`GET /runs/{run_id}/rooms` returns each `debate_room`, including participants,
representatives, stance, evidence focus, synthesis, and claims.

## Frontend Interaction

The deployed frontend reads the backend URL from:

```text
frontend/public/config.js
```

```js
window.DN_CONFIG = window.DN_CONFIG || {
  API_URL: 'https://ethglobalnyc-production.up.railway.app',
  RUN: {
    agents: 200,
    rooms: 12,
    seed: 205,
    voice_mode: 'llm',
    agent_wallets: true,
    wallet_provider: 'dynamic',
    wallet_store: 'colony/data/agent-wallets.dynamic.200.public.json',
  },
}
```

The interaction code lives in:

```text
frontend/public/dinasty/databridge.js
frontend/public/dinasty/hud.js
```

Frontend flow:

1. `databridge.js` loads the latest successful backend run from `GET /runs`.
2. The `Run LLM agents` button calls `POST /runs/demo`.
3. The browser listens to `GET /runs/{run_id}/stream`.
4. When events arrive, the frontend seeds colony stats and the thought ticker.
5. If the backend is unavailable, the frontend falls back to `/data/demo.jsonl`.

Minimal browser-side call:

```js
async function startRun() {
  const apiUrl = window.DN_CONFIG.API_URL
  const response = await fetch(`${apiUrl}/runs/demo`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      agents: 200,
      rooms: 12,
      seed: 205,
      voice_mode: 'llm',
      agent_wallets: true,
      wallet_provider: 'dynamic',
      wallet_store: 'colony/data/agent-wallets.dynamic.200.public.json',
    }),
  })
  const run = await response.json()
  return run.id
}
```

## Railway Variables

Required for the API:

```env
COLONY_API_RUNS_DIR=/data/runs
COLONY_API_CORS_ORIGINS=*
COLONY_API_DEFAULT_AGENTS=200
COLONY_API_DEFAULT_ROOMS=12
COLONY_API_DEFAULT_SEED=205
COLONY_API_DEFAULT_VOICE_MODE=llm
COLONY_API_DEFAULT_AGENT_WALLETS=true
COLONY_API_DEFAULT_WALLET_PROVIDER=dynamic
COLONY_API_DEFAULT_WALLET_STORE=colony/data/agent-wallets.dynamic.200.public.json
```

The sanitized wallet store already contains `ant_0000` through `ant_0199`, so
those defaults reuse the existing Dynamic wallet addresses and deterministic ENS
names. Dynamic API variables are only needed when creating additional wallets.

Required for LLM mode:

```env
COLONY_LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=...
COLONY_LLM_BASE_URL=https://openrouter.ai/api/v1
COLONY_LLM_MODEL=deepseek/deepseek-v4-flash
COLONY_LLM_TIMEOUT_SECONDS=30
OPENROUTER_APP_TITLE=Colony Harness
OPENROUTER_HTTP_REFERER=https://ethglobalnyc-production.up.railway.app
COLONY_DEEPSEEK_API_KEY=...
COLONY_DEEPSEEK_BASE_URL=https://openrouter.ai/api/v1
COLONY_DEEPSEEK_MODEL=deepseek/deepseek-v4-flash
```
