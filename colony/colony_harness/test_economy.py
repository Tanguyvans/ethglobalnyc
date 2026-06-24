"""Checks for the internal USDC economy ledger."""

from __future__ import annotations

import unittest

from .agent import AntAgent
from .decision import build_collective_decision
from .economy import EconomyLedger, build_paid_knowledge_views, market_spec_for_match, settle_internal_pool
from .genes import Genome, SourceWeights
from .models import CivicAction, Finding, Forecast, InternalStake, MarketSpec, MatchContext
from .scouts import synthetic_probabilities


def _genome(query_budget: float = 1.0, edge_threshold: float = 0.02) -> Genome:
    return Genome(
        estimator="poisson",
        model="parametric",
        risk_appetite=0.1,
        edge_threshold=edge_threshold,
        source_weights=SourceWeights(stats=0.25, odds=0.25, news=0.25, debate=0.25),
        herd_bias=0.0,
        query_budget=query_budget,
        persona="cold probabilist",
    )


def _agent(
    agent_id: str,
    *,
    bankroll: float = 10.0,
    world_verified: bool = False,
    genome: Genome | None = None,
) -> AntAgent:
    return AntAgent(
        agent_id=agent_id,
        name=agent_id.replace("_", "-"),
        generation=0,
        genome=genome or _genome(),
        bankroll=bankroll,
        accuracy=0.5,
        world_verified=world_verified,
    )


def _forecast(
    agent: AntAgent,
    match: MatchContext,
    *,
    probability: float,
    side: str,
    visible_findings: int = 4,
    stake: float = 1.0,
) -> Forecast:
    edge = probability - match.market_home_probability if side == "home" else match.market_home_probability - probability
    if side == "draw":
        edge = 0.01
    return Forecast(
        agent_id=agent.agent_id,
        wallet_address=agent.wallet_address,
        ens_name=agent.ens_name,
        access_tier="public",
        visible_findings=visible_findings,
        persona=agent.genome.persona,
        risk_profile="balanced",
        social_stance="neutral_draw" if side == "draw" else ("supportive_home" if side == "home" else "opposing_home"),
        activity_level="regular",
        influence_weight="medium",
        response_delay="normal",
        active_windows="pre_match",
        home_probability=probability,
        market_edge=round(probability - match.market_home_probability, 4),
        edge_threshold=agent.genome.edge_threshold,
        edge=round(edge, 4),
        side=side,  # type: ignore[arg-type]
        stake=stake,
        bankroll=agent.bankroll,
        decision_reason=f"test {side} forecast",
        genome_id=agent.genome_id,
    )


def _civic_action(agent: AntAgent, *, side: str, action_type: str = "vote_only", weight: float = 1.0) -> CivicAction:
    return CivicAction(
        action_id=f"civic:round:{agent.agent_id}",
        round_id="round_society_decision",
        agent_id=agent.agent_id,
        action_type=action_type,
        civic_choice=side,  # type: ignore[arg-type]
        commitment_label="none",
        status="accepted",
        action_points_spent=1,
        credits_spent=0.0,
        target=side,
        effect_type="civic_vote",
        effect_summary=f"{agent.agent_id} supports {side}",
        source="camel",
        weight=weight,
    )


def _review_civic_action(agent: AntAgent, *, side: str, weight: float = 1.05) -> CivicAction:
    return CivicAction(
        action_id=f"civic_review:round:{agent.agent_id}",
        round_id="round_society_decision",
        agent_id=agent.agent_id,
        action_type="vote_only",
        civic_choice=side,  # type: ignore[arg-type]
        commitment_label="none",
        status="reviewed",
        action_points_spent=0,
        credits_spent=0.0,
        target=side,
        effect_type="civic_vote",
        effect_summary=f"{agent.agent_id} revised to {side}",
        source="camel",
        weight=weight,
        metadata={"phase": "post_resolution_review"},
    )


