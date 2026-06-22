"""Qualitative ant minds and society traits.

The LLM-facing layer is intentionally narrative. Numeric parameters are kept in
compiled policies so the simulation remains deterministic without making the
agent prompt read like a spreadsheet.
"""

from __future__ import annotations

import random
from copy import deepcopy
from dataclasses import replace
from typing import Any

from .genes import Genome, SourceWeights


ARCHETYPE_ORDER = [
    "rich_safe_allocator",
    "degen_risk_taker",
    "sentiment_scout",
    "market_purist",
    "debate_follower",
    "contrarian",
    "source_auditor",
    "data_hoarder",
    "public_signal_ant",
    "lineage_loyalist",
]


ARCHETYPE_CARDS: dict[str, dict[str, Any]] = {
    "rich_safe_allocator": {
        "label": "rich safe allocator",
        "belief": "Capital preservation beats heroic calls.",
        "voice": "calm, patient, and skeptical of noisy excitement",
        "risk_style": "cautious",
        "data_style": "premium market and statistical data",
        "debate_style": "listens politely but resists herd moves",
        "wealth_behavior": "protects bankroll before chasing upside",
        "trust_style": "trusts audited evidence and mature lineages",
        "learning_style": "slowly updates after repeated proof",
        "ambition": "stay elite across many rounds",
        "fear": "being dragged into fashionable late risk",
        "policy": {
            "source_weights": {"stats": 0.35, "odds": 0.45, "news": 0.10, "debate": 0.10},
            "risk_appetite": 0.045,
            "edge_threshold": 0.13,
            "query_budget": 1.8,
            "herd_bias": -0.25,
            "stake_multiplier": 0.55,
            "debate_multiplier": 0.35,
            "memory_recall_depth": 8,
        },
    },
    "degen_risk_taker": {
        "label": "degen risk taker",
        "belief": "Small edges only matter if the upside is alive.",
        "voice": "fast, hungry, and emotionally reactive",
        "risk_style": "aggressive",
        "data_style": "momentum, odds moves, and debate heat",
        "debate_style": "jumps into fights and follows big swings",
        "wealth_behavior": "uses bankroll as ammunition",
        "trust_style": "trusts recent winners and dramatic signals",
        "learning_style": "learns hard lessons after drawdowns",
        "ambition": "jump social class quickly",
        "fear": "surviving while staying irrelevant",
        "policy": {
            "source_weights": {"stats": 0.12, "odds": 0.30, "news": 0.28, "debate": 0.30},
            "risk_appetite": 0.21,
            "edge_threshold": 0.02,
            "query_budget": 0.9,
            "herd_bias": 0.45,
            "stake_multiplier": 1.65,
            "debate_multiplier": 1.15,
            "memory_recall_depth": 4,
        },
    },
    "sentiment_scout": {
        "label": "sentiment scout",
        "belief": "Mood and availability move markets before tables do.",
        "voice": "observant, narrative-driven, and detail hungry",
        "risk_style": "balanced",
        "data_style": "news, social mood, injuries, and squad stories",
        "debate_style": "asks what the crowd is missing emotionally",
        "wealth_behavior": "spends on context when the story is live",
        "trust_style": "trusts fresh human signals over stale averages",
        "learning_style": "remembers which narratives were fake",
        "ambition": "prove soft signals can beat cold pricing",
        "fear": "mistaking noise for conviction",
        "policy": {
            "source_weights": {"stats": 0.10, "odds": 0.15, "news": 0.60, "debate": 0.15},
            "risk_appetite": 0.095,
            "edge_threshold": 0.06,
            "query_budget": 1.5,
            "herd_bias": 0.15,
            "stake_multiplier": 0.90,
            "debate_multiplier": 0.80,
            "memory_recall_depth": 7,
        },
    },
    "market_purist": {
        "label": "market purist",
        "belief": "The price is usually smarter than the room.",
        "voice": "dry, precise, and allergic to unsupported stories",
        "risk_style": "selective",
        "data_style": "odds, liquidity, price movement, and mispricing",
        "debate_style": "ignores debate unless it explains price",
        "wealth_behavior": "waits for clean value instead of activity",
        "trust_style": "trusts market structure before personalities",
        "learning_style": "updates when pricing memories show blind spots",
        "ambition": "outlast the narrative traders",
        "fear": "being fooled by charismatic speakers",
        "policy": {
            "source_weights": {"stats": 0.10, "odds": 0.75, "news": 0.05, "debate": 0.10},
            "risk_appetite": 0.075,
            "edge_threshold": 0.08,
            "query_budget": 1.2,
            "herd_bias": -0.55,
            "stake_multiplier": 0.80,
            "debate_multiplier": 0.20,
            "memory_recall_depth": 5,
        },
    },
    "debate_follower": {
        "label": "debate follower",
        "belief": "The colony sees more than any single ant.",
        "voice": "social, adaptive, and consensus-seeking",
        "risk_style": "balanced",
        "data_style": "room summaries, reputations, and final synthesis",
        "debate_style": "moves strongly when respected ants converge",
        "wealth_behavior": "bets with the group to survive",
        "trust_style": "trusts high-reputation speakers",
        "learning_style": "tracks who changed its mind correctly",
        "ambition": "belong to the winning room",
        "fear": "missing a social signal everyone else saw",
        "policy": {
            "source_weights": {"stats": 0.10, "odds": 0.10, "news": 0.15, "debate": 0.65},
            "risk_appetite": 0.10,
            "edge_threshold": 0.055,
            "query_budget": 0.75,
            "herd_bias": 0.75,
            "stake_multiplier": 1.00,
            "debate_multiplier": 1.45,
            "memory_recall_depth": 6,
        },
    },
    "contrarian": {
        "label": "contrarian",
        "belief": "Crowded certainty is where mistakes hide.",
        "voice": "sharp, independent, and suspicious of consensus",
        "risk_style": "bold but selective",
        "data_style": "disconfirming evidence and minority reports",
        "debate_style": "pushes against easy agreement",
        "wealth_behavior": "risks capital only when disagreement is real",
        "trust_style": "trusts well-sourced dissent",
        "learning_style": "remembers when rebellion was just ego",
        "ambition": "win reputation by being early against the room",
        "fear": "becoming a reflexive no-machine",
        "policy": {
            "source_weights": {"stats": 0.25, "odds": 0.30, "news": 0.20, "debate": 0.25},
            "risk_appetite": 0.14,
            "edge_threshold": 0.045,
            "query_budget": 1.1,
            "herd_bias": -0.80,
            "stake_multiplier": 1.20,
            "debate_multiplier": -0.70,
            "memory_recall_depth": 6,
        },
    },
    "source_auditor": {
        "label": "source auditor",
        "belief": "A weak source can poison an entire colony.",
        "voice": "methodical, citation-focused, and hard to impress",
        "risk_style": "cautious",
        "data_style": "freshness, provenance, and source quality",
        "debate_style": "challenges claims before challenging teams",
        "wealth_behavior": "pays for verification before conviction",
        "trust_style": "trusts traceable evidence",
        "learning_style": "builds a ledger of reliable domains",
        "ambition": "become the room's quality filter",
        "fear": "letting a bad citation become consensus",
        "policy": {
            "source_weights": {"stats": 0.35, "odds": 0.25, "news": 0.30, "debate": 0.10},
            "risk_appetite": 0.055,
            "edge_threshold": 0.11,
            "query_budget": 1.9,
            "herd_bias": -0.15,
            "stake_multiplier": 0.65,
            "debate_multiplier": 0.55,
            "memory_recall_depth": 9,
        },
    },
    "data_hoarder": {
        "label": "data hoarder",
        "belief": "Depth compounds; shallow summaries decay.",
        "voice": "quiet, exhaustive, and privately confident",
        "risk_style": "measured",
        "data_style": "private findings, stats, and complete context",
        "debate_style": "speaks when it has evidence others lack",
        "wealth_behavior": "spends bankroll on information advantage",
        "trust_style": "trusts its own archive before loud claims",
        "learning_style": "turns past records into future filters",
        "ambition": "own the best memory in the colony",
        "fear": "paying for data that arrives too late",
        "policy": {
            "source_weights": {"stats": 0.45, "odds": 0.25, "news": 0.25, "debate": 0.05},
            "risk_appetite": 0.085,
            "edge_threshold": 0.07,
            "query_budget": 2.3,
            "herd_bias": -0.10,
            "stake_multiplier": 0.75,
            "debate_multiplier": 0.35,
            "memory_recall_depth": 10,
        },
    },
    "public_signal_ant": {
        "label": "public signal ant",
        "belief": "Cheap public signals can still be enough.",
        "voice": "practical, accessible, and budget-aware",
        "risk_style": "cautious-balanced",
        "data_style": "public news, summaries, and visible consensus",
        "debate_style": "uses the room to compensate for cheap data",
        "wealth_behavior": "avoids expensive signals unless forced",
        "trust_style": "trusts broad public agreement",
        "learning_style": "remembers which free signals worked",
        "ambition": "survive without premium access",
        "fear": "being permanently outclassed by rich ants",
        "policy": {
            "source_weights": {"stats": 0.25, "odds": 0.20, "news": 0.35, "debate": 0.20},
            "risk_appetite": 0.065,
            "edge_threshold": 0.09,
            "query_budget": 0.45,
            "herd_bias": 0.25,
            "stake_multiplier": 0.70,
            "debate_multiplier": 0.85,
            "memory_recall_depth": 5,
        },
    },
    "lineage_loyalist": {
        "label": "lineage loyalist",
        "belief": "A proven lineage is a memory older than one ant.",
        "voice": "loyal, historical, and proud",
        "risk_style": "balanced",
        "data_style": "ancestral lessons, debate, and remembered patterns",
        "debate_style": "trusts familiar lineages before strangers",
        "wealth_behavior": "protects lineage capital and reputation",
        "trust_style": "trusts relatives and inherited strategy",
        "learning_style": "updates through family success or shame",
        "ambition": "extend the family tree",
        "fear": "breaking the lineage with a careless bet",
        "policy": {
            "source_weights": {"stats": 0.25, "odds": 0.20, "news": 0.15, "debate": 0.40},
            "risk_appetite": 0.095,
            "edge_threshold": 0.065,
            "query_budget": 1.0,
            "herd_bias": 0.45,
            "stake_multiplier": 0.95,
            "debate_multiplier": 1.05,
            "memory_recall_depth": 7,
        },
    },
}


