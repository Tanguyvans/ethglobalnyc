# SOLANA — watched address

Stored address (see `watch-address.txt`):

```
31DuznH5P6FAV4qnSvaahoUndgWzEKbGRjERKTV3Qfiu
```

## What this address is (read on-chain 2026-06-18, mainnet-beta)

A **regular Solana wallet** — a normal user wallet, not a program or token mint.
- **Owner program:** `11111111111111111111111111111111` (System Program) → it's a plain
  account, `executable: false`. So: a wallet, controlled by whoever holds its keypair.
- **Format:** base58, 44 chars, no `0x` → Solana (not EVM). Unrelated to the EVM/Polygon
  and Arc wallets used elsewhere in this repo.

## Holdings (live at time of check)

| Asset | Amount | Notes |
|---|---|---|
| **SOL** (native) | **4.324098044 SOL** | 4,324,098,044 lamports |
| **USDC** (SPL) | **4001.000504 USDC** | mint `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v` = Circle's canonical Solana USDC |

So it's a funded wallet holding ~4.3 SOL + ~$4,001 USDC. One SPL token account (the USDC ATA).

## Transaction history (rough, to date)

- **49 signatures total** lifetime (the RPC returned 49 against a 1000 cap, so this is the
  *complete* history, not a truncated window).
- **48 succeeded, 1 failed.**
- **Active window:** oldest seen **2025-08-07**, newest **2025-12-29**. Appears **dormant
  since ~Dec 2025** (~6 months idle as of 2026-06-18).
- Activity came in small clusters of 1–3 txs on given days (e.g. 2025-11-08, 2025-11-12,
  2025-12-12) — a pattern consistent with occasional transfers / swaps rather than a bot or
  high-frequency program.
- **Per-transaction decode not available from the public RPC** — `api.mainnet-beta.solana.com`
  prunes ledger data older than a few months, and all this wallet's activity predates that
  window, so `getTransaction` returns "not found." To classify each tx (transfer vs swap vs
  program call), use an indexer that keeps full history: Solscan / Helius / Solana FM (below).

## How this was queried (read-only, repeatable)

```bash
ADDR=31DuznH5P6FAV4qnSvaahoUndgWzEKbGRjERKTV3Qfiu
RPC=https://api.mainnet-beta.solana.com
# identity + SOL balance
curl -s "$RPC" -H 'content-type: application/json' \
  --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"getAccountInfo\",\"params\":[\"$ADDR\",{\"encoding\":\"jsonParsed\"}]}"
curl -s "$RPC" -H 'content-type: application/json' \
  --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"getBalance\",\"params\":[\"$ADDR\"]}"
# SPL token holdings
curl -s "$RPC" -H 'content-type: application/json' \
  --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"getTokenAccountsByOwner\",\"params\":[\"$ADDR\",{\"programId\":\"TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA\"},{\"encoding\":\"jsonParsed\"}]}"
# full signature history
curl -s "$RPC" -H 'content-type: application/json' \
  --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"getSignaturesForAddress\",\"params\":[\"$ADDR\",{\"limit\":1000}]}"
```

Human explorers (full history + decoded txs):
- https://solscan.io/account/31DuznH5P6FAV4qnSvaahoUndgWzEKbGRjERKTV3Qfiu
- https://solana.fm/address/31DuznH5P6FAV4qnSvaahoUndgWzEKbGRjERKTV3Qfiu

*Read-only watch entry — no keys here, nothing executed against this wallet.*
