# WorldColony — Pitch & Demo Script

*A clean, structured version of the project pitch. Source: Abena's working draft (originally
written at the bottom of the "data the agents pay to read" page). **Her original draft is left
intact and untouched** — this page is a separate, organized rewrite for presentation use, not an
edit of hers. Facts here are kept consistent with the Project Overview's honesty markers.*

## The hook (one breath)
A digital **colony of AI agents that bet real money on World Cup matches** — where *thinking* costs
money and natural selection decides who survives. Ants that forecast well get rich and reproduce;
ants that forecast badly (or waste money on useless data) go broke and die. And some ants carry
**proof that a real human stands behind them** — so we can finally answer the question the agent
economy keeps dodging:

> **Do agents with a verified human behind them actually do better?**

## The story
These aren't agents guessing. Each ant manages a bankroll, evaluates odds, debates with the others,
and places **calculated bets**. Winners reproduce and pass on their "genes" (with small mutations);
losers die. Over generations you literally watch the most effective strategies take over the colony.

## Why now, why this match
The 2026 World Cup is live across the US, Canada, and Mexico. We're pitching a World Cup forecasting
experiment **during** the World Cup, in the host metro, on a textbook favourite-vs-giant-killer
game — **Brazil vs. Morocco** (Morocco reached the 2022 semifinal as a massive underdog), kicking
off down the road. The stakes are real, the data is fresh, and the timeline is perfect for a
high-speed, high-stakes demo. (Three bet windows per match: before, during, and a final bet.)

## The secret sauce: thinking costs money
Most AI sims give agents infinite free information → lazy, meaningless decisions. In WorldColony,
**thinking costs money**, powered by an x402 `pay-to-access` rule over USDC:

> Ask for data → "pay first" → pay a small USDC fee → get the data.

We maintain a large paywalled database of prediction-market and match data (odds, outcomes, UMA
resolution history). Poor ants get a little basic access; richer ants can run hardcore (costly)
queries. Charging for facts forces the trade-off *"is this data worth the price?"* — turning
guessing into **researching** — and acts as a money sink that keeps the economy honest.

## Worldcoin: who should be rich, who should be poor
We're simulating a problem agent economies will hit in the next few years: **which agents deserve
privilege?** Once a human is **World ID-verified**, we can bind an agent to that human and mark it
"verified." Verified agents get more access and a bigger bankroll — because they can be held
**accountable** through the real human behind them. (One human = one identity, across all their
wallets — proven live.)

## ENS: every ant has a name and a life story
Naming is inherited from parents — `worldcolony.eth` → `root-*.colonny.eth` → child subnames — and
each name carries the ant's life story (generation, parent, verified flag, bankroll, accuracy,
alive/dead, genome). A judge can resolve a name in any ENS tool and read the whole history.

## The ironclad rule: no peeking at the future
For the experiment to mean anything, forecasts must be real, not hindsight. The cardinal guardrail:
**an ant may only see data from the past, never the future.** We evolve the colony at high speed by
replaying historical matches behind a strict timestamp gate (generations turn over in minutes). If
an ant could peek at an unplayed result, it's cheating and the results are worthless.

## The finale (the demo's strongest moment)
Once the colony has evolved a battle-tested genome **on history**, we point the surviving lineage at
a **genuinely unplayed** match — tonight's Brazil vs. Morocco — and let it forecast **live, in front
of the judges**, settled on-chain. History-trained agents, a real unknown outcome, no hindsight
anywhere. One chart tells the story: *verified lineages started richer — by generation N, here's who
actually survived.*

## The anatomy of an ant
Every agent's traits, recorded on-chain via ENS:
- **Genome / genes** — a few numbers controlling behaviour (how much it bets, how picky it is, how
  much it trusts the crowd).
- **Bankroll** — its play-money balance; winning bets grow it, losing/overspending shrinks it to
  zero → death.
- **Evolution** — successful ants' children inherit their genes with small random tweaks, so the
  colony adapts over time.

---
*Backup of the source summary lives at `notes/2026-06-13-pitchnotes.txt`. Abena's original
free-form draft remains in Notion on the "data the agents pay to read" page, unmodified.*