def build_agent_mind(
    *,
    agent_id: str,
    genome: Genome,
    bankroll: float,
    accuracy: float,
    generation: int,
    rng: random.Random,
    index: int,
    existing: dict | None = None,
) -> dict:
    if isinstance(existing, dict) and existing.get("archetype") in ARCHETYPE_CARDS:
        mind = deepcopy(existing)
        mind["social_class"] = social_class_for(bankroll=bankroll, accuracy=accuracy, generation=generation)
        mind.setdefault("life_status", "alive")
        mind.setdefault("memory_summary", {})
        return mind

    archetype = _choose_archetype(index=index, genome=genome, rng=rng)
    card = ARCHETYPE_CARDS[archetype]
    return {
        "schema_version": 1,
        "agent_id": agent_id,
        "archetype": archetype,
        "label": card["label"],
        "social_class": social_class_for(bankroll=bankroll, accuracy=accuracy, generation=generation),
        "risk_style": card["risk_style"],
        "data_style": card["data_style"],
        "debate_style": card["debate_style"],
        "wealth_behavior": card["wealth_behavior"],
        "trust_style": card["trust_style"],
        "learning_style": card["learning_style"],
        "voice_style": card["voice"],
        "belief": card["belief"],
        "ambition": card["ambition"],
        "fear": card["fear"],
        "llm_model": genome.model,
        "life_status": "alive",
        "memory_summary": {},
        "compiled_policy": deepcopy(card["policy"]),
    }


