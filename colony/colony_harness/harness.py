"""Colony harness orchestration."""

from __future__ import annotations

import json
import random
from pathlib import Path

from .agent import AntAgent
from .debate import DebateFeed
from .genes import random_genome
from .models import MatchContext, RoundResult
from .voice import TemplateVoiceModel, VoiceModel


class ColonyHarness:
    def __init__(
        self,
        population_size: int = 40,
        speaker_slots: int = 6,
        seed: int = 42,
        starting_bankroll: float = 100.0,
        voice_model: VoiceModel | None = None,
    ) -> None:
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
        self.agents = self._spawn_agents()

    def _spawn_agents(self) -> list[AntAgent]:
        agents: list[AntAgent] = []
        for index in range(self.population_size):
            genome = random_genome(self.rng)
            agent = AntAgent(
                agent_id=f"ant_{index:04d}",
                name=f"ant-{index:04d}",
                generation=0,
                genome=genome,
                bankroll=round(self.starting_bankroll * self.rng.uniform(0.92, 1.08), 4),
                accuracy=round(self.rng.uniform(0.35, 0.65), 4),
            )
            agents.append(agent)
        return agents

    def select_speakers(self) -> list[AntAgent]:
        ranked = sorted(
            self.agents,
            key=lambda ant: (ant.bankroll * 0.7) + (ant.accuracy * 100.0 * 0.3),
            reverse=True,
        )
        elite_count = max(1, self.speaker_slots // 2)
        elite = ranked[:elite_count]
        remaining = [agent for agent in self.agents if agent not in elite]
        wildcards = self.rng.sample(remaining, k=self.speaker_slots - elite_count)
        return elite + wildcards

    def run_round(self, match: MatchContext) -> RoundResult:
        feed = DebateFeed()

        for speaker in self.select_speakers():
            feed.append(speaker.speak(match, self.rng, self.voice_model))

        debate_signal = feed.consensus_home_probability()
        forecasts = [agent.forecast(match, debate_signal) for agent in self.agents]
        commitments = [
            agent.commit_bet(forecast, match.round_id)
            for agent, forecast in zip(self.agents, forecasts, strict=True)
        ]

        home_bets = sum(1 for forecast in forecasts if forecast.side == "home")
        away_bets = sum(1 for forecast in forecasts if forecast.side == "away")
        passes = sum(1 for forecast in forecasts if forecast.side == "pass")
        total_staked = round(sum(forecast.stake for forecast in forecasts), 4)

        summary = {
            "population": self.population_size,
            "speaker_slots": self.speaker_slots,
            "debate_home_probability": None if debate_signal is None else round(debate_signal, 4),
            "market_home_probability": match.market_home_probability,
            "home_bets": home_bets,
            "away_bets": away_bets,
            "passes": passes,
            "total_staked": total_staked,
        }

        return RoundResult(
            round_id=match.round_id,
            claims=feed.claims,
            forecasts=forecasts,
            commitments=commitments,
            summary=summary,
        )

    def write_jsonl(self, result: RoundResult, output_path: str | Path) -> None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        events = []
        events.append({"event_type": "round_summary", **result.summary})
        # Emit the roster up front so a replay consumer can bind agent_id -> index
        # before any debate_claim/forecast/bet_commitment references an agent.
        events.extend(
            {"event_type": "agent_record", **record} for record in self.public_roster()
        )
        events.extend({"event_type": "debate_claim", **claim.to_dict()} for claim in result.claims)
        events.extend({"event_type": "forecast", **forecast.to_dict()} for forecast in result.forecasts)
        events.extend({"event_type": "bet_commitment", **commitment.to_dict()} for commitment in result.commitments)

        with path.open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    def public_roster(self) -> list[dict]:
        return [agent.public_record for agent in self.agents]
