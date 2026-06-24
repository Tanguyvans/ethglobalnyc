# Colony, in plain English

*For the product side of the team. No technical background needed.*

## The idea in one breath
We are building a **digital colony of "ant" forecasters** for the long term, not just a stage
demo. Each ant reads reliable World Cup information, forms a thesis, chooses a team or draw, and
decides how much fake money it can risk while trying to survive. Ants that reason and size risk well
gain reputation and capital; ants that are reckless go broke over time. Future children inherit
their parent's strategy with small random tweaks, so the colony can evolve across many matches.

It's two things at once, and that's the point:
- a **forecasting society** (can different agent personalities interpret the same match better
  together?), and
- a **long-running experiment** about AI agents handling scarce capital and reputation.

## How one ant lives (the loop)
Picture a single ant going around a circle:

1. **Born** with a starting balance of fake credits.
2. **Reads reliable match context** — form, tactics, players, market context, and debate notes.
3. **Forms a thesis** — for example, "the attacker is in form, but the upset risk is still high."
4. **Commits a stake level** — `micro`, `small`, `medium`, or rarely `high`.
5. **The match resolves** — the real outcome comes in.
6. **Gets paid or loses** — balance and reputation move up or down.
7. Then either:
   - **survives** and goes around again,
   - **dies** if it ran out of money, or
   - **reproduces** if it got rich enough — spawning a baby that inherits its strategy
     (slightly mutated) and a share of its money.

Repeat across the whole colony, generation after generation. The mix of strategies in the
population shifts over time — that shift *is* the evolution, and it's the thing we put on screen.

## Why this is more than a leaderboard
Two design rules keep it honest:

1. **The genes have to actually drive behavior.** If a "winning" ant is just lucky, that's a
   leaderboard with a death animation, not evolution. So genes are real dials (bet size,
   pickiness, trust-the-crowd) that visibly change outcomes.
2. **Winning has to mean "smarter than the market," not "guessed the favorite."** Picking
   Brazil to beat a minnow isn't skill. We score ants on *beating the betting market's odds*,
   so the impressive claim — "our agents out-forecast the market" — is real.

## The three "rails" (the moving parts), in plain terms
- **Identity (ENS):** every ant gets a readable name and a stored life story. The product
  moment: someone types an ant's name and reads its whole life — born, bets, wins, losses,
  kids, death.
- **Personhood (Worldcoin):** we can prove a real human stands behind a founder ant. This
  powers our headline experiment (below). *We've tested this and it works — see
  `worldcoin-in-plain-english.md`.*
- **Money (fake credits first, Arc later):** the active colony economy uses fake credits so we can
  test survival behavior safely. Arc and pay-to-read data remain settlement rails for later
  experiments. *See `clickhouse-in-plain-english.md`.*

## What the Run button does now
The main `Run` button starts a fresh colony run for the selected match. The ants read the match
context, produce thesis-based judgments, debate, commit fake-credit stakes, and return a colony
decision with the arguments behind it.

So the product is no longer just "ants talk, then we narrate a bet." It is:

> **ants read -> ants argue -> ants commit scarce credits -> match resolves -> survivors learn**

The manual on-chain staking and settlement controls can still exist for debugging or experiments,
but they are not the default product loop while the society design is still being tested.

One important honesty check: if an Arc/USDC route is enabled later and the backend does not have
the required signing wallets configured, the ants can still forecast and debate with fake credits,
but the app should clearly say that no on-chain transaction happened.

For the full 200-ant colony on Railway, the private testnet wallet JSON is too large for one
environment variable. The backend can now read it split across
`COLONY_API_FORECAST_WALLETS_JSON_0`, `COLONY_API_FORECAST_WALLETS_JSON_1`, and so on, then
rebuild the complete signer store before sending contract transactions. The addresses can stay
public, but the private keys still live only in Railway env/private local files.

When a new ant is created, its life record is stored in `child_ants.json` under the API runs
directory, and its wallet is added to the selected reproduction wallet store. On Railway, that
API runs directory should be a mounted volume if we want the new colony members to survive
restarts.

## The headline experiment
We can mark some family lines as **human-verified** (a real person vouched for the founder)
and give them a head start — more starting money. Then we let the colony run and ask a real,
open question:

> **Do the privileged human-backed family lines take over, or do lean anonymous ants
> out-compete them on pure skill?**

Whatever happens is a genuine finding about AI-agent economics. One chart — *"verified lines
started with 3x the money; by generation 12, here's who survived"* — is more compelling than any
architecture diagram.

(One honesty note we're careful about: if verified ants win *only* because they started
richer, we've measured "started richer," not "human-backing helps." So we control for the
head start in how we set up the experiment.)

## What's real vs. what we just narrate
Being upfront keeps the product credible:
- **Real and working:** the ant loop, the genes/evolution, the play-money economy, the
  pay-to-read data gate, the human-verification, the live charts.
- **Sped up but real:** we can **replay** past matches at high speed so dozens of generations can
  turn over during a short product preview. The data is real; only the clock is fast.
- **Narrated only (future work):** thousands of ants, an 8-week live run on the real
  tournament, and a few sponsor integrations we describe but don't fully build.

## The one-sentence pitch
**A colony of AI agents that bet on the World Cup, where good forecasters breed and bad ones
go broke — and a live experiment on whether being human-backed actually helps an agent survive.**