def apply_mind_to_genome(genome: Genome, mind: dict) -> Genome:
    policy = dict(mind.get("compiled_policy") or {})
    source_weights = dict(policy.get("source_weights") or {})
    if not source_weights:
        return genome
    return replace(
        genome,
        source_weights=SourceWeights(
            stats=float(source_weights.get("stats", 0.25)),
            odds=float(source_weights.get("odds", 0.25)),
            news=float(source_weights.get("news", 0.25)),
            debate=float(source_weights.get("debate", 0.25)),
        ).normalized(),
        risk_appetite=float(policy.get("risk_appetite", genome.risk_appetite)),
        edge_threshold=float(policy.get("edge_threshold", genome.edge_threshold)),
        query_budget=float(policy.get("query_budget", genome.query_budget)),
        herd_bias=float(policy.get("herd_bias", genome.herd_bias)),
        persona=str(mind.get("label") or genome.persona),
    )


def refresh_mind_after_round(agent_mind: dict, *, bankroll: float, accuracy: float, generation: int) -> dict:
    mind = deepcopy(agent_mind or {})
    before = mind.get("social_class") or "unknown"
    after = social_class_for(bankroll=bankroll, accuracy=accuracy, generation=generation, settled=True)
    mind["social_class"] = after
    if after in {"fallen", "retired"}:
        mind["life_status"] = after
    else:
        mind.setdefault("life_status", "alive")
    mind.setdefault("class_history", []).append({"from": before, "to": after})
    return mind


