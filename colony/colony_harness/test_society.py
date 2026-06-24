"""Tests for civic society action resolution."""

from __future__ import annotations

import unittest

from .agent import AntAgent
from .economy import EconomyLedger
from .genes import Genome, SourceWeights
from .models import DebateRoom, Finding, Forecast, JudgmentRevision, MatchContext
from .society import (
    apply_calibration_reputation_changes,
    apply_execution_guidance,
    apply_civic_reputation_changes,
    apply_society_commitment_policy,
    apply_source_audit_effects,
    build_society_state,
    build_society_reviews,
    civic_layer_metrics,
    execute_society_resolutions,
    resolve_civic_actions,
    resolve_review_civic_actions,
    resolve_society_backlogs,
    settle_civic_rewards,
    society_commitment_policy,
)


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


def _agent(agent_id: str, *, bankroll: float = 10.0) -> AntAgent:
    return AntAgent(
        agent_id=agent_id,
        name=agent_id.replace("_", "-"),
        generation=0,
        genome=_genome(),
        bankroll=bankroll,
        accuracy=0.5,
    )


def _forecast(
    agent_id: str,
    *,
    action: str,
    source: str = "camel",
    target: str = "",
    stake: float = 0.0,
    side: str = "draw",
) -> Forecast:
    return Forecast(
        agent_id=agent_id,
        wallet_address="",
        ens_name="",
        access_tier="public",
        visible_findings=2,
        persona="test ant",
        risk_profile="balanced",
        social_stance="neutral_draw",
        activity_level="regular",
        influence_weight="medium",
        response_delay="normal",
        active_windows="pre_match",
        home_probability=0.5,
        market_edge=0.0,
        edge_threshold=0.02,
        edge=0.01,
        side=side,  # type: ignore[arg-type]
        stake=stake,
        bankroll=10.0,
        decision_reason="test forecast",
        judgment={
            "agent_id": agent_id,
            "source": source,
            "action": action,
            "civic_choice": side,
            "commitment_label": "none",
            "risk_intent": "none",
            "action_target": target,
            "conviction": "low",
            "intent": "buy_info" if action in {"request_evidence", "fund_scout"} else "pass",
            "social_move": "ask_for_data" if action == "request_evidence" else "listen",
            "one_line": "Needs more source-grounded evidence.",
            "doubts": ["lineup reliability"],
            "evidence_used": [],
            "evidence_distrusted": ["E2"],
            "debate_question": "Can we trust the lineup note?",
        },
    )


def _room() -> DebateRoom:
    return DebateRoom(
        room_id="room_lineup",
        stance="topic_room",
        evidence_focus="lineup reliability",
        participant_ids=[],
        representative_ids=[],
        claims=[],
        synthesis_home_probability=None,
        synthesis_confidence=0.0,
        synthesis="",
    )


def _finding(
    finding_id: str,
    *,
    source_type: str = "lineup",
    summary: str = "Official lineup report confirms availability.",
    confidence: float = 0.82,
    source_quality: str = "verified",
) -> Finding:
    return Finding(
        finding_id=finding_id,
        scout_name="test_scout",
        access_level="public",
        source_type=source_type,  # type: ignore[arg-type]
        finding_name=source_type,
        home_probability=0.5,
        home_delta=0.0,
        confidence=confidence,
        cost=0.0,
        summary=summary,
        evidence_claims=[
            {
                "claim": summary,
                "claim_type": source_type,
                "source_quality": source_quality,
            }
        ],
    )


