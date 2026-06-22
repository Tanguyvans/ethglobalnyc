"""Tests for the Colony evaluation harness."""

from __future__ import annotations

import unittest

from colony.evaluate_colony import (
    default_scenarios,
    parse_int_list,
    score_forecasts,
    summarize_matrix,
    target_home_probability,
)

from .models import Forecast


def _forecast(*, agent_id: str, side: str, home_probability: float, stake: float = 10.0) -> Forecast:
    return Forecast(
        agent_id=agent_id,
        wallet_address="",
        ens_name="",
        access_tier="public",
        visible_findings=0,
        persona="test",
        risk_profile="balanced",
        social_stance="neutral_draw",
        activity_level="active",
        influence_weight="medium",
        response_delay="normal",
        active_windows="pre_match",
        home_probability=home_probability,
        market_edge=0.0,
        edge_threshold=0.0,
        edge=0.0,
        side=side,  # type: ignore[arg-type]
        stake=stake,
        bankroll=100.0,
        decision_reason="test",
    )


class EvaluationTests(unittest.TestCase):
    def test_target_home_probability_maps_three_way_results(self) -> None:
        self.assertEqual(target_home_probability("home"), 1.0)
        self.assertEqual(target_home_probability("draw"), 0.5)
        self.assertEqual(target_home_probability("away"), 0.0)

    def test_score_forecasts_computes_brier_accuracy_and_roi(self) -> None:
        forecasts = [
            _forecast(agent_id="ant_0001", side="home", home_probability=0.8, stake=10.0),
            _forecast(agent_id="ant_0002", side="away", home_probability=0.2, stake=5.0),
        ]

        score = score_forecasts(forecasts, result_side="home")

        self.assertEqual(score["forecast_count"], 2)
        self.assertEqual(score["side_accuracy"], 0.5)
        self.assertAlmostEqual(score["brier_home"], 0.34)
        self.assertEqual(score["normalized_roi"], 0.333333)
        self.assertEqual(score["side_counts"], {"away": 1, "home": 1})

    def test_default_scenarios_are_settled(self) -> None:
        scenarios = default_scenarios()

        self.assertGreaterEqual(len(scenarios), 5)
        self.assertNotIn("pending", {scenario.result_side for scenario in scenarios})

    def test_parse_int_list_uses_default_and_rejects_bad_values(self) -> None:
        self.assertEqual(parse_int_list(None, default=[12], name="--agent-counts"), [12])
        self.assertEqual(parse_int_list("12, 32,64", default=[1], name="--agent-counts"), [12, 32, 64])
        with self.assertRaises(ValueError):
            parse_int_list("12, nope", default=[1], name="--agent-counts")
        with self.assertRaises(ValueError):
            parse_int_list("12,0", default=[1], name="--agent-counts")

    def test_summarize_matrix_selects_best_variants(self) -> None:
        summary = summarize_matrix(
            [
                {
                    "summary": {
                        "variants": {
                            "no_debate": {
                                "avg_brier_home": 0.2,
                                "avg_side_accuracy": 0.6,
                                "avg_normalized_roi": 0.1,
                            },
                            "debate_memory_injected": {
                                "avg_brier_home": 0.1,
                                "avg_side_accuracy": 0.7,
                                "avg_normalized_roi": 0.3,
                            },
                        }
                    }
                }
            ]
        )

        self.assertEqual(summary["best_by_brier"], "debate_memory_injected")
        self.assertEqual(summary["best_by_side_accuracy"], "debate_memory_injected")
        self.assertEqual(summary["best_by_roi"], "debate_memory_injected")
        self.assertEqual(summary["win_counts"]["brier"], {"debate_memory_injected": 1})
        self.assertEqual(summary["win_counts"]["side_accuracy"], {"debate_memory_injected": 1})


if __name__ == "__main__":
    unittest.main()
