"""Civic action resolver for the ant society.

This turns qualitative CAMEL judgments into replayable world actions. The
first version is intentionally small: one action per judged ant, attention
costs for useful social work, and optional fake-credit spend for scout funding.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

from .agent import AntAgent
from .economy import EconomyLedger
from .models import (
    CalibrationReputationChange,
    CivicAction,
    CivicReputationChange,
    CivicReward,
    DebateRoom,
    Finding,
    Forecast,
    JudgmentRevision,
    MatchContext,
    Side,
    SocietyExecution,
    SocietyReview,
    SocietyResolution,
)

ACTION_POINT_COSTS = {
    "commit_stake": 1,
    "vote_only": 1,
    "request_evidence": 1,
    "challenge_source": 1,
    "call_discussion": 1,
    "minority_report": 1,
    "fund_scout": 1,
    "hold_position": 0,
}
SCOUT_FUND_CREDIT_COST = 0.05
CIVIC_REWARD_BLOCKER_CLEARED = 0.04
CIVIC_REWARD_WEAK_SOURCE_FOUND = 0.06
CIVIC_REPUTATION_BLOCKER_CLEARED = 0.05
CIVIC_REPUTATION_WEAK_SOURCE_FOUND = 0.08


def resolve_civic_actions(
    *,
    match: MatchContext,
    agents: list[AntAgent],
    forecasts: list[Forecast],
    ledger: EconomyLedger,
) -> tuple[list[CivicAction], dict]:
    agents_by_id = {agent.agent_id: agent for agent in agents}
    actions: list[CivicAction] = []
    target_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    civic_choice_counts: Counter[str] = Counter()
    commitment_counts: Counter[str] = Counter()
    stake_level_counts: Counter[str] = Counter()
    risk_read_counts: Counter[str] = Counter()
    main_signal_counts: Counter[str] = Counter()
    effect_counts: Counter[str] = Counter()
    action_points_spent = 0
    credits_spent = 0.0

    for index, forecast in enumerate(forecasts, start=1):
        judgment = forecast.judgment or {}
        if not judgment:
            continue
        agent = agents_by_id.get(forecast.agent_id)
        if agent is None:
            continue

        action_type = _clean_action(judgment.get("action"))
        civic_choice = _clean_side(judgment.get("civic_choice") or forecast.side)
        commitment_label = _clean_text(judgment.get("commitment_label")) or "none"
        source = _clean_text(judgment.get("source")) or "unknown"
        target = _action_target(action_type=action_type, judgment=judgment, forecast=forecast)
        stake_level = _clean_text(judgment.get("stake_level") or commitment_label) or "micro"
        risk_read = _clean_text(judgment.get("risk_read")) or "acceptable"
        main_signal = _clean_text(judgment.get("main_signal")) or "mixed"
        effect_type = _effect_type(action_type)
        action_points = ACTION_POINT_COSTS.get(action_type, 1)
        status = "accepted"
        credit_cost = 0.0

        if not _is_survival_judgment_source(source) or (
            _is_camel_fallback_source(source) and action_type == "hold_position"
        ):
            status = "skipped_unavailable_judgment"
            action_points = 0
        elif action_type == "hold_position":
            status = "observed"
        elif action_type == "fund_scout":
            credit_cost = SCOUT_FUND_CREDIT_COST
            paid = ledger.debit_agent(
                agent,
                credit_cost,
                payee_id="scout_pool",
                payment_type="fund_scout",
                resource_id=target,
                description=f"Funded scout work for {target}.",
                metadata={
                    "action_type": action_type,
                    "civic_choice": civic_choice,
                    "commitment_label": commitment_label,
                },
            )
            if not paid:
                status = "rejected_insufficient_credits"
                action_points = 0
                credit_cost = 0.0

        action = CivicAction(
            action_id=f"civic:{match.round_id}:{index:05d}",
            round_id=match.round_id,
            agent_id=forecast.agent_id,
            action_type=action_type,
            civic_choice=civic_choice,
            commitment_label=commitment_label,
            status=status,
            action_points_spent=action_points,
            credits_spent=round(credit_cost, 4),
            target=target,
            effect_type=effect_type,
            effect_summary=_effect_summary(
                action_type=action_type,
                civic_choice=civic_choice,
                target=target,
                commitment_label=commitment_label,
                status=status,
            ),
            source=source,
            weight=_action_weight(action_type=action_type, commitment_label=commitment_label, status=status),
            metadata={
                "conviction": judgment.get("conviction") or "",
                "intent": judgment.get("intent") or "",
                "risk_intent": judgment.get("risk_intent") or "",
                "risk_read": risk_read,
                "stake_level": stake_level,
                "thesis": judgment.get("thesis") or "",
                "main_signal": main_signal,
                "survival_reason": judgment.get("survival_reason") or "",
                "social_move": judgment.get("social_move") or "",
                "one_line": judgment.get("one_line") or "",
                "evidence_used": judgment.get("evidence_used") or [],
                "evidence_distrusted": judgment.get("evidence_distrusted") or [],
                "debate_question": judgment.get("debate_question") or "",
            },
        )
        actions.append(action)
        action_counts[action_type] += 1
        status_counts[status] += 1
        if status != "skipped_unavailable_judgment":
            civic_choice_counts[civic_choice] += 1
            commitment_counts[commitment_label] += 1
            stake_level_counts[stake_level] += 1
            risk_read_counts[risk_read] += 1
            main_signal_counts[main_signal] += 1
        effect_counts[effect_type] += 1
        if status == "accepted":
            target_counts[target] += 1
            action_points_spent += action_points
            credits_spent = round(credits_spent + credit_cost, 4)

    summary = {
        "civic_action_count": len(actions),
        "civic_action_counts": dict(action_counts),
        "civic_action_statuses": dict(status_counts),
        "civic_choice_counts": dict(civic_choice_counts),
        "civic_commitment_counts": dict(commitment_counts),
        "civic_stake_level_counts": dict(stake_level_counts),
        "civic_risk_read_counts": dict(risk_read_counts),
        "civic_main_signal_counts": dict(main_signal_counts),
        "civic_effect_counts": dict(effect_counts),
        "civic_action_points_spent": action_points_spent,
        "civic_credits_spent": round(credits_spent, 4),
        "civic_targets": dict(target_counts),
        "evidence_request_targets": _targets_for(actions, "evidence_request"),
        "source_challenge_targets": _targets_for(actions, "source_audit"),
        "discussion_targets": _targets_for(actions, "discussion_call"),
        "minority_report_targets": _targets_for(actions, "minority_report"),
        "funded_scout_targets": _targets_for(actions, "scout_funding"),
    }
    return actions, summary


def resolve_review_civic_actions(
    *,
    match: MatchContext,
    forecasts: list[Forecast],
    revisions: list[JudgmentRevision],
) -> tuple[list[CivicAction], dict]:
    forecasts_by_agent = {forecast.agent_id: forecast for forecast in forecasts}
    actions: list[CivicAction] = []
    action_counts: Counter[str] = Counter()
    choice_counts: Counter[str] = Counter()
    stake_level_counts: Counter[str] = Counter()
    risk_read_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    changed_count = 0

    for index, revision in enumerate(revisions, start=1):
        forecast = forecasts_by_agent.get(revision.agent_id)
        if forecast is None:
            continue
        judgment = revision.judgment or forecast.judgment or {}
        action_type = _clean_action(judgment.get("action") or revision.revised_action)
        civic_choice = _clean_side(judgment.get("civic_choice") or revision.revised_side)
        commitment_label = _clean_text(judgment.get("commitment_label")) or "none"
        target = _action_target(action_type=action_type, judgment=judgment, forecast=forecast)
        stake_level = _clean_text(judgment.get("stake_level") or commitment_label) or "micro"
        risk_read = _clean_text(judgment.get("risk_read")) or "acceptable"
        source = _clean_text(judgment.get("source")) or "unknown"
        if _is_survival_judgment_source(source):
            status = "reviewed"
        else:
            status = "skipped_review_unavailable"

        action = CivicAction(
            action_id=f"civic_review:{match.round_id}:{index:05d}",
            round_id=match.round_id,
            agent_id=revision.agent_id,
            action_type=action_type,
            civic_choice=civic_choice,
            commitment_label=commitment_label,
            status=status,
            action_points_spent=0,
            credits_spent=0.0,
            target=target,
            effect_type=_effect_type(action_type),
            effect_summary=_review_effect_summary(revision, civic_choice=civic_choice, action_type=action_type),
            source=source,
            weight=_review_action_weight(action_type=action_type, changed=revision.changed, status=status),
            metadata={
                "phase": "post_resolution_review",
                "revision_id": revision.revision_id,
                "previous_side": revision.previous_side,
                "previous_action": revision.previous_action,
                "previous_stake": revision.previous_stake,
                "review_ids": revision.review_ids,
                "changed": revision.changed,
                "conviction": judgment.get("conviction") or "",
                "risk_intent": judgment.get("risk_intent") or "",
                "risk_read": risk_read,
                "stake_level": stake_level,
                "thesis": judgment.get("thesis") or "",
                "main_signal": judgment.get("main_signal") or "",
                "survival_reason": judgment.get("survival_reason") or "",
                "social_move": judgment.get("social_move") or "",
                "one_line": judgment.get("one_line") or revision.reason,
                "evidence_used": judgment.get("evidence_used") or [],
                "evidence_distrusted": judgment.get("evidence_distrusted") or [],
                "debate_question": judgment.get("debate_question") or "",
            },
        )
        actions.append(action)
        action_counts[action_type] += 1
        choice_counts[civic_choice] += 1
        stake_level_counts[stake_level] += 1
        risk_read_counts[risk_read] += 1
        status_counts[status] += 1
        if revision.changed:
            changed_count += 1

    summary = {
        "review_judgment_count": len(revisions),
        "review_judgment_changed_count": changed_count,
        "review_civic_action_count": len(actions),
        "review_civic_action_counts": dict(action_counts),
        "review_civic_choice_counts": dict(choice_counts),
        "review_civic_stake_level_counts": dict(stake_level_counts),
        "review_civic_risk_read_counts": dict(risk_read_counts),
        "review_civic_action_statuses": dict(status_counts),
    }
    return actions, summary


def civic_layer_metrics(
    *,
    civic_summary: dict,
    population: int,
    participating_bets: int,
    total_staked: float,
) -> dict:
    choice_counts = {
        str(key): int(value)
        for key, value in (civic_summary.get("civic_choice_counts") or {}).items()
    }
    participation = sum(choice_counts.values())
    if not choice_counts or participation <= 0:
        leading_choice = "none"
        leading_support = "0/0"
        civic_confidence = "none"
    else:
        leading_choice, leading_count = sorted(
            choice_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[0]
        leading_support = f"{leading_count}/{participation}"
        civic_confidence = _support_label(leading_count=leading_count, participation=participation)

    commitment_level = _commitment_level(
        population=population,
        participating_bets=participating_bets,
        total_staked=total_staked,
    )
    unresolved = _dominant_unresolved_target(civic_summary)
    note = _civic_note(
        leading_choice=leading_choice,
        leading_support=leading_support,
        civic_confidence=civic_confidence,
        commitment_level=commitment_level,
        unresolved=unresolved,
    )
    return {
        "civic_leading_choice": leading_choice,
        "civic_leading_support": leading_support,
        "civic_participation": participation,
        "civic_confidence": civic_confidence,
        "financial_commitment_level": commitment_level,
        "civic_unresolved_target": unresolved,
        "civic_decision_note": note,
    }


def build_society_state(
    *,
    match: MatchContext,
    civic_actions: list[CivicAction],
    rooms: list[DebateRoom],
) -> dict:
    accepted = [action for action in civic_actions if action.status == "accepted"]
    evidence_requests = _group_effects(accepted, "evidence_request")
    source_audits = _group_effects(accepted, "source_audit")
    discussion_calls = _group_effects(accepted, "discussion_call")
    minority_reports = _group_effects(accepted, "minority_report")
    scout_funding = _group_effects(accepted, "scout_funding")
    civic_votes = _choice_support(accepted)
    existing_room_topics = {
        room.room_id: _clean_text(room.evidence_focus or room.stance).lower()
        for room in rooms
    }
    return {
        "round_id": match.round_id,
        "state_version": "civic_society_v1",
        "phase": "post_judgment_action_resolution",
        "civic_votes": civic_votes,
        "evidence_backlog": [
            _backlog_item(target, actions, kind="evidence_request")
            for target, actions in sorted(evidence_requests.items())
        ],
        "source_audit_backlog": [
            _backlog_item(target, actions, kind="source_audit")
            for target, actions in sorted(source_audits.items())
        ],
        "discussion_backlog": [
            _discussion_item(target, actions, existing_room_topics)
            for target, actions in sorted(discussion_calls.items())
        ],
        "minority_reports": [
            _backlog_item(target, actions, kind="minority_report")
            for target, actions in sorted(minority_reports.items())
        ],
        "scout_funding_pool": [
            _funding_item(target, actions)
            for target, actions in sorted(scout_funding.items())
        ],
        "decision_guidance": _decision_guidance(
            civic_votes=civic_votes,
            evidence_requests=evidence_requests,
            source_audits=source_audits,
            discussion_calls=discussion_calls,
            minority_reports=minority_reports,
            scout_funding=scout_funding,
        ),
    }


def society_commitment_policy(society_state: dict) -> dict:
    guidance = society_state.get("execution_guidance") or society_state.get("decision_guidance") or {}
    posture = str(guidance.get("posture") or "no_civic_layer")
    blockers = [str(item) for item in (guidance.get("open_blockers") or [])]

    if posture == "no_civic_layer":
        return _commitment_policy(
            execution_mode="baseline",
            financial_execution_label="baseline",
            stake_scale=1.0,
            should_place_single_bet=True,
            max_commitment_label="baseline",
            reason="No civic layer was produced; keep baseline execution behavior.",
            blockers=blockers,
        )
    if "source_audits_open" in blockers or "weak_sources_found" in blockers:
        return _commitment_policy(
            execution_mode="research_first",
            financial_execution_label="paused",
            stake_scale=0.0,
            should_place_single_bet=False,
            max_commitment_label="none",
            reason="Source quality blockers are open; pause financial commitment until contested evidence is reviewed.",
            blockers=blockers,
        )
    if "evidence_requests_open" in blockers:
        return _commitment_policy(
            execution_mode="micro_commitment_only",
            financial_execution_label="tiny",
            stake_scale=0.25,
            should_place_single_bet=False,
            max_commitment_label="small",
            reason="Evidence requests are open; keep only tiny exploratory commitments.",
            blockers=blockers,
        )
    if "discussion_calls_open" in blockers or "minority_reports_present" in blockers:
        return _commitment_policy(
            execution_mode="discussion_first",
            financial_execution_label="small",
            stake_scale=0.5,
            should_place_single_bet=False,
            max_commitment_label="small",
            reason="Social disagreement remains; wait for discussion before scaling commitment.",
            blockers=blockers,
        )
    return _commitment_policy(
        execution_mode="commitment_review",
        financial_execution_label="normal",
        stake_scale=1.0,
        should_place_single_bet=True,
        max_commitment_label="high",
        reason="No civic blockers remain; normal commitment review is allowed.",
        blockers=blockers,
    )


def apply_society_commitment_policy(forecasts: list[Forecast], policy: dict) -> list[Forecast]:
    scale = float(policy.get("stake_scale") if policy.get("stake_scale") is not None else 1.0)
    scale = max(0.0, min(scale, 1.0))
    if scale >= 0.9999:
        return forecasts

    updated: list[Forecast] = []
    reason = str(policy.get("reason") or "Society commitment policy adjusted stake.")
    label = str(policy.get("financial_execution_label") or "adjusted")
    for forecast in forecasts:
        judgment = forecast.judgment or {}
        if not _is_survival_judgment_source(str(judgment.get("source") or "")):
            updated.append(forecast)
            continue
        new_stake = round(forecast.stake * scale, 4)
        updated.append(
            replace(
                forecast,
                stake=new_stake,
                decision_reason=(
                    f"{forecast.decision_reason}; society execution={label}: {reason}"
                ),
            )
        )
    return updated


def resolve_society_backlogs(*, match: MatchContext, society_state: dict) -> tuple[list[SocietyResolution], dict]:
    resolutions: list[SocietyResolution] = []
    funding_by_target = {
        str(item.get("target") or ""): float(item.get("credits") or 0.0)
        for item in society_state.get("scout_funding_pool", [])
    }

    for item in society_state.get("evidence_backlog", []):
        resolutions.append(
            _resolution_from_backlog_item(
                match=match,
                index=len(resolutions) + 1,
                item=item,
                resolution_type="evidence_scout",
                status=_execution_status(item, queued="scout_queued"),
                next_step="Run focused scout or attach existing evidence before scaling commitment.",
                credit_budget=funding_by_target.get(str(item.get("target") or ""), 0.0),
            )
        )
    for item in society_state.get("source_audit_backlog", []):
        resolutions.append(
            _resolution_from_backlog_item(
                match=match,
                index=len(resolutions) + 1,
                item=item,
                resolution_type="source_audit",
                status="audit_queued",
                next_step="Audit cited source quality and downgrade weak evidence if needed.",
                credit_budget=0.0,
            )
        )
    for item in society_state.get("discussion_backlog", []):
        boosted_rooms = item.get("boosted_rooms") or []
        status = "room_boosted" if boosted_rooms else _execution_status(item, queued="room_queued")
        resolutions.append(
            _resolution_from_backlog_item(
                match=match,
                index=len(resolutions) + 1,
                item=item,
                resolution_type="discussion",
                status=status,
                next_step="Open or boost a debate room before the next commitment review.",
                credit_budget=0.0,
                metadata={"boosted_rooms": boosted_rooms},
            )
        )
    for item in society_state.get("minority_reports", []):
        resolutions.append(
            _resolution_from_backlog_item(
                match=match,
                index=len(resolutions) + 1,
                item=item,
                resolution_type="minority_review",
                status="attached_to_final_review",
                next_step="Carry minority report into the final review and score it after outcome.",
                credit_budget=0.0,
            )
        )
    for item in society_state.get("scout_funding_pool", []):
        resolutions.append(
            _resolution_from_backlog_item(
                match=match,
                index=len(resolutions) + 1,
                item=item,
                resolution_type="scout_funding",
                status="budget_reserved" if float(item.get("credits") or 0.0) > 0 else "watchlist",
                next_step="Reserve fake credits for focused scout execution.",
                credit_budget=float(item.get("credits") or 0.0),
            )
        )

    summary = {
        "society_resolution_count": len(resolutions),
        "society_resolution_counts": dict(Counter(resolution.resolution_type for resolution in resolutions)),
        "society_resolution_statuses": dict(Counter(resolution.status for resolution in resolutions)),
        "society_resolution_credit_budget": round(sum(resolution.credit_budget for resolution in resolutions), 4),
    }
    return resolutions, summary


def execute_society_resolutions(
    *,
    match: MatchContext,
    resolutions: list[SocietyResolution],
    rooms: list[DebateRoom],
) -> tuple[list[SocietyExecution], dict]:
    executions: list[SocietyExecution] = []
    for index, resolution in enumerate(resolutions, start=1):
        if resolution.resolution_type == "evidence_scout":
            executions.append(_execute_evidence_scout(match, resolution, index=index))
        elif resolution.resolution_type == "source_audit":
            executions.append(_execute_source_audit(match, resolution, index=index))
        elif resolution.resolution_type == "discussion":
            executions.append(_execute_discussion(resolution, rooms, index=index))
        elif resolution.resolution_type == "minority_review":
            executions.append(_execution_from_resolution(
                resolution,
                index=index,
                status="attached_to_review",
                result_summary="Minority report is attached to final review and later outcome scoring.",
                blocker_effect="soft_blocker_retained",
            ))
        elif resolution.resolution_type == "scout_funding":
            executions.append(_execution_from_resolution(
                resolution,
                index=index,
                status="budget_reserved",
                result_summary=f"Reserved {resolution.credit_budget:.4f} fake credits for focused scout work.",
                blocker_effect="none",
                metadata={"credit_budget": resolution.credit_budget},
            ))
        else:
            executions.append(_execution_from_resolution(
                resolution,
                index=index,
                status="unknown_resolution_type",
                result_summary="No executor is registered for this resolution type.",
                blocker_effect="blocker_retained",
            ))

    summary = {
        "society_execution_count": len(executions),
        "society_execution_counts": dict(Counter(execution.execution_type for execution in executions)),
        "society_execution_statuses": dict(Counter(execution.status for execution in executions)),
        "society_execution_blocker_effects": dict(Counter(execution.blocker_effect for execution in executions)),
        "society_execution_resolved": sum(1 for execution in executions if execution.blocker_effect == "blocker_cleared"),
        "society_execution_pending": sum(1 for execution in executions if execution.blocker_effect == "blocker_retained"),
    }
    return executions, summary


def apply_execution_guidance(society_state: dict, executions: list[SocietyExecution]) -> dict:
    if not executions:
        society_state["execution_guidance"] = dict(society_state.get("decision_guidance") or {})
        return society_state

    open_blockers: list[str] = []
    if _has_pending(executions, "evidence_scout"):
        open_blockers.append("evidence_requests_open")
    if _has_pending(executions, "source_audit"):
        open_blockers.append("source_audits_open")
    if any(execution.blocker_effect == "source_quality_failed" for execution in executions):
        open_blockers.append("weak_sources_found")
    if _has_pending(executions, "discussion"):
        open_blockers.append("discussion_calls_open")
    if any(execution.execution_type == "minority_review" for execution in executions):
        open_blockers.append("minority_reports_present")

    leading_choice = str((society_state.get("civic_votes") or {}).get("leading_choice") or "none")
    if leading_choice == "none":
        posture = "no_civic_layer"
        commitment_mode = "baseline_only"
    elif "source_audits_open" in open_blockers or "weak_sources_found" in open_blockers:
        posture = "slow_down_until_sources_are_audited"
        commitment_mode = "civic_only"
    elif "evidence_requests_open" in open_blockers:
        posture = "gather_more_evidence_before_scaling_commitment"
        commitment_mode = "civic_only"
    elif "discussion_calls_open" in open_blockers or "minority_reports_present" in open_blockers:
        posture = "discuss_before_scaling_commitment"
        commitment_mode = "civic_only"
    else:
        posture = "ready_for_commitment_review"
        commitment_mode = "funded_research" if society_state.get("scout_funding_pool") else "civic_only"

    society_state["execution_guidance"] = {
        "leading_choice": leading_choice,
        "posture": posture,
        "open_blockers": open_blockers,
        "commitment_mode": commitment_mode,
    }
    return society_state


def apply_source_audit_effects(
    *,
    findings: list[Finding],
    executions: list[SocietyExecution],
) -> tuple[list[Finding], list[dict], dict]:
    effects: list[dict] = []
    weak_audits: dict[str, dict] = {}

    for index, execution in enumerate(executions, start=1):
        if execution.execution_type != "source_audit":
            continue
        finding_ids = list(execution.produced_finding_ids)
        if not finding_ids:
            finding_ids = [
                str(value)
                for value in (execution.metadata or {}).get("matched_finding_ids", [])
                if str(value)
            ]
        if execution.blocker_effect == "source_quality_failed":
            status = "downgraded"
        elif execution.blocker_effect == "blocker_cleared":
            status = "confirmed"
        elif execution.blocker_effect == "blocker_retained":
            status = "pending"
        else:
            status = "observed"

        effect = {
            "effect_id": f"source_audit_effect:{execution.round_id}:{index:05d}",
            "round_id": execution.round_id,
            "execution_id": execution.execution_id,
            "target": execution.target,
            "status": status,
            "blocker_effect": execution.blocker_effect,
            "finding_ids": finding_ids,
            "source_quality_labels": list((execution.metadata or {}).get("source_quality_labels") or []),
            "choice_context": dict((execution.metadata or {}).get("choice_context") or {}),
            "related_action_ids": list((execution.metadata or {}).get("related_action_ids") or []),
        }
        effects.append(effect)
        if status == "downgraded":
            for finding_id in finding_ids:
                weak_audits[finding_id] = effect

    if not weak_audits:
        return list(findings), effects, _source_audit_effect_summary(effects)

    audited_findings = [
        _downgrade_finding_from_source_audit(finding, weak_audits[finding.finding_id])
        if finding.finding_id in weak_audits
        else finding
        for finding in findings
    ]
    return audited_findings, effects, _source_audit_effect_summary(effects)


def build_society_reviews(
    *,
    executions: list[SocietyExecution],
    source_audit_effects: list[dict],
) -> tuple[list[SocietyReview], dict]:
    effects_by_execution_id = {
        str(effect.get("execution_id")): effect
        for effect in source_audit_effects
        if isinstance(effect, dict) and str(effect.get("execution_id"))
    }
    reviews: list[SocietyReview] = []
    for index, execution in enumerate(executions, start=1):
        effect = effects_by_execution_id.get(execution.execution_id, {})
        context = dict(effect.get("choice_context") or (execution.metadata or {}).get("choice_context") or {})
        affected_side = _dominant_context_side(context)
        decision_effect, status = _review_effect_for_execution(execution, effect)
        reviews.append(
            SocietyReview(
                review_id=f"review:{execution.round_id}:{index:05d}",
                round_id=execution.round_id,
                review_type=f"{execution.execution_type}_review",
                target=execution.target,
                affected_side=affected_side,
                status=status,
                decision_effect=decision_effect,
                support_count=_support_count_from_context_or_execution(context, execution),
                summary=_review_summary(
                    execution=execution,
                    effect=effect,
                    affected_side=affected_side,
                    status=status,
                    decision_effect=decision_effect,
                ),
                related_execution_id=execution.execution_id,
                metadata={
                    "execution_type": execution.execution_type,
                    "execution_status": execution.status,
                    "blocker_effect": execution.blocker_effect,
                    "produced_finding_ids": execution.produced_finding_ids,
                    "related_action_ids": list((execution.metadata or {}).get("related_action_ids") or []),
                    "choice_context": context,
                    "source_audit_effect_id": effect.get("effect_id") or "",
                    "source_audit_status": effect.get("status") or "",
                },
            )
        )

    summary = {
        "society_review_count": len(reviews),
        "society_review_types": dict(Counter(review.review_type for review in reviews)),
        "society_review_statuses": dict(Counter(review.status for review in reviews)),
        "society_review_effects": dict(Counter(review.decision_effect for review in reviews)),
        "society_review_affected_sides": dict(Counter(review.affected_side for review in reviews)),
    }
    return reviews, summary


def settle_civic_rewards(
    *,
    agents: list[AntAgent],
    civic_actions: list[CivicAction],
    executions: list[SocietyExecution],
    ledger: EconomyLedger,
) -> tuple[list[CivicReward], dict]:
    agents_by_id = {agent.agent_id: agent for agent in agents}
    actions_by_id = {action.action_id: action for action in civic_actions}
    rewards: list[CivicReward] = []

    for execution in executions:
        reward_pool = _reward_pool_for_execution(execution)
        if reward_pool <= 0.0:
            continue
        contributor_actions = [
            actions_by_id[action_id]
            for action_id in execution.metadata.get("related_action_ids", []) or execution.metadata.get("action_ids", [])
            if action_id in actions_by_id
        ]
        if not contributor_actions:
            contributor_actions = [
                actions_by_id[action_id]
                for action_id in _related_action_ids_from_execution(execution)
                if action_id in actions_by_id
            ]
        contributors = sorted({action.agent_id for action in contributor_actions if action.agent_id in agents_by_id})
        if not contributors:
            continue
        per_agent = round(reward_pool / len(contributors), 4)
        if per_agent <= 0.0:
            continue
        for agent_id in contributors:
            reward_id = f"reward:{execution.round_id}:{len(rewards) + 1:05d}"
            agent = agents_by_id[agent_id]
            ledger.credit_agent(agent, per_agent, reason="civic_reward", related_id=reward_id)
            related_action_id = next(
                (action.action_id for action in contributor_actions if action.agent_id == agent_id),
                "",
            )
            rewards.append(
                CivicReward(
                    reward_id=reward_id,
                    round_id=execution.round_id,
                    agent_id=agent_id,
                    amount=per_agent,
                    reason=_reward_reason_for_execution(execution),
                    related_execution_id=execution.execution_id,
                    related_action_id=related_action_id,
                    metadata={
                        "execution_type": execution.execution_type,
                        "execution_status": execution.status,
                        "blocker_effect": execution.blocker_effect,
                        "target": execution.target,
                    },
                )
            )

    summary = {
        "civic_reward_count": len(rewards),
        "civic_reward_total": round(sum(reward.amount for reward in rewards), 4),
        "civic_reward_reasons": dict(Counter(reward.reason for reward in rewards)),
        "civic_reward_agents": dict(Counter(reward.agent_id for reward in rewards)),
    }
    return rewards, summary


def apply_civic_reputation_changes(
    *,
    agents: list[AntAgent],
    civic_actions: list[CivicAction],
    executions: list[SocietyExecution],
) -> tuple[list[CivicReputationChange], dict]:
    agents_by_id = {agent.agent_id: agent for agent in agents}
    actions_by_id = {action.action_id: action for action in civic_actions}
    changes: list[CivicReputationChange] = []

    for execution in executions:
        delta_pool = _reputation_pool_for_execution(execution)
        if delta_pool <= 0.0:
            continue
        contributor_actions = [
            actions_by_id[action_id]
            for action_id in _related_action_ids_from_execution(execution)
            if action_id in actions_by_id
        ]
        contributors = sorted({action.agent_id for action in contributor_actions if action.agent_id in agents_by_id})
        if not contributors:
            continue
        per_agent = round(delta_pool / len(contributors), 4)
        if per_agent <= 0.0:
            continue
        for agent_id in contributors:
            agent = agents_by_id[agent_id]
            related_action_id = next(
                (action.action_id for action in contributor_actions if action.agent_id == agent_id),
                "",
            )
            score_after = _apply_reputation_delta(
                agent,
                delta=per_agent,
                reason=_reputation_reason_for_execution(execution),
                execution=execution,
                related_action_id=related_action_id,
            )
            changes.append(
                CivicReputationChange(
                    change_id=f"civic_rep:{execution.round_id}:{len(changes) + 1:05d}",
                    round_id=execution.round_id,
                    agent_id=agent_id,
                    delta=per_agent,
                    score_after=score_after,
                    reason=_reputation_reason_for_execution(execution),
                    related_execution_id=execution.execution_id,
                    related_action_id=related_action_id,
                    metadata={
                        "execution_type": execution.execution_type,
                        "execution_status": execution.status,
                        "blocker_effect": execution.blocker_effect,
                        "target": execution.target,
                    },
                )
            )

    summary = {
        "civic_reputation_change_count": len(changes),
        "civic_reputation_delta_total": round(sum(change.delta for change in changes), 4),
        "civic_reputation_reasons": dict(Counter(change.reason for change in changes)),
        "civic_reputation_agents": dict(Counter(change.agent_id for change in changes)),
    }
    return changes, summary


def apply_calibration_reputation_changes(
    *,
    round_id: str,
    agents: list[AntAgent],
    forecasts: list[Forecast],
    result_side: str,
) -> tuple[list[CalibrationReputationChange], dict]:
    if result_side not in {"home", "draw", "away"}:
        return [], _calibration_reputation_summary([])

    agents_by_id = {agent.agent_id: agent for agent in agents}
    changes: list[CalibrationReputationChange] = []
    for forecast in forecasts:
        agent = agents_by_id.get(forecast.agent_id)
        if agent is None:
            continue
        delta, reason = _calibration_delta_for_forecast(forecast, result_side=result_side)
        if delta == 0.0:
            continue
        score_after = _apply_calibration_reputation_delta(
            agent,
            round_id=round_id,
            delta=delta,
            reason=reason,
            forecast=forecast,
            result_side=result_side,
        )
        changes.append(
            CalibrationReputationChange(
                change_id=f"calibration_rep:{round_id}:{len(changes) + 1:05d}",
                round_id=round_id,
                agent_id=forecast.agent_id,
                delta=delta,
                score_after=score_after,
                reason=reason,
                forecast_side=forecast.side,
                result_side=result_side,  # type: ignore[arg-type]
                stake=forecast.stake,
                metadata={
                    "commitment_label": (forecast.judgment or {}).get("commitment_label") or "",
                    "action": (forecast.judgment or {}).get("action") or "",
                    "source": (forecast.judgment or {}).get("source") or "baseline",
                    "confidence": (forecast.judgment or {}).get("conviction") or "",
                    "market_edge": forecast.market_edge,
                    "edge": forecast.edge,
                },
            )
        )
    return changes, _calibration_reputation_summary(changes)


def _commitment_policy(
    *,
    execution_mode: str,
    financial_execution_label: str,
    stake_scale: float,
    should_place_single_bet: bool,
    max_commitment_label: str,
    reason: str,
    blockers: list[str],
) -> dict:
    return {
        "execution_mode": execution_mode,
        "financial_execution_label": financial_execution_label,
        "stake_scale": round(stake_scale, 4),
        "should_place_single_bet": should_place_single_bet,
        "max_commitment_label": max_commitment_label,
        "reason": reason,
        "blockers": blockers,
    }


def _resolution_from_backlog_item(
    *,
    match: MatchContext,
    index: int,
    item: dict,
    resolution_type: str,
    status: str,
    next_step: str,
    credit_budget: float,
    metadata: dict | None = None,
) -> SocietyResolution:
    target = str(item.get("target") or "")
    priority = str(item.get("priority") or "low")
    support_count = int(item.get("support_count") or 0)
    related_action_ids = [
        str(action_id)
        for action_id in item.get("related_action_ids", [])
        if str(action_id)
    ]
    reason = _resolution_reason(
        resolution_type=resolution_type,
        target=target,
        priority=priority,
        support_count=support_count,
        status=status,
    )
    return SocietyResolution(
        resolution_id=f"resolution:{match.round_id}:{index:05d}",
        round_id=match.round_id,
        resolution_type=resolution_type,
        target=target,
        status=status,
        priority=priority,
        support_count=support_count,
        credit_budget=round(max(credit_budget, 0.0), 4),
        next_step=next_step,
        reason=reason,
        related_action_ids=related_action_ids,
        metadata={
            "choice_context": item.get("choice_context") or {},
            "sample_reasons": item.get("sample_reasons") or [],
            **dict(metadata or {}),
        },
    )


def _execution_status(item: dict, *, queued: str) -> str:
    status = str(item.get("status") or "")
    priority = str(item.get("priority") or "")
    if status in {"queued_now", "queued_next", "boost_existing_room", "funded"}:
        return queued
    if priority in {"high", "medium"}:
        return queued
    return "watchlist"


def _resolution_reason(
    *,
    resolution_type: str,
    target: str,
    priority: str,
    support_count: int,
    status: str,
) -> str:
    if status == "watchlist":
        return f"{resolution_type} for {target} has low support and remains on the watchlist."
    return f"{resolution_type} for {target} is {status} with {priority} priority from {support_count} ants."


def _execute_evidence_scout(match: MatchContext, resolution: SocietyResolution, *, index: int) -> SocietyExecution:
    findings = _matching_findings(match.findings, resolution.target)
    if findings:
        finding_ids = [finding.finding_id for finding in findings[:5]]
        return _execution_from_resolution(
            resolution,
            index=index,
            status="resolved_from_existing_evidence",
            result_summary=f"Found {len(findings)} existing evidence items for {resolution.target}.",
            blocker_effect="blocker_cleared",
            produced_finding_ids=finding_ids,
            metadata={"matched_finding_ids": finding_ids},
        )
    return _execution_from_resolution(
        resolution,
        index=index,
        status="queued_external_scout",
        result_summary=f"No local evidence matched {resolution.target}; keep focused scout queued.",
        blocker_effect="blocker_retained",
    )


def _execute_source_audit(match: MatchContext, resolution: SocietyResolution, *, index: int) -> SocietyExecution:
    findings = _matching_findings(match.findings, resolution.target)
    if not findings:
        return _execution_from_resolution(
            resolution,
            index=index,
            status="audit_pending_no_local_source",
            result_summary=f"No local source matched {resolution.target}; audit remains queued.",
            blocker_effect="blocker_retained",
        )

    qualities = [_finding_quality_label(finding) for finding in findings]
    finding_ids = [finding.finding_id for finding in findings[:5]]
    if any(quality in {"weak", "unknown"} for quality in qualities):
        return _execution_from_resolution(
            resolution,
            index=index,
            status="audit_resolved_weak_source",
            result_summary=f"Audit found weak or unknown source quality for {resolution.target}.",
            blocker_effect="source_quality_failed",
            produced_finding_ids=finding_ids,
            metadata={"source_quality_labels": qualities, "matched_finding_ids": finding_ids},
        )
    return _execution_from_resolution(
        resolution,
        index=index,
        status="audit_resolved_source_ok",
        result_summary=f"Audit found usable local source quality for {resolution.target}.",
        blocker_effect="blocker_cleared",
        produced_finding_ids=finding_ids,
        metadata={"source_quality_labels": qualities, "matched_finding_ids": finding_ids},
    )


def _execute_discussion(resolution: SocietyResolution, rooms: list[DebateRoom], *, index: int) -> SocietyExecution:
    boosted = [
        room.room_id
        for room in rooms
        if _text_matches(resolution.target, f"{room.room_id} {room.evidence_focus} {room.stance} {room.synthesis}")
    ]
    if boosted:
        return _execution_from_resolution(
            resolution,
            index=index,
            status="room_boosted",
            result_summary=f"Boosted existing room(s) for {resolution.target}.",
            blocker_effect="blocker_cleared",
            metadata={"boosted_rooms": boosted},
        )
    return _execution_from_resolution(
        resolution,
        index=index,
        status="room_queued",
        result_summary=f"No existing room matched {resolution.target}; new discussion remains queued.",
        blocker_effect="blocker_retained",
    )


def _execution_from_resolution(
    resolution: SocietyResolution,
    *,
    index: int,
    status: str,
    result_summary: str,
    blocker_effect: str,
    produced_finding_ids: list[str] | None = None,
    metadata: dict | None = None,
) -> SocietyExecution:
    return SocietyExecution(
        execution_id=f"execution:{resolution.round_id}:{index:05d}",
        round_id=resolution.round_id,
        resolution_id=resolution.resolution_id,
        execution_type=resolution.resolution_type,
        target=resolution.target,
        status=status,
        result_summary=result_summary,
        produced_finding_ids=list(produced_finding_ids or []),
        blocker_effect=blocker_effect,
        metadata={
            "related_action_ids": resolution.related_action_ids,
            "choice_context": (resolution.metadata or {}).get("choice_context") or {},
            "sample_reasons": (resolution.metadata or {}).get("sample_reasons") or [],
            **dict(metadata or {}),
        },
    )


def _matching_findings(findings: list[Finding], target: str) -> list[Finding]:
    return [finding for finding in findings if _finding_matches(finding, target)]


def _finding_matches(finding: Finding, target: str) -> bool:
    haystack = " ".join(
        [
            finding.finding_id,
            finding.scout_name,
            finding.source_type,
            finding.finding_name,
            finding.summary,
            " ".join(finding.citations),
            " ".join(_claim_texts(finding.evidence_claims)),
        ]
    )
    return _text_matches(target, haystack)


def _text_matches(needle: str, haystack: str) -> bool:
    target_tokens = _meaningful_tokens(needle)
    if not target_tokens:
        return False
    haystack_lower = haystack.lower()
    return any(token in haystack_lower for token in target_tokens)


def _meaningful_tokens(value: str) -> list[str]:
    stop = {"the", "and", "for", "with", "source", "quality", "reliability", "evidence"}
    tokens = []
    for token in _clean_text(value).lower().replace("_", " ").replace(":", " ").split():
        if token in stop:
            continue
        if len(token) >= 3 or any(char.isdigit() for char in token):
            tokens.append(token)
    return tokens[:6]


def _claim_texts(claims: list[dict]) -> list[str]:
    texts = []
    for claim in claims:
        texts.extend(str(claim.get(key) or "") for key in ("claim", "summary", "claim_type", "source_quality", "claim_quality"))
    return texts


def _finding_quality_label(finding: Finding) -> str:
    quality_text = " ".join(
        [
            finding.source_type,
            finding.scout_name,
            finding.finding_name,
            finding.summary,
            " ".join(_claim_texts(finding.evidence_claims)),
        ]
    ).lower()
    if any(term in quality_text for term in ("weak", "low", "rumor", "rumour", "unverified", "unknown")):
        return "weak"
    if any(term in quality_text for term in ("high", "verified", "trusted", "official", "confirmed")):
        return "strong"
    if finding.confidence >= 0.72:
        return "strong"
    if finding.confidence <= 0.45:
        return "weak"
    return "usable"


def _downgrade_finding_from_source_audit(finding: Finding, effect: dict) -> Finding:
    audited_claims = []
    for claim in finding.evidence_claims:
        updated = dict(claim)
        updated["source_quality_before_audit"] = updated.get("source_quality") or "unknown"
        updated["source_quality"] = "weak"
        updated["audit_status"] = "downgraded_by_colony_source_audit"
        updated["audit_execution_id"] = effect.get("execution_id") or ""
        updated["audit_target"] = effect.get("target") or ""
        if str(updated.get("claim_quality") or "").lower() not in {"low", "weak"}:
            updated["claim_quality_before_audit"] = updated.get("claim_quality") or "unknown"
            updated["claim_quality"] = "disputed"
        audited_claims.append(updated)

    summary = finding.summary
    audit_note = f" Source audit downgraded this finding via {effect.get('execution_id', 'unknown audit')}."
    if audit_note.strip() not in summary:
        summary = f"{summary}{audit_note}".strip()

    return replace(
        finding,
        confidence=round(min(finding.confidence, 0.35), 4),
        summary=summary,
        evidence_claims=audited_claims,
    )


def _source_audit_effect_summary(effects: list[dict]) -> dict:
    statuses = Counter(str(effect.get("status") or "unknown") for effect in effects)
    return {
        "source_audit_effect_count": len(effects),
        "source_audit_effect_statuses": dict(statuses),
        "source_audit_downgraded_findings": sorted(
            {
                str(finding_id)
                for effect in effects
                if effect.get("status") == "downgraded"
                for finding_id in effect.get("finding_ids", [])
                if str(finding_id)
            }
        ),
    }


def _review_effect_for_execution(execution: SocietyExecution, effect: dict) -> tuple[str, str]:
    if execution.execution_type == "source_audit":
        if effect.get("status") == "downgraded" or execution.blocker_effect == "source_quality_failed":
            return "downgrade_side", "contested_source_downgraded"
        if effect.get("status") == "confirmed" or execution.blocker_effect == "blocker_cleared":
            return "clear_blocker", "source_confirmed"
        return "keep_blocker", "source_audit_pending"
    if execution.execution_type == "evidence_scout":
        if execution.blocker_effect == "blocker_cleared":
            return "clear_blocker", "evidence_gap_resolved"
        return "keep_blocker", "evidence_gap_open"
    if execution.execution_type == "discussion":
        if execution.blocker_effect == "blocker_cleared":
            return "clear_blocker", "discussion_advanced"
        return "keep_blocker", "discussion_pending"
    if execution.execution_type == "minority_review":
        return "carry_minority", "minority_carried"
    if execution.execution_type == "scout_funding":
        return "reserve_budget", "funding_reserved"
    return "observe", "review_observed"


def _review_summary(
    *,
    execution: SocietyExecution,
    effect: dict,
    affected_side: str,
    status: str,
    decision_effect: str,
) -> str:
    if decision_effect == "downgrade_side":
        findings = ", ".join(str(item) for item in effect.get("finding_ids", []) if str(item)) or "matched findings"
        side_text = f" for {affected_side}" if affected_side != "none" else ""
        return f"Review downgraded {execution.target}{side_text}: {findings} failed source audit."
    if decision_effect == "clear_blocker":
        side_text = f" for {affected_side}" if affected_side != "none" else ""
        return f"Review cleared {execution.execution_type}{side_text}: {execution.result_summary}"
    if decision_effect == "keep_blocker":
        return f"Review keeps blocker open for {execution.target}: {execution.result_summary}"
    if decision_effect == "carry_minority":
        return f"Review carries minority report on {execution.target} into the final decision notes."
    if decision_effect == "reserve_budget":
        return f"Review reserved scout budget for {execution.target}."
    return f"Review observed {execution.execution_type} for {execution.target}: {status}."


def _dominant_context_side(context: dict) -> str:
    counts = {
        str(side): int(count or 0)
        for side, count in context.items()
        if str(side) in {"home", "draw", "away"}
    }
    if not counts:
        return "none"
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _support_count_from_context_or_execution(context: dict, execution: SocietyExecution) -> int:
    count = sum(
        int(value or 0)
        for side, value in context.items()
        if str(side) in {"home", "draw", "away"}
    )
    if count > 0:
        return count
    return len((execution.metadata or {}).get("related_action_ids") or [])


def _has_pending(executions: list[SocietyExecution], execution_type: str) -> bool:
    return any(
        execution.execution_type == execution_type and execution.blocker_effect == "blocker_retained"
        for execution in executions
    )


def _reward_pool_for_execution(execution: SocietyExecution) -> float:
    if execution.blocker_effect == "source_quality_failed":
        return CIVIC_REWARD_WEAK_SOURCE_FOUND
    if execution.blocker_effect == "blocker_cleared":
        return CIVIC_REWARD_BLOCKER_CLEARED
    return 0.0


def _reward_reason_for_execution(execution: SocietyExecution) -> str:
    if execution.blocker_effect == "source_quality_failed":
        return "useful_source_audit"
    if execution.execution_type == "evidence_scout":
        return "useful_evidence_request"
    if execution.execution_type == "discussion":
        return "useful_discussion_call"
    if execution.execution_type == "source_audit":
        return "source_audit_cleared"
    return "useful_civic_action"


def _reputation_pool_for_execution(execution: SocietyExecution) -> float:
    if execution.blocker_effect == "source_quality_failed":
        return CIVIC_REPUTATION_WEAK_SOURCE_FOUND
    if execution.blocker_effect == "blocker_cleared":
        return CIVIC_REPUTATION_BLOCKER_CLEARED
    return 0.0


def _reputation_reason_for_execution(execution: SocietyExecution) -> str:
    if execution.blocker_effect == "source_quality_failed":
        return "caught_weak_source"
    if execution.execution_type == "evidence_scout":
        return "resolved_evidence_gap"
    if execution.execution_type == "discussion":
        return "resolved_discussion_need"
    if execution.execution_type == "source_audit":
        return "cleared_source_audit"
    return "useful_civic_contribution"


def _apply_reputation_delta(
    agent: AntAgent,
    *,
    delta: float,
    reason: str,
    execution: SocietyExecution,
    related_action_id: str,
) -> float:
    mind = agent.mind or {}
    reputation = dict(mind.get("civic_reputation") or {})
    score = round(float(reputation.get("score") or 0.0) + delta, 4)
    score = max(-1.0, min(1.0, score))
    events = list(reputation.get("events") or [])
    events.append(
        {
            "round_id": execution.round_id,
            "delta": round(delta, 4),
            "score_after": score,
            "reason": reason,
            "execution_id": execution.execution_id,
            "action_id": related_action_id,
            "target": execution.target,
        }
    )
    mind["civic_reputation"] = {"score": score, "events": events[-12:]}
    agent.mind = mind
    return score


def _calibration_delta_for_forecast(forecast: Forecast, *, result_side: str) -> tuple[float, str]:
    committed = forecast.stake > 0.0
    correct = forecast.side == result_side
    if correct and committed:
        return 0.03, "correct_committed_choice"
    if correct:
        return 0.015, "correct_civic_choice"
    if committed:
        return -0.025, "wrong_committed_choice"
    return -0.01, "wrong_civic_choice"


def _apply_calibration_reputation_delta(
    agent: AntAgent,
    *,
    round_id: str,
    delta: float,
    reason: str,
    forecast: Forecast,
    result_side: str,
) -> float:
    mind = agent.mind or {}
    reputation = dict(mind.get("calibration_reputation") or {})
    score = round(float(reputation.get("score") or 0.0) + delta, 4)
    score = max(-1.0, min(1.0, score))
    events = list(reputation.get("events") or [])
    events.append(
        {
            "round_id": round_id,
            "delta": round(delta, 4),
            "score_after": score,
            "reason": reason,
            "forecast_side": forecast.side,
            "result_side": result_side,
            "stake": forecast.stake,
        }
    )
    mind["calibration_reputation"] = {"score": score, "events": events[-12:]}
    agent.mind = mind
    return score


def _calibration_reputation_summary(changes: list[CalibrationReputationChange]) -> dict:
    return {
        "calibration_reputation_change_count": len(changes),
        "calibration_reputation_delta_total": round(sum(change.delta for change in changes), 4),
        "calibration_reputation_reasons": dict(Counter(change.reason for change in changes)),
        "calibration_reputation_agents": dict(Counter(change.agent_id for change in changes)),
    }


def _related_action_ids_from_execution(execution: SocietyExecution) -> list[str]:
    values = execution.metadata.get("related_action_ids") if execution.metadata else []
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if str(value)]


def _targets_for(actions: list[CivicAction], effect_type: str) -> dict:
    counts: Counter[str] = Counter()
    for action in actions:
        if action.status == "accepted" and action.effect_type == effect_type:
            counts[action.target] += 1
    return dict(counts)


def _group_effects(actions: list[CivicAction], effect_type: str) -> dict[str, list[CivicAction]]:
    grouped: dict[str, list[CivicAction]] = {}
    for action in actions:
        if action.effect_type != effect_type:
            continue
        grouped.setdefault(action.target, []).append(action)
    return grouped


def _choice_support(actions: list[CivicAction]) -> dict:
    counts: Counter[str] = Counter()
    weighted: Counter[str] = Counter()
    for action in actions:
        if action.civic_choice not in {"home", "draw", "away"}:
            continue
        counts[action.civic_choice] += 1
        weighted[action.civic_choice] += action.weight
    leading = "none"
    if counts:
        leading = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return {
        "leading_choice": leading,
        "counts": dict(counts),
        "weighted": {key: round(value, 4) for key, value in weighted.items()},
    }


def _backlog_item(target: str, actions: list[CivicAction], *, kind: str) -> dict:
    supporters = sorted({action.agent_id for action in actions})
    choices = Counter(action.civic_choice for action in actions)
    priority = _priority_label(len(actions), sum(action.weight for action in actions))
    return {
        "target": target,
        "kind": kind,
        "supporters": supporters,
        "related_action_ids": [action.action_id for action in actions],
        "support_count": len(supporters),
        "choice_context": dict(choices),
        "priority": priority,
        "status": _status_for_priority(priority),
        "sample_reasons": _sample_reasons(actions),
    }


def _discussion_item(target: str, actions: list[CivicAction], existing_room_topics: dict[str, str]) -> dict:
    item = _backlog_item(target, actions, kind="discussion_call")
    normalized_target = target.lower()
    boosted_rooms = [
        room_id
        for room_id, topic in existing_room_topics.items()
        if normalized_target and (normalized_target in topic or topic in normalized_target)
    ]
    item["status"] = "boost_existing_room" if boosted_rooms else item["status"]
    item["boosted_rooms"] = boosted_rooms
    return item


def _funding_item(target: str, actions: list[CivicAction]) -> dict:
    item = _backlog_item(target, actions, kind="scout_funding")
    item["credits"] = round(sum(action.credits_spent for action in actions), 4)
    item["status"] = "funded" if item["credits"] > 0 else item["status"]
    return item


def _decision_guidance(
    *,
    civic_votes: dict,
    evidence_requests: dict[str, list[CivicAction]],
    source_audits: dict[str, list[CivicAction]],
    discussion_calls: dict[str, list[CivicAction]],
    minority_reports: dict[str, list[CivicAction]],
    scout_funding: dict[str, list[CivicAction]],
) -> dict:
    blockers = []
    leading_choice = str(civic_votes.get("leading_choice", "none"))
    if leading_choice == "none":
        return {
            "leading_choice": "none",
            "posture": "no_civic_layer",
            "open_blockers": [],
            "commitment_mode": "baseline_only",
        }
    if evidence_requests:
        blockers.append("evidence_requests_open")
    if source_audits:
        blockers.append("source_audits_open")
    if discussion_calls:
        blockers.append("discussion_calls_open")
    if minority_reports:
        blockers.append("minority_reports_present")
    commitment_mode = "funded_research" if scout_funding else "civic_only"
    if not blockers:
        posture = "ready_for_commitment_review"
    elif "source_audits_open" in blockers:
        posture = "slow_down_until_sources_are_audited"
    elif "evidence_requests_open" in blockers:
        posture = "gather_more_evidence_before_scaling_commitment"
    else:
        posture = "discuss_before_scaling_commitment"
    return {
        "leading_choice": leading_choice,
        "posture": posture,
        "open_blockers": blockers,
        "commitment_mode": commitment_mode,
    }


def _priority_label(count: int, weight: float) -> str:
    if count >= 5 or weight >= 5.0:
        return "high"
    if count >= 2 or weight >= 2.0:
        return "medium"
    return "low"


def _status_for_priority(priority: str) -> str:
    if priority == "high":
        return "queued_now"
    if priority == "medium":
        return "queued_next"
    return "watchlist"


def _sample_reasons(actions: list[CivicAction]) -> list[str]:
    reasons = []
    for action in actions:
        text = _clean_text((action.metadata or {}).get("one_line"))
        if text and text not in reasons:
            reasons.append(text)
        if len(reasons) >= 3:
            break
    return reasons


def _support_label(*, leading_count: int, participation: int) -> str:
    if participation <= 0:
        return "none"
    doubled = leading_count * 2
    if doubled <= participation:
        return "split"
    if leading_count * 3 < participation * 2:
        return "low"
    if leading_count * 5 < participation * 4:
        return "medium"
    return "high"


def _commitment_level(*, population: int, participating_bets: int, total_staked: float) -> str:
    if population <= 0 or participating_bets <= 0 or total_staked <= 0:
        return "none"
    if participating_bets * 4 < population:
        return "low"
    if participating_bets * 2 < population:
        return "medium"
    return "high"


def _dominant_unresolved_target(civic_summary: dict) -> str:
    targets: Counter[str] = Counter()
    for key in ("evidence_request_targets", "source_challenge_targets", "discussion_targets"):
        targets.update({str(target): int(count) for target, count in (civic_summary.get(key) or {}).items()})
    if not targets:
        return ""
    return sorted(targets.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _civic_note(
    *,
    leading_choice: str,
    leading_support: str,
    civic_confidence: str,
    commitment_level: str,
    unresolved: str,
) -> str:
    if leading_choice == "none":
        return "No natural civic layer was produced for this round."
    note = (
        f"Civic layer leans {leading_choice} with {leading_support} support, "
        f"{civic_confidence} social confidence, and {commitment_level} financial commitment."
    )
    if unresolved:
        note += f" Main unresolved work: {unresolved}."
    return note


def _clean_action(value: object) -> str:
    action = _clean_text(value).lower()
    if action in ACTION_POINT_COSTS:
        return action
    return "vote_only"


def _clean_side(value: object) -> Side:
    side = _clean_text(value).lower()
    if side in {"home", "draw", "away"}:
        return side  # type: ignore[return-value]
    return "draw"


def _action_target(*, action_type: str, judgment: dict, forecast: Forecast) -> str:
    explicit = _clean_text(judgment.get("action_target"))
    if explicit:
        return explicit
    if action_type == "request_evidence":
        return _first_clean(judgment.get("doubts")) or "missing_evidence"
    if action_type == "challenge_source":
        return _first_clean(judgment.get("evidence_distrusted")) or "source_quality"
    if action_type == "call_discussion":
        return _clean_text(judgment.get("debate_question")) or "debate_question"
    if action_type == "minority_report":
        return f"minority_{forecast.side}"
    if action_type == "fund_scout":
        return "scouting_backlog"
    if action_type == "commit_stake":
        return forecast.side
    if action_type == "vote_only":
        return forecast.side
    return "none"


def _effect_type(action_type: str) -> str:
    return {
        "commit_stake": "stake_commitment",
        "vote_only": "civic_vote",
        "request_evidence": "evidence_request",
        "challenge_source": "source_audit",
        "call_discussion": "discussion_call",
        "minority_report": "minority_report",
        "fund_scout": "scout_funding",
        "hold_position": "observation",
    }.get(action_type, "civic_vote")


def _effect_summary(
    *,
    action_type: str,
    civic_choice: str,
    target: str,
    commitment_label: str,
    status: str,
) -> str:
    if status == "skipped_unavailable_judgment":
        return "No civic action was executed because the natural judgment was unavailable."
    if status == "rejected_insufficient_credits":
        return f"Scout funding for {target} was rejected because the ant lacked credits."
    if action_type == "commit_stake":
        return f"Committed {commitment_label} survival stake behind {civic_choice}."
    if action_type == "vote_only":
        return f"Registered a civic choice for {civic_choice}; Survival Thesis V1 should normally convert this to micro stake."
    if action_type == "request_evidence":
        return f"Created an evidence request for {target}."
    if action_type == "challenge_source":
        return f"Created a source audit request for {target}."
    if action_type == "call_discussion":
        return f"Called for discussion around {target}."
    if action_type == "minority_report":
        return f"Published a minority report around {target}."
    if action_type == "fund_scout":
        return f"Funded scout work for {target}."
    return "Observed without changing the civic state."


def _action_weight(*, action_type: str, commitment_label: str, status: str) -> float:
    if status != "accepted":
        return 0.0
    if action_type == "commit_stake":
        return {"micro": 0.82, "small": 1.1, "medium": 1.25, "high": 1.4}.get(commitment_label, 1.0)
    if action_type in {"challenge_source", "minority_report"}:
        return 1.15
    if action_type in {"request_evidence", "call_discussion", "fund_scout"}:
        return 1.05
    return 1.0


def _review_action_weight(*, action_type: str, changed: bool, status: str) -> float:
    if status != "reviewed":
        return 0.0
    base = 1.05 if changed else 0.85
    if action_type in {"challenge_source", "minority_report"}:
        return round(base + 0.08, 4)
    if action_type == "commit_stake":
        return round(base + 0.12, 4)
    return round(base, 4)


def _review_effect_summary(revision: JudgmentRevision, *, civic_choice: str, action_type: str) -> str:
    if revision.changed:
        return (
            f"Revised after society review from {revision.previous_side}/{revision.previous_action} "
            f"to {civic_choice}/{action_type}."
        )
    return f"Reaffirmed {civic_choice}/{action_type} after society review."


def _first_clean(value: object) -> str:
    if not isinstance(value, list):
        return ""
    for item in value:
        text = _clean_text(item)
        if text:
            return text
    return ""


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\n", " ").split()).strip()


def _is_survival_judgment_source(source: str) -> bool:
    return source in {"camel", "camel_error", "camel_unavailable"}


def _is_camel_fallback_source(source: str) -> bool:
    return source in {"camel_error", "camel_unavailable"}
