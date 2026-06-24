"""Collective betting decision for a Colony round."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .agent import AntAgent
from .models import CivicAction, CollectiveDecision, Forecast, MatchContext

ACCESS_MULTIPLIERS = {
    "public": 1.0,
    "shared": 1.25,
    "private": 1.6,
}
WORLD_VERIFIED_MULTIPLIER = 1.25
VERIFIED_LINEAGE_MULTIPLIER = 1.1
DEFAULT_COLLECTIVE_EDGE_THRESHOLD = 0.015
SOCIETY_DECISION_WEIGHTS = {
    "civic": 0.32,
    "action_quality": 0.16,
    "reputation": 0.12,
    "risk": 0.14,
    "commitment": 0.16,
    "review": 0.12,
    "blocker_penalty": 0.16,
}


@dataclass(frozen=True)
class WeightedVote:
    agent: AntAgent
    forecast: Forecast
    probability_vote: str
    weight: float
    components: dict[str, float]


def build_collective_decision(
    *,
    match: MatchContext,
    agents: list[AntAgent],
    forecasts: list[Forecast],
    civic_actions: list[CivicAction] | None = None,
    society_state: dict | None = None,
    collective_edge_threshold: float = DEFAULT_COLLECTIVE_EDGE_THRESHOLD,
) -> CollectiveDecision:
    agents_by_id = {agent.agent_id: agent for agent in agents}
    votes = [
        _weighted_vote(agents_by_id[forecast.agent_id], forecast)
        for forecast in forecasts
        if forecast.agent_id in agents_by_id
    ]
    if not votes:
        raise ValueError("cannot build a collective decision without votes")

    total_weight = sum(vote.weight for vote in votes)
    weighted_home_probability = sum(vote.forecast.home_probability * vote.weight for vote in votes) / total_weight
    weighted_edge = weighted_home_probability - match.market_home_probability
    raw_counts = _raw_counts(forecasts)
    agent_predictions = [_agent_prediction_payload(vote, match) for vote in votes]
    prediction_counts = _prediction_counts(agent_predictions)
    weighted_side_support = _weighted_side_support(votes)
    forecast_weighted_side_support = dict(weighted_side_support)
    society_decision = _society_decision_v2(
        agents_by_id=agents_by_id,
        forecasts=forecasts,
        civic_actions=civic_actions or [],
        society_state=society_state or {},
    )
    recommendation_side = _collective_recommendation_side(
        weighted_side_support=weighted_side_support,
        raw_counts=raw_counts,
        weighted_edge=weighted_edge,
        collective_edge_threshold=collective_edge_threshold,
    )
    if society_decision:
        recommendation_side = society_decision["side"]
        weighted_side_support = society_decision["normalized_scores"]
    prediction_side = recommendation_side
    prediction_outcome = _winner_label(prediction_side, match)
    recommendation_outcome = _winner_label(recommendation_side, match)
    support_margin = _support_margin(weighted_side_support)
    prediction_value_signal = _prediction_value_signal(
        prediction_side=prediction_side,
        weighted_edge=weighted_edge,
        support_margin=support_margin,
    )
    confidence = (
        society_decision["confidence"]
        if society_decision
        else _decision_confidence(
            edge=prediction_value_signal,
            support_margin=support_margin,
            participation=len(votes),
        )
    )
    calibrated_home_probability = _calibrated_home_probability(
        weighted_home_probability=weighted_home_probability,
        weighted_side_support=weighted_side_support,
        prediction_side=prediction_side,
    )
    score_projection = _score_projection(
        home_probability=calibrated_home_probability,
        home_team=match.home_team,
        away_team=match.away_team,
        recommendation_side=prediction_side,
    )
    agent_votes = [_agent_vote_payload(vote, match) for vote in sorted(votes, key=lambda item: item.weight, reverse=True)]
    final_prediction = _final_prediction_payload(
        match=match,
        recommendation_side=prediction_side,
        recommendation_outcome=prediction_outcome,
        score_projection=score_projection,
        confidence=confidence,
        weighted_edge=weighted_edge,
    )

    return CollectiveDecision(
        round_id=match.round_id,
        match={
            "home_team": match.home_team,
            "away_team": match.away_team,
            "market_home_probability": round(match.market_home_probability, 4),
        },
        method={
            "name": "civic_society_decision_v2" if society_decision else "privilege_weighted_prediction_vote",
            "description": _method_description(society_decision=bool(society_decision)),
            "collective_edge_threshold": collective_edge_threshold,
            "access_multipliers": ACCESS_MULTIPLIERS,
            "world_verified_multiplier": WORLD_VERIFIED_MULTIPLIER,
            "verified_lineage_multiplier": VERIFIED_LINEAGE_MULTIPLIER,
            "weight_cap": 4.0,
            "evidence_depth_range": [0.88, 1.16],
            "society_decision_weights": SOCIETY_DECISION_WEIGHTS,
        },
        match_call={
            "predicted_winner": prediction_outcome,
            "lean": prediction_side,
            "is_pickem": prediction_side == "draw",
        },
        prediction=final_prediction,
        recommendation={
            "side": recommendation_side,
            "outcome": recommendation_outcome,
            "winner": recommendation_outcome,
            "should_place_single_bet": True,
            "confidence_label": _confidence_label(confidence),
            "rationale": (
                _society_rationale(society_decision, match)
                if society_decision
                else _rationale(
                    side=recommendation_side,
                    match=match,
                    weighted_home_probability=weighted_home_probability,
                    weighted_edge=weighted_edge,
                    confidence=confidence,
                    support_margin=support_margin,
                )
            ),
        },
        internal_metrics={
            "decision_layer": "society_v2" if society_decision else "legacy_weighted_forecast",
            "weighted_home_probability": round(weighted_home_probability, 4),
            "weighted_away_probability": round(1.0 - weighted_home_probability, 4),
            "market_home_probability": round(match.market_home_probability, 4),
            "market_edge": round(weighted_edge, 4),
            "prediction_value_signal": round(prediction_value_signal, 4),
            "calibrated_home_probability": round(calibrated_home_probability, 4),
            "confidence": confidence,
            "society_decision": society_decision or {},
        },
        score_projection=score_projection,
        vote_breakdown={
            "ants": len(votes),
            "raw_forecast_sides": raw_counts,
            "raw_prediction_winners": prediction_counts["winner"],
            "raw_scorelines": prediction_counts["scoreline"],
            "raw_total_goals": prediction_counts["total_goals"],
            "weighted_side_support": weighted_side_support,
            "forecast_weighted_side_support": forecast_weighted_side_support,
            "support_margin": round(support_margin, 4),
            "average_weight": round(total_weight / len(votes), 4),
            "total_weight": round(total_weight, 4),
        },
        top_supporters=_top_supporters(votes, recommendation_side, match),
        agent_predictions=agent_predictions,
        agent_votes=agent_votes,
    )


def _weighted_vote(agent: AntAgent, forecast: Forecast) -> WeightedVote:
    access = ACCESS_MULTIPLIERS.get(forecast.access_tier, 1.0)
    world = WORLD_VERIFIED_MULTIPLIER if agent.world_verified else 1.0
    lineage = VERIFIED_LINEAGE_MULTIPLIER if agent.verified_lineage else 1.0
    reputation = 0.65 + max(0.0, min(agent.accuracy, 1.0))
    conviction = 0.65 + min(abs(forecast.edge) / 0.08, 1.35)
    budget = 1.0 + min(max(agent.genome.query_budget, 0.0), 3.0) * 0.05
    evidence_depth = _evidence_depth_multiplier(forecast.visible_findings)
    participation = 1.0 if forecast.stake > 0.0 else 0.25
    raw_weight = access * world * lineage * reputation * conviction * budget * evidence_depth * participation
    weight = min(raw_weight, 4.0)
    return WeightedVote(
        agent=agent,
        forecast=forecast,
        probability_vote=_prediction_side(forecast.home_probability),
        weight=round(weight, 4),
        components={
            "access": round(access, 4),
            "world": round(world, 4),
            "lineage": round(lineage, 4),
            "reputation": round(reputation, 4),
            "conviction": round(conviction, 4),
            "query_budget": round(budget, 4),
            "evidence_depth": round(evidence_depth, 4),
            "participation": round(participation, 4),
        },
    )


def _evidence_depth_multiplier(visible_findings: int) -> float:
    finding_count = min(max(int(visible_findings or 0), 0), 8)
    return 0.88 + finding_count * 0.035


def _recommendation_side(weighted_edge: float, threshold: float) -> str:
    if weighted_edge >= threshold:
        return "home"
    if weighted_edge <= -threshold:
        return "away"
    return "home" if weighted_edge >= 0 else "away"


def _collective_recommendation_side(
    *,
    weighted_side_support: dict[str, float],
    raw_counts: dict[str, int],
    weighted_edge: float,
    collective_edge_threshold: float,
) -> str:
    strongest_side = max(weighted_side_support, key=weighted_side_support.get)
    if strongest_side == "draw" and raw_counts.get("draw", 0) > 0:
        return "draw"
    if raw_counts.get(strongest_side, 0) > 0:
        return strongest_side
    return _recommendation_side(weighted_edge, collective_edge_threshold)


def _raw_counts(forecasts: list[Forecast]) -> dict[str, int]:
    counts = {"home": 0, "draw": 0, "away": 0}
    for forecast in forecasts:
        counts[forecast.side] = counts.get(forecast.side, 0) + 1
    return counts


def _weighted_side_support(votes: list[WeightedVote]) -> dict[str, float]:
    home = sum(vote.weight for vote in votes if vote.forecast.side == "home")
    draw = sum(vote.weight for vote in votes if vote.forecast.side == "draw")
    away = sum(vote.weight for vote in votes if vote.forecast.side == "away")
    if home == 0.0 and draw == 0.0 and away == 0.0:
        home = sum(vote.forecast.home_probability * vote.weight for vote in votes)
        away = sum((1.0 - vote.forecast.home_probability) * vote.weight for vote in votes)
    total = max(home + draw + away, 1e-9)
    return {
        "home": round(home / total, 4),
        "draw": round(draw / total, 4),
        "away": round(away / total, 4),
    }


def _society_decision_v2(
    *,
    agents_by_id: dict[str, AntAgent],
    forecasts: list[Forecast],
    civic_actions: list[CivicAction],
    society_state: dict,
) -> dict | None:
    actions = [
        action
        for action in civic_actions
        if action.civic_choice in {"home", "draw", "away"}
        and action.status not in {"skipped_unavailable_judgment", "rejected_insufficient_credits"}
    ]
    actions = _latest_civic_actions_by_agent(actions)
    if not actions:
        return None

    components = {
        side: {"civic": 0.0, "action_quality": 0.0, "reputation": 0.0, "risk": 0.0, "commitment": 0.0}
        for side in ("home", "draw", "away")
    }
    for action in actions:
        side = action.civic_choice
        agent = agents_by_id.get(action.agent_id)
        base = _civic_action_base_weight(action)
        reputation = _agent_reputation_multiplier(agent)
        components[side]["civic"] += base * reputation
        components[side]["action_quality"] += base * _civic_action_quality(action)
        components[side]["reputation"] += base * reputation
        components[side]["risk"] += base * _risk_coherence(action)

    for forecast in forecasts:
        if forecast.side not in {"home", "draw", "away"}:
            continue
        components[forecast.side]["commitment"] += _commitment_units(forecast.stake)

    blocker_penalties = _society_blocker_penalties(society_state)
    normalized_components = {
        component: _normalize_side_scores({side: values[component] for side, values in components.items()})
        for component in ("civic", "action_quality", "reputation", "risk", "commitment")
    }
    review_signal = _society_review_signal(society_state)
    normalized_components["review"] = _normalize_side_scores(review_signal)
    normalized_penalties = _normalize_side_scores(blocker_penalties)
    raw_scores: dict[str, float] = {}
    for side in ("home", "draw", "away"):
        score = 0.0
        for component, weight in SOCIETY_DECISION_WEIGHTS.items():
            if component == "blocker_penalty":
                continue
            score += normalized_components[component][side] * weight
        score -= normalized_penalties[side] * SOCIETY_DECISION_WEIGHTS["blocker_penalty"]
        raw_scores[side] = round(max(0.0, score), 6)

    normalized_scores = _normalize_side_scores(raw_scores)
    side = max(normalized_scores, key=normalized_scores.get)
    blockers = _society_open_blockers(society_state)
    confidence = _society_decision_confidence(
        normalized_scores=normalized_scores,
        actions=actions,
        selected_side=side,
        blockers=blockers,
        normalized_commitment=normalized_components["commitment"],
    )
    return {
        "version": "civic_society_decision_v2",
        "side": side,
        "normalized_scores": normalized_scores,
        "raw_scores": {key: round(value, 4) for key, value in raw_scores.items()},
        "component_scores": {
            key: {side: round(value, 4) for side, value in scores.items()}
            for key, scores in normalized_components.items()
        },
        "blocker_penalties": {side: round(value, 4) for side, value in normalized_penalties.items()},
        "reviews": _society_review_payloads(society_state),
        "open_blockers": blockers,
        "civic_action_count": len(actions),
        "support_margin": round(_support_margin(normalized_scores), 4),
        "confidence": confidence,
        "weights": dict(SOCIETY_DECISION_WEIGHTS),
    }


def _normalize_side_scores(scores: dict[str, float]) -> dict[str, float]:
    total = sum(max(float(value), 0.0) for value in scores.values())
    if total <= 1e-9:
        return {"home": 0.0, "draw": 0.0, "away": 0.0}
    return {
        "home": round(max(float(scores.get("home", 0.0)), 0.0) / total, 4),
        "draw": round(max(float(scores.get("draw", 0.0)), 0.0) / total, 4),
        "away": round(max(float(scores.get("away", 0.0)), 0.0) / total, 4),
    }


def _civic_action_base_weight(action: CivicAction) -> float:
    if action.status == "accepted":
        return max(float(action.weight or 0.0), 0.1)
    if action.status == "reviewed":
        return max(float(action.weight or 0.0), 0.1)
    if action.status == "observed":
        return 0.3
    return 0.0


def _latest_civic_actions_by_agent(actions: list[CivicAction]) -> list[CivicAction]:
    latest: dict[str, tuple[int, int, CivicAction]] = {}
    for index, action in enumerate(actions):
        rank = _civic_action_phase_rank(action)
        previous = latest.get(action.agent_id)
        if previous is None or (rank, index) >= (previous[0], previous[1]):
            latest[action.agent_id] = (rank, index, action)
    return [
        item[2]
        for item in sorted(latest.values(), key=lambda value: (value[0], value[1], value[2].agent_id))
    ]


def _civic_action_phase_rank(action: CivicAction) -> int:
    phase = str((action.metadata or {}).get("phase") or "")
    if phase == "post_resolution_review" or action.action_id.startswith("civic_review:"):
        return 2
    return 1


def _civic_action_quality(action: CivicAction) -> float:
    if action.action_type == "commit_stake":
        thesis_bonus = 0.04 if str((action.metadata or {}).get("thesis") or "").strip() else 0.0
        signal_bonus = 0.03 if str((action.metadata or {}).get("main_signal") or "").strip() else 0.0
        survival_bonus = 0.03 if str((action.metadata or {}).get("survival_reason") or "").strip() else 0.0
        level = {"micro": 0.96, "small": 1.05, "medium": 1.12, "high": 1.18}.get(action.commitment_label, 1.0)
        return round(level + thesis_bonus + signal_bonus + survival_bonus, 4)
    if action.action_type == "challenge_source":
        return 1.16
    if action.action_type == "minority_report":
        return 1.12
    if action.action_type in {"request_evidence", "fund_scout"}:
        return 1.08
    if action.action_type == "call_discussion":
        return 1.04
    if action.action_type == "hold_position":
        return 0.55
    return 1.0


def _risk_coherence(action: CivicAction) -> float:
    metadata = action.metadata or {}
    risk_read = str(metadata.get("risk_read") or "acceptable")
    stake_level = str(metadata.get("stake_level") or action.commitment_label or "micro")
    conviction = str(metadata.get("conviction") or "medium")
    if risk_read == "too_risky":
        return {"micro": 1.18, "small": 0.95, "medium": 0.58, "high": 0.35}.get(stake_level, 0.8)
    if risk_read == "attractive":
        base = {"micro": 0.68, "small": 0.9, "medium": 1.12, "high": 1.18}.get(stake_level, 0.9)
        if stake_level == "high" and conviction != "high":
            base -= 0.18
        return round(max(base, 0.35), 4)
    base = {"micro": 0.88, "small": 1.08, "medium": 1.12, "high": 0.82}.get(stake_level, 1.0)
    if stake_level == "high" and conviction == "high":
        base = 1.02
    return round(base, 4)


def _agent_reputation_multiplier(agent: AntAgent | None) -> float:
    if agent is None:
        return 1.0
    civic = _mind_reputation_score(agent, "civic_reputation")
    calibration = _mind_reputation_score(agent, "calibration_reputation")
    value = 1.0 + civic * 0.3 + calibration * 0.2
    return round(max(0.72, min(1.28, value)), 4)


def _mind_reputation_score(agent: AntAgent, key: str) -> float:
    reputation = (agent.mind or {}).get(key) or {}
    try:
        return max(-1.0, min(1.0, float(reputation.get("score") or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _commitment_units(stake: float) -> float:
    if stake <= 0.0:
        return 0.0
    capped = min(float(stake), 20.0)
    return capped ** 0.5


def _society_blocker_penalties(society_state: dict) -> dict[str, float]:
    penalties = {"home": 0.0, "draw": 0.0, "away": 0.0}
    blockers = set(_society_open_blockers(society_state))
    for key, factor, blocker in (
        ("evidence_backlog", 0.05, "evidence_requests_open"),
        ("source_audit_backlog", 0.14, "source_audits_open"),
        ("discussion_backlog", 0.04, "discussion_calls_open"),
        ("minority_reports", 0.03, "minority_reports_present"),
    ):
        if blocker not in blockers:
            continue
        for item in society_state.get(key, []) or []:
            priority = _priority_penalty_multiplier(str(item.get("priority") or "low"))
            context = item.get("choice_context") or {}
            if not isinstance(context, dict):
                continue
            for side, count in context.items():
                if side in penalties:
                    penalties[side] += factor * priority * max(int(count or 0), 0)
    for effect in society_state.get("source_audit_effects", []) or []:
        if not isinstance(effect, dict) or effect.get("status") != "downgraded":
            continue
        context = effect.get("choice_context") or {}
        if not isinstance(context, dict):
            continue
        for side, count in context.items():
            if side in penalties:
                penalties[side] += 0.18 * max(int(count or 0), 0)
    return penalties


def _society_review_signal(society_state: dict) -> dict[str, float]:
    signal = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for review in society_state.get("reviews", []) or []:
        if not isinstance(review, dict):
            continue
        side = str(review.get("affected_side") or "none")
        if side not in signal:
            continue
        effect = str(review.get("decision_effect") or "")
        support = max(int(review.get("support_count") or 0), 1)
        if effect == "clear_blocker":
            signal[side] += 1.0 * support
        elif effect == "carry_minority":
            signal[side] += 0.45 * support
        elif effect == "reserve_budget":
            signal[side] += 0.3 * support
    return signal


def _society_review_payloads(society_state: dict) -> list[dict]:
    reviews = society_state.get("reviews") or []
    if not isinstance(reviews, list):
        return []
    payloads = []
    for review in reviews:
        if not isinstance(review, dict):
            continue
        payloads.append(
            {
                "review_id": review.get("review_id") or "",
                "review_type": review.get("review_type") or "",
                "affected_side": review.get("affected_side") or "none",
                "status": review.get("status") or "",
                "decision_effect": review.get("decision_effect") or "",
                "support_count": review.get("support_count") or 0,
                "summary": review.get("summary") or "",
            }
        )
    return payloads[:8]


def _priority_penalty_multiplier(priority: str) -> float:
    if priority == "high":
        return 1.4
    if priority == "medium":
        return 1.0
    return 0.65


def _society_open_blockers(society_state: dict) -> list[str]:
    guidance = society_state.get("execution_guidance") or society_state.get("decision_guidance") or {}
    blockers = guidance.get("open_blockers") or []
    if not isinstance(blockers, list):
        return []
    return [str(blocker) for blocker in blockers if str(blocker)]


def _society_decision_confidence(
    *,
    normalized_scores: dict[str, float],
    actions: list[CivicAction],
    selected_side: str,
    blockers: list[str],
    normalized_commitment: dict[str, float],
) -> float:
    margin = _support_margin(normalized_scores)
    participation_score = min(len(actions) / 80.0, 1.0)
    commitment_alignment = float(normalized_commitment.get(selected_side, 0.0))
    blocker_penalty = min(len(blockers) * 0.08, 0.32)
    if "weak_sources_found" in blockers:
        blocker_penalty += 0.08
    confidence = 0.24 + min(margin / 0.28, 1.0) * 0.38 + participation_score * 0.14
    confidence += min(commitment_alignment, 1.0) * 0.12
    confidence -= blocker_penalty
    return round(max(0.18, min(confidence, 0.9)), 4)


def _support_margin(weighted_side_support: dict[str, float]) -> float:
    values = sorted((float(value) for value in weighted_side_support.values()), reverse=True)
    if len(values) < 2:
        return values[0] if values else 0.0
    return values[0] - values[1]


def _prediction_value_signal(*, prediction_side: str, weighted_edge: float, support_margin: float) -> float:
    if prediction_side == "away":
        return -weighted_edge
    if prediction_side == "draw":
        return support_margin * 0.08
    return weighted_edge


def _calibrated_home_probability(
    *,
    weighted_home_probability: float,
    weighted_side_support: dict[str, float],
    prediction_side: str,
) -> float:
    home_support = float(weighted_side_support.get("home", 0.0))
    away_support = float(weighted_side_support.get("away", 0.0))
    support_probability = 0.5 + (home_support - away_support) * 0.22
    if prediction_side == "draw":
        value = 0.5 + (home_support - away_support) * 0.04
    elif prediction_side == "home":
        value = max(weighted_home_probability, support_probability, 0.501)
    elif prediction_side == "away":
        value = min(weighted_home_probability, support_probability, 0.499)
    else:
        value = weighted_home_probability
    return round(min(max(value, 0.01), 0.99), 4)


def _decision_confidence(*, edge: float, support_margin: float, participation: int) -> float:
    edge_score = min(abs(edge) / 0.08, 1.0)
    margin_score = min(support_margin / 0.25, 1.0)
    participation_score = min(participation / 100.0, 1.0)
    confidence = 0.25 + edge_score * 0.45 + margin_score * 0.2 + participation_score * 0.1
    return round(min(confidence, 0.95), 4)


def _confidence_label(confidence: float) -> str:
    if confidence >= 0.72:
        return "high"
    if confidence >= 0.48:
        return "medium"
    return "low"


def _score_projection(*, home_probability: float, home_team: str, away_team: str, recommendation_side: str) -> dict:
    favorite_gap = home_probability - 0.5
    total_goals = 2.45 + min(abs(favorite_gap) * 1.2, 0.35)
    home_goals = total_goals * (0.5 + favorite_gap * 0.72)
    away_goals = max(0.15, total_goals - home_goals)
    rounded_home = max(0, round(home_goals))
    rounded_away = max(0, round(away_goals))
    if recommendation_side == "draw":
        shared = max(0, round(total_goals / 2))
        rounded_home = shared
        rounded_away = shared
    elif rounded_home == rounded_away:
        if recommendation_side == "home":
            rounded_home += 1
        elif recommendation_side == "away":
            rounded_away += 1
    return {
        "home_team": home_team,
        "away_team": away_team,
        "expected_home_goals": round(home_goals, 2),
        "expected_away_goals": round(away_goals, 2),
        "expected_total_goals": round(total_goals, 2),
        "most_likely_score": {
            "home": rounded_home,
            "away": rounded_away,
            "label": f"{home_team} {rounded_home}-{rounded_away} {away_team}",
        },
        "note": "Goal estimates are a lightweight projection from collective win probability, not a full goal model.",
    }


def _winner_label(side: str, match: MatchContext) -> str:
    if side == "home":
        return match.home_team
    if side == "away":
        return match.away_team
    if side == "draw":
        return "draw"
    if side == "pickem":
        return "too_close_to_call"
    return "draw"


def _probability_side(home_probability: float) -> str:
    if abs(home_probability - 0.5) < 0.006:
        return "draw"
    return "home" if home_probability > 0.5 else "away"


def _prediction_side(home_probability: float) -> str:
    if abs(home_probability - 0.5) < 0.006:
        return "draw"
    return "home" if home_probability > 0.5 else "away"


def _prediction_winner(home_probability: float, match: MatchContext) -> str:
    side = _prediction_side(home_probability)
    if side == "home":
        return match.home_team
    if side == "away":
        return match.away_team
    return "draw"


def _goal_band(total_goals: float) -> str:
    if total_goals >= 2.65:
        return "over_2_5"
    if total_goals <= 2.25:
        return "under_2_5"
    return "around_2_3_goals"


def _agent_scoreline(vote: WeightedVote, match: MatchContext) -> dict:
    side = _prediction_side(vote.forecast.home_probability)
    projection = _score_projection(
        home_probability=vote.forecast.home_probability,
        home_team=match.home_team,
        away_team=match.away_team,
        recommendation_side=side,
    )
    return projection["most_likely_score"]


def _agent_prediction_payload(vote: WeightedVote, match: MatchContext) -> dict:
    forecast = vote.forecast
    scoreline = _agent_scoreline(vote, match)
    total_goals = scoreline["home"] + scoreline["away"]
    edge_label = _edge_label(forecast.edge)
    return {
        "agent_id": vote.agent.agent_id,
        "wallet_address": vote.agent.wallet_address,
        "ens_name": vote.agent.ens_name,
        "model": forecast.model or vote.agent.genome.model,
        "persona": forecast.persona,
        "datafeed_interests": forecast.datafeed_interests,
        "source_weights": forecast.source_weights,
        "prediction": {
            "winner": _prediction_winner(forecast.home_probability, match),
            "side": _prediction_side(forecast.home_probability),
            "scoreline": scoreline,
            "total_goals": _goal_band(float(total_goals)),
            "both_teams_score": "yes" if scoreline["home"] > 0 and scoreline["away"] > 0 else "no",
            "confidence": edge_label,
        },
        "bet_intent": {
            "side": forecast.side,
            "outcome": _winner_label(forecast.side, match),
            "value": edge_label,
            "risk_profile": forecast.risk_profile,
        },
        "weight": vote.weight,
        "access_tier": forecast.access_tier,
        "risk_profile": forecast.risk_profile,
        "survival_thesis": _survival_thesis_payload(forecast),
        "reason": forecast.decision_reason,
    }


def _final_prediction_payload(
    *,
    match: MatchContext,
    recommendation_side: str,
    recommendation_outcome: str,
    score_projection: dict,
    confidence: float,
    weighted_edge: float,
) -> dict:
    scoreline = score_projection["most_likely_score"]
    total_goals = int(scoreline["home"]) + int(scoreline["away"])
    return {
        "winner": recommendation_outcome,
        "side": recommendation_side,
        "scoreline": scoreline,
        "total_goals": _goal_band(float(total_goals)),
        "both_teams_score": "yes" if scoreline["home"] > 0 and scoreline["away"] > 0 else "no",
        "confidence": _confidence_label(confidence),
        "value": _edge_label(abs(weighted_edge)),
        "sentence": _prediction_sentence(
            match=match,
            recommendation_side=recommendation_side,
            recommendation_outcome=recommendation_outcome,
            scoreline=scoreline,
            confidence=confidence,
        ),
    }


def _prediction_sentence(
    *,
    match: MatchContext,
    recommendation_side: str,
    recommendation_outcome: str,
    scoreline: dict,
    confidence: float,
) -> str:
    if recommendation_side == "draw":
        return (
            f"The colony calls a draw in {match.home_team} vs {match.away_team}, "
            f"with a {scoreline['label']} score call and {_confidence_label(confidence)} confidence."
        )
    return (
        f"The colony leans {recommendation_outcome}, with a {scoreline['label']} score call "
        f"and {_confidence_label(confidence)} confidence."
    )


def _edge_label(edge: float) -> str:
    value = abs(edge)
    if value >= 0.055:
        return "strong"
    if value >= 0.025:
        return "medium"
    if value > 0:
        return "thin"
    return "none"


def _prediction_counts(agent_predictions: list[dict]) -> dict[str, dict[str, int]]:
    winners = Counter(str(item["prediction"]["winner"]) for item in agent_predictions)
    scorelines = Counter(str(item["prediction"]["scoreline"]["label"]) for item in agent_predictions)
    total_goals = Counter(str(item["prediction"]["total_goals"]) for item in agent_predictions)
    return {
        "winner": dict(winners),
        "scoreline": dict(scorelines.most_common(10)),
        "total_goals": dict(total_goals),
    }


def _method_description(*, society_decision: bool) -> str:
    if society_decision:
        return (
            "When CAMEL-backed civic actions exist, the final side is selected by a civic society score: "
            "social choice, thesis quality, reputation, survival-risk coherence, capped financial commitment, "
            "post-resolution reviews, and unresolved blockers. "
            "The legacy weighted forecast remains available as a baseline signal, but stake size alone cannot "
            "dominate the colony decision."
        )
    return (
        "Every ant emits a post-debate prediction. Internally, the prediction is scored against "
        "the market anchor so the colony can detect value. Votes are weighted by "
        "knowledge access, World/lineage verification, historical accuracy, and conviction. "
        "Votes with deeper visible evidence get a modest boost, while evidence-thin votes are damped. "
        "For group-stage markets every ant must pick one outcome: home win, draw, or away win. "
        "The final prediction and bet follow the strongest weighted outcome after debate."
    )


def _rationale(
    *,
    side: str,
    match: MatchContext,
    weighted_home_probability: float,
    weighted_edge: float,
    confidence: float,
    support_margin: float,
) -> str:
    team = _winner_label(side, match)
    value = _edge_label(abs(weighted_edge))
    confidence_label = _confidence_label(confidence)
    return (
        f"Weighted colony interactions favor {team} with {value} value "
        f"and {confidence_label} confidence."
    )


def _society_rationale(society_decision: dict, match: MatchContext) -> str:
    side = str(society_decision.get("side") or "draw")
    team = _winner_label(side, match)
    margin = float(society_decision.get("support_margin") or 0.0)
    blockers = society_decision.get("open_blockers") or []
    blocker_text = "no open blockers"
    if blockers:
        blocker_text = "open blockers: " + ", ".join(str(item) for item in blockers)
    return (
        f"Civic society score favors {team} with margin {margin:.2f}; "
        f"the decision combines civic choice, thesis quality, reputation, survival-risk coherence, "
        f"capped commitment, post-resolution reviews, and {blocker_text}."
    )


def _top_supporters(
    votes: list[WeightedVote],
    recommendation_side: str,
    match: MatchContext,
    count: int = 12,
) -> list[dict]:
    sorted_votes = sorted(
        votes,
        key=lambda vote: _side_support_score(vote, recommendation_side),
        reverse=True,
    )
    return [_agent_vote_payload(vote, match) for vote in sorted_votes[:count]]


def _side_support_score(vote: WeightedVote, side: str) -> float:
    if side == "draw":
        alignment = 1.0 if vote.forecast.side == "draw" else 0.35
        closeness = 1.0 - min(abs(vote.forecast.home_probability - 0.5) / 0.08, 1.0)
        return alignment * closeness * vote.weight
    alignment = 1.0 if vote.forecast.side == side else 0.35
    probability = vote.forecast.home_probability if side == "home" else 1.0 - vote.forecast.home_probability
    return alignment * probability * vote.weight


def _agent_vote_payload(vote: WeightedVote, match: MatchContext) -> dict:
    forecast = vote.forecast
    agent = vote.agent
    return {
        "agent_id": agent.agent_id,
        "wallet_address": agent.wallet_address,
        "ens_name": agent.ens_name,
        "genome_id": forecast.genome_id,
        "model": forecast.model or agent.genome.model,
        "persona": forecast.persona,
        "datafeed_interests": forecast.datafeed_interests,
        "source_weights": forecast.source_weights,
        "prediction": _agent_prediction_payload(vote, match)["prediction"],
        "access_tier": forecast.access_tier,
        "risk_profile": forecast.risk_profile,
        "world_verified": agent.world_verified,
        "verified_lineage": agent.verified_lineage,
        "accuracy": round(agent.accuracy, 4),
        "forecast_side": forecast.side,
        "probability_vote": vote.probability_vote,
        "home_probability": forecast.home_probability,
        "market_edge": forecast.market_edge,
        "edge": forecast.edge,
        "stake": forecast.stake,
        "survival_thesis": _survival_thesis_payload(forecast),
        "weight": vote.weight,
        "weight_components": vote.components,
        "decision_reason": forecast.decision_reason,
    }


def _survival_thesis_payload(forecast: Forecast) -> dict:
    judgment = forecast.judgment or {}
    return {
        "pick": forecast.side,
        "thesis": judgment.get("thesis") or "",
        "main_signal": judgment.get("main_signal") or "",
        "conviction": judgment.get("conviction") or "",
        "risk_read": judgment.get("risk_read") or "",
        "stake_level": judgment.get("stake_level") or "",
        "survival_reason": judgment.get("survival_reason") or "",
    }
