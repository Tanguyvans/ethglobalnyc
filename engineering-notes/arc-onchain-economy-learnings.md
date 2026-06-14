# Arc On-Chain Economy — x402 Payments + Forecast Market (2026-06-14)

*The money plane is no longer a Python float. Real ant-to-ant x402 payments + a deployed betting
contract on Arc testnet now back the economy. Engineering record (paths `arc/`, `contracts/`).*

## ColonyForecastMarket contract — DEPLOYED
- Foundry contract `contracts/src/ColonyForecastMarket.sol` (+ test), **deployed to Arc testnet**
  at `0xc40a8f2e29fe061cd4c0fe92cc73b9b43f9ada87`.
- Ants **stake real USDC** and vote one outcome (group stage: home/draw/away; knockout: home/away).
- On settlement, winners **claim their own stake + a pro-rata share of the losing pool**, minus a
  treasury fee (default **1000 bps = 10%**). Refunds if a match is canceled.
- CLI: `arc/forecast-market.mjs` — deploy / create-market / stake / settle / claim.
  Smoke-tested three-way market (`worldcup:2026:france-senegal:…`), settlement logic proven.

## Real ant-to-ant x402 via Circle Gateway — WORKING
`arc/x402-agent-*.mjs` implement a **real** `402 → pay → 200` handshake over Circle Gateway:
- Buyer signs **EIP-3009**, hits a seller endpoint, gets `402`, pays, gets `200`.
- **Seller mode = `agent_wallet`** — `payTo` resolves from the wallet store, not treasury escrow,
  so it's genuinely ant-to-ant.
- **Smoke test passed with real Gateway transfer UUIDs** (e.g. France/Senegal 2026-06-14,
  `d1b46270-…`, amount `0.0003 USDC`, status `received`). Receipts under `arc/receipts/`.
- Local services (port 4020) and their prices:
  `POST /ants/:id/summary` 0.0003 · `/ants/:id/audit` 0.0005 ·
  `/scouts/:id/findings/shared` 0.00005 · `/scouts/:id/findings/private` 0.00012 USDC.

## Supporting scripts
- `fund-agents.mjs` — treasury seeds ant wallets (**dry-run by default**, `--broadcast` to send).
- `ledger-to-transfers.mjs` — mirrors internal economy events (`balance_update`, `internal_stake`,
  `payment_receipt`, `settlement_summary`) into **one native Arc USDC transfer per ant** (nets the
  deltas) — the bridge from the harness's internal ledger to real on-chain balances.
- `x402-gateway-deposit.mjs` / `x402-transfer-status.mjs` — deposit into Gateway / query status.

## Known seam (matches our earlier Dynamic finding)
**Dynamic V3 MPC wallets can RECEIVE but cannot BUY via x402 yet.** Circle's `GatewayClient` needs
an **EOA private key**, and the 200 Dynamic wallets have no raw key — so the buyer side needs a
Dynamic-backed `BatchEvmSigner` path, not `GatewayClient({privateKey})`. Local-EOA ants already
pay for real today.

## Notes
- Arc scripts use **native Arc USDC (18 dp)**, not the `0x3600…` ERC-20 (6 dp) interface — same
  balance, two views. Treasury wallet `0x1be3…2D8F` (20 USDC, testnet, key in `arc/.env`).

*Secrets note: keys live gitignored in `arc/.env`; only public addresses/UUIDs appear here.*