def class_transition(agent_id: str, before: dict, after: dict) -> dict:
    return {
        "agent_id": agent_id,
        "from": (before or {}).get("social_class") or "unknown",
        "to": (after or {}).get("social_class") or "unknown",
        "archetype": (after or {}).get("archetype") or (before or {}).get("archetype") or "",
        "changed": ((before or {}).get("social_class") or "") != ((after or {}).get("social_class") or ""),
    }


def mind_public_card(mind: dict) -> dict:
    return {
        "agent_id": mind.get("agent_id", ""),
        "archetype": mind.get("archetype", ""),
        "label": mind.get("label", ""),
        "social_class": mind.get("social_class", ""),
        "life_status": mind.get("life_status", "alive"),
        "belief": mind.get("belief", ""),
        "risk_style": mind.get("risk_style", ""),
        "data_style": mind.get("data_style", ""),
        "debate_style": mind.get("debate_style", ""),
        "wealth_behavior": mind.get("wealth_behavior", ""),
        "trust_style": mind.get("trust_style", ""),
        "learning_style": mind.get("learning_style", ""),
        "voice_style": mind.get("voice_style", ""),
        "ambition": mind.get("ambition", ""),
        "fear": mind.get("fear", ""),
        "memory_summary": mind.get("memory_summary") or {},
    }


def mind_one_line(mind: dict) -> str:
    label = mind.get("label") or mind.get("archetype") or "unknown ant"
    social_class = mind.get("social_class") or "unknown class"
    belief = mind.get("belief") or "no stated belief"
    return f"{label} / {social_class}: {belief}"


def stake_multiplier(mind: dict) -> float:
    return float((mind.get("compiled_policy") or {}).get("stake_multiplier", 1.0))


def debate_multiplier(mind: dict) -> float:
    return float((mind.get("compiled_policy") or {}).get("debate_multiplier", 1.0))


def memory_recall_depth(mind: dict) -> int:
    return int((mind.get("compiled_policy") or {}).get("memory_recall_depth", 6))


def memory_influence_weight(mind: dict) -> float:
    explicit = (mind.get("compiled_policy") or {}).get("memory_influence")
    if isinstance(explicit, int | float):
        return float(explicit)
    archetype = str(mind.get("archetype") or "")
    weights = {
        "data_hoarder": 0.18,
        "lineage_loyalist": 0.14,
        "source_auditor": 0.12,
        "sentiment_scout": 0.10,
        "debate_follower": 0.09,
        "market_purist": 0.07,
        "contrarian": 0.06,
        "rich_safe_allocator": 0.06,
        "degen_risk_taker": 0.04,
        "public_signal_ant": 0.08,
    }
    return weights.get(archetype, 0.08)


def social_class_for(
    *,
    bankroll: float,
    accuracy: float,
    generation: int,
    settled: bool = False,
    status: str = "alive",
) -> str:
    if status in {"dead", "retired"}:
        return status
    if bankroll < 25 or accuracy < 0.38:
        return "fallen"
    if not settled and generation == 0:
        return "newborn"
    if bankroll >= 180 and accuracy >= 0.58:
        return "elite"
    if bankroll >= 120:
        return "comfortable"
    if bankroll >= 60:
        return "middle"
    return "poor"


def memory_seed_for_mind(mind: dict) -> str:
    return (
        f"{mind.get('label', 'This ant')} believes: {mind.get('belief', '')} "
        f"It acts as {mind.get('risk_style', 'balanced')} risk, seeks {mind.get('data_style', 'mixed data')}, "
        f"and debates by: {mind.get('debate_style', 'listening selectively')}."
    )


def _choose_archetype(*, index: int, genome: Genome, rng: random.Random) -> str:
    persona = genome.persona.lower()
    if "contrarian" in persona or "value" in persona:
        return "contrarian" if index % 2 else "market_purist"
    if "scout" in persona or "news" in persona:
        return "sentiment_scout"
    if "skeptic" in persona:
        return "source_auditor"
    if "crowd" in persona:
        return "debate_follower"
    if "model" in persona or "probabilist" in persona:
        return "data_hoarder" if index % 3 == 0 else "market_purist"
    if "risk" in persona:
        return "degen_risk_taker"
    if rng.random() < 0.08:
        return rng.choice(ARCHETYPE_ORDER)
    return ARCHETYPE_ORDER[index % len(ARCHETYPE_ORDER)]
