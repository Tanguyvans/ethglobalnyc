# WorldColony

WorldColony is an evolutionary ecosystem of forecasting agent "ants" that earn or die by the
quality of their World Cup predictions. Each ant has a heritable genome, its own wallet, and an
ENS identity. Ants debate in rooms, buy data, make forecasts, stake USDC, and survive or reproduce
based on how well they predict match outcomes.

## Live Demo

- Demo: https://worldcolony.nyc
- API: https://ethglobalnyc-production.up.railway.app
- Project overview: [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)

## Smart Contract

The forecast escrow smart contract is deployed on Arc testnet:

[0xc40a8f2e29fe061cd4c0fe92cc73b9b43f9ada87](https://explorer.testnet.arc.network/address/0xc40a8f2e29fe061cd4c0fe92cc73b9b43f9ada87)

This `ColonyForecastMarket` contract lets ants stake USDC on forecast outcomes. After settlement,
correct voters can claim winnings from the losing pool minus the treasury fee.

## Main Pieces

- `frontend/`: Vite, React, and Three.js dashboard.
- `colony/` and `colony_api/`: agent simulation, evolution loop, and FastAPI backend.
- `arc/`: Arc testnet USDC flows, x402 payments, and forecast-market tooling.
- `clickhouse_api/`: metered knowledge plane with timestamp-gated market data.
- `polymarket/` and `polygun/`: real prediction-market execution and trade records.
- `ens/`, `worldcoin/`, and `dynamic/`: identity, verification, and wallet integrations.

## Verification Artifacts

- ENS: `worldcolony.eth`
- Arc forecast contract: [`0xc40a8f2e29fe061cd4c0fe92cc73b9b43f9ada87`](https://explorer.testnet.arc.network/address/0xc40a8f2e29fe061cd4c0fe92cc73b9b43f9ada87)
- Trades ledger: [predictions.json](predictions.json)
- Full architecture notes: [MIROFISH_ARCHITECTURE_AND_WORKFLOW.md](MIROFISH_ARCHITECTURE_AND_WORKFLOW.md)
