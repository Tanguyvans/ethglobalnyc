# ENS Agent Identity Pipeline

Colony uses ENS as the public identity layer for ant agents.

The important separation is:

1. **Local identity assignment**: every generated ant gets a wallet address and a deterministic ENS name.
2. **World access assignment**: selected ants expose `world_status=world_verified` and `world_access_tier=premium_world` after a real AgentKit receipt is stored.
3. **Identity record export**: the roster is written as ENSIP-26-ready records.
4. **On-chain publication**: selected records are registered as ENSv2 subnames and written to the agent resolver.
5. **Run state update**: new runs reuse stable subdomains and rewrite mutable records such as `deployment_id` and `active`.

This keeps the simulation usable before spending gas, while making the on-chain demo a real extension of the same data.

## Identity Model

Each ant has:

```text
agent_id        ant_0001
wallet_address  0x2D84...
ens_name        root-onyx-1.colonny.eth
generation      0
lineage         root-onyx-1.colonny.eth
world_status    unverified
world_access     standard
deployment_id   demo_001
active          true
```

Generation-0 ants are lineage roots. Children receive their own ENS names but point back to their parent and lineage root:

```text
gold-lens-42.colonny.eth
  parent  = root-fable-0.colonny.eth
  lineage = root-fable-0.colonny.eth
  world   = unverified
  access  = standard
```

Wallets are local throwaway EVM wallets stored in `colony/secrets/agent-wallets.local.json`, which is gitignored. Only public addresses and ENS names are exported. World ID is a separate privilege layer: if 5 ants out of 50 are verified, only those 5 get `premium_world` capabilities.

ENS subdomains are stable identities. A new run should not delete and recreate names; it should rewrite records:

```text
root-onyx-1.colonny.eth
  com.colony.deployment_id = demo_002
  com.colony.active        = true
```

## Generation Flow

Copy the environment template once:

```bash
cp colony/.env.example colony/.env
```

Set the reusable ENS values:

```env
COLONY_ENS_PARENT=colonny.eth
COLONY_ENS_VERSION=v2
COLONY_PROFILE_BASE_URL=https://colony.app/ants
COLONY_WORLD_VERIFICATIONS=colony/secrets/world-agentkit-verifications.local.json
SEPOLIA_RPC_URL=https://ethereum-sepolia-rpc.publicnode.com
PROJECT_ENS_PRIVATE_KEY=
```

`PROJECT_ENS_PRIVATE_KEY` is the publisher key. The publisher wallet address is derived from it, so it does not need to be duplicated in `.env`.

Generate agents with wallets and ENS names:

```bash
python3 colony/run_demo.py \
  --agents 4 \
  --agent-wallets \
  --identity-out colony/data/ens-identities.demo.json \
  --show-roster
```

During generation:

```text
AntAgent.wallet_address is assigned/reused from the local wallet store.
AntAgent.ens_name is deterministically assigned from the ENS parent.
AntAgent.world_status is derived from a stored Worldcoin AgentKit receipt.
The public roster includes wallet_address, ens_name, world_status, and world_access_tier.
The identity JSON contains the records that can later be published on-chain.
```

The ENS name is deterministic, so the same agent under the same parent gets the same name across runs.

## ENSIP-26 Records

Each exported identity has:

```text
addr                 the ant wallet address
agent-context        JSON identity card for agent discovery
agent-endpoint[web]  web/profile URL
com.colony.*         compact Colony-specific indexes
```

The `agent-context` record is the canonical machine-readable entrypoint:

```json
{
  "schema": "ensip-26",
  "kind": "colony_ant",
  "agent_id": "ant_0001",
  "ens_name": "root-onyx-1.colonny.eth",
  "wallets": {
    "evm": "0x2D84...",
    "arc_testnet": "0x2D84..."
  },
  "generation": 0,
  "parent": "",
  "lineage": "root-onyx-1.colonny.eth",
  "deployment_id": "demo_001",
  "active": true,
  "world_status": "unverified",
  "world_access_tier": "standard",
  "capabilities": ["stats_scout", "forecast", "debate", "trade"]
}
```

## ENSv2 Publication

Names created in `app.ens.dev` are ENSv2 names. ENSv2 needs two one-time pieces before subnames can be created:

1. A per-owner permissioned resolver.
2. A subregistry attached to the parent name.

The publisher handles both automatically.

Check the parent:

```bash
python3 colony/register_ens_identities.py \
  colony/data/ens-identities.demo.json \
  --check-parent
```

Expected ready state:

```text
Parent:      colonny.eth
Version:     v2
Controller:  0xa569...
Subregistry: 0x0C15...
Ready:       yes
```

Publish one ant:

```bash
python3 colony/register_ens_identities.py \
  colony/data/ens-identities.demo.json \
  --agent-id ant_0001 \
  --broadcast
```

The first ENSv2 publish for a parent may send up to five transactions:

```text
deploy owner resolver
deploy parent subregistry
attach subregistry to parent
register ant subname
write resolver records
```

After the parent is ready, each new ant normally needs two transactions:

