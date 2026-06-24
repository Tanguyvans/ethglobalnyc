# WorldColony

WorldColony is a long-term forecasting-agent society, not a one-off hackathon demo. A colony of
agent "ants" reads reliable football information, forms survival theses, debates risk, commits
scarce credits, and learns from match outcomes. The objective is not just to pick winners; it is to
survive over time with limited capital, reputation, and attention.

Each ant has a persona, a genome, an identity record, and a bankroll. In the current Survival
Thesis V1 loop, ants produce a qualitative pick with a thesis, main signal, conviction, risk read,
and mandatory-but-sized stake level (`micro`, `small`, `medium`, or `high`). On-chain rails remain
available for settlement experiments, but the default colony economy now uses fake credits until
the agent society is stable enough to deserve real money.

## Product Preview

- App: https://worldcolony.nyc
- API: https://ethglobalnyc-production.up.railway.app
- Project overview: [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)
- Colony strategy and harness docs: [colony/README.md](colony/README.md)
- Economy and society RFC: [colony/docs/economy-v2-society-rfc.md](colony/docs/economy-v2-society-rfc.md)

## Settlement Rails

The forecast escrow smart contract is deployed on Arc testnet:

[0xc40a8f2e29fe061cd4c0fe92cc73b9b43f9ada87](https://explorer.testnet.arc.network/address/0xc40a8f2e29fe061cd4c0fe92cc73b9b43f9ada87)

This `ColonyForecastMarket` contract lets ants stake USDC on forecast outcomes. It is treated as an
optional settlement rail for on-chain experiments. The active colony strategy is developed first in
the fake-credit economy so agent behavior, stake sizing, debate quality, and survival incentives can
be tested before real capital is connected by default.

## Main Pieces

- `frontend/`: Vite, React, and Three.js dashboard.
- `colony/` and `colony_api/`: Survival Thesis Colony simulation, evolution loop, and FastAPI backend.
- `arc/`: optional Arc testnet USDC flows, x402 payments, and forecast-market tooling.
- `clickhouse_api/`: metered knowledge plane with timestamp-gated market data.
- `polymarket/` and `polygun/`: real prediction-market execution and trade records.
- `ens/`, `worldcoin/`, and `dynamic/`: identity, verification, and wallet integrations.

## Verification Artifacts

- ENS: `worldcolony.eth`
- Arc forecast contract: [`0xc40a8f2e29fe061cd4c0fe92cc73b9b43f9ada87`](https://explorer.testnet.arc.network/address/0xc40a8f2e29fe061cd4c0fe92cc73b9b43f9ada87)
- Trades ledger: [predictions.json](predictions.json)
- Full architecture notes: [MIROFISH_ARCHITECTURE_AND_WORKFLOW.md](MIROFISH_ARCHITECTURE_AND_WORKFLOW.md)
