# World Colony — Working Messaging Brief

## Purpose

Use this document as context for another LLM that will review additional project materials and produce stronger positioning, product descriptions, hackathon copy, architecture explanations, and API documentation.

World Colony began as a World Cup-focused agent project, but the current direction is **general-purpose**. Do not describe it as only a sports, betting, or World Cup product.

## Current 500-Character Description

> World Colony is a swarm of low-cost, free AI agents that pool and trade information to reach auditable decisions. Each agent pays to query a shared knowledge graph, debates the evidence with the others, then logs a timestamped, verifiable verdict. Like ants moving a crumb no single one could lift, many cheap models together rival costly frontier AI — without its prices, rate limits or IP rules. A simple decision API lets any execution layer act on the colony's collective intelligence.

**Character count:** 488 characters, including spaces.

### Previous version (kept for reference)

> World Colony is a blockchain-powered swarm of low-cost, open AI agents that gathers information, debates options and produces auditable decisions. Like ants moving a crumb together, many small models can match the work of expensive proprietary AI without shifting prices, access limits or restrictive IP rules. A simple decision API lets any execution layer turn their collective intelligence into trades, transactions and other on-chain actions across sports, markets and general-purpose workflows.

## Core Idea

World Colony is an information-gathering and decision-making engine made from many low-cost AI agents. The agents can research, debate, compare evidence, reach decisions, and leave an auditable decision trail. Blockchain infrastructure can verify the process and support execution of resulting actions.

A separate execution layer can poll the agents' decision API and translate approved decisions into actions such as:

- trades;
- blockchain transactions;
- market participation;
- automated research workflows;
- governance actions;
- alerts or recommendations;
- other programmable tasks.

The system should be positioned as a general framework, not as a single-purpose World Cup application.

## Main Metaphor: Ants Versus an Excavator

An ant may weigh only about 0.1 grams and cannot move a one-gram crumb alone. A group of ants can coordinate and move it together.

The analogy:

- **Ants:** many inexpensive, focused, open or replaceable AI agents working together;
- **Crumb:** a task, question, decision, or blockchain action;
- **Excavator:** one large proprietary frontier model or centralized AI provider.

An excavator can perform the task, but it may be excessive and expensive. Its price, rate limits, access rules, product requirements, or acceptable-use policies may change. A swarm of smaller agents can provide a cheaper, more resilient and less permission-dependent alternative.

Use the metaphor to communicate coordination and economics. Avoid making absolute technical or legal claims that cannot be proven, such as saying the system literally has “no rules” or can never be controlled.

## Positioning Themes

1. **Collective intelligence**  
   Many small agents combine research and judgment to perform work that may otherwise require a large model.

2. **Low-cost inference**  
   The architecture is intended to use inexpensive models and specialized agents instead of depending entirely on costly frontier models.

3. **Open and replaceable components**  
   Agents and models should be interchangeable where practical, reducing dependence on one vendor.

4. **Auditable decisions**  
   Decisions should be logged with timestamps, evidence, confidence, and agent contributions.

5. **Blockchain-powered execution**  
   Blockchain can verify decisions, preserve records, coordinate agents, handle payments, and execute transactions.

6. **Separation of decision and execution**  
   The ant swarm produces decisions. An external execution layer reads those decisions and performs the final action.

7. **General-purpose design**  
   Sports predictions are one demonstration, not the product boundary.

## Current Decision API Concept

The execution layer should be able to poll an API for one or more decisions.

### Existing Domain-Specific Schema

```json
{
  "uuid": "string",
  "timestamp": "ISO-8601 datetime",
  "event_name": "string",
  "decision": "win | lose | draw",
  "side": "home | away",
  "team_choice": "string",
  "confidence": 0.0
}
```

### Suggested General-Purpose Evolution

The present schema works for sports, but a generic system should not require `home`, `away`, `team_choice`, or `win/lose/draw`.

