"""Voice models for debate speakers."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from .genes import Genome
from .models import MatchContext, Side


class VoiceModel(Protocol):
    def render_claim(
        self,
        *,
        agent_name: str,
        genome: Genome,
        match: MatchContext,
        probability: float,
        direction: Side,
    ) -> str:
        """Render the public debate message for a speaker."""


@dataclass
class TemplateVoiceModel:
    """Deterministic local voice model used by default."""

    def render_claim(
        self,
        *,
        agent_name: str,
        genome: Genome,
        match: MatchContext,
        probability: float,
        direction: Side,
    ) -> str:
        if direction == "home":
            return (
                f"{agent_name}: I price {match.home_team} above the market. "
                f"My {genome.persona} read is {probability:.1%} home win probability."
            )

        away_probability = 1.0 - probability
        return (
            f"{agent_name}: I am fading {match.home_team}. "
            f"My {genome.persona} read gives {match.away_team} about {away_probability:.1%}."
        )


@dataclass
class OpenAICompatibleVoiceModel:
    """LLM-backed speaker voice using an OpenAI-compatible chat API."""

    api_key: str
    base_url: str
    model: str
    timeout_seconds: int = 30

    @classmethod
    def from_env(cls) -> "OpenAICompatibleVoiceModel":
        api_key = os.environ.get("COLONY_LLM_API_KEY", "").strip()
        base_url = os.environ.get("COLONY_LLM_BASE_URL", "").strip()
        model = os.environ.get("COLONY_LLM_MODEL", "minimax-m3").strip()
        timeout = int(os.environ.get("COLONY_LLM_TIMEOUT_SECONDS", "30"))

        if not api_key:
            raise ValueError("COLONY_LLM_API_KEY is missing")
        if not base_url:
            raise ValueError("COLONY_LLM_BASE_URL is missing")
        if not model:
            raise ValueError("COLONY_LLM_MODEL is missing")

        return cls(api_key=api_key, base_url=base_url.rstrip("/"), model=model, timeout_seconds=timeout)

    def render_claim(
        self,
        *,
        agent_name: str,
        genome: Genome,
        match: MatchContext,
        probability: float,
        direction: Side,
    ) -> str:
        prompt = (
            "Write one concise public debate message for a forecasting ant.\n"
            "Do not change the probability. Do not invent external facts.\n"
            "Keep it under 45 words. Write in English.\n\n"
            f"Ant name: {agent_name}\n"
            f"Persona: {genome.persona}\n"
            f"Model species: {genome.model}\n"
            f"Match: {match.home_team} vs {match.away_team}\n"
            f"Market home probability: {match.market_home_probability:.3f}\n"
            f"Ant home probability: {probability:.3f}\n"
            f"Direction: {direction}\n"
        )

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are the voice layer for a bounded ant-colony debate feed.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.8,
            "max_tokens": 120,
        }

        request = urllib.request.Request(
            url=f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM voice call failed: HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM voice call failed: {exc}") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected LLM response shape: {data}") from exc

        return str(content).strip()