```text
register ant subname
write resolver records
```

Already registered ENSv2 subnames are skipped for the create step, so the script can safely continue a partial publication run.
For subsequent runs, this is the expected path: existing subdomains are detected, creation is skipped, and resolver records are rewritten.
For long testnet batches, the publisher reads the `pending` nonce before each transaction and retries nonce-low sends. This is important on public Sepolia RPCs, where a previously accepted transaction can make the next locally selected nonce stale.

The 200-agent demo batch published all generated Dynamic-wallet identities under `colonny.eth` on Sepolia ENSv2. Three spot checks were read back successfully:

```text
root-fable-0.colonny.eth   -> 0x3fB467e269e4C0BfdeAA99086f7854d3590A078D
root-onyx-99.colonny.eth   -> 0x428ab0660cFfed98bBa097fcfa6Cb4EEB502891A
root-fable-199.colonny.eth -> 0x34F32499dCE99f977B039BfD8Ff6eed403435326
```

The ENS UI can lag behind the chain index. For demos, verify with RPC reads when the UI has not indexed every subname yet.

## Premium World Agents

World ID verification is attached to selected agents, not to the whole lineage. This is the clean model for premium tools: a colony can have 50 ants where only 5 have World ID-backed privileges.

First generate identities so every ant has a wallet and ENS name:

```bash
python3 colony/run_demo.py \
  --agents 50 \
  --agent-wallets \
  --identity-out colony/data/ens-identities.demo.json \
  --show-roster
```

Then run the real AgentKit flow for the selected premium ants. This is one command, but the CLI still creates one World ID challenge per wallet:

```bash
python3 colony/register_world_agent.py \
  ant_0000 ant_0007 ant_0012 ant_0028 ant_0034 \
  --identity-json colony/data/ens-identities.demo.json \
  --skip-existing
```

This launches:

```bash
npx -y @worldcoin/agentkit-cli register <agent-wallet>
```

and stores the resulting tx/nullifier receipt in `COLONY_WORLD_VERIFICATIONS`.

Then regenerate/export while requiring those receipts:

```bash
python3 colony/run_demo.py \
  --agents 50 \
  --agent-wallets \
  --world-agent ant_0000 \
  --world-agent ant_0007 \
  --world-agent ant_0012 \
  --world-agent ant_0028 \
  --world-agent ant_0034 \
  --identity-out colony/data/ens-identities.demo.json
```

Each verified ant gets:

```text
com.colony.world = world_verified
com.colony.world_access_tier = premium_world
com.colony.capabilities = ...,world_agentkit,premium_data,x402_privileged
```

## Fresh Deploy Script

For new colonies, use the deploy orchestrator instead of manually composing `run_demo`,
`register_world_agent`, and `register_ens_identities`.

Dry-run ENS publication:

```bash
python3 colony/deploy_agents.py \
  --agents 50 \
  --world-count 5 \
  --deployment-id demo_001 \
  --identity-out colony/data/ens-identities.deploy.json
```

This does four steps:

```text
1. Generate 50 agents with wallets and ENS identity records.
2. Register ant_0000 through ant_0004 with Worldcoin AgentKit.
3. Regenerate the identity records with premium_world capabilities.
4. Run ENS publication in dry-run mode.
```

If `--deployment-id` is omitted, the deploy script generates a UTC id such as
`deploy_20260613_184200`.

When the dry-run is correct, broadcast Sepolia ENS transactions:

```bash
python3 colony/deploy_agents.py \
  --agents 50 \
  --world-count 5 \
  --deployment-id demo_001 \
  --identity-out colony/data/ens-identities.deploy.json \
  --ens-broadcast
```

For hand-picked World agents:

```bash
python3 colony/deploy_agents.py \
  --agents 50 \
  --world-agent ant_0000 \
  --world-agent ant_0007 \
  --world-agent ant_0012 \
  --deployment-id demo_custom_001 \
  --identity-out colony/data/ens-identities.deploy.json
```

## New Run Flow

To run the same colony again, keep the same ENS names and use a new deployment id:

```bash
python3 colony/deploy_agents.py \
  --agents 50 \
  --world-count 5 \
  --deployment-id demo_002 \
  --identity-out colony/data/ens-identities.deploy.json \
  --ens-broadcast
```

When a subdomain already exists, publication prints `exists` for the create step and still
writes the new records. That is intentional.

To mark the previous identity JSON inactive:

```bash
python3 colony/cleanup_ens_identities.py \
  colony/data/ens-identities.deploy.json \
  --broadcast
```

This writes:

```text
com.colony.active = false
```

Use `--clear-records` only when you want to wipe resolver data for testing. Do not use it as
the normal new-run flow.

## ENSIP-25 Later

ENSIP-25 should be added once Colony has an on-chain agent registry.

Future flow:

```text
ColonyAgentRegistry:
  ant_0001 -> root-onyx-1.colonny.eth

ENS text record:
  agent-registration[<registry>][ant_0001] = 1
```

Until that registry exists, ENSIP-26 is the right standard to implement first.
