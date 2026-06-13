"""Shared data models for the Colony harness."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

Side = Literal["home", "away", "pass"]


@dataclass(frozen=True)
class MatchContext:
    round_id: str
    home_team: str
    away_team: str
    market_home_probability: float
    stats_home_signal: float
    odds_home_signal: float
    news_home_signal: float

    @classmethod
    def from_dict(cls, data: dict) -> "MatchContext":
        match = data["match"]
        return cls(
            round_id=data["round_id"],
            home_team=match["home_team"],
            away_team=match["away_team"],
            market_home_probability=float(match["market_home_probability"]),
            stats_home_signal=float(match["stats_home_signal"]),
            odds_home_signal=float(match["odds_home_signal"]),
            news_home_signal=float(match["news_home_signal"]),
        )


@dataclass(frozen=True)
class DebateClaim:
    round_id: str
    speaker_id: str
    speaker_name: str
    model: str
    persona: str
    stated_home_probability: float
    confidence: float
    direction: Side
    message: str
    evidence_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Forecast:
    agent_id: str
    home_probability: float
    edge: float
    side: Side
    stake: float
    bankroll: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class BetCommitment:
    agent_id: str
    round_id: str
    commitment: str
    reveal: dict

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RoundResult:
    round_id: str
    claims: list[DebateClaim]
    forecasts: list[Forecast]
    commitments: list[BetCommitment]
    summary: dict

    def to_dict(self) -> dict:
        return {
            "round_id": self.round_id,
            "claims": [claim.to_dict() for claim in self.claims],
            "forecasts": [forecast.to_dict() for forecast in self.forecasts],
            "commitments": [commitment.to_dict() for commitment in self.commitments],
            "summary": self.summary,
        }
