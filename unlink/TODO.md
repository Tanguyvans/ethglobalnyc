# Unlink — TODO

## Blocked: complete the 1 USDC test transfer
Everything is wired and verified except one value. Status (2026-06-13):
- API key works; tenant is provisioned on **arc-testnet** (NOT base-sepolia).
- Both test wallets register fine (`ensureRegistered` OK on arc-testnet).
- `transfer-demo.mjs` validated against the real SDK types; parses + imports load.

Remaining:
- [ ] Get **`UNLINK_TEST_TOKEN`** — the ERC-20 token address for arc-testnet (USDC), from the
      dashboard project/environment config. `faucet()` and `transfer()` both require it; could
      not be discovered via SDK (`getEnvironmentInfo`/`ENVIRONMENTS`/`getBalances` have no token list).
- [ ] Set `UNLINK_ENVIRONMENT=arc-testnet` in `unlink/.env`.
- [ ] Confirm token decimals (6 vs 18) → set `UNLINK_TRANSFER_AMOUNT` (1 USDC = 1000000 @ 6dp).
- [ ] Run `cd unlink && node transfer-demo.mjs` → faucet-fund A → 1 USDC A→B → verify balances.

## Later
- [ ] Evaluate Unlink as a **privacy layer for Colony ant USDC on Arc** (both live on arc-testnet,
      chain 5042002). Private ant-to-ant stakes/inheritance vs. fully-public transfers.
