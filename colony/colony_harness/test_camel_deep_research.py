"""Tests for CAMEL deep-research claim normalization."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


COLONY_DIR = Path(__file__).resolve().parents[1]
if str(COLONY_DIR) not in sys.path:
    sys.path.insert(0, str(COLONY_DIR))

from colony_harness import live_scouts  # noqa: E402


class CamelDeepResearchTests(unittest.TestCase):
    def test_native_payload_becomes_source_grounded_evidence_claim(self) -> None:
        role = live_scouts.CamelResearchRole(
            role_id="availability_lineup",
            query_template="{home_team} {away_team} injuries",
            focus="injury and lineup status",
            claim_types=("injury_availability", "lineup"),
        )

        claim = live_scouts._claim_from_camel_payload(
            {
                "claim_type": "injury_availability",
                "subject": "Neymar",
                "team": "Brazil",
                "player": "Neymar",
                "claim": "Brazil forward Neymar will miss the Haiti match because of a calf injury.",
                "confidence": 0.81,
                "source_title": "Brazil team news",
                "source_url": "https://www.bbc.com/sport/football/example",
                "source_published": "2026-06-19",
                "metrics": {"status": "out"},
            },
            role=role,
            home_team="Brazil",
            away_team="Haiti",
            known_players={"Brazil": ["Neymar"], "Haiti": []},
        )

        self.assertIsNotNone(claim)
        assert claim is not None
        self.assertEqual(claim.claim_type, "injury_availability")
        self.assertEqual(claim.team, "Brazil")
        self.assertEqual(claim.player, "Neymar")
        self.assertEqual(claim.impact, "negative_home")
        self.assertEqual(claim.metrics["camel_role"], "availability_lineup")
        self.assertTrue(claim.metrics["camel_native"])
        self.assertEqual(live_scouts._critic_filter_camel_claims([claim]), [claim])

    def test_native_payload_without_source_url_is_rejected(self) -> None:
        role = live_scouts.CamelResearchRole(
            role_id="tactical_matchup",
            query_template="{home_team} {away_team} tactical",
            focus="tactical matchup",
            claim_types=("tactical",),
        )

        claim = live_scouts._claim_from_camel_payload(
            {
                "claim_type": "tactical",
                "team": "Brazil",
                "claim": "Brazil are expected to press high and attack through both wide channels.",
                "source_title": "No source",
            },
            role=role,
            home_team="Brazil",
            away_team="Haiti",
            known_players=None,
        )

        self.assertIsNone(claim)


if __name__ == "__main__":
    unittest.main()