class EconomyTests(unittest.TestCase):
    def test_group_stage_market_allows_draw_result(self) -> None:
        match = MatchContext(
            round_id="round_group",
            home_team="France",
            away_team="Senegal",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
            group_name="Group A",
            score="1-1",
        )

        spec = market_spec_for_match(match)

        self.assertEqual(spec.market_type, "three_way")
        self.assertEqual(spec.outcomes, ["home_win", "draw", "away_win"])
        self.assertEqual(spec.result_side, "draw")
        self.assertEqual(spec.settlement_status, "settled")

    def test_knockout_market_is_binary_qualification(self) -> None:
        match = MatchContext(
            round_id="round_ko",
            home_team="Brazil",
            away_team="Morocco",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
            stage_name="Round of 16",
            score="2-1",
        )

        spec = market_spec_for_match(match)

        self.assertEqual(spec.market_type, "binary_qualification")
        self.assertEqual(spec.outcomes, ["home_qualifies", "away_qualifies"])
        self.assertEqual(spec.result_side, "home")

    def test_unresolved_market_result_is_pending_not_betting_side(self) -> None:
        match = MatchContext(
            round_id="round_pending",
            home_team="France",
            away_team="Senegal",
            market_home_probability=0.55,
            stats_home_signal=0.55,
            odds_home_signal=0.55,
            news_home_signal=0.55,
        )
        spec = market_spec_for_match(match)
        ledger = EconomyLedger(match.round_id)

        summary = settle_internal_pool(market_spec=spec, agents=[], ledger=ledger)

        self.assertEqual(spec.result_side, "pending")
        self.assertEqual(spec.settlement_status, "pending")
        self.assertEqual(summary["result_side"], "pending")
        self.assertEqual(summary["status"], "pending")

    def test_synthetic_kg_probabilities_keep_france_senegal_contested(self) -> None:
        market, stats, odds, news = synthetic_probabilities("France", "Senegal")

        self.assertLess(market, 0.5)
        self.assertGreater(stats, 0.5)
        self.assertLess(odds, 0.5)
        self.assertGreater(news, 0.5)

    def test_world_verified_agents_pay_discounted_data_price(self) -> None:
        finding = Finding(
            finding_id="finding:shared",
            scout_name="lineup_scout",
            access_level="shared",
            source_type="lineup",
            finding_name="lineup",
            home_probability=0.55,
            home_delta=0.02,
            confidence=0.7,
            cost=0.0,
        )
        match = MatchContext(
            round_id="round_data",
            home_team="France",
            away_team="Senegal",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
            findings=[finding],
        )
        standard = _agent("ant_0000", bankroll=1.0)
        premium = _agent("ant_0001", bankroll=1.0, world_verified=True)
        ledger = EconomyLedger(match.round_id)

        views = build_paid_knowledge_views(match, [standard, premium], ledger)

        self.assertEqual(views[standard.agent_id].access_tier, "shared")
        self.assertEqual(views[premium.agent_id].access_tier, "shared")
        amounts = {receipt.payer_id: receipt.amount for receipt in ledger.payment_receipts}
        self.assertEqual(amounts[standard.agent_id], 0.05)
        self.assertEqual(amounts[premium.agent_id], 0.025)
        self.assertEqual(standard.bankroll, 0.95)
        self.assertEqual(premium.bankroll, 0.975)

    def test_forecast_still_bets_when_forced_pick_is_below_edge_threshold(self) -> None:
        match = MatchContext(
            round_id="round_low_conviction",
            home_team="France",
            away_team="Senegal",
            market_home_probability=0.55,
            stats_home_signal=0.54,
            odds_home_signal=0.54,
            news_home_signal=0.54,
        )
        agent = _agent("ant_0000", bankroll=100.0, genome=_genome(edge_threshold=0.02))

        forecast = agent.forecast(match, debate_home_probability=None)

        self.assertEqual(forecast.side, "home")
        self.assertGreater(forecast.stake, 0.0)
        self.assertLess(forecast.edge, forecast.edge_threshold)
        self.assertIn("low-conviction bet", forecast.decision_reason)

    def test_forecast_bets_when_edge_clears_threshold(self) -> None:
        match = MatchContext(
            round_id="round_bet",
            home_team="France",
            away_team="Senegal",
            market_home_probability=0.5,
            stats_home_signal=0.56,
            odds_home_signal=0.56,
            news_home_signal=0.56,
        )
        agent = _agent("ant_0000", bankroll=100.0, genome=_genome(edge_threshold=0.02))

        forecast = agent.forecast(match, debate_home_probability=None)

        self.assertEqual(forecast.side, "home")
        self.assertGreater(forecast.stake, 0.0)
        self.assertGreaterEqual(forecast.edge, forecast.edge_threshold)
        self.assertIn("bet", forecast.decision_reason)

    def test_collective_decision_still_recommends_side_when_no_forecast_clears_edge(self) -> None:
        match = MatchContext(
            round_id="round_collective_low_conviction",
            home_team="France",
            away_team="Senegal",
            market_home_probability=0.55,
            stats_home_signal=0.54,
            odds_home_signal=0.54,
            news_home_signal=0.54,
        )
        agents = [_agent(f"ant_{index:04d}", genome=_genome(edge_threshold=0.02)) for index in range(3)]
        forecasts = [agent.forecast(match, debate_home_probability=None) for agent in agents]

        decision = build_collective_decision(match=match, agents=agents, forecasts=forecasts)

        self.assertEqual({forecast.side for forecast in forecasts}, {"home"})
        self.assertEqual(decision.recommendation["side"], "home")
        self.assertTrue(decision.recommendation["should_place_single_bet"])
        self.assertEqual(decision.match_call["lean"], "home")
        self.assertEqual(decision.prediction["winner"], "France")

    def test_collective_prediction_follows_weighted_side_support_not_home_average_only(self) -> None:
        match = MatchContext(
            round_id="round_support_consensus",
            home_team="France",
            away_team="Senegal",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
        )
        agents = [_agent(f"ant_{index:04d}", genome=_genome(edge_threshold=0.02)) for index in range(3)]
        forecasts = [
            _forecast(agents[0], match, probability=0.56, side="home"),
            _forecast(agents[1], match, probability=0.49, side="away"),
            _forecast(agents[2], match, probability=0.49, side="away"),
        ]

        decision = build_collective_decision(match=match, agents=agents, forecasts=forecasts)

        self.assertEqual(decision.recommendation["side"], "away")
        self.assertEqual(decision.match_call["lean"], "away")
        self.assertEqual(decision.prediction["winner"], "Senegal")
        self.assertGreater(
            decision.prediction["scoreline"]["away"],
            decision.prediction["scoreline"]["home"],
        )

    def test_close_draw_support_does_not_become_medium_confidence_from_binary_edge(self) -> None:
        match = MatchContext(
            round_id="round_close_draw",
            home_team="France",
            away_team="Iraq",
            market_home_probability=0.465,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
        )
        agents = [_agent(f"ant_{index:04d}") for index in range(50)]
        sides = ["draw"] * 24 + ["away"] * 16 + ["home"] * 10
        probabilities = {"draw": 0.5, "away": 0.49, "home": 0.51}
        forecasts = [
            _forecast(agent, match, probability=probabilities[side], side=side)
            for agent, side in zip(agents, sides)
        ]

        decision = build_collective_decision(match=match, agents=agents, forecasts=forecasts)

        self.assertEqual(decision.recommendation["side"], "draw")
        self.assertLess(decision.internal_metrics["confidence"], 0.48)
        self.assertEqual(decision.recommendation["confidence_label"], "low")

    def test_society_decision_uses_civic_actions_when_available(self) -> None:
        match = MatchContext(
            round_id="round_society_decision",
            home_team="France",
            away_team="Senegal",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
        )
        agents = [_agent(f"ant_{index:04d}") for index in range(7)]
        forecasts = [
            _forecast(agents[0], match, probability=0.45, side="away", stake=100.0),
            *[
                _forecast(agent, match, probability=0.51, side="home", stake=0.0)
                for agent in agents[1:]
            ],
        ]
        actions = [
            _civic_action(agents[0], side="away", action_type="commit_stake", weight=1.2),
            *[_civic_action(agent, side="home") for agent in agents[1:]],
        ]

        decision = build_collective_decision(
            match=match,
            agents=agents,
            forecasts=forecasts,
            civic_actions=actions,
            society_state={"execution_guidance": {"open_blockers": []}},
        )

        self.assertEqual(decision.method["name"], "civic_society_decision_v2")
        self.assertEqual(decision.internal_metrics["decision_layer"], "society_v2")
        self.assertIn("risk", decision.internal_metrics["society_decision"]["component_scores"])
        self.assertEqual(decision.recommendation["side"], "home")
        self.assertEqual(decision.prediction["winner"], "France")
        self.assertGreater(
            decision.internal_metrics["society_decision"]["normalized_scores"]["home"],
            decision.internal_metrics["society_decision"]["normalized_scores"]["away"],
        )

    def test_society_decision_exposes_blockers_and_lowers_confidence(self) -> None:
        match = MatchContext(
            round_id="round_society_blockers",
            home_team="France",
            away_team="Senegal",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
        )
        agents = [_agent(f"ant_{index:04d}") for index in range(5)]
        forecasts = [
            _forecast(agent, match, probability=0.51, side="home", stake=0.0)
            for agent in agents
        ]
        actions = [
            _civic_action(agent, side="home", action_type="request_evidence", weight=1.05)
            for agent in agents
        ]

        decision = build_collective_decision(
            match=match,
            agents=agents,
            forecasts=forecasts,
            civic_actions=actions,
            society_state={
                "execution_guidance": {"open_blockers": ["evidence_requests_open"]},
                "evidence_backlog": [
                    {
                        "priority": "high",
                        "choice_context": {"home": 5},
                    }
                ],
            },
        )

        society_decision = decision.internal_metrics["society_decision"]
        self.assertEqual(decision.recommendation["side"], "home")
        self.assertIn("evidence_requests_open", society_decision["open_blockers"])
        self.assertLess(decision.internal_metrics["confidence"], 0.7)
        self.assertIn("open blockers", decision.recommendation["rationale"])

    def test_society_decision_penalizes_downgraded_source_context(self) -> None:
        match = MatchContext(
            round_id="round_society_source_effect",
            home_team="France",
            away_team="Senegal",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
        )
        agents = [_agent(f"ant_{index:04d}") for index in range(4)]
        sides = ["home", "home", "away", "away"]
        forecasts = [
            _forecast(agent, match, probability=0.51 if side == "home" else 0.49, side=side, stake=0.0)
            for agent, side in zip(agents, sides)
        ]
        actions = [
            _civic_action(agent, side=side)
            for agent, side in zip(agents, sides)
        ]

        decision = build_collective_decision(
            match=match,
            agents=agents,
            forecasts=forecasts,
            civic_actions=actions,
            society_state={
                "execution_guidance": {"open_blockers": ["weak_sources_found"]},
                "source_audit_effects": [
                    {
                        "status": "downgraded",
                        "choice_context": {"home": 2},
                        "finding_ids": ["finding_bad_home"],
                    }
                ],
            },
        )

        self.assertEqual(decision.recommendation["side"], "away")
        penalties = decision.internal_metrics["society_decision"]["blocker_penalties"]
        self.assertGreater(penalties["home"], penalties["away"])

    def test_society_decision_exposes_post_resolution_reviews(self) -> None:
        match = MatchContext(
            round_id="round_society_review",
            home_team="France",
            away_team="Senegal",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
        )
        agents = [_agent(f"ant_{index:04d}") for index in range(3)]
        forecasts = [
            _forecast(agent, match, probability=0.51, side="home", stake=0.0)
            for agent in agents
        ]
        actions = [_civic_action(agent, side="home") for agent in agents]

        decision = build_collective_decision(
            match=match,
            agents=agents,
            forecasts=forecasts,
            civic_actions=actions,
            society_state={
                "execution_guidance": {"open_blockers": []},
                "reviews": [
                    {
                        "review_id": "review:round:00001",
                        "review_type": "evidence_scout_review",
                        "affected_side": "home",
                        "status": "evidence_gap_resolved",
                        "decision_effect": "clear_blocker",
                        "support_count": 3,
                        "summary": "Review cleared evidence gap for home.",
                    }
                ],
            },
        )

        society_decision = decision.internal_metrics["society_decision"]
        self.assertEqual(society_decision["component_scores"]["review"], {"away": 0.0, "draw": 0.0, "home": 1.0})
        self.assertEqual(society_decision["reviews"][0]["decision_effect"], "clear_blocker")
        self.assertIn("post-resolution reviews", decision.recommendation["rationale"])

    def test_society_decision_uses_review_action_as_latest_agent_choice(self) -> None:
        match = MatchContext(
            round_id="round_society_review_choice",
            home_team="France",
            away_team="Senegal",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
        )
        agents = [_agent(f"ant_{index:04d}") for index in range(3)]
        forecasts = [
            _forecast(agent, match, probability=0.49, side="away", stake=0.0)
            for agent in agents
        ]
        initial_actions = [_civic_action(agent, side="home") for agent in agents]
        review_actions = [_review_civic_action(agent, side="away") for agent in agents]

        decision = build_collective_decision(
            match=match,
            agents=agents,
            forecasts=forecasts,
            civic_actions=initial_actions + review_actions,
            society_state={"execution_guidance": {"open_blockers": []}},
        )

        self.assertEqual(decision.recommendation["side"], "away")
        self.assertEqual(decision.internal_metrics["society_decision"]["component_scores"]["civic"]["away"], 1.0)
        self.assertEqual(decision.internal_metrics["society_decision"]["component_scores"]["civic"]["home"], 0.0)

    def test_settlement_distributes_losing_pool_80_10_10(self) -> None:
        winner = _agent("ant_0000", bankroll=0.0)
        contributor = _agent("ant_0001", bankroll=0.0)
        loser = _agent("ant_0002", bankroll=0.0)
        ledger = EconomyLedger("round_settle")
        ledger.internal_stakes = [
            InternalStake("round_settle", winner.agent_id, "home", 10.0, 1.0),
            InternalStake("round_settle", loser.agent_id, "away", 10.0, 1.0),
        ]
        ledger.record_contributor(contributor.agent_id, 1.0)
        spec = MarketSpec(
            round_id="round_settle",
            market_type="three_way",
            outcomes=["home_win", "draw", "away_win"],
            result_side="home",
            settlement_status="settled",
        )

        summary = settle_internal_pool(market_spec=spec, agents=[winner, contributor, loser], ledger=ledger)

        self.assertEqual(summary["losing_pool"], 10.0)
        self.assertEqual(summary["correct_reward_pool"], 8.0)
        self.assertEqual(summary["contributor_pool"], 1.0)
        self.assertEqual(summary["treasury_fee"], 1.0)
        self.assertEqual(winner.bankroll, 18.0)
        self.assertEqual(contributor.bankroll, 1.0)
        self.assertEqual(ledger.treasury_balance, 1.0)


if __name__ == "__main__":
    unittest.main()
