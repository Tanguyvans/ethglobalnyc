"""Bounded debate feed."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import DebateClaim


@dataclass
class DebateFeed:
    claims: list[DebateClaim] = field(default_factory=list)

    def append(self, claim: DebateClaim) -> None:
        self.claims.append(claim)

    def consensus_home_probability(self) -> float | None:
        if not self.claims:
            return None
        weighted_sum = 0.0
        total_weight = 0.0
        for claim in self.claims:
            weight = max(claim.confidence, 0.05)
            weighted_sum += claim.stated_home_probability * weight
            total_weight += weight
        return weighted_sum / max(total_weight, 1e-9)

    def to_jsonl_events(self) -> list[dict]:
        return [{"event_type": "debate_claim", **claim.to_dict()} for claim in self.claims]
