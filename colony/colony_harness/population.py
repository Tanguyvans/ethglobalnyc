"""Population state persistence for Colony harness runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agent import AntAgent
from .genes import Genome


POPULATION_SCHEMA_VERSION = 1


def agent_to_state(agent: AntAgent) -> dict[str, Any]:
    state = {
        "agent_id": agent.agent_id,
        "name": agent.name,
        "genome_id": agent.genome_id,
        "generation": agent.generation,
        "bankroll": round(agent.bankroll, 4),
        "accuracy": round(agent.accuracy, 4),
        "wallet_address": agent.wallet_address,
        "genome": agent.genome.to_dict(),
    }
    if agent.evolution_role:
        state["evolution_role"] = agent.evolution_role
    if agent.parent_genome_id:
        state["parent_genome_id"] = agent.parent_genome_id
    if agent.previous_genome_id:
        state["previous_genome_id"] = agent.previous_genome_id
    if agent.last_settlement:
        state["last_settlement"] = agent.last_settlement
    return state


def agent_from_state(data: dict[str, Any]) -> AntAgent:
    genome = Genome.from_dict(data["genome"])
    expected_genome_id = str(data.get("genome_id") or "")
    if expected_genome_id and expected_genome_id != genome.stable_id():
        raise ValueError(
            f"Population state genome_id mismatch for {data.get('agent_id')}: "
            f"{expected_genome_id} != {genome.stable_id()}"
        )
    return AntAgent(
        agent_id=str(data["agent_id"]),
        name=str(data.get("name") or data["agent_id"]).replace("_", "-"),
        generation=int(data.get("generation") or 0),
        genome=genome,
        bankroll=float(data.get("bankroll") or 0.0),
        accuracy=float(data.get("accuracy") or 0.0),
        wallet_address=str(data.get("wallet_address") or ""),
        evolution_role=str(data.get("evolution_role") or ""),
        parent_genome_id=str(data.get("parent_genome_id") or ""),
        previous_genome_id=str(data.get("previous_genome_id") or ""),
        last_settlement=dict(data.get("last_settlement") or {}),
    )


def population_to_state(
    agents: list[AntAgent],
    *,
    seed: int,
    note: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": POPULATION_SCHEMA_VERSION,
        "seed": seed,
        "note": note,
        "population_size": len(agents),
        "agents": [agent_to_state(agent) for agent in agents],
    }


def save_population_state(
    path: str | Path,
    agents: list[AntAgent],
    *,
    seed: int,
    note: str = "",
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = population_to_state(agents, seed=seed, note=note)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def load_population_state(path: str | Path) -> list[AntAgent]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if int(payload.get("schema_version") or 0) != POPULATION_SCHEMA_VERSION:
        raise ValueError(f"Unsupported population schema_version in {source}")
    agents = [agent_from_state(record) for record in payload.get("agents") or []]
    if not agents:
        raise ValueError(f"Population state has no agents: {source}")
    _validate_unique_ids(agents)
    return agents


def _validate_unique_ids(agents: list[AntAgent]) -> None:
    agent_ids = [agent.agent_id for agent in agents]
    duplicate_agent_ids = sorted({agent_id for agent_id in agent_ids if agent_ids.count(agent_id) > 1})
    if duplicate_agent_ids:
        raise ValueError(f"Duplicate agent_id values in population state: {duplicate_agent_ids}")
