"""Colony harness orchestration."""

from __future__ import annotations

import json
import random
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path

from .agent import AntAgent
from .colony_config import apply_colony_config_to_genome, normalize_colony_config
from .debate import DebateFeed
from .decision import build_collective_decision
from .economy import (
    EconomyLedger,
    build_paid_knowledge_views,
    debit_internal_stakes,
    market_spec_for_match,
    settle_internal_pool,
    settle_room_payments,
)
from .genes import random_genome
from .memory import (
    SURVIVAL_MEMORY_VERSION,
    build_ant_memory_store,
    forecast_memory_signal,
    forecast_memory_text,
    recall_query_for_match,
)
from .models import DebateClaim, DebateRoom, JudgmentRevision, KnowledgeView, MatchContext, RoundResult
from .mind import (
    apply_mind_to_genome,
    build_agent_mind,
    class_transition,
    memory_recall_depth,
    mind_public_card,
    refresh_mind_after_round,
)
from .population import normalize_agent_lineages
from .reasoning import CamelReasoner, apply_judgment_to_forecast
from .social import build_social_actions
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
from .voice import TemplateVoiceModel, VoiceModel
from .wallets import WalletStore
from .world_graph import build_world_graph


@dataclass(frozen=True)
class DebateProfile:
    agent: AntAgent
    view: KnowledgeView
    match: MatchContext
    probability: float
    stance: str
    evidence_focus: str
    score: float


@dataclass(frozen=True)
class ConversationVenue:
    room_id: str
    topic: str
    description: str
    stance: str = "topic_room"