class SocietyTests(unittest.TestCase):
    def test_request_evidence_becomes_replayable_civic_action(self) -> None:
        match = MatchContext(
            round_id="round_society",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
        )
        agent = _agent("ant_0001")
        ledger = EconomyLedger(match.round_id)

        actions, summary = resolve_civic_actions(
            match=match,
            agents=[agent],
            forecasts=[_forecast(agent.agent_id, action="request_evidence", target="lineup")],
            ledger=ledger,
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action_type, "request_evidence")
        self.assertEqual(actions[0].effect_type, "evidence_request")
        self.assertEqual(actions[0].action_points_spent, 1)
        self.assertEqual(actions[0].credits_spent, 0.0)
        self.assertEqual(summary["evidence_request_targets"], {"lineup": 1})
        self.assertEqual(summary["civic_action_points_spent"], 1)
        self.assertEqual(ledger.payment_receipts, [])

    def test_fund_scout_spends_fake_credits(self) -> None:
        match = MatchContext(
            round_id="round_society",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
        )
        agent = _agent("ant_0001", bankroll=1.0)
        ledger = EconomyLedger(match.round_id)

        actions, summary = resolve_civic_actions(
            match=match,
            agents=[agent],
            forecasts=[_forecast(agent.agent_id, action="fund_scout", target="injury_report")],
            ledger=ledger,
        )

        self.assertEqual(actions[0].status, "accepted")
        self.assertEqual(actions[0].effect_type, "scout_funding")
        self.assertEqual(actions[0].credits_spent, 0.05)
        self.assertEqual(summary["funded_scout_targets"], {"injury_report": 1})
        self.assertEqual(summary["civic_credits_spent"], 0.05)
        self.assertEqual(agent.bankroll, 0.95)
        self.assertEqual(ledger.payment_receipts[0].payment_type, "fund_scout")

    def test_unavailable_judgment_does_not_spend_attention(self) -> None:
        match = MatchContext(
            round_id="round_society",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
        )
        agent = _agent("ant_0001")
        ledger = EconomyLedger(match.round_id)

        actions, summary = resolve_civic_actions(
            match=match,
            agents=[agent],
            forecasts=[_forecast(agent.agent_id, action="hold_position", source="camel_error")],
            ledger=ledger,
        )

        self.assertEqual(actions[0].status, "skipped_unavailable_judgment")
        self.assertEqual(actions[0].action_points_spent, 0)
        self.assertEqual(summary["civic_action_points_spent"], 0)
        self.assertEqual(summary["civic_action_statuses"], {"skipped_unavailable_judgment": 1})

    def test_civic_layer_separates_social_choice_from_financial_commitment(self) -> None:
        metrics = civic_layer_metrics(
            civic_summary={
                "civic_choice_counts": {"home": 7, "draw": 2, "away": 1},
                "evidence_request_targets": {"lineup": 4},
                "source_challenge_targets": {},
                "discussion_targets": {},
            },
            population=10,
            participating_bets=0,
            total_staked=0.0,
        )

        self.assertEqual(metrics["civic_leading_choice"], "home")
        self.assertEqual(metrics["civic_leading_support"], "7/10")
        self.assertEqual(metrics["financial_commitment_level"], "none")
        self.assertEqual(metrics["civic_unresolved_target"], "lineup")
        self.assertIn("Civic layer leans home", metrics["civic_decision_note"])

    def test_society_state_queues_evidence_backlog(self) -> None:
        match = MatchContext(
            round_id="round_society",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
        )
        agents = [_agent("ant_0001"), _agent("ant_0002")]
        ledger = EconomyLedger(match.round_id)
        forecasts = [
            _forecast("ant_0001", action="request_evidence", target="lineup reliability"),
            _forecast("ant_0002", action="request_evidence", target="lineup reliability"),
        ]
        actions, _summary = resolve_civic_actions(
            match=match,
            agents=agents,
            forecasts=forecasts,
            ledger=ledger,
        )

        state = build_society_state(match=match, civic_actions=actions, rooms=[_room()])

        self.assertEqual(state["evidence_backlog"][0]["target"], "lineup reliability")
        self.assertEqual(state["evidence_backlog"][0]["priority"], "medium")
        self.assertEqual(state["evidence_backlog"][0]["status"], "queued_next")
        self.assertEqual(state["decision_guidance"]["posture"], "gather_more_evidence_before_scaling_commitment")

    def test_society_state_source_audit_slows_commitment(self) -> None:
        match = MatchContext(
            round_id="round_society",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
        )
        agent = _agent("ant_0001")
        ledger = EconomyLedger(match.round_id)
        actions, _summary = resolve_civic_actions(
            match=match,
            agents=[agent],
            forecasts=[_forecast(agent.agent_id, action="challenge_source", target="E2 source_quality")],
            ledger=ledger,
        )

        state = build_society_state(match=match, civic_actions=actions, rooms=[])

        self.assertEqual(state["source_audit_backlog"][0]["target"], "E2 source_quality")
        self.assertEqual(state["decision_guidance"]["posture"], "slow_down_until_sources_are_audited")
        self.assertIn("source_audits_open", state["decision_guidance"]["open_blockers"])

    def test_empty_society_state_is_not_marked_ready(self) -> None:
        match = MatchContext(
            round_id="round_society",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
        )

        state = build_society_state(match=match, civic_actions=[], rooms=[])

        self.assertEqual(state["decision_guidance"]["posture"], "no_civic_layer")
        self.assertEqual(state["decision_guidance"]["commitment_mode"], "baseline_only")

    def test_source_audit_policy_pauses_camel_stakes(self) -> None:
        state = {
            "decision_guidance": {
                "posture": "slow_down_until_sources_are_audited",
                "open_blockers": ["source_audits_open"],
            }
        }
        policy = society_commitment_policy(state)
        forecasts = [
            _forecast("ant_0001", action="commit_stake", stake=8.0),
            _forecast("ant_0002", action="commit_stake", source="baseline", stake=8.0),
        ]

        updated = apply_society_commitment_policy(forecasts, policy)

        self.assertFalse(policy["should_place_single_bet"])
        self.assertEqual(policy["financial_execution_label"], "paused")
        self.assertEqual(updated[0].stake, 0.0)
        self.assertEqual(updated[1].stake, 8.0)

    def test_evidence_request_policy_allows_only_micro_commitment(self) -> None:
        state = {
            "decision_guidance": {
                "posture": "gather_more_evidence_before_scaling_commitment",
                "open_blockers": ["evidence_requests_open"],
            }
        }
        policy = society_commitment_policy(state)

        updated = apply_society_commitment_policy(
            [_forecast("ant_0001", action="commit_stake", stake=8.0)],
            policy,
        )

        self.assertFalse(policy["should_place_single_bet"])
        self.assertEqual(policy["financial_execution_label"], "tiny")
        self.assertEqual(updated[0].stake, 2.0)

    def test_society_backlog_resolution_queues_supported_evidence_scout(self) -> None:
        match = MatchContext(
            round_id="round_society",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
        )
        agents = [_agent("ant_0001"), _agent("ant_0002")]
        ledger = EconomyLedger(match.round_id)
        actions, _summary = resolve_civic_actions(
            match=match,
            agents=agents,
            forecasts=[
                _forecast("ant_0001", action="request_evidence", target="lineup reliability"),
                _forecast("ant_0002", action="request_evidence", target="lineup reliability"),
            ],
            ledger=ledger,
        )
        state = build_society_state(match=match, civic_actions=actions, rooms=[])

        resolutions, summary = resolve_society_backlogs(match=match, society_state=state)

        self.assertEqual(summary["society_resolution_counts"], {"evidence_scout": 1})
        self.assertEqual(resolutions[0].resolution_type, "evidence_scout")
        self.assertEqual(resolutions[0].status, "scout_queued")
        self.assertEqual(resolutions[0].support_count, 2)
        self.assertEqual(len(resolutions[0].related_action_ids), 2)

    def test_society_backlog_resolution_always_queues_source_audit(self) -> None:
        match = MatchContext(
            round_id="round_society",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
        )
        agent = _agent("ant_0001")
        ledger = EconomyLedger(match.round_id)
        actions, _summary = resolve_civic_actions(
            match=match,
            agents=[agent],
            forecasts=[_forecast(agent.agent_id, action="challenge_source", target="E2 source_quality")],
            ledger=ledger,
        )
        state = build_society_state(match=match, civic_actions=actions, rooms=[])

        resolutions, summary = resolve_society_backlogs(match=match, society_state=state)

        self.assertEqual(summary["society_resolution_counts"], {"source_audit": 1})
        self.assertEqual(resolutions[0].status, "audit_queued")
        self.assertEqual(resolutions[0].priority, "low")

    def test_society_backlog_resolution_reserves_scout_funding(self) -> None:
        match = MatchContext(
            round_id="round_society",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
        )
        agent = _agent("ant_0001", bankroll=1.0)
        ledger = EconomyLedger(match.round_id)
        actions, _summary = resolve_civic_actions(
            match=match,
            agents=[agent],
            forecasts=[_forecast(agent.agent_id, action="fund_scout", target="injury_report")],
            ledger=ledger,
        )
        state = build_society_state(match=match, civic_actions=actions, rooms=[])

        resolutions, summary = resolve_society_backlogs(match=match, society_state=state)

        self.assertEqual(summary["society_resolution_counts"], {"scout_funding": 1})
        self.assertEqual(summary["society_resolution_credit_budget"], 0.05)
        self.assertEqual(resolutions[0].status, "budget_reserved")

    def test_execution_resolves_evidence_from_existing_findings(self) -> None:
        match = MatchContext(
            round_id="round_society",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
            findings=[_finding("finding_lineup", summary="Official lineup reliability report.")],
        )
        agents = [_agent("ant_0001"), _agent("ant_0002")]
        ledger = EconomyLedger(match.round_id)
        actions, _summary = resolve_civic_actions(
            match=match,
            agents=agents,
            forecasts=[
                _forecast("ant_0001", action="request_evidence", target="lineup reliability"),
                _forecast("ant_0002", action="request_evidence", target="lineup reliability"),
            ],
            ledger=ledger,
        )
        state = build_society_state(match=match, civic_actions=actions, rooms=[])
        resolutions, _resolution_summary = resolve_society_backlogs(match=match, society_state=state)

        executions, summary = execute_society_resolutions(match=match, resolutions=resolutions, rooms=[])

        self.assertEqual(summary["society_execution_statuses"], {"resolved_from_existing_evidence": 1})
        self.assertEqual(executions[0].blocker_effect, "blocker_cleared")
        self.assertEqual(executions[0].produced_finding_ids, ["finding_lineup"])

    def test_execution_guidance_keeps_weak_source_blocker(self) -> None:
        match = MatchContext(
            round_id="round_society",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
            findings=[
                _finding(
                    "finding_e2",
                    source_type="news",
                    summary="E2 rumor source remains unverified.",
                    confidence=0.3,
                    source_quality="unverified",
                )
            ],
        )
        agent = _agent("ant_0001")
        ledger = EconomyLedger(match.round_id)
        actions, _summary = resolve_civic_actions(
            match=match,
            agents=[agent],
            forecasts=[_forecast(agent.agent_id, action="challenge_source", target="E2 source_quality")],
            ledger=ledger,
        )
        state = build_society_state(match=match, civic_actions=actions, rooms=[])
        resolutions, _resolution_summary = resolve_society_backlogs(match=match, society_state=state)
        executions, _execution_summary = execute_society_resolutions(match=match, resolutions=resolutions, rooms=[])

        updated_state = apply_execution_guidance(state, executions)
        policy = society_commitment_policy(updated_state)

        self.assertEqual(executions[0].status, "audit_resolved_weak_source")
        self.assertIn("weak_sources_found", updated_state["execution_guidance"]["open_blockers"])
        self.assertEqual(policy["financial_execution_label"], "paused")

    def test_execution_guidance_clears_ok_source_audit(self) -> None:
        match = MatchContext(
            round_id="round_society",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
            findings=[_finding("finding_e2", source_type="news", summary="E2 official source confirmed.", source_quality="official")],
        )
        agent = _agent("ant_0001")
        ledger = EconomyLedger(match.round_id)
        actions, _summary = resolve_civic_actions(
            match=match,
            agents=[agent],
            forecasts=[_forecast(agent.agent_id, action="challenge_source", target="E2 source_quality")],
            ledger=ledger,
        )
        state = build_society_state(match=match, civic_actions=actions, rooms=[])
        resolutions, _resolution_summary = resolve_society_backlogs(match=match, society_state=state)
        executions, _execution_summary = execute_society_resolutions(match=match, resolutions=resolutions, rooms=[])

        updated_state = apply_execution_guidance(state, executions)
        policy = society_commitment_policy(updated_state)

        self.assertEqual(executions[0].status, "audit_resolved_source_ok")
        self.assertEqual(updated_state["execution_guidance"]["open_blockers"], [])
        self.assertEqual(policy["financial_execution_label"], "normal")

    def test_source_audit_effect_downgrades_weak_finding(self) -> None:
        weak_finding = _finding(
            "finding_e2",
            source_type="news",
            summary="E2 rumor source remains unverified.",
            confidence=0.3,
            source_quality="unverified",
        )
        match = MatchContext(
            round_id="round_society",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
            findings=[weak_finding],
        )
        agent = _agent("ant_0001")
        ledger = EconomyLedger(match.round_id)
        actions, _summary = resolve_civic_actions(
            match=match,
            agents=[agent],
            forecasts=[_forecast(agent.agent_id, action="challenge_source", target="E2 source_quality", side="home")],
            ledger=ledger,
        )
        state = build_society_state(match=match, civic_actions=actions, rooms=[])
        resolutions, _resolution_summary = resolve_society_backlogs(match=match, society_state=state)
        executions, _execution_summary = execute_society_resolutions(match=match, resolutions=resolutions, rooms=[])

        audited_findings, effects, summary = apply_source_audit_effects(
            findings=match.findings,
            executions=executions,
        )

        self.assertEqual(summary["source_audit_effect_statuses"], {"downgraded": 1})
        self.assertEqual(summary["source_audit_downgraded_findings"], ["finding_e2"])
        self.assertEqual(effects[0]["choice_context"], {"home": 1})
        self.assertEqual(audited_findings[0].confidence, 0.3)
        self.assertEqual(audited_findings[0].evidence_claims[0]["source_quality"], "weak")
        self.assertEqual(
            audited_findings[0].evidence_claims[0]["audit_status"],
            "downgraded_by_colony_source_audit",
        )

    def test_source_audit_effect_confirms_ok_finding_without_downgrade(self) -> None:
        strong_finding = _finding(
            "finding_e2",
            source_type="news",
            summary="E2 official source confirmed.",
            confidence=0.82,
            source_quality="official",
        )
        match = MatchContext(
            round_id="round_society",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
            findings=[strong_finding],
        )
        agent = _agent("ant_0001")
        ledger = EconomyLedger(match.round_id)
        actions, _summary = resolve_civic_actions(
            match=match,
            agents=[agent],
            forecasts=[_forecast(agent.agent_id, action="challenge_source", target="E2 source_quality", side="away")],
            ledger=ledger,
        )
        state = build_society_state(match=match, civic_actions=actions, rooms=[])
        resolutions, _resolution_summary = resolve_society_backlogs(match=match, society_state=state)
        executions, _execution_summary = execute_society_resolutions(match=match, resolutions=resolutions, rooms=[])

        audited_findings, effects, summary = apply_source_audit_effects(
            findings=match.findings,
            executions=executions,
        )

        self.assertEqual(summary["source_audit_effect_statuses"], {"confirmed": 1})
        self.assertEqual(summary["source_audit_downgraded_findings"], [])
        self.assertEqual(effects[0]["choice_context"], {"away": 1})
        self.assertIs(audited_findings[0], strong_finding)
        self.assertEqual(audited_findings[0].evidence_claims[0]["source_quality"], "official")

    def test_society_review_records_downgraded_source_after_execution(self) -> None:
        weak_finding = _finding(
            "finding_e2",
            source_type="news",
            summary="E2 rumor source remains unverified.",
            confidence=0.3,
            source_quality="unverified",
        )
        match = MatchContext(
            round_id="round_society",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
            findings=[weak_finding],
        )
        agent = _agent("ant_0001")
        ledger = EconomyLedger(match.round_id)
        actions, _summary = resolve_civic_actions(
            match=match,
            agents=[agent],
            forecasts=[_forecast(agent.agent_id, action="challenge_source", target="E2 source_quality", side="home")],
            ledger=ledger,
        )
        state = build_society_state(match=match, civic_actions=actions, rooms=[])
        resolutions, _resolution_summary = resolve_society_backlogs(match=match, society_state=state)
        executions, _execution_summary = execute_society_resolutions(match=match, resolutions=resolutions, rooms=[])
        _audited_findings, effects, _effect_summary = apply_source_audit_effects(
            findings=match.findings,
            executions=executions,
        )

        reviews, summary = build_society_reviews(executions=executions, source_audit_effects=effects)

        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].review_type, "source_audit_review")
        self.assertEqual(reviews[0].affected_side, "home")
        self.assertEqual(reviews[0].decision_effect, "downgrade_side")
        self.assertEqual(reviews[0].status, "contested_source_downgraded")
        self.assertIn("failed source audit", reviews[0].summary)
        self.assertEqual(summary["society_review_effects"], {"downgrade_side": 1})

    def test_society_review_clears_confirmed_source_audit(self) -> None:
        strong_finding = _finding(
            "finding_e2",
            source_type="news",
            summary="E2 official source confirmed.",
            confidence=0.82,
            source_quality="official",
        )
        match = MatchContext(
            round_id="round_society",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
            findings=[strong_finding],
        )
        agent = _agent("ant_0001")
        ledger = EconomyLedger(match.round_id)
        actions, _summary = resolve_civic_actions(
            match=match,
            agents=[agent],
            forecasts=[_forecast(agent.agent_id, action="challenge_source", target="E2 source_quality", side="away")],
            ledger=ledger,
        )
        state = build_society_state(match=match, civic_actions=actions, rooms=[])
        resolutions, _resolution_summary = resolve_society_backlogs(match=match, society_state=state)
        executions, _execution_summary = execute_society_resolutions(match=match, resolutions=resolutions, rooms=[])
        _audited_findings, effects, _effect_summary = apply_source_audit_effects(
            findings=match.findings,
            executions=executions,
        )

        reviews, summary = build_society_reviews(executions=executions, source_audit_effects=effects)

        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].affected_side, "away")
        self.assertEqual(reviews[0].decision_effect, "clear_blocker")
        self.assertEqual(reviews[0].status, "source_confirmed")
        self.assertEqual(summary["society_review_statuses"], {"source_confirmed": 1})

    def test_review_judgment_becomes_zero_cost_review_civic_action(self) -> None:
        match = MatchContext(
            round_id="round_society",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
        )
        forecast = _forecast("ant_0001", action="vote_only", side="away")
        revision = JudgmentRevision(
            revision_id="judgment_revision:round_society:00001",
            round_id=match.round_id,
            agent_id="ant_0001",
            phase="post_resolution_review",
            previous_side="home",
            revised_side="away",
            previous_action="challenge_source",
            revised_action="vote_only",
            previous_stake=0.0,
            revised_stake=0.0,
            changed=True,
            reason="The reviewed source was downgraded.",
            review_ids=["review:round_society:00001"],
            judgment={
                "source": "camel",
                "action": "vote_only",
                "civic_choice": "away",
                "commitment_label": "none",
                "one_line": "The reviewed source was downgraded.",
            },
        )

        actions, summary = resolve_review_civic_actions(
            match=match,
            forecasts=[forecast],
            revisions=[revision],
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].status, "reviewed")
        self.assertEqual(actions[0].action_points_spent, 0)
        self.assertEqual(actions[0].credits_spent, 0.0)
        self.assertEqual(actions[0].civic_choice, "away")
        self.assertEqual(actions[0].metadata["phase"], "post_resolution_review")
        self.assertEqual(summary["review_judgment_changed_count"], 1)

    def test_civic_rewards_pay_useful_evidence_requesters(self) -> None:
        match = MatchContext(
            round_id="round_society",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
            findings=[_finding("finding_lineup", summary="Official lineup reliability report.")],
        )
        agents = [_agent("ant_0001"), _agent("ant_0002")]
        ledger = EconomyLedger(match.round_id)
        actions, _summary = resolve_civic_actions(
            match=match,
            agents=agents,
            forecasts=[
                _forecast("ant_0001", action="request_evidence", target="lineup reliability"),
                _forecast("ant_0002", action="request_evidence", target="lineup reliability"),
            ],
            ledger=ledger,
        )
        state = build_society_state(match=match, civic_actions=actions, rooms=[])
        resolutions, _resolution_summary = resolve_society_backlogs(match=match, society_state=state)
        executions, _execution_summary = execute_society_resolutions(match=match, resolutions=resolutions, rooms=[])

        rewards, summary = settle_civic_rewards(
            agents=agents,
            civic_actions=actions,
            executions=executions,
            ledger=ledger,
        )

        self.assertEqual(len(rewards), 2)
        self.assertEqual(summary["civic_reward_total"], 0.04)
        self.assertEqual({reward.amount for reward in rewards}, {0.02})
        self.assertEqual({agent.bankroll for agent in agents}, {10.02})
        self.assertEqual(summary["civic_reward_reasons"], {"useful_evidence_request": 2})

    def test_civic_rewards_pay_source_auditor_for_weak_source(self) -> None:
        match = MatchContext(
            round_id="round_society",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
            findings=[
                _finding(
                    "finding_e2",
                    source_type="news",
                    summary="E2 rumor source remains unverified.",
                    confidence=0.3,
                    source_quality="unverified",
                )
            ],
        )
        agent = _agent("ant_0001")
        ledger = EconomyLedger(match.round_id)
        actions, _summary = resolve_civic_actions(
            match=match,
            agents=[agent],
            forecasts=[_forecast(agent.agent_id, action="challenge_source", target="E2 source_quality")],
            ledger=ledger,
        )
        state = build_society_state(match=match, civic_actions=actions, rooms=[])
        resolutions, _resolution_summary = resolve_society_backlogs(match=match, society_state=state)
        executions, _execution_summary = execute_society_resolutions(match=match, resolutions=resolutions, rooms=[])

        rewards, summary = settle_civic_rewards(
            agents=[agent],
            civic_actions=actions,
            executions=executions,
            ledger=ledger,
        )

        self.assertEqual(len(rewards), 1)
        self.assertEqual(rewards[0].amount, 0.06)
        self.assertEqual(rewards[0].reason, "useful_source_audit")
        self.assertEqual(agent.bankroll, 10.06)
        self.assertEqual(summary["civic_reward_total"], 0.06)

    def test_civic_rewards_do_not_pay_pending_external_scout(self) -> None:
        match = MatchContext(
            round_id="round_society",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
        )
        agent = _agent("ant_0001")
        ledger = EconomyLedger(match.round_id)
        actions, _summary = resolve_civic_actions(
            match=match,
            agents=[agent],
            forecasts=[_forecast(agent.agent_id, action="request_evidence", target="lineup reliability")],
            ledger=ledger,
        )
        state = build_society_state(match=match, civic_actions=actions, rooms=[])
        resolutions, _resolution_summary = resolve_society_backlogs(match=match, society_state=state)
        executions, _execution_summary = execute_society_resolutions(match=match, resolutions=resolutions, rooms=[])

        rewards, summary = settle_civic_rewards(
            agents=[agent],
            civic_actions=actions,
            executions=executions,
            ledger=ledger,
        )

        self.assertEqual(rewards, [])
        self.assertEqual(summary["civic_reward_total"], 0)
        self.assertEqual(agent.bankroll, 10.0)

    def test_civic_reputation_tracks_useful_evidence_work(self) -> None:
        match = MatchContext(
            round_id="round_society",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
            findings=[_finding("finding_lineup", summary="Official lineup reliability report.")],
        )
        agents = [_agent("ant_0001"), _agent("ant_0002")]
        ledger = EconomyLedger(match.round_id)
        actions, _summary = resolve_civic_actions(
            match=match,
            agents=agents,
            forecasts=[
                _forecast("ant_0001", action="request_evidence", target="lineup reliability"),
                _forecast("ant_0002", action="request_evidence", target="lineup reliability"),
            ],
            ledger=ledger,
        )
        state = build_society_state(match=match, civic_actions=actions, rooms=[])
        resolutions, _resolution_summary = resolve_society_backlogs(match=match, society_state=state)
        executions, _execution_summary = execute_society_resolutions(match=match, resolutions=resolutions, rooms=[])

        changes, summary = apply_civic_reputation_changes(
            agents=agents,
            civic_actions=actions,
            executions=executions,
        )

        self.assertEqual(len(changes), 2)
        self.assertEqual(summary["civic_reputation_delta_total"], 0.05)
        self.assertEqual({change.delta for change in changes}, {0.025})
        self.assertEqual({agent.mind["civic_reputation"]["score"] for agent in agents}, {0.025})
        self.assertEqual(summary["civic_reputation_reasons"], {"resolved_evidence_gap": 2})

    def test_civic_reputation_tracks_weak_source_audit(self) -> None:
        match = MatchContext(
            round_id="round_society",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
            findings=[
                _finding(
                    "finding_e2",
                    source_type="news",
                    summary="E2 rumor source remains unverified.",
                    confidence=0.3,
                    source_quality="unverified",
                )
            ],
        )
        agent = _agent("ant_0001")
        ledger = EconomyLedger(match.round_id)
        actions, _summary = resolve_civic_actions(
            match=match,
            agents=[agent],
            forecasts=[_forecast(agent.agent_id, action="challenge_source", target="E2 source_quality")],
            ledger=ledger,
        )
        state = build_society_state(match=match, civic_actions=actions, rooms=[])
        resolutions, _resolution_summary = resolve_society_backlogs(match=match, society_state=state)
        executions, _execution_summary = execute_society_resolutions(match=match, resolutions=resolutions, rooms=[])

        changes, summary = apply_civic_reputation_changes(
            agents=[agent],
            civic_actions=actions,
            executions=executions,
        )

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].delta, 0.08)
        self.assertEqual(changes[0].reason, "caught_weak_source")
        self.assertEqual(agent.mind["civic_reputation"]["score"], 0.08)
        self.assertEqual(summary["civic_reputation_delta_total"], 0.08)

    def test_civic_reputation_does_not_change_for_pending_external_scout(self) -> None:
        match = MatchContext(
            round_id="round_society",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
        )
        agent = _agent("ant_0001")
        ledger = EconomyLedger(match.round_id)
        actions, _summary = resolve_civic_actions(
            match=match,
            agents=[agent],
            forecasts=[_forecast(agent.agent_id, action="request_evidence", target="lineup reliability")],
            ledger=ledger,
        )
        state = build_society_state(match=match, civic_actions=actions, rooms=[])
        resolutions, _resolution_summary = resolve_society_backlogs(match=match, society_state=state)
        executions, _execution_summary = execute_society_resolutions(match=match, resolutions=resolutions, rooms=[])

        changes, summary = apply_civic_reputation_changes(
            agents=[agent],
            civic_actions=actions,
            executions=executions,
        )

        self.assertEqual(changes, [])
        self.assertEqual(summary["civic_reputation_delta_total"], 0)
        self.assertFalse(agent.mind)

    def test_calibration_reputation_waits_for_known_result(self) -> None:
        agent = _agent("ant_0001")

        changes, summary = apply_calibration_reputation_changes(
            round_id="round_society",
            agents=[agent],
            forecasts=[_forecast(agent.agent_id, action="vote_only", side="home")],
            result_side="pending",
        )

        self.assertEqual(changes, [])
        self.assertEqual(summary["calibration_reputation_delta_total"], 0)
        self.assertFalse(agent.mind)

    def test_calibration_reputation_rewards_correct_civic_choice(self) -> None:
        agent = _agent("ant_0001")

        changes, summary = apply_calibration_reputation_changes(
            round_id="round_society",
            agents=[agent],
            forecasts=[_forecast(agent.agent_id, action="vote_only", side="home")],
            result_side="home",
        )

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].delta, 0.015)
        self.assertEqual(changes[0].reason, "correct_civic_choice")
        self.assertEqual(changes[0].forecast_side, "home")
        self.assertEqual(changes[0].result_side, "home")
        self.assertEqual(agent.mind["calibration_reputation"]["score"], 0.015)
        self.assertEqual(summary["calibration_reputation_reasons"], {"correct_civic_choice": 1})

    def test_calibration_reputation_penalizes_wrong_committed_choice(self) -> None:
        agent = _agent("ant_0001")

        changes, summary = apply_calibration_reputation_changes(
            round_id="round_society",
            agents=[agent],
            forecasts=[_forecast(agent.agent_id, action="commit_stake", side="away", stake=3.0)],
            result_side="home",
        )

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].delta, -0.025)
        self.assertEqual(changes[0].reason, "wrong_committed_choice")
        self.assertEqual(agent.mind["calibration_reputation"]["score"], -0.025)
        self.assertEqual(summary["calibration_reputation_delta_total"], -0.025)


if __name__ == "__main__":
    unittest.main()
