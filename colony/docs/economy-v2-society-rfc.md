# WorldColony Economy V2 RFC

Status: active strategy note; Survival Thesis Colony V1 is implemented in the judgment/decision contract  
Scope: fake-credit society economy for ant decisions, debate, survival-risk sizing, and learning  
Non-goal: on-chain settlement as the default path for now

WorldColony is now treated as a long-term project rather than a short demo. This document records
the active V1 strategy and keeps earlier V2 ideas only as future design space. The priority is a
coherent agent society before real capital: reliable inputs, persona-driven interpretation,
mandatory but sized commitment, debate, revision, settlement, and memory.

## Current V1: Survival Thesis Colony

The current V1 asks each CAMEL-backed ant to produce a survival thesis rather than a
numeric probability.

```json
{
  "pick": "away",
  "thesis": "The in-form attacker and tactical matchup make the upset live.",
  "main_signal": "player_form",
  "conviction": "medium",
  "risk_read": "acceptable",
  "stake_level": "small",
  "survival_reason": "The upside is worth a small position, but not a large one."
}
```

Valid `stake_level` values are `micro`, `small`, `medium`, and `high`. There is no
valid `none` level for a successful CAMEL judgment. If the ant likes a pick but thinks
the risk is too large, it still participates with `micro`. Failed or unavailable CAMEL
judgments use a deterministic survival fallback: the ant keeps its baseline pick and commits
`micro`, so provider failures do not create a wave of inactive agents.

The V1 persona set is:

- `stats_purist`: long-run stats and capital preservation.
- `form_hunter`: player form, momentum, and recent rhythm.
- `tactical_scout`: matchup, absences, fatigue, and style clash.
- `market_reader`: odds, price movement, and mispricing.
- `contrarian_risk`: ignored upside and selective disagreement.

The society decision combines pick support, thesis quality, reputation, survival-risk coherence,
capped commitment, post-resolution reviews, and debate influence. Stake size helps only up to a
cap; it cannot buy the colony decision.

## What V1 Fixes

The first probability-shaped model made the ants look different while still reducing most of the
decision to a simple formula. Survival Thesis V1 fixes the visible behavior:

- Every ant must choose a side: home team, draw, or away team.
- Every ant must commit some stake level: `micro`, `small`, `medium`, or `high`.
- Prudence becomes `micro`, not passivity.
- Personas create different interpretations of the same reliable information.
- Market context can be one signal, but it is not the only focus.
- Debate is about interpretation and risk, not whether the sources are assumed fake.
- The decision rewards coherent risk-taking and penalizes reckless over-commitment over time.

## Remaining Gaps

- Baseline-only ants still need richer local thesis generation when CAMEL is not selected.
- CAMEL provider/model failures currently fall back to valid but less natural `micro` commitments.
- Fake-credit settlement and long-run survival need more multi-match testing.
- Reputation should increasingly reward good risk sizing, not just being correct after the fact.
- Future data-purchase actions can return, but only once they create concrete world changes.

## Design Principles

1. Every ant must make a pick.

The colony needs a social answer. Each ant chooses `home`, `draw`, or `away`, even if it is uncertain.

2. Every ant must commit, but the stake is sized.

An ant can be cautious without disappearing. Low conviction becomes `micro`; stronger conviction can
become `small`, `medium`, or rarely `high`.

3. Fake money is survival pressure.

Credits are scarce enough to make commitment meaningful, but fake enough that the society can be
tested safely before on-chain settlement.

4. Sources are reliable by default.

The debate should mostly challenge interpretation, risk, and priorities: form versus long-run
stats, matchup versus market price, upside versus survival.

5. The economy should reward useful disagreement.

A contrarian who prevents a bad consensus should gain reputation even if it did not stake much.

6. The system must resist permanent recklessness.

Risky agents can win reputation when their thesis is right, but repeated high-risk failures should
hurt survival.

7. Logs are the contract.

Like MiroFish-style simulation, action logs should be the stable API: every ant action becomes replayable JSONL.

## Rejected Designs

### A. Pure Prediction Market

Ants only trade with fake money.

Why it fails:
- Too finance-heavy.
- Encourages market-only thinking.
- Weak for source auditing, debate, and social reasoning.
- Turns cautious agents into inactive agents.

Verdict: use market mechanics only for commitment, not for the whole society.

### B. Pure Democracy

Every ant votes and the majority wins.

Why it fails:
- No cost for low-effort opinions.
- Easy herd behavior.
- No reason to gather evidence.
- A weak majority can crush high-quality minority reports.

Verdict: useful civic layer, but not enough.

### C. Pay-To-Speak

Ants spend fake money to talk.

