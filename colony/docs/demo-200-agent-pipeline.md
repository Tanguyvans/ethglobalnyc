# 200-Agent Demo Pipeline

This is the current demo-ready Colony path for the France vs Senegal test round.

## What Is Already Deployed

- 200 Dynamic V3 WaaS/MPC wallets were created and persisted in the gitignored Dynamic wallet store.
- 200 ENSv2 subdomains were published on Sepolia under `colonny.eth`.
- Each subdomain has resolver records written, including `addr` and ENSIP-26-style text records.
- The `addr` records point to the corresponding Dynamic wallet public addresses.
- `colonny.eth` is ENSv2, has a subregistry attached, and is controlled by the configured publisher wallet.

Verified examples:

```text
ant_0000 root-fable-0.colonny.eth
resolved_addr = 0x3fB467e269e4C0BfdeAA99086f7854d3590A078D
matches identity JSON = true

ant_0099 root-onyx-99.colonny.eth
resolved_addr = 0x428ab0660cFfed98bBa097fcfa6Cb4EEB502891A
matches identity JSON = true

ant_0199 root-fable-199.colonny.eth
resolved_addr = 0x34F32499dCE99f977B039BfD8Ff6eed403435326
matches identity JSON = true
```

ENS UI indexing may lag. On-chain verification is the source of truth.

## Run The Communicating Colony

Use the already-created Dynamic wallets and deterministic ENS names:

```bash
python3 colony/run_demo.py \
  --agents 200 \
  --rooms 12 \
  --seed 205 \
  --voice-mode llm \
  --agent-wallets \
  --wallet-provider dynamic \
  --wallet-store colony/secrets/agent-wallets.dynamic.200.json \
  --identity-out colony/runs/identity_200_dynamic_communicating_clean_seed205.json \
  --debug
```

The latest clean demo run is:

```text
colony/runs/20260613_183244_round_world_cup_demo_001
```

## Current Demo Result

```text
Population: 200 predictors
Wallets: 200
ENS names: 200
Rooms: 5
Room claims: 15
Final claims: 1
Social actions: 361
Prediction cards: 200
Technical passes: 0
```

Prediction result:

```text
France / home: 53
Draw: 100
Senegal / away: 47
Collective decision: draw
Score call: France 1-1 Senegal
Confidence: medium
```

Social action result:

```text
CREATE_POST: 206
CREATE_COMMENT: 72
QUOTE_POST: 52
LIKE_POST: 20
REPOST: 7
FOLLOW: 4
```

## LLM Boundary

`--voice-mode llm` calls the configured OpenAI-compatible provider for debate voices. In the current design:

- 15 room representatives speak through the LLM.
- 1 final synthesis is produced.
- all 200 ants still participate through forecasts, social actions, prediction cards, wallet-linked commitments, and the collective decision.

This means the OpenRouter dashboard should show debate-call volume, not 200 separate LLM calls. Making every prediction card an LLM call is a separate, more expensive mode.

The demo run was checked for:

- no `voice recovery`
- no `LLM voice call failed`
- no public percentages or raw probability strings
- no leaked decimal confidence values in public artifacts

## Opinion Changes

Using the same seed and reconstructing the no-debate baseline, the debate changed 37 of 200 final sides.

Before debate:

```text
draw: 114
home: 46
away: 40
```

After debate:

```text
draw: 100
home: 53
away: 47
```

Transitions:

```text
draw -> home: 13
draw -> away: 12
home -> draw: 7
away -> draw: 4
away -> home: 1
```

Changes by risk profile:

```text
balanced: 19
risky: 11
secure: 7
```

Example changed agents:

```text
ant_0001: draw -> home
ant_0011: home -> draw
ant_0017: away -> home
ant_0026: away -> draw
ant_0039: draw -> home
ant_0075: draw -> away
```

## ENS Publication Notes

For the 200-agent testnet publish, the first small canary succeeded, then the full batch hit a transient Sepolia RPC `nonce too low` error. The publisher now reads the `pending` nonce before each transaction and retries nonce-low sends.

Dynamic wallet creation also hit intermittent provider-side `HTTP 500 {"error":"Failed to create wallet"}` responses during the 200-wallet run. The Dynamic wallet path now retries transient HTTP 5xx / transport errors and reuses the same gitignored wallet store so the run can resume safely.

## Files To Open During Demo

- `summary.md`: top-level run result
- `debate.md`: room representatives and LLM messages
- `social_feed.md`: readable OASIS/MiroFish-style interactions
- `social_profiles.json`: 200 ants with wallet and ENS names
- `forecasts.csv`: every final side and stake
- `decision.compact.json`: execution-friendly colony decision
- `identity_200_dynamic_communicating_clean_seed205.json`: 200 ENS identity records
