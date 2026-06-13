"""Genome definitions for Colony agents."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass
from typing import Literal


Estimator = Literal["poisson", "llm"]
ModelSpecies = Literal["deepseek-v3.2", "qwen-3", "minimax-m2", "claude-haiku", "parametric"]


PERSONA_TRAITS = [
    "cold probabilist",
    "market contrarian",
    "news-sensitive scout",
    "risk-on striker",
    "defensive skeptic",
    "crowd watcher",
    "model maximalist",
    "quiet value hunter",
]


@dataclass(frozen=True)
class SourceWeights:
    stats: float
    odds: float
    news: float
    debate: float

    def normalized(self) -> "SourceWeights":
        total = max(self.stats + self.odds + self.news + self.debate, 1e-9)
        return SourceWeights(
            stats=self.stats / total,
            odds=self.odds / total,
            news=self.news / total,
            debate=self.debate / total,
        )

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class Genome:
    estimator: Estimator
    model: ModelSpecies
    risk_appetite: float
    edge_threshold: float
    source_weights: SourceWeights
    herd_bias: float
    query_budget: float
    persona: str

    def public_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        data = asdict(self)
        data["source_weights"] = self.source_weights.to_dict()
        return data


def _random_weights(rng: random.Random) -> SourceWeights:
    raw = [rng.random() + 0.05 for _ in range(4)]
    total = sum(raw)
    return SourceWeights(
        stats=raw[0] / total,
        odds=raw[1] / total,
        news=raw[2] / total,
        debate=raw[3] / total,
    )


def random_genome(rng: random.Random, llm_probability: float = 0.18) -> Genome:
    estimator: Estimator = "llm" if rng.random() < llm_probability else "poisson"
    if estimator == "llm":
        model: ModelSpecies = rng.choice(["deepseek-v3.2", "qwen-3", "minimax-m2", "claude-haiku"])
    else:
        model = "parametric"

    return Genome(
        estimator=estimator,
        model=model,
        risk_appetite=round(rng.uniform(0.02, 0.18), 4),
        edge_threshold=round(rng.uniform(0.01, 0.18), 4),
        source_weights=_random_weights(rng).normalized(),
        herd_bias=round(rng.uniform(-1.0, 1.0), 4),
        query_budget=round(rng.uniform(0.1, 2.0), 4),
        persona=rng.choice(PERSONA_TRAITS),
    )
