"""Tests for civic reputation in social role selection."""

from __future__ import annotations

import unittest

from .agent import AntAgent
from .genes import Genome, SourceWeights
from .harness import _civic_reputation_debate_bonus, _debate_score


def _genome() -> Genome:
    return Genome(
        estimator="poisson",
        model="parametric",
        risk_appetite=0.1,
        edge_threshold=0.02,
        source_weights=SourceWeights(stats=0.25, odds=0.25, news=0.25, debate=0.25),
        herd_bias=0.0,
        query_budget=1.0,
        persona="test ant",
    )


def _agent(agent_id: str, *, reputation: float = 0.0, bankroll: float = 100.0, accuracy: float = 0.5) -> AntAgent:
    return AntAgent(
        agent_id=agent_id,
        name=agent_id.replace("_", "-"),
        generation=0,
        genome=_genome(),
        bankroll=bankroll,
        accuracy=accuracy,
        mind={"civic_reputation": {"score": reputation, "events": []}},
    )


class CivicReputationSelectionTests(unittest.TestCase):
    def test_civic_reputation_increases_debate_score(self) -> None:
        neutral = _agent("ant_0001", reputation=0.0)
        useful = _agent("ant_0002", reputation=0.4)

        self.assertGreater(_debate_score(useful), _debate_score(neutral))
        self.assertEqual(_civic_reputation_debate_bonus(useful), 4.8)

    def test_civic_reputation_bonus_is_capped(self) -> None:
        very_high = _agent("ant_0001", reputation=10.0)
        very_low = _agent("ant_0002", reputation=-10.0)

        self.assertEqual(_civic_reputation_debate_bonus(very_high), 6.0)
        self.assertEqual(_civic_reputation_debate_bonus(very_low), -4.0)

    def test_civic_reputation_cannot_fully_override_large_capital_gap(self) -> None:
        rich_neutral = _agent("ant_0001", reputation=0.0, bankroll=120.0)
        poor_reputed = _agent("ant_0002", reputation=1.0, bankroll=100.0)

        self.assertGreater(_debate_score(rich_neutral), _debate_score(poor_reputed))


if __name__ == "__main__":
    unittest.main()