```json
{
  "uuid": "string",
  "timestamp": "ISO-8601 datetime",
  "domain": "sports | markets | governance | research | other",
  "event_name": "string",
  "question": "string",
  "decision_type": "classification | ranking | prediction | action",
  "decision": "string or structured object",
  "selected_option": "string",
  "confidence": 0.0,
  "evidence": [],
  "agent_votes": [],
  "status": "proposed | approved | rejected | executed",
  "execution_payload": {},
  "chain_reference": "optional string"
}
```

The final API design should clarify whether confidence is represented from `0–1` or `0–100`, how conflicting decisions are handled, and what makes a decision final.

## Architecture in Plain Language

1. A task or question enters World Colony.
2. Multiple low-cost agents gather information independently or collaboratively.
3. Agents share evidence, challenge assumptions, debate, or vote.
4. The system aggregates their conclusions.
5. A structured decision is written to an auditable log.
6. A client polls or subscribes to the decision API.
7. The client's execution layer validates the decision and performs the corresponding action.
8. Execution status and transaction references are written back to the log.

## Messaging Guardrails

### Emphasize

- swarm coordination;
- affordable, specialized agents;
- transparent decision logs;
- vendor independence;
- composable APIs;
- blockchain verification and execution;
- applications beyond sports.

### Avoid

- presenting World Colony as only a betting bot;
- claiming small models always outperform frontier models;
- saying agents have literally “no rules”;
- implying all intellectual-property restrictions disappear automatically;
- suggesting the system executes irreversible transactions without validation;
- describing blockchain as necessary for every internal operation;
- retaining World Cup terminology in the generic core architecture.

## Source Notes

The current brief is based on:

- the written World Colony description;
- the ant-versus-excavator analogy;
- notes about open, low-cost, IP-independent agents;
- the proposed decision-log API;
- the proposed separation between Tanguy's decision API and the execution layer;
- two audio recordings supplied on June 19, 2026;
- the instruction to pivot the hackathon project from World Cup-specific to general-purpose infrastructure.

Audio files supplied:

- `2026-06-19 09.53.17.ogg`
- `2026-06-19 09.53.21.ogg`

When the recordings or future materials conflict with this brief, identify the conflict rather than silently choosing one version.

## Instructions for a Future LLM

Review all supplied materials before rewriting the project description.

Your tasks:

1. Extract recurring ideas, technical facts, metaphors, user problems, differentiators, and unsupported claims.
2. Separate the current implemented product from the long-term vision.
3. Determine the intended audience for each version: judges, developers, investors, users, or partners.
4. Preserve the swarm-of-ants metaphor, but make it credible and concise.
5. Explain why multiple inexpensive agents are useful without attacking proprietary model providers.
6. Treat sports and World Cup predictions as a demonstration or vertical, not the platform definition.
7. Explain the boundary between the decision engine and the execution layer.
8. Recommend a generic API schema while preserving backward compatibility with the sports schema.
9. Produce evidence-based copy and mark any claim that requires validation.
10. Return several deliverables:
   - a one-sentence tagline;
   - a 280-character description;
   - a description of no more than 500 characters;
   - a 100-word description;
   - a developer-focused architecture summary;
   - a judge-facing hackathon pitch;
   - a list of claims that need proof.

## Questions Future Materials Should Resolve

- Are the agents fully open source, or are only some models and components open?
- What exactly is stored or verified on-chain?
- How do agents communicate, debate, and reach consensus?
- How are low-quality or malicious agents detected?
- Is the decision log append-only?
- Who can submit tasks and who can approve execution?
- Does the execution layer poll, use webhooks, or subscribe to an event stream?
- What chains and transaction types are supported?
- How are inference costs measured against frontier-model alternatives?
- What parts are implemented today?
- What parts are still a hackathon prototype?
- What is the first non-sports use case?
- What is the clearest user problem World Colony solves?

## Working Tagline Directions

These are exploratory, not final:

- **Small agents. Collective intelligence. Verifiable action.**
- **A colony of open agents that researches, decides and acts.**
- **Affordable AI swarms for auditable on-chain decisions.**
- **Many small minds. One verifiable decision layer.**