class ColonyHarness:
    def __init__(
        self,
        population_size: int = 40,
        speaker_slots: int = 6,
        seed: int = 42,
        starting_bankroll: float = 100.0,
        voice_model: VoiceModel | None = None,
        create_agent_wallets: bool = False,
        wallet_store_path: str | Path | None = None,
        wallet_provider: str | None = None,
        dynamic_env_path: str | Path | None = None,
        agents: list[AntAgent] | None = None,
        colony_config: dict | None = None,
        memory_influence: bool = False,
        memory_write_enabled: bool = True,
        judgment_reasoner: CamelReasoner | None = None,
        judgment_agent_count: int = 0,
        judgment_concurrency: int = 1,
    ) -> None:
        if agents is not None:
            population_size = len(agents)
        if population_size < 1:
            raise ValueError("population_size must be positive")
        if speaker_slots < 1:
            raise ValueError("speaker_slots must be positive")

        self.population_size = population_size
        self.speaker_slots = min(speaker_slots, population_size)
        self.seed = seed
        self.rng = random.Random(seed)
        self.starting_bankroll = starting_bankroll
        self.voice_model = voice_model or TemplateVoiceModel()
        self.memory_influence = memory_influence
        self.memory_write_enabled = memory_write_enabled
        self.judgment_reasoner = judgment_reasoner
        self.judgment_agent_count = max(0, judgment_agent_count)
        self.judgment_concurrency = max(1, judgment_concurrency)
        self.colony_config = normalize_colony_config(colony_config) if colony_config else None
        self.wallet_store = (
            WalletStore(wallet_store_path, provider=wallet_provider, dynamic_env_path=dynamic_env_path)
            if create_agent_wallets or wallet_store_path
            else None
        )
        self.memory_store = build_ant_memory_store()
        self.agents = agents if agents is not None else self._spawn_agents()
        self._ensure_agent_minds(apply_policy=agents is None)
        if agents is not None and self.wallet_store is not None:
            self._attach_wallets()
        normalize_agent_lineages(self.agents)

    def _spawn_agents(self) -> list[AntAgent]:
        agents: list[AntAgent] = []
        for index in range(self.population_size):
            agent_id = f"ant_{index:04d}"
            wallet_address = ""
            if self.wallet_store is not None:
                wallet_address = self.wallet_store.get_or_create(agent_id).address
            genome = random_genome(self.rng)
            genome = apply_colony_config_to_genome(genome, self.colony_config, self.rng, index=index)
            mind = build_agent_mind(
                agent_id=agent_id,
                genome=genome,
                bankroll=round(self.starting_bankroll, 4),
                accuracy=0.5,
                generation=0,
                rng=self.rng,
                index=index,
            )
            genome = apply_mind_to_genome(genome, mind)
            agent = AntAgent(
                agent_id=agent_id,
                name=f"ant-{index:04d}",
                generation=0,
                genome=genome,
                bankroll=round(self.starting_bankroll * self.rng.uniform(0.92, 1.08), 4),
                accuracy=round(self.rng.uniform(0.35, 0.65), 4),
                wallet_address=wallet_address,
                lineage_id=f"lineage_{agent_id}",
                lineage_root_agent_id=agent_id,
                mind=mind,
            )
            agents.append(agent)
        return agents

    def _ensure_agent_minds(self, *, apply_policy: bool = False) -> None:
        for index, agent in enumerate(self.agents):
            mind = build_agent_mind(
                agent_id=agent.agent_id,
                genome=agent.genome,
                bankroll=agent.bankroll,
                accuracy=agent.accuracy,
                generation=agent.generation,
                rng=self.rng,
                index=index,
                existing=agent.mind,
            )
            agent.mind = mind
            if apply_policy:
                agent.genome = apply_mind_to_genome(agent.genome, mind)

    def _attach_wallets(self) -> None:
        if self.wallet_store is None:
            return
        for agent in self.agents:
            if not agent.wallet_address:
                agent.wallet_address = self.wallet_store.get_or_create(agent.agent_id).address

    def select_debaters(self) -> list[tuple[AntAgent, str]]:
        ranked = sorted(
            self.agents,
            key=_debate_score,
            reverse=True,
        )
        elite_count = max(1, self.speaker_slots // 2)
        elite = ranked[:elite_count]
        remaining = [agent for agent in self.agents if agent not in elite]
        wildcards = self.rng.sample(remaining, k=self.speaker_slots - elite_count)
        selected: list[tuple[AntAgent, str]] = []
        for rank, agent in enumerate(elite, start=1):
            score = _debate_score(agent)
            civic_bonus = _civic_reputation_debate_bonus(agent)
            selected.append((
                agent,
                f"elite rank {rank}: debate score {score:.2f}, civic reputation bonus {civic_bonus:.2f}",
            ))
        for agent in wildcards:
            selected.append((agent, "wildcard: exploration slot for diversity and noisy debate"))
        return selected

    def select_speakers(self) -> list[AntAgent]:
        return [agent for agent, _reason in self.select_debaters()]

    def _judgment_agent_ids(self) -> set[str]:
        if self.judgment_reasoner is None or self.judgment_agent_count <= 0:
            return set()
        count = min(self.judgment_agent_count, len(self.agents))
        selected: list[AntAgent] = []
        seen_archetypes: set[str] = set()
        ranked = sorted(self.agents, key=lambda ant: (-ant.bankroll, ant.agent_id))
        for agent in ranked:
            archetype = str((agent.mind or {}).get("archetype") or agent.genome.persona)
            if archetype in seen_archetypes:
                continue
            selected.append(agent)
            seen_archetypes.add(archetype)
            if len(selected) >= count:
                return {item.agent_id for item in selected}
        for agent in ranked:
            if agent not in selected:
                selected.append(agent)
            if len(selected) >= count:
                break
        return {item.agent_id for item in selected}

    def run_round(self, match: MatchContext) -> RoundResult:
        self._ensure_agent_minds(apply_policy=False)
        agent_minds_before = {agent.agent_id: dict(agent.mind or {}) for agent in self.agents}
        memory_recall = self._recall_agent_memories(match)
        memory_signals = {
            str(item.get("agent_id")): item.get("memory_signal") or {}
            for item in memory_recall
        }
        market_spec = market_spec_for_match(match)
        ledger = EconomyLedger(match.round_id)
        knowledge_views_by_agent = build_paid_knowledge_views(match, self.agents, ledger)
        profiles = self._build_debate_profiles(match, knowledge_views_by_agent)
        self._last_profiles = profiles
        rooms = self._run_room_debates(profiles)
        settle_room_payments(rooms=rooms, agents=self.agents, ledger=ledger)
        feed = self._run_final_chamber(rooms, match)

        debate_signal = feed.consensus_home_probability()
        forecasts = []
        judgment_contexts = []
        allow_draw = market_spec.market_type == "three_way"
        judgment_agent_ids = self._judgment_agent_ids()
        judgment_debate_messages = _judgment_debate_messages(rooms, feed)
        for agent in self.agents:
            view = knowledge_views_by_agent[agent.agent_id]
            visible_match = view.to_match_context(match)
            signal = memory_signals.get(agent.agent_id) or {}
            use_memory = self.memory_influence and bool(signal.get("available"))
            forecast = agent.forecast(
                visible_match,
                debate_signal,
                view.access_tier,
                len(view.visible_findings),
                allow_draw=allow_draw,
                memory_home_probability=signal.get("home_probability") if use_memory else None,
                memory_confidence=float(signal.get("confidence") or 0.0) if use_memory else 0.0,
            )
            if self.judgment_reasoner is not None and agent.agent_id in judgment_agent_ids:
                judgment_contexts.append((len(forecasts), agent, visible_match))
            forecasts.append(forecast)
        if judgment_contexts:
            forecasts = self._apply_natural_judgments(
                forecasts=forecasts,
                contexts=judgment_contexts,
                debate_messages=judgment_debate_messages,
            )
        recall_counts = {
            str(item.get("agent_id")): len((item.get("recall") or {}).get("results") or [])
            for item in memory_recall
        }
        forecasts = [
            replace(forecast, memory_recall_count=recall_counts.get(forecast.agent_id, 0))
            for forecast in forecasts
        ]
        civic_actions, civic_summary = resolve_civic_actions(
            match=match,
            agents=self.agents,
            forecasts=forecasts,
            ledger=ledger,
        )
        society_state = build_society_state(match=match, civic_actions=civic_actions, rooms=rooms)
        society_resolutions, society_resolution_summary = resolve_society_backlogs(
            match=match,
            society_state=society_state,
        )
        society_executions, society_execution_summary = execute_society_resolutions(
            match=match,
            resolutions=society_resolutions,
            rooms=rooms,
        )
        audited_findings, source_audit_effects, source_audit_effect_summary = apply_source_audit_effects(
            findings=match.findings,
            executions=society_executions,
        )
        society_reviews, society_review_summary = build_society_reviews(
            executions=society_executions,
            source_audit_effects=source_audit_effects,
        )
        effective_match = replace(match, findings=audited_findings)
        civic_rewards, civic_reward_summary = settle_civic_rewards(
            agents=self.agents,
            civic_actions=civic_actions,
            executions=society_executions,
            ledger=ledger,
        )
        civic_reputation_changes, civic_reputation_summary = apply_civic_reputation_changes(
            agents=self.agents,
            civic_actions=civic_actions,
            executions=society_executions,
        )
        society_state = apply_execution_guidance(society_state, society_executions)
        society_policy = society_commitment_policy(society_state)
        society_state["commitment_policy"] = society_policy
        society_state["resolutions"] = [resolution.to_dict() for resolution in society_resolutions]
        society_state["executions"] = [execution.to_dict() for execution in society_executions]
        society_state["source_audit_effects"] = source_audit_effects
        society_state["reviews"] = [review.to_dict() for review in society_reviews]
        review_judgment_contexts = _review_judgment_contexts(
            forecasts=forecasts,
            agents=self.agents,
            knowledge_views_by_agent=knowledge_views_by_agent,
            effective_match=effective_match,
            judgment_agent_ids=judgment_agent_ids,
        )
        judgment_revisions: list[JudgmentRevision] = []
        if society_reviews and review_judgment_contexts:
            forecasts, judgment_revisions = self._apply_review_judgments(
                forecasts=forecasts,
                contexts=review_judgment_contexts,
                review_messages=_society_review_messages(society_reviews),
                review_ids=[review.review_id for review in society_reviews],
            )
        review_civic_actions, review_civic_summary = resolve_review_civic_actions(
            match=match,
            forecasts=forecasts,
            revisions=judgment_revisions,
        )
        society_state["judgment_revisions"] = [revision.to_dict() for revision in judgment_revisions]
        society_state["review_civic_actions"] = [action.to_dict() for action in review_civic_actions]
        decision_civic_actions = civic_actions + review_civic_actions
        forecasts = apply_society_commitment_policy(forecasts, society_policy)
        forecasts = debit_internal_stakes(agents=self.agents, forecasts=forecasts, ledger=ledger)
        forecasts_by_agent = {forecast.agent_id: forecast for forecast in forecasts}
        social_actions = build_social_actions(
            match=match,
            rooms=rooms,
            final_claims=feed.claims,
            forecasts_by_agent=forecasts_by_agent,
            rng=self.rng,
        )
        commitments = [
            agent.commit_bet(forecast, match.round_id)
            for agent, forecast in zip(self.agents, forecasts, strict=True)
        ]

        active_forecasts = [forecast for forecast in forecasts if forecast.stake > 0.0]
        home_bets = sum(1 for forecast in active_forecasts if forecast.side == "home")
        draw_bets = sum(1 for forecast in active_forecasts if forecast.side == "draw")
        away_bets = sum(1 for forecast in active_forecasts if forecast.side == "away")
        participating_bets = home_bets + draw_bets + away_bets
        prediction_sides = Counter(_prediction_side(forecast.home_probability) for forecast in forecasts)
        total_staked = round(sum(forecast.stake for forecast in forecasts), 4)
        civic_metrics = civic_layer_metrics(
            civic_summary=civic_summary,
            population=self.population_size,
            participating_bets=participating_bets,
            total_staked=total_staked,
        )
        risk_profiles = Counter(forecast.risk_profile for forecast in forecasts)
        judgment_intents = Counter(
            str((forecast.judgment or {}).get("intent") or "baseline")
            for forecast in forecasts
        )
        judgment_actions = Counter(
            str((forecast.judgment or {}).get("action") or (forecast.judgment or {}).get("intent") or "baseline")
            for forecast in forecasts
        )
        judgment_commitments = Counter(
            str((forecast.judgment or {}).get("commitment_label") or "baseline")
            for forecast in forecasts
        )
        judgment_stake_levels = Counter(
            str((forecast.judgment or {}).get("stake_level") or "baseline")
            for forecast in forecasts
        )
        judgment_risk_reads = Counter(
            str((forecast.judgment or {}).get("risk_read") or "baseline")
            for forecast in forecasts
        )
        judgment_main_signals = Counter(
            str((forecast.judgment or {}).get("main_signal") or "baseline")
            for forecast in forecasts
        )

        debate_quality = _debate_quality_metrics(rooms)
        collective_decision = build_collective_decision(
            match=effective_match,
            agents=self.agents,
            forecasts=forecasts,
            civic_actions=decision_civic_actions,
            society_state=society_state,
        )
        collective_decision = _apply_society_policy_to_decision(collective_decision, society_policy)
        settlement_summary = settle_internal_pool(
            market_spec=market_spec,
            agents=self.agents,
            ledger=ledger,
        )
        calibration_reputation_changes, calibration_reputation_summary = apply_calibration_reputation_changes(
            round_id=match.round_id,
            agents=self.agents,
            forecasts=forecasts,
            result_side=market_spec.result_side,
        )
        class_transitions = self._refresh_agent_classes(agent_minds_before)
        memory_writes = (
            self._write_agent_memories(
                match=match,
                forecasts=forecasts,
                result_side=market_spec.result_side,
            )
            if self.memory_write_enabled
            else []
        )
        summary = {
            "population": self.population_size,
            "home_team": match.home_team,
            "away_team": match.away_team,
            "side_labels": {
                "home": match.home_team,
                "draw": "Draw",
                "away": match.away_team,
            },
            "speaker_slots": self.speaker_slots,
            "market_type": market_spec.market_type,
            "market_outcomes": market_spec.outcomes,
            "market_result_side": market_spec.result_side,
            "settlement_status": settlement_summary["status"],
            "room_count": len(rooms),
            "room_claims": sum(len(room.claims) for room in rooms),
            "final_claims": len(feed.claims),
            **debate_quality,
            "debate_home_probability": None if debate_signal is None else round(debate_signal, 4),
            "market_home_probability": match.market_home_probability,
            "findings": len(effective_match.findings),
            "public_findings": sum(1 for finding in effective_match.findings if finding.access_level == "public"),
            "shared_findings": sum(1 for finding in effective_match.findings if finding.access_level == "shared"),
            "private_findings": sum(1 for finding in effective_match.findings if finding.access_level == "private"),
            "public_views": sum(1 for view in knowledge_views_by_agent.values() if view.access_tier == "public"),
            "shared_views": sum(1 for view in knowledge_views_by_agent.values() if view.access_tier == "shared"),
            "private_views": sum(1 for view in knowledge_views_by_agent.values() if view.access_tier == "private"),
            "home_bets": home_bets,
            "draw_bets": draw_bets,
            "away_bets": away_bets,
            "stake_counts_by_team": {
                match.home_team: home_bets,
                "Draw": draw_bets,
                match.away_team: away_bets,
            },
            "prediction_home": prediction_sides.get("home", 0),
            "prediction_draw": prediction_sides.get("draw", 0),
            "prediction_away": prediction_sides.get("away", 0),
            "prediction_counts_by_team": {
                match.home_team: prediction_sides.get("home", 0),
                "Draw": prediction_sides.get("draw", 0),
                match.away_team: prediction_sides.get("away", 0),
            },
            "participating_bets": participating_bets,
            "judgment_reasoner": "camel" if self.judgment_reasoner is not None else "baseline",
            "judgment_agent_count": len(judgment_agent_ids),
            "judgment_intents": dict(judgment_intents),
            "judgment_actions": dict(judgment_actions),
            "judgment_commitments": dict(judgment_commitments),
            "judgment_stake_levels": dict(judgment_stake_levels),
            "judgment_risk_reads": dict(judgment_risk_reads),
            "judgment_main_signals": dict(judgment_main_signals),
            **civic_summary,
            **civic_metrics,
            "society_posture": society_state.get("decision_guidance", {}).get("posture", ""),
            "society_open_blockers": society_state.get("decision_guidance", {}).get("open_blockers", []),
            "society_commitment_mode": society_state.get("decision_guidance", {}).get("commitment_mode", ""),
            "society_execution_mode": society_policy.get("execution_mode", ""),
            "financial_execution_label": society_policy.get("financial_execution_label", ""),
            "society_stake_scale": society_policy.get("stake_scale", 1.0),
            "society_authorized_single_bet": society_policy.get("should_place_single_bet", True),
            **society_resolution_summary,
            **society_execution_summary,
            **source_audit_effect_summary,
            **society_review_summary,
            **review_civic_summary,
            **civic_reward_summary,
            **civic_reputation_summary,
            **calibration_reputation_summary,
            "risk_profiles": dict(risk_profiles),
            "total_staked": total_staked,
            "decision_side": collective_decision.recommendation["side"],
            "decision_label": {
                "home": match.home_team,
                "draw": "Draw",
                "away": match.away_team,
            }.get(str(collective_decision.recommendation["side"]), str(collective_decision.recommendation["side"])),
            "decision_winner": collective_decision.recommendation["winner"],
            "decision_confidence": collective_decision.internal_metrics["confidence"],
            "decision_market_edge": collective_decision.internal_metrics["market_edge"],
            "decision_home_probability": collective_decision.internal_metrics["weighted_home_probability"],
            "payment_receipts": len(ledger.payment_receipts),
            "balance_updates": len(ledger.balance_updates),
            "treasury_balance": settlement_summary.get("treasury_balance", 0.0),
            "losing_pool": settlement_summary.get("losing_pool", 0.0),
            "contributor_pool": settlement_summary.get("contributor_pool", 0.0),
            "memory_backend": self.memory_store.healthcheck().get("backend"),
            "memory_influence": self.memory_influence,
            "memory_write_enabled": self.memory_write_enabled,
            "memory_recalls": len(memory_recall),
            "memory_writes": len(memory_writes),
            "archetypes": dict(Counter(str(agent.mind.get("archetype") or "unknown") for agent in self.agents)),
            "social_classes": dict(Counter(str(agent.mind.get("social_class") or "unknown") for agent in self.agents)),
        }
        all_debate_claims = [claim for room in rooms for claim in room.claims] + feed.claims
        world_graph = build_world_graph(effective_match, claims=all_debate_claims, forecasts=forecasts)

        return RoundResult(
            round_id=match.round_id,
            market_spec=market_spec,
            claims=feed.claims,
            rooms=rooms,
            social_actions=social_actions,
            civic_actions=civic_actions,
            society_resolutions=society_resolutions,
            society_executions=society_executions,
            society_reviews=society_reviews,
            judgment_revisions=judgment_revisions,
            review_civic_actions=review_civic_actions,
            civic_rewards=civic_rewards,
            civic_reputation_changes=civic_reputation_changes,
            calibration_reputation_changes=calibration_reputation_changes,
            forecasts=forecasts,
            commitments=commitments,
            findings=effective_match.findings,
            knowledge_views=list(knowledge_views_by_agent.values()),
            world_graph=world_graph,
            collective_decision=collective_decision,
            summary=summary,
            payment_receipts=ledger.payment_receipts,
            balance_updates=ledger.balance_updates,
            internal_stakes=ledger.internal_stakes,
            settlement_summary=settlement_summary,
            agent_minds=[mind_public_card(agent.mind) for agent in self.agents],
            memory_recall=memory_recall,
            memory_writes=memory_writes,
            class_transitions=class_transitions,
            society_state=society_state,
            evolution_trace={
                "mode": "round_observation",
                "note": "Full reproduction still runs through evolve_population.py; this trace records class and memory movement for the round.",
                "archetypes": summary["archetypes"],
                "social_classes": summary["social_classes"],
            },
        )

    def _apply_natural_judgments(
        self,
        *,
        forecasts: list,
        contexts: list[tuple[int, AntAgent, MatchContext]],
        debate_messages: list[str],
    ) -> list:
        if self.judgment_reasoner is None or not contexts:
            return forecasts

        updated = list(forecasts)
        worker_count = min(self.judgment_concurrency, len(contexts))

        def judge(context: tuple[int, AntAgent, MatchContext]) -> tuple[int, object]:
            index, agent, visible_match = context
            reasoner = CamelReasoner(self.judgment_reasoner.config)
            judgment = reasoner.private_judgment(
                agent=agent,
                match=visible_match,
                debate_messages=debate_messages,
            )
            return index, apply_judgment_to_forecast(
                forecast=forecasts[index],
                match=visible_match,
                judgment=judgment,
            )

        if worker_count <= 1:
            for context in contexts:
                index, forecast = judge(context)
                updated[index] = forecast
            return updated

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(judge, context) for context in contexts]
            for future in as_completed(futures):
                index, forecast = future.result()
                updated[index] = forecast
        return updated

    def _apply_review_judgments(
        self,
        *,
        forecasts: list,
        contexts: list[tuple[int, AntAgent, MatchContext]],
        review_messages: list[str],
        review_ids: list[str],
    ) -> tuple[list, list[JudgmentRevision]]:
        if self.judgment_reasoner is None or not contexts:
            return forecasts, []

        updated = list(forecasts)
        revisions: list[JudgmentRevision] = []
        worker_count = min(self.judgment_concurrency, len(contexts))

        def judge(context: tuple[int, AntAgent, MatchContext]) -> tuple[int, object, JudgmentRevision]:
            index, agent, visible_match = context
            previous = forecasts[index]
            previous_action = str((previous.judgment or {}).get("action") or "baseline")
            reasoner = CamelReasoner(self.judgment_reasoner.config)
            judgment = reasoner.private_judgment(
                agent=agent,
                match=visible_match,
                debate_messages=_review_messages_for_forecast(previous, review_messages),
            )
            review_base = replace(
                previous,
                decision_reason=(
                    f"previous pre-review choice={previous.side}; "
                    f"action={previous_action}; stake={previous.stake:.4f}"
                ),
            )
            revised = apply_judgment_to_forecast(
                forecast=review_base,
                match=visible_match,
                judgment=judgment,
            )
            revised_judgment = {
                **dict(revised.judgment or {}),
                "phase": "post_resolution_review",
                "previous_side": previous.side,
                "previous_action": previous_action,
                "review_ids": review_ids,
            }
            revised = replace(
                revised,
                judgment=revised_judgment,
                decision_reason=f"{revised.decision_reason}; post-resolution review considered",
            )
            revision = _judgment_revision_from_forecasts(
                round_id=visible_match.round_id,
                index=index,
                previous=previous,
                revised=revised,
                review_ids=review_ids,
            )
            return index, revised, revision

        if worker_count <= 1:
            for context in contexts:
                index, forecast, revision = judge(context)
                updated[index] = forecast
                revisions.append(revision)
            return updated, revisions

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(judge, context) for context in contexts]
            for future in as_completed(futures):
                index, forecast, revision = future.result()
                updated[index] = forecast
                revisions.append(revision)
        revisions.sort(key=lambda revision: revision.revision_id)
        return updated, revisions

    def _recall_agent_memories(self, match: MatchContext) -> list[dict]:
        rows = []
        for agent in self.agents:
            query = recall_query_for_match(
                home_team=match.home_team,
                away_team=match.away_team,
                archetype=str(agent.mind.get("archetype") or ""),
            )
            recall = self.memory_store.recall(
                agent_id=agent.agent_id,
                query=query,
                limit=memory_recall_depth(agent.mind),
                metadata={
                    "round_id": match.round_id,
                    "home_team": match.home_team,
                    "away_team": match.away_team,
                    "memory_version": SURVIVAL_MEMORY_VERSION,
                },
            )
            signal = forecast_memory_signal(recall)
            rows.append(
                {
                    "agent_id": agent.agent_id,
                    "archetype": agent.mind.get("archetype", ""),
                    "social_class": agent.mind.get("social_class", ""),
                    "query": query,
                    "recall": recall,
                    "memory_signal": signal,
                }
            )
        return rows

    def _write_agent_memories(
        self,
        *,
        match: MatchContext,
        forecasts: list,
        result_side: str,
    ) -> list[dict]:
        agents_by_id = {agent.agent_id: agent for agent in self.agents}
        writes = []
        for forecast in forecasts:
            agent = agents_by_id.get(forecast.agent_id)
            if agent is None:
                continue
            text = forecast_memory_text(
                forecast={"round_id": match.round_id, **forecast.to_dict()},
                mind=agent.mind,
                result_side=result_side,
            )
            metadata = {
                "round_id": match.round_id,
                "memory_version": SURVIVAL_MEMORY_VERSION,
                "home_team": match.home_team,
                "away_team": match.away_team,
                "memory_type": "forecast_attempt",
                "archetype": agent.mind.get("archetype", ""),
                "social_class": agent.mind.get("social_class", ""),
                "side": forecast.side,
                "result_side": result_side,
            }
            record = self.memory_store.remember(agent_id=agent.agent_id, text=text, metadata=metadata)
            writes.append({"agent_id": agent.agent_id, "text": text, "record": record})
        return writes

    def _refresh_agent_classes(self, before_by_agent: dict[str, dict]) -> list[dict]:
        transitions = []
        for agent in self.agents:
            before = before_by_agent.get(agent.agent_id, {})
            after = refresh_mind_after_round(
                agent.mind,
                bankroll=agent.bankroll,
                accuracy=agent.accuracy,
                generation=agent.generation,
            )
            agent.mind = after
            transitions.append(class_transition(agent.agent_id, before, after))
        return transitions

    def write_jsonl(self, result: RoundResult, output_path: str | Path) -> None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        events = []
        events.append({"event_type": "round_summary", **result.summary})
        events.append({"event_type": "market_spec", **result.market_spec.to_dict()})
        # Emit the roster up front so a replay consumer can bind agent_id -> index
        # before any debate_claim/forecast/bet_commitment references an agent.
        events.extend(
            {"event_type": "agent_record", **record} for record in self.public_roster()
        )
        events.extend({"event_type": "agent_mind", **mind} for mind in result.agent_minds)
        events.extend({"event_type": "memory_recall", **row} for row in result.memory_recall)
        events.extend({"event_type": "memory_write", **row} for row in result.memory_writes)
        events.extend({"event_type": "class_transition", **row} for row in result.class_transitions)
        events.append({"event_type": "evolution_trace", **result.evolution_trace})
        events.extend({"event_type": "payment_receipt", **receipt.to_dict()} for receipt in result.payment_receipts)
        events.extend({"event_type": "balance_update", **update.to_dict()} for update in result.balance_updates)
        events.extend({"event_type": "finding", **finding.to_dict()} for finding in result.findings)
        events.extend({"event_type": "knowledge_view", **view.to_dict()} for view in result.knowledge_views)
        events.extend({"event_type": "debate_room", **room.to_dict()} for room in result.rooms)
        events.extend({"event_type": "social_action", **action.to_dict()} for action in result.social_actions)
        events.append({"event_type": "world_graph", **result.world_graph.to_dict()})
        events.extend({"event_type": "debate_claim", **claim.to_dict()} for claim in result.claims)
        events.extend(
            {"event_type": "natural_judgment", **forecast.judgment}
            for forecast in result.forecasts
            if forecast.judgment
        )
        events.extend({"event_type": "civic_action", **action.to_dict()} for action in result.civic_actions)
        events.extend({"event_type": "judgment_revision", **revision.to_dict()} for revision in result.judgment_revisions)
        events.extend({"event_type": "review_civic_action", **action.to_dict()} for action in result.review_civic_actions)
        events.extend({"event_type": "society_resolution", **resolution.to_dict()} for resolution in result.society_resolutions)
        events.extend({"event_type": "society_execution", **execution.to_dict()} for execution in result.society_executions)
        events.extend({"event_type": "society_review", **review.to_dict()} for review in result.society_reviews)
        events.extend(
            {"event_type": "source_audit_effect", **effect}
            for effect in result.society_state.get("source_audit_effects", [])
            if isinstance(effect, dict)
        )
        events.extend({"event_type": "civic_reward", **reward.to_dict()} for reward in result.civic_rewards)
        events.extend(
            {"event_type": "civic_reputation_change", **change.to_dict()}
            for change in result.civic_reputation_changes
        )
        events.extend(
            {"event_type": "calibration_reputation_change", **change.to_dict()}
            for change in result.calibration_reputation_changes
        )
        events.append({"event_type": "society_state", **result.society_state})
        events.extend({"event_type": "forecast", **forecast.to_dict()} for forecast in result.forecasts)
        events.extend({"event_type": "internal_stake", **stake.to_dict()} for stake in result.internal_stakes)
        events.append({"event_type": "collective_decision", **result.collective_decision.to_dict()})
        events.extend({"event_type": "bet_commitment", **commitment.to_dict()} for commitment in result.commitments)
        events.append({"event_type": "settlement_summary", **result.settlement_summary})

        with path.open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    def public_roster(self) -> list[dict]:
        return [agent.public_record for agent in self.agents]

    def _build_debate_profiles(
        self,
        match: MatchContext,
        knowledge_views_by_agent: dict[str, KnowledgeView],
    ) -> list[DebateProfile]:
        profiles: list[DebateProfile] = []
        for agent in self.agents:
            view = knowledge_views_by_agent[agent.agent_id]
            visible_match = view.to_match_context(match)
            probability = agent.private_baseline_probability(visible_match)
            profiles.append(
                DebateProfile(
                    agent=agent,
                    view=view,
                    match=visible_match,
                    probability=probability,
                    stance=_stance_for_probability(probability, visible_match.market_home_probability),
                    evidence_focus=_evidence_focus(visible_match),
                    score=_debate_score(agent),
                )
            )
        return profiles

    def _run_room_debates(self, profiles: list[DebateProfile]) -> list[DebateRoom]:
        rooms: list[DebateRoom] = []
        carried_claims_by_agent: dict[str, list[DebateClaim]] = {}
        speaking_visits_by_agent: dict[str, int] = {}
        venues = _conversation_venues(profiles, max_rooms=self._target_room_count())
        for venue in venues:
            room_profiles = _select_venue_participants(profiles, venue)
            representatives = _select_venue_speakers(room_profiles, venue, speaking_visits_by_agent)
            roles = _roles_for_representatives(len(representatives))
            room_claims: list[DebateClaim] = []
            for representative, role in zip(representatives, roles, strict=True):
                carried_claims = carried_claims_by_agent.get(representative.agent.agent_id, [])[-2:]
                prior_claims = carried_claims + room_claims
                prior_rooms = sorted({claim.room_id for claim in carried_claims if claim.room_id})
                room_claims.append(
                    representative.agent.speak(
                        representative.match,
                        self.rng,
                        self.voice_model,
                        selection_reason=(
                            f"{role} in {venue.room_id}: topic={venue.topic}, "
                            f"participants={len(room_profiles)}, "
                            f"debate_score={representative.score:.2f}, "
                            f"civic_rep={_civic_reputation_score(representative.agent):.3f}, "
                            f"civic_bonus={_civic_reputation_debate_bonus(representative.agent):.2f}, "
                            f"carried_from={','.join(prior_rooms) if prior_rooms else 'none'}"
                        ),
                        access_tier=representative.view.access_tier,
                        visible_findings=len(representative.view.visible_findings),
                        prior_claims=prior_claims,
                        debate_phase="room",
                        room_id=venue.room_id,
                        debate_role=role,
                        debate_focus=venue.topic,
                    )
                )
                claim = room_claims[-1]
                carried_claims_by_agent.setdefault(representative.agent.agent_id, []).append(claim)
                speaking_visits_by_agent[representative.agent.agent_id] = (
                    speaking_visits_by_agent.get(representative.agent.agent_id, 0) + 1
                )

            synthesis_probability = _weighted_claim_probability(room_claims)
            synthesis_confidence = _average_confidence(room_claims)
            rooms.append(
                DebateRoom(
                    room_id=venue.room_id,
                    stance=venue.stance,
                    evidence_focus=venue.topic,
                    participant_ids=[profile.agent.agent_id for profile in room_profiles],
                    representative_ids=[profile.agent.agent_id for profile in representatives],
                    claims=room_claims,
                    synthesis_home_probability=None if synthesis_probability is None else round(synthesis_probability, 4),
                    synthesis_confidence=round(synthesis_confidence, 4),
                    synthesis=_room_synthesis(
                        room_id=venue.room_id,
                        stance=venue.stance,
                        evidence_focus=venue.topic,
                        participants=len(room_profiles),
                        claims=room_claims,
                    ),
                )
            )
        return rooms

    def _run_final_chamber(self, rooms: list[DebateRoom], match: MatchContext) -> DebateFeed:
        final_feed = DebateFeed()
        if not rooms:
            return final_feed
        room_claims = [claim for room in rooms for claim in room.claims]
        synthesis_probability = _weighted_room_probability(rooms)
        if synthesis_probability is None:
            synthesis_probability = _weighted_claim_probability(room_claims) or match.market_home_probability
        referenced_evidence = _final_referenced_evidence(rooms)
        diagnostics = _final_chamber_diagnostics(
            match=match,
            rooms=rooms,
            probability=synthesis_probability,
            evidence=referenced_evidence,
        )
        final_feed.append(
            DebateClaim(
                round_id=match.round_id,
                speaker_id="colony_synthesis",
                speaker_name="final-chamber",
                model="synthesis",
                persona="room aggregator",
                access_tier="public",
                visible_findings=sum(len(claim.referenced_evidence) for claim in room_claims),
                claim_type="synthesis",
                selection_reason=(
                    f"aggregated {len(rooms)} rooms and {len(room_claims)} room claims; "
                    f"room_lean={_lean_label(synthesis_probability)}"
                ),
                stated_home_probability=round(synthesis_probability, 4),
                confidence=round(_average_room_confidence(rooms), 4),
                direction=_direction_for_probability(synthesis_probability, match.market_home_probability),
                message=_final_chamber_message(
                    match=match,
                    rooms=rooms,
                    probability=synthesis_probability,
                    evidence=referenced_evidence,
                    diagnostics=diagnostics,
                ),
                debate_phase="final",
                room_id="final",
                debate_role="synthesis",
                evidence_tags=_final_evidence_tags(rooms),
                referenced_evidence=referenced_evidence,
                diagnostics=diagnostics,
            )
        )
        return final_feed

    def _profile_by_agent_id(self, agent_id: str) -> DebateProfile | None:
        for profile in getattr(self, "_last_profiles", []):
            if profile.agent.agent_id == agent_id:
                return profile
        return None

    def _target_room_count(self) -> int:
        return max(1, min(self.speaker_slots, max(1, (self.population_size + 7) // 8)))


def _debate_score(agent: AntAgent) -> float:
    return (agent.bankroll * 0.7) + (agent.accuracy * 100.0 * 0.3) + _civic_reputation_debate_bonus(agent)


def _civic_reputation_score(agent: AntAgent) -> float:
    reputation = (agent.mind or {}).get("civic_reputation") or {}
    return max(-1.0, min(1.0, float(reputation.get("score") or 0.0)))


def _civic_reputation_debate_bonus(agent: AntAgent) -> float:
    return round(max(-4.0, min(6.0, _civic_reputation_score(agent) * 12.0)), 4)


def _debate_quality_metrics(rooms: list[DebateRoom]) -> dict:
    room_claims = [claim for room in rooms for claim in room.claims]
    disputes = [claim.dispute for claim in room_claims if claim.dispute]
    subjects: set[str] = set()
    critique_types: set[str] = set()
    subject_shifts = 0
    carried_claims = 0

    for claim in room_claims:
        if "carried_from=none" not in claim.selection_reason:
            carried_claims += 1
        for evidence in claim.referenced_evidence:
            subject = str(evidence.get("subject") or evidence.get("team") or evidence.get("player") or "").strip()
            if subject:
                subjects.add(subject.lower())
        if claim.dispute:
            critique_type = str(claim.dispute.get("critique_type") or "dispute")
            if critique_type:
                critique_types.add(critique_type)
            target_subject = str(claim.dispute.get("target_subject") or "").strip().lower()
            counter_subject = str(claim.dispute.get("counter_subject") or "").strip().lower()
            if target_subject and counter_subject and target_subject != counter_subject:
                subject_shifts += 1

    room_claim_count = len(room_claims)
    dispute_count = len(disputes)
    return {
        "dispute_count": dispute_count,
        "dispute_rate": round(dispute_count / room_claim_count, 4) if room_claim_count else 0.0,
        "subject_count": len(subjects),
        "critique_type_count": len(critique_types),
        "subject_shift_count": subject_shifts,
        "carried_claim_count": carried_claims,
    }


def _stance_for_probability(probability: float, market_probability: float) -> str:
    edge = probability - market_probability
    if edge >= 0.01:
        return "support_home"
    if edge <= -0.01:
        return "support_away"
    return "uncertainty"


def _evidence_focus(match: MatchContext) -> str:
    scored: list[tuple[float, str]] = []
    for finding in match.findings:
        for evidence in finding.evidence_claims:
            subject = str(evidence.get("subject") or evidence.get("team") or finding.source_type or "general")
            confidence = float(evidence.get("confidence") or finding.confidence or 0.35)
            if evidence.get("player"):
                confidence += 0.25
            if evidence.get("claim_type") == "injury_availability":
                confidence += 0.2
            scored.append((confidence, _clean_focus(subject)))
    if scored:
        scored.sort(reverse=True)
        return scored[0][1]
    source_scores = {
        "stats": match.stats_home_signal,
        "odds": match.odds_home_signal,
        "news": match.news_home_signal,
    }
    return max(source_scores, key=source_scores.get)


def _clean_focus(value: str) -> str:
    cleaned = " ".join(value.lower().replace("_", " ").split())
    return cleaned[:40] or "general"


def _conversation_venues(profiles: list[DebateProfile], *, max_rooms: int) -> list[ConversationVenue]:
    evidence_text = " ".join(_visible_evidence_text(profile.match) for profile in profiles[: min(len(profiles), 12)])
    candidates: list[tuple[str, str]] = []
    if _has_availability_evidence(profiles, tokens=("neymar",)):
        candidates.append(("neymar_availability", "How much does Neymar availability move Brazil?"))
    if _has_availability_evidence(profiles, tokens=("nayef aguerd", "ez abde", "morocco")):
        candidates.append(("morocco_availability", "Do Morocco injuries offset the Neymar drag?"))
    if "recent_form" in evidence_text or "recent form" in evidence_text or "last matches" in evidence_text:
        candidates.append(("team_form", "What do recent matches say about each team's baseline?"))
    if "match_history" in evidence_text or "head-to-head" in evidence_text or "previous meetings" in evidence_text:
        candidates.append(("match_history", "Does head-to-head or recent match history change the baseline?"))
    if "tactical" in evidence_text or "pressing" in evidence_text or "set-piece" in evidence_text:
        candidates.append(("tactical_matchup", "Do tactical styles or set pieces create a matchup edge?"))
    if "player_form" in evidence_text or "season form" in evidence_text or "goals" in evidence_text:
        candidates.append(("player_form", "Which key players are in form strongly enough to change the room's read?"))
    candidates.extend(
        [
            ("market_pricing", "Has the market already accounted for the injury news?"),
            ("source_audit", "Which sources are reliable enough to change the room's read?"),
            ("stats_form", "Do baseline stats overpower noisy news?"),
            ("uncertainty", "Should the room widen uncertainty instead of taking a side?"),
        ]
    )
    venues = []
    for index, (topic, description) in enumerate(candidates[:max_rooms], start=1):
        venues.append(
            ConversationVenue(
                room_id=f"room-{index:02d}",
                topic=topic,
                description=description,
            )
        )
    return venues


def _has_availability_evidence(profiles: list[DebateProfile], *, tokens: tuple[str, ...]) -> bool:
    for profile in profiles[: min(len(profiles), 12)]:
        for finding in profile.match.findings:
            for evidence in finding.evidence_claims:
                if evidence.get("claim_type") != "injury_availability":
                    continue
                text = " ".join(
                    str(evidence.get(field) or "")
                    for field in ("subject", "team", "player", "claim")
                ).lower()
                if any(token in text for token in tokens):
                    return True
    return False


def _visible_evidence_text(match: MatchContext) -> str:
    parts: list[str] = []
    for finding in match.findings:
        parts.append(finding.summary)
        for evidence in finding.evidence_claims:
            parts.append(str(evidence.get("claim_type") or ""))
            parts.append(str(evidence.get("subject") or ""))
            parts.append(str(evidence.get("team") or ""))
            parts.append(str(evidence.get("player") or ""))
            parts.append(str(evidence.get("claim") or ""))
    return " ".join(parts).lower()


def _select_venue_participants(profiles: list[DebateProfile], venue: ConversationVenue) -> list[DebateProfile]:
    target_size = max(6, min(len(profiles), max(10, len(profiles) // 3)))
    scored = sorted(
        ((_venue_affinity(profile, venue), profile) for profile in profiles),
        key=lambda item: (item[0], item[1].score),
        reverse=True,
    )
    participants = [profile for score, profile in scored if score >= 0.35][:target_size]
    if len(participants) < min(4, len(profiles)):
        participants = [profile for _score, profile in scored[: min(target_size, len(profiles))]]
    participants.sort(key=lambda profile: (_venue_affinity(profile, venue), profile.score), reverse=True)
    return participants


def _venue_affinity(profile: DebateProfile, venue: ConversationVenue) -> float:
    weights = profile.agent.genome.source_weights.normalized()
    text = _visible_evidence_text(profile.match)
    score = 0.15 + (profile.score / 400.0)
    if venue.topic == "neymar_availability":
        score += 0.75 if "neymar" in text else 0.0
        score += weights.news * 0.8
        score += weights.debate * 0.25
    elif venue.topic == "morocco_availability":
        score += 0.55 if any(token in text for token in ("nayef aguerd", "ez abde", "morocco")) else 0.0
        score += weights.news * 0.55
        score += weights.stats * 0.2
    elif venue.topic == "market_pricing":
        score += weights.odds * 1.0
        score += 0.25 if profile.agent.genome.herd_bias < -0.2 else 0.0
    elif venue.topic == "team_form":
        score += weights.stats * 0.9
        score += 0.45 if "recent_form" in text or "last matches" in text else 0.0
    elif venue.topic == "match_history":
        score += weights.stats * 0.8
        score += weights.news * 0.2
        score += 0.5 if "match_history" in text or "head-to-head" in text or "previous meetings" in text else 0.0
    elif venue.topic == "tactical_matchup":
        score += weights.stats * 0.7
        score += weights.news * 0.25
        score += 0.5 if "tactical" in text or "pressing" in text or "set-piece" in text else 0.0
    elif venue.topic == "player_form":
        score += weights.stats * 0.55
        score += weights.news * 0.35
        score += 0.45 if "player_form" in text or "season form" in text or "goals" in text else 0.0
    elif venue.topic == "source_audit":
        score += weights.news * 0.4
        score += min(profile.agent.genome.query_budget / 2.0, 1.0) * 0.45
        score += 0.2 if profile.view.access_tier in {"shared", "private"} else 0.0
    elif venue.topic == "stats_form":
        score += weights.stats * 1.0
        score += 0.2 if profile.probability > profile.match.market_home_probability else 0.0
    elif venue.topic == "uncertainty":
        edge = abs(profile.probability - profile.match.market_home_probability)
        score += max(0.0, 0.45 - edge * 8.0)
        score += 0.2 if "skeptic" in profile.agent.genome.persona else 0.0
    return score


def _select_venue_speakers(
    room_profiles: list[DebateProfile],
    venue: ConversationVenue,
    speaking_visits_by_agent: dict[str, int],
) -> list[DebateProfile]:
    if len(room_profiles) <= 3:
        return room_profiles
    ranked = sorted(
        room_profiles,
        key=lambda profile: (
            _venue_affinity(profile, venue) + min(speaking_visits_by_agent.get(profile.agent.agent_id, 0), 2) * 0.12,
            profile.score,
        ),
        reverse=True,
    )
    speakers = [ranked[0]]
    bridge_candidates = [
        profile
        for profile in ranked[1:]
        if speaking_visits_by_agent.get(profile.agent.agent_id, 0) > 0 and profile not in speakers
    ]
    if bridge_candidates:
        speakers.append(bridge_candidates[0])
    contrast_candidates = [
        profile
        for profile in ranked[1:]
        if profile.stance != speakers[0].stance and profile not in speakers
    ]
    if contrast_candidates:
        speakers.append(contrast_candidates[0])
    for profile in ranked[1:]:
        if len(speakers) >= 3:
            break
        if profile not in speakers:
            speakers.append(profile)
    return speakers


def _select_final_representatives(rooms: list[DebateRoom], speaker_slots: int) -> list[tuple[DebateRoom, str]]:
    selected: list[tuple[DebateRoom, str]] = []
    used_agents: set[str] = set()
    for room in rooms:
        chosen = ""
        for agent_id in room.representative_ids:
            if agent_id not in used_agents:
                chosen = agent_id
                break
        if not chosen and room.representative_ids:
            chosen = room.representative_ids[0]
        if not chosen:
            continue
        selected.append((room, chosen))
        used_agents.add(chosen)
        if len(selected) >= speaker_slots:
            break
    return selected


def _cluster_profiles(profiles: list[DebateProfile], *, max_rooms: int) -> list[list[DebateProfile]]:
    buckets: dict[tuple[str, str], list[DebateProfile]] = {}
    for profile in profiles:
        buckets.setdefault((profile.stance, profile.evidence_focus), []).append(profile)

    ordered_buckets = sorted(
        buckets.values(),
        key=lambda bucket: (len(bucket), max(profile.score for profile in bucket)),
        reverse=True,
    )
    rooms: list[list[DebateProfile]] = [list(bucket) for bucket in ordered_buckets[:max_rooms]]
    if not rooms:
        return []

    for bucket in ordered_buckets[max_rooms:]:
        target = _best_merge_room(rooms, bucket[0])
        target.extend(bucket)

    while len(rooms) < max_rooms:
        largest = max(rooms, key=len)
        if len(largest) < 6:
            break
        split_at = len(largest) // 2
        rooms.append(largest[split_at:])
        del largest[split_at:]

    for room in rooms:
        room.sort(key=lambda profile: profile.score, reverse=True)
    return rooms


def _best_merge_room(rooms: list[list[DebateProfile]], profile: DebateProfile) -> list[DebateProfile]:
    same_stance = [room for room in rooms if room and room[0].stance == profile.stance]
    candidates = same_stance or rooms
    return min(candidates, key=len)


def _select_room_representatives(room_profiles: list[DebateProfile]) -> list[DebateProfile]:
    if len(room_profiles) <= 2:
        return room_profiles
    representatives = [room_profiles[0]]
    different_stance = [profile for profile in room_profiles[1:] if profile.stance != room_profiles[0].stance]
    if different_stance:
        representatives.append(different_stance[0])
    different_focus = [
        profile
        for profile in room_profiles[1:]
        if profile.evidence_focus != room_profiles[0].evidence_focus and profile not in representatives
    ]
    if different_focus:
        representatives.append(different_focus[0])
    for profile in room_profiles[1:]:
        if len(representatives) >= 3:
            break
        if profile not in representatives:
            representatives.append(profile)
    return representatives


def _roles_for_representatives(count: int) -> list[str]:
    roles = ["advocate", "challenger", "source_auditor"]
    if count > len(roles):
        roles.extend(["skeptic"] * (count - len(roles)))
    return roles[:count]


def _judgment_debate_messages(rooms: list[DebateRoom], feed: DebateFeed) -> list[str]:
    messages: list[str] = []
    for room in rooms:
        if room.synthesis:
            messages.append(f"{room.room_id} synthesis: {room.synthesis}")
        for claim in room.claims[:2]:
            messages.append(
                f"{claim.speaker_name} ({claim.debate_role or claim.claim_type}) said: {claim.message}"
            )
        if len(messages) >= 8:
            break
    for claim in feed.claims[:2]:
        messages.append(f"final chamber said: {claim.message}")
    return messages[:8]


def _review_judgment_contexts(
    *,
    forecasts: list,
    agents: list[AntAgent],
    knowledge_views_by_agent: dict[str, KnowledgeView],
    effective_match: MatchContext,
    judgment_agent_ids: set[str],
) -> list[tuple[int, AntAgent, MatchContext]]:
    agents_by_id = {agent.agent_id: agent for agent in agents}
    contexts: list[tuple[int, AntAgent, MatchContext]] = []
    for index, forecast in enumerate(forecasts):
        if forecast.agent_id not in judgment_agent_ids:
            continue
        agent = agents_by_id.get(forecast.agent_id)
        view = knowledge_views_by_agent.get(forecast.agent_id)
        if agent is None or view is None:
            continue
        contexts.append((index, agent, _visible_effective_match(view, effective_match)))
    return contexts


def _visible_effective_match(view: KnowledgeView, effective_match: MatchContext) -> MatchContext:
    effective_by_id = {finding.finding_id: finding for finding in effective_match.findings}
    visible_findings = [
        effective_by_id.get(finding.finding_id, finding)
        for finding in view.visible_findings
    ]
    return replace(effective_match, findings=visible_findings)


def _society_review_messages(reviews) -> list[str]:
    messages = []
    for review in reviews[:6]:
        side = review.affected_side if review.affected_side != "none" else "all sides"
        messages.append(
            f"POST-RESOLUTION REVIEW {review.review_id}: {review.decision_effect} "
            f"for {side}; status={review.status}; {review.summary}"
        )
    return messages


def _review_messages_for_forecast(forecast, review_messages: list[str]) -> list[str]:
    previous_action = str((forecast.judgment or {}).get("action") or "baseline")
    previous_line = str((forecast.judgment or {}).get("one_line") or forecast.decision_reason)
    return [
        f"Your previous civic choice was {forecast.side}; previous action={previous_action}; previous stake={forecast.stake:.4f}.",
        f"Previous reason: {previous_line}",
        *review_messages,
        "You may keep your prior choice, reduce risk, request more evidence, or change side if the reviews undermine your evidence.",
    ]


def _judgment_revision_from_forecasts(
    *,
    round_id: str,
    index: int,
    previous,
    revised,
    review_ids: list[str],
) -> JudgmentRevision:
    previous_action = str((previous.judgment or {}).get("action") or "baseline")
    revised_action = str((revised.judgment or {}).get("action") or "baseline")
    changed = (
        previous.side != revised.side
        or previous_action != revised_action
        or round(float(previous.stake), 4) != round(float(revised.stake), 4)
    )
    return JudgmentRevision(
        revision_id=f"judgment_revision:{round_id}:{index + 1:05d}",
        round_id=round_id,
        agent_id=revised.agent_id,
        phase="post_resolution_review",
        previous_side=previous.side,
        revised_side=revised.side,
        previous_action=previous_action,
        revised_action=revised_action,
        previous_stake=round(float(previous.stake), 4),
        revised_stake=round(float(revised.stake), 4),
        changed=changed,
        reason=str((revised.judgment or {}).get("one_line") or ""),
        review_ids=review_ids,
        judgment=dict(revised.judgment or {}),
        metadata={
            "previous_reason": previous.decision_reason,
            "revised_reason": revised.decision_reason,
        },
    )


def _apply_society_policy_to_decision(decision, policy: dict):
    recommendation = dict(decision.recommendation)
    original_rationale = str(recommendation.get("rationale") or "")
    policy_reason = str(policy.get("reason") or "")
    recommendation.update(
        {
            "should_place_single_bet": bool(policy.get("should_place_single_bet", True)),
            "financial_execution": {
                "mode": policy.get("execution_mode", ""),
                "label": policy.get("financial_execution_label", ""),
                "stake_scale": policy.get("stake_scale", 1.0),
                "max_commitment_label": policy.get("max_commitment_label", ""),
                "blockers": policy.get("blockers", []),
            },
            "rationale": (
                f"{original_rationale} Society policy: {policy_reason}"
                if policy_reason
                else original_rationale
            ),
        }
    )
    return replace(decision, recommendation=recommendation)


def _dominant_label(labels: object) -> str:
    counts: dict[str, int] = {}
    for label in labels:
        text = str(label)
        counts[text] = counts.get(text, 0) + 1
    if not counts:
        return "general"
    return max(counts.items(), key=lambda item: (item[1], item[0]))[0]


def _weighted_claim_probability(claims: list[DebateClaim]) -> float | None:
    if not claims:
        return None
    weighted_sum = 0.0
    total_weight = 0.0
    for claim in claims:
        weight = max(claim.confidence, 0.05)
        weighted_sum += claim.stated_home_probability * weight
        total_weight += weight
    return weighted_sum / max(total_weight, 1e-9)


def _average_confidence(claims: list[DebateClaim]) -> float:
    if not claims:
        return 0.0
    return sum(claim.confidence for claim in claims) / len(claims)


def _weighted_room_probability(rooms: list[DebateRoom]) -> float | None:
    weighted_sum = 0.0
    total_weight = 0.0
    for room in rooms:
        if room.synthesis_home_probability is None:
            continue
        weight = max(room.synthesis_confidence, 0.05) * max(len(room.participant_ids), 1)
        weighted_sum += room.synthesis_home_probability * weight
        total_weight += weight
    if total_weight <= 0:
        return None
    return weighted_sum / total_weight


def _average_room_confidence(rooms: list[DebateRoom]) -> float:
    if not rooms:
        return 0.0
    return sum(max(room.synthesis_confidence, 0.05) for room in rooms) / len(rooms)


def _direction_for_probability(probability: float, market_probability: float) -> str:
    edge = probability - market_probability
    if edge >= 0.01:
        return "home"
    if edge <= -0.01:
        return "away"
    return "draw"


def _room_probability_range(rooms: list[DebateRoom]) -> str:
    probabilities = [room.synthesis_home_probability for room in rooms if room.synthesis_home_probability is not None]
    if not probabilities:
        return "n/a"
    return f"{min(probabilities):.1%}-{max(probabilities):.1%}"


def _final_evidence_tags(rooms: list[DebateRoom]) -> list[str]:
    tags: list[str] = []
    for room in rooms:
        if room.evidence_focus and room.evidence_focus not in tags:
            tags.append(room.evidence_focus)
        for claim in room.claims:
            for tag in claim.evidence_tags:
                if tag not in tags:
                    tags.append(tag)
    return tags[:5]


def _final_referenced_evidence(rooms: list[DebateRoom], limit: int = 5) -> list[dict]:
    scored: list[tuple[float, dict]] = []
    seen: set[tuple[str, str, str]] = set()
    for room in rooms:
        room_weight = max(room.synthesis_confidence, 0.05)
        for claim in room.claims:
            for evidence in claim.referenced_evidence[:2]:
                subject = str(evidence.get("subject") or evidence.get("team") or "")
                claim_text = str(evidence.get("claim") or "")
                source = str(evidence.get("source_title") or evidence.get("source_url") or "")
                key = (subject.lower(), claim_text.lower()[:96], source.lower()[:96])
                if key in seen:
                    continue
                seen.add(key)
                confidence = float(evidence.get("confidence") or claim.confidence or 0.3)
                score = confidence + room_weight + (0.15 if evidence.get("player") else 0.0)
                if evidence.get("claim_type") == "injury_availability":
                    score += 0.2
                scored.append((score, evidence))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [evidence for _score, evidence in scored[:limit]]


def _final_chamber_message(
    *,
    match: MatchContext,
    rooms: list[DebateRoom],
    probability: float,
    evidence: list[dict],
    diagnostics: dict | None = None,
) -> str:
    diagnostics = diagnostics or _final_chamber_diagnostics(
        match=match,
        rooms=rooms,
        probability=probability,
        evidence=evidence,
    )
    market_line = str(diagnostics.get("consensus") or "")
    focus_line = str(diagnostics.get("main_evidence_thread") or "")
    disagreement_line = str(diagnostics.get("minority_report") or diagnostics.get("unresolved_risk") or "")
    parts = [market_line, focus_line, disagreement_line]
    return " ".join(part for part in parts if part)


def _final_chamber_diagnostics(
    *,
    match: MatchContext,
    rooms: list[DebateRoom],
    probability: float,
    evidence: list[dict],
) -> dict:
    edge = probability - match.market_home_probability
    if abs(edge) < 0.006:
        consensus = f"Final chamber keeps {match.home_team} close to market."
        consensus_label = "close_to_market"
    elif edge > 0:
        if probability < 0.5:
            consensus = (
                f"Final chamber still favors {match.away_team}, "
                f"but prices {match.home_team} above market."
            )
            consensus_label = "away_favored_home_above_market"
        else:
            consensus = f"Final chamber favors {match.home_team} above market."
            consensus_label = "above_market_home"
    else:
        if probability > 0.5:
            consensus = (
                f"Final chamber still favors {match.home_team}, "
                f"but trims it below market."
            )
            consensus_label = "home_favored_below_market"
        else:
            consensus = f"Final chamber favors {match.away_team} and trims {match.home_team} below market."
            consensus_label = "away_favored_home_below_market"

    focus_line = _final_focus_line(evidence, match=match) or _final_room_focus_line(rooms)
    dispute = _final_dispute_summary(match, rooms)
    unresolved_risk = _final_unresolved_risk_line(match, rooms, evidence)
    minority_report = str(dispute.get("line") or unresolved_risk)
    probabilities = [room.synthesis_home_probability for room in rooms if room.synthesis_home_probability is not None]
    room_range = _room_probability_range(rooms)
    spread = None if not probabilities else round(max(probabilities) - min(probabilities), 4)
    return {
        "consensus": consensus,
        "consensus_label": consensus_label,
        "main_evidence_thread": focus_line,
        "minority_report": minority_report,
        "source_dispute": dispute,
        "unresolved_risk": unresolved_risk,
        "room_probability_range": room_range,
        "room_probability_spread": spread,
        "room_count": len(rooms),
        "room_claims": sum(len(room.claims) for room in rooms),
    }


def _final_focus_line(evidence: list[dict], *, match: MatchContext) -> str:
    if not evidence:
        return ""
    excluded_teams = {match.home_team, match.away_team}
    availability = [item for item in evidence if item.get("claim_type") == "injury_availability"]
    player_form = [item for item in evidence if item.get("claim_type") == "player_form"]
    recent_form = [item for item in evidence if item.get("claim_type") == "recent_form"]
    if availability:
        subjects = _subject_list(availability, limit=3, exclude_if_possible=excluded_teams)
        return f"The main live question is availability: {subjects}."
    if player_form:
        return f"Player form is the strongest shared thread: {_subject_list(player_form, limit=3, exclude_if_possible=excluded_teams)}."
    if recent_form:
        return f"Recent form is the common thread: {_subject_list(recent_form, limit=3)}."
    return f"The room evidence clusters around {_subject_list(evidence, limit=3, exclude_if_possible=excluded_teams)}."


def _final_room_focus_line(rooms: list[DebateRoom]) -> str:
    focuses = [room.evidence_focus.replace("_", " ") for room in rooms if room.evidence_focus]
    if not focuses:
        return ""
    return f"The rooms mostly argued about {_join_human(focuses[:3])}."


def _final_disagreement_line(match: MatchContext, rooms: list[DebateRoom], evidence: list[dict]) -> str:
    dispute = _final_dispute_summary(match, rooms)
    if dispute.get("line"):
        return str(dispute["line"])

    return _final_unresolved_risk_line(match, rooms, evidence)


def _final_unresolved_risk_line(match: MatchContext, rooms: list[DebateRoom], evidence: list[dict]) -> str:

    probabilities = [room.synthesis_home_probability for room in rooms if room.synthesis_home_probability is not None]
    if not probabilities:
        return "The remaining disagreement is source quality, not the direction of the match."
    spread = max(probabilities) - min(probabilities)
    excluded_teams = {match.home_team, match.away_team}
    negative_home = _subject_list(
        [item for item in evidence if item.get("impact") == "negative_home"],
        limit=2,
        exclude_if_possible=excluded_teams,
    )
    negative_away = _subject_list(
        [item for item in evidence if item.get("impact") == "negative_away"],
        limit=2,
        exclude_if_possible=excluded_teams,
    )
    if negative_home and negative_away:
        return f"Unresolved: which risk should dominate, {negative_home} or {negative_away}."
    if spread >= 0.018:
        return "Unresolved: the rooms agree on the topics, but not on how much weight to give them."
    if negative_home:
        return f"Unresolved: whether the market already accounts for {negative_home}."
    if negative_away:
        return f"Unresolved: whether {negative_away} is enough to lift {match.home_team}."
    return "Unresolved: source quality still decides how much the room should move."


def _final_dispute_summary(match: MatchContext, rooms: list[DebateRoom]) -> dict:
    disputes = [claim.dispute for room in rooms for claim in room.claims if claim.dispute]
    if not disputes:
        return {}

    critique_counts: dict[str, int] = {}
    for dispute in disputes:
        critique_type = str(dispute.get("critique_type") or "dispute")
        critique_counts[critique_type] = critique_counts.get(critique_type, 0) + 1

    dominant_type = max(critique_counts.items(), key=lambda item: (item[1], _dispute_priority(item[0])))[0]
    dominant_pair = _dominant_dispute_subject_pair(
        dispute for dispute in disputes if dispute.get("critique_type") == dominant_type
    )

    if dominant_type == "source_quality":
        if dominant_pair:
            target_subject, counter_subject = dominant_pair
            if target_subject and counter_subject and target_subject != counter_subject:
                line = f"Minority report: source quality dispute favors checking {counter_subject} against {target_subject}."
                return _dispute_summary_dict(disputes, critique_counts, dominant_type, dominant_pair, line)
        line = "Minority report: the sharpest objection is source quality, not another price model."
        return _dispute_summary_dict(disputes, critique_counts, dominant_type, dominant_pair, line)
    if dominant_type == "counter_evidence":
        if dominant_pair:
            target_subject, counter_subject = dominant_pair
            if target_subject and counter_subject and target_subject != counter_subject:
                line = f"Minority report: the live counterweight is {counter_subject} against {target_subject}."
                return _dispute_summary_dict(disputes, critique_counts, dominant_type, dominant_pair, line)
        line = "Minority report: challengers are arguing counter-evidence more than raw conviction."
        return _dispute_summary_dict(disputes, critique_counts, dominant_type, dominant_pair, line)
    if dominant_type in {"home_probability_too_low", "underpriced_home"}:
        line = f"Minority report: some rooms think the debate is still too low on {match.home_team} after the risk adjustment."
        return _dispute_summary_dict(disputes, critique_counts, dominant_type, dominant_pair, line)
    if dominant_type in {"home_probability_too_high", "overpriced_home"}:
        line = f"Minority report: some rooms think the debate is still too optimistic on {match.home_team} after the evidence."
        return _dispute_summary_dict(disputes, critique_counts, dominant_type, dominant_pair, line)
    if dominant_type == "impact_size":
        line = "Minority report: the topic is accepted, but the impact size is still disputed."
        return _dispute_summary_dict(disputes, critique_counts, dominant_type, dominant_pair, line)
    return {}


def _dispute_summary_dict(
    disputes: list[dict],
    critique_counts: dict[str, int],
    dominant_type: str,
    dominant_pair: tuple[str, str] | None,
    line: str,
) -> dict:
    target_subject = ""
    counter_subject = ""
    if dominant_pair:
        target_subject, counter_subject = dominant_pair
    return {
        "line": line,
        "dominant_type": dominant_type,
        "critique_counts": dict(sorted(critique_counts.items())),
        "target_subject": target_subject,
        "counter_subject": counter_subject,
        "dispute_count": len(disputes),
    }


def _dominant_dispute_subject_pair(disputes) -> tuple[str, str] | None:
    subject_pairs: dict[tuple[str, str], int] = {}
    for dispute in disputes:
        target_subject = str(dispute.get("target_subject") or "").strip()
        counter_subject = str(dispute.get("counter_subject") or "").strip()
        if target_subject or counter_subject:
            key = (target_subject, counter_subject)
            subject_pairs[key] = subject_pairs.get(key, 0) + 1
    if not subject_pairs:
        return None
    return max(subject_pairs.items(), key=lambda item: (item[1], item[0]))[0]


def _dispute_priority(critique_type: str) -> int:
    priority = {
        "source_quality": 5,
        "counter_evidence": 4,
        "impact_size": 3,
        "home_probability_too_high": 2,
        "home_probability_too_low": 2,
        "overpriced_home": 2,
        "underpriced_home": 2,
    }
    return priority.get(critique_type, 1)


def _subject_list(
    evidence: list[dict],
    *,
    limit: int,
    exclude_if_possible: set[str] | None = None,
) -> str:
    subjects: list[str] = []
    for item in evidence:
        subject = str(item.get("subject") or item.get("player") or item.get("team") or "").strip()
        if subject and subject not in subjects:
            subjects.append(subject)
    if exclude_if_possible:
        specific_subjects = [subject for subject in subjects if subject not in exclude_if_possible]
        if specific_subjects:
            subjects = specific_subjects
    return _join_human(subjects[:limit]) if subjects else "the available evidence"


def _join_human(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _room_synthesis(
    *,
    room_id: str,
    stance: str,
    evidence_focus: str,
    participants: int,
    claims: list[DebateClaim],
) -> str:
    probability = _weighted_claim_probability(claims)
    top_subjects = []
    for claim in claims:
        for evidence in claim.referenced_evidence[:2]:
            subject = evidence.get("subject") or evidence.get("team")
            if subject and subject not in top_subjects:
                top_subjects.append(str(subject))
    subjects = ", ".join(top_subjects[:3]) if top_subjects else evidence_focus
    return (
        f"{room_id} grouped {participants} predictors around {stance}/{evidence_focus}. "
        f"Room synthesis is {_lean_label(probability)}, with evidence focus on {subjects}."
    )


def _lean_label(value: float | None) -> str:
    if value is None:
        return "unclear"
    if value >= 0.515:
        return "leaning home"
    if value <= 0.485:
        return "leaning away"
    return "contested"


def _prediction_side(home_probability: float) -> str:
    if abs(home_probability - 0.5) < 0.006:
        return "draw"
    return "home" if home_probability > 0.5 else "away"