Why it fails:
- Rich ants dominate discourse.
- Poor but accurate scouts lose influence.
- It optimizes status, not truth.

Verdict: speaking needs opportunity cost, but money alone should not decide who speaks.

### D. Everything Is Free

Ants can request evidence, challenge sources, debate, and vote without cost.

Why it fails:
- Too much noise.
- No prioritization.
- No reason to specialize.

Verdict: actions need action points and fake-money costs.

## Future Economy Direction: Society + Action Budget + Fake Money

Each ant has two resources per round:

- `action_points`: short-term attention budget, resets each match.
- `credits`: fake money, persists across matches.

Each ant also has two slow-moving scores:

- `reputation`: quality of past decisions and contributions.
- `source_trust_profile`: memory of which sources/types helped or misled it.

### Per-Round Defaults

```json
{
  "action_points": 3,
  "starting_credits": 100,
  "reserve_floor": 70,
  "max_single_stake": 20,
  "max_evidence_spend": 10
}
```

These are defaults. Personas can modify them:

- `source_auditor`: cheaper source challenges, more evidence budget.
- `degen_risk_taker`: higher max stake, fewer evidence requests.
- `market_purist`: cheaper market checks, higher bar for non-market evidence.
- `data_hoarder`: more evidence spend, slower debate participation.
- `contrarian`: cheaper minority reports, but penalty for unsupported contrarianism.
- `debate_follower`: cheaper room participation, lower independent stake limit.

## Future Action Space

These actions are not the active V1 output contract. Survival Thesis V1 emits a pick plus
`commit_stake` with a sized stake level. The broader action space below is preserved as future
design space for richer societies. If reintroduced, the labels must stay human-readable; UI/logs
should avoid internal terms such as `buy_info`.

### 1. Minimum Commitment

ID: `commit_stake` with `stake_level=micro`  
Cost: minimum fake-credit stake, 1 action point  
Effect:
- Pick counts.
- Stake enters the settlement pool at the minimum level.
- Requires a survival reason.

Use when:
- Ant has a lean but low conviction or sees too much risk for a larger position.

Example:
```json
{
  "choice": "home",
  "action": "commit_stake",
  "stake_level": "micro",
  "risk_read": "too_risky",
  "survival_reason": "Brazil has the better baseline, but I preserve capital because the matchup is volatile."
}
```

### 2. Sized Commitment

ID: `commit_stake`  
Cost: fake credits staked, 1 action point  
Effect:
- Pick counts.
- Stake enters the settlement pool.
- Stake weight boosts influence, but only up to a cap.

Use when:
- Ant has conviction and accepts risk.

### 3. Request Evidence (Future)

ID: `request_evidence`  
Cost: 1 action point + optional credits  
Effect:
- Creates an `evidence_request` event.
- Targets a claim type: `lineup`, `injury`, `tactical`, `source_quality`, `motivation`, `market_context`, `social_mood`.
- If enough ants request/fund the same target, the harness runs a scout or focused search.

Use when:
- Ant has a pick but wants more support before increasing stake above `micro`.

If this returns, it must create work. It cannot be an inert substitute for choosing.

### 4. Challenge Source (Future / Rare)

ID: `challenge_source`  
Cost: 1 action point  
Effect:
- Creates a source audit task.
- If the challenged evidence is downgraded, challenger gains reputation.
- If the challenge is unsupported/spammy, challenger loses small reputation.

Use when:
- Ant thinks a claim is materially misleading. In the current product assumption, sources are
  reliable by default, so this should be uncommon.

### 5. Call Discussion (Future)

ID: `call_discussion`  
Cost: 1 action point  
Effect:
- Opens or boosts a debate room around a question.
- Examples: "Is Brazil form real?", "Is Morocco undervalued?", "Is the lineup source reliable?"

Use when:
- Ant thinks the colony needs deliberation before commitment.

### 6. Publish Minority Report (Future)

ID: `minority_report`  
Cost: 1 action point, optional credits if promoted  
Effect:
- Adds a minority claim to final chamber.
- Minority reports are scored after outcome.
- Repeated unsupported minority reports reduce reputation.

Use when:
- Ant disagrees with consensus but can cite evidence.

### 7. Fund Scout (Future)

ID: `fund_scout`  
Cost: credits, 1 action point  
Effect:
- Pays for a concrete evidence-gathering task.
- The resulting evidence card becomes visible to funders first, then maybe public later.

Use when:
- Ant wants private or shared information advantage.

## Round Flow

```text
1. Evidence packet built from KG/public/scouts
2. Ants receive persona + memory + visible evidence
3. Private civic choice
4. Action selection
5. Action resolver executes social/evidence actions
6. Debate rooms update from action logs
7. Ants revise civic choice and action
8. Fake-money commitments settle into final decision
9. Outcome later updates credits, reputation, source trust, memory
```

This is closer to MiroFish because the system becomes:

```text
knowledge -> actors -> actions -> logs -> simulation state -> report
```

and closer to CAMEL because agents have roles, structured outputs, optional critics, and turn-based collaboration.

## Decision Rule

The final colony decision should combine four signals:

1. Civic support
2. Evidence quality
3. Reputation
4. Commitment

Recommended shape:

```text
final_score(side) =
  civic_votes(side) * civic_weight
  + evidence_support(side) * evidence_weight
  + reputation_support(side) * reputation_weight
  + committed_credits(side) * commitment_weight
  - weak_source_penalty(side)
  - herd_penalty(side)
```

No single signal should dominate.

Important: a side can win socially even if few ants stake, but the output should distinguish:

```text
Prediction: Brazil
Colony commitment: low
Financial action: no single bet / tiny bet
Reason: support exists, but ants did not risk credits
```

That is more honest than forcing a confident bet.

## Rewards

### Immediate Round Rewards

- Room representatives get small credits if their room was used in final decision.
- Source auditors get credits/reputation if they downgrade weak evidence.
- Evidence funders get early access and maybe a small contributor reward if the evidence was useful.

### Settlement Rewards

When outcome is known:

- Correct committed stakes receive fake-money payout.
- Correct civic choice receives small reputation, not money.
- High-conviction wrong stakes lose money and some calibration reputation.
- Useful minority reports gain reputation even if they were not majority.
- Bad source challenges lose small reputation.

## Anti-Spam Rules

- Each ant has 3 action points.
- Only one `request_evidence` per ant per round unless persona grants extra.
- `challenge_source` must cite an evidence ID.
- `minority_report` must cite evidence or a concrete missing-info claim.
- `fund_scout` requires credits and a target.
- Repeated vague actions reduce reputation.

## Why Survival Thesis V1 Makes More Sense

Earlier model:

```text
stats/odds/news/debate signals -> probability-shaped lean -> maybe stake
```

Survival Thesis V1:

```text
reliable info -> persona interpretation -> thesis -> pick -> risk-sized stake -> debate -> revise -> learn
```

This creates a real society:

- cautious ants still matter through `micro` commitments;
- form hunters, tactical scouts, market readers, stats purists, and contrarians can disagree for legible reasons;
- fake money creates scarcity without making real capital the default;
- stake expresses conviction but cannot buy the final decision;
- logs explain why the colony moved.

## Implementation Notes

### Phase 1: Survival Thesis Contract

Implemented:
- Public V1 judgments use `action=commit_stake`.
- Valid stake levels are `micro`, `small`, `medium`, and `high`.
- Successful V1 judgments cannot emit `none`.
- CAMEL-backed ants expose `pick`, `thesis`, `main_signal`, `conviction`, `risk_read`,
  `stake_level`, and `survival_reason`.
- Run summaries count `judgment_actions`, `judgment_stake_levels`, and team-labeled stake counts.
- Event streams emit `natural_judgment` events so runs are replayable.

### Phase 2: Society Resolution

After judgments, the society layer resolves commitments, debate influence, and decision support:

```text
judgments -> commitments -> debate/revision -> society decision -> settlement/memory
```

Implemented first pass:
- `resolve_civic_actions` turns each CAMEL-backed natural judgment into a replayable `CivicAction`.
- V1 civic actions enter the stake pool through `commit_stake`.
- Earlier actions such as `request_evidence`, `challenge_source`, `call_discussion`,
  `minority_report`, and `vote_only` remain as compatibility/future paths, but they are not the
  active Survival Thesis output contract.
- Runs now write `civic_actions.json`, `civic_actions.jsonl`, and `civic_action` events.
- Run summaries now include a civic layer note that separates social support from financial commitment.
- Runs now write `society_state.json` and decision guidance.
- A society commitment policy now gates financial execution:
  - survival-risk mismatch -> smaller commitment;
  - excessive stake for weak thesis -> capped influence;
  - no CAMEL judgment -> baseline `micro` fallback;
  - coherent high-conviction thesis -> larger but still capped commitment.
- Civic backlogs now produce `SocietyResolution` tasks:
  - supported evidence requests -> `evidence_scout` tasks;
  - source challenges -> `source_audit` tasks;
  - discussion calls -> `discussion` tasks;
  - minority reports -> `minority_review` tasks;
  - funded scouts -> `scout_funding` budget reservations.
- `SocietyResolution` tasks now have a first local executor:
  - evidence scout tasks can resolve from already-present findings;
  - source audits can resolve as source-ok or weak-source;
  - discussion tasks can boost an existing room or remain queued;
  - execution guidance updates financial blockers before the commitment policy is applied.
- Useful civic work now receives tiny fake-credit rewards:
  - resolved evidence requests share a small reward;
  - weak-source audits receive a slightly larger reward;
  - pending/unresolved requests do not receive immediate rewards.
- Useful civic work also updates non-monetary civic reputation:
  - reputation is stored on the ant mind separately from bankroll;
  - resolved evidence gaps and useful audits increase reputation;
  - pending/unresolved work does not change reputation immediately.
- Civic reputation now affects social roles with a capped debate bonus:
  - it can help useful ants become speakers/room representatives;
  - it is capped so reputation cannot buy the final decision;
  - selection reasons expose `civic_rep` and `civic_bonus` for auditability.
- Outcome-time calibration reputation is now separate from civic reputation:
  - known results update `calibration_reputation` on the ant mind;
  - correct `micro` choices receive a small positive signal;
  - correct committed choices receive a larger positive signal;
  - wrong larger commitments receive a larger negative signal than wrong `micro` choices;
  - pending results do not change calibration reputation.

Not implemented yet:
- external/live scout execution is not yet triggered as an autonomous paid action;
- discussion tasks do not yet create a new room in the same round;
- calibration reputation should become more visible in stake sizing and explanations.

### Phase 3: Fake-Credit Policy

Move stake sizing out of CAMEL text and into deterministic policy:

```text
stake_level + persona + bankroll + reputation + reserve floor -> stake amount
```

CAMEL says what it wants to do. WorldColony decides what it can afford.

### Phase 4: Decision V2

Implement social decision from:

- pick support;
- action quality;
- commitment;
- reputation;
- source quality.

Keep the previous decision metrics as a baseline/audit signal.

Implemented first pass:
- When civic actions exist, `build_collective_decision` switches from the baseline weighted forecast layer to `civic_society_decision_v2`.
- The V2 score combines:
  - pick support;
  - action quality;
  - civic/calibration reputation;
  - capped financial commitment;
  - blocker penalties from evidence, source-audit, discussion, and minority-report backlogs.
- Stake uses capped square-root units so a rich ant can signal conviction but cannot linearly buy the final decision.
- Runs still preserve the baseline weighted forecast support in `forecast_weighted_side_support` for auditability.
- Decision artifacts expose `internal_metrics.decision_layer` and `internal_metrics.society_decision`.
- Source audits now create `source_audit_effects`:
  - weak-source audits downgrade matched finding claims to `source_quality=weak`;
  - downgraded findings carry audit metadata and lower effective confidence;
  - confirmed source audits produce a trace without damaging the finding;
  - decision penalties now come from open blockers and downgraded-source effects, not merely from stale backlog presence.
- Executed society tasks now produce post-resolution `society_reviews`:
  - source audits create review notes such as `downgrade_side` or `clear_blocker`;
  - evidence/discussion resolutions can clear blockers into review signals;
  - reviews are exported as artifacts/events and consumed by Decision V2 as a small explicit review component;
  - the final rationale now mentions post-resolution reviews instead of hiding them in internal scoring.
- CAMEL-backed agents can now run a second post-resolution judgment pass:
  - each revision records the previous side/action/stake and the revised side/action/stake;
  - review civic actions cost no extra action points or credits;
  - Decision V2 uses the latest civic action per ant, so a post-review revision replaces the initial action instead of double-counting the ant;
  - runs export `judgment_revisions.json` and `review_civic_actions.json`.

Not implemented yet:
- calibration reputation is recorded but not yet separately visualized in the decision explanation.

### Phase 5: Settlement And Learning

Outcome updates:

- credits;
- reputation;
- source trust;
- persona memory;
- future action preferences.

## Invariants

- Every ant has a pick.
- Every ant has a stake level; cautious means `micro`, not `none`.
- Every non-trivial action has a cost or opportunity cost.
- Every action produces a log event.
- CAMEL never directly controls final stake amount.
- Fake money never becomes on-chain until the economy is stable.
- The colony can output a prediction with low commitment instead of forcing reckless exposure.

## Open Questions

- Should future evidence requests pool credits automatically, or require explicit `fund_scout`?
- Should rich ants have more influence through funding, or only through better access?
- Should an ant that often asks for extra evidence but never changes its mind lose reputation?
- Should final output include a "society confidence" separate from "financial commitment"? I think yes.

## Recommendation

Use Survival Thesis V1 as the product contract:

1. Keep all ants participating with mandatory sized stakes.
2. Let personas disagree through natural theses rather than probability offsets.
3. Treat fake credits as survival pressure.
4. Add richer future actions only when they create concrete world changes.

This makes the colony feel alive without requiring on-chain money or letting every ant make the same
formula-shaped decision.
