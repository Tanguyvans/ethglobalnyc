"""Lightweight ant memory adapter.

Mem0 is used when installed and configured. Local runs always have a deterministic
JSON fallback so ant creation and prediction attempts can be tested offline.
"""

from __future__ import annotations

import json
import os
import re
from statistics import mean
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_MEMORY_PATH = Path("colony/secrets/ant-memory.jsonl")
SURVIVAL_MEMORY_VERSION = "survival_thesis_v1"


class AntMemoryStore:
    backend_name = "base"

    def recall(self, *, agent_id: str, query: str, limit: int, metadata: dict | None = None) -> dict:
        raise NotImplementedError

    def remember(self, *, agent_id: str, text: str, metadata: dict | None = None) -> dict:
        raise NotImplementedError

    def healthcheck(self) -> dict:
        return {"backend": self.backend_name, "ok": True}


class JsonAntMemoryStore(AntMemoryStore):
    backend_name = "json"

    def __init__(self, path: str | Path = DEFAULT_MEMORY_PATH) -> None:
        self.path = Path(path)

    def recall(self, *, agent_id: str, query: str, limit: int, metadata: dict | None = None) -> dict:
        metadata = dict(metadata or {})
        records = [row for row in self._read_records() if row.get("agent_id") == agent_id]
        candidate_records = _scoped_records(records, metadata)
        scored = sorted(
            ((_score_memory(row, query), row) for row in candidate_records),
            key=lambda item: (item[0], str(item[1].get("created_at") or "")),
            reverse=True,
        )
        results = [row for score, row in scored if score > 0][:limit]
        if not results and candidate_records:
            results = list(reversed(candidate_records[-limit:]))
        return {
            "agent_id": agent_id,
            "backend": self.backend_name,
            "query": query,
            "metadata": metadata,
            "candidate_count": len(candidate_records),
            "filtered_count": max(0, len(records) - len(candidate_records)),
            "results": results,
        }

    def remember(self, *, agent_id: str, text: str, metadata: dict | None = None) -> dict:
        record = {
            "agent_id": agent_id,
            "memory": " ".join(str(text).split()),
            "metadata": dict(metadata or {}),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "backend": self.backend_name,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return record

    def healthcheck(self) -> dict:
        return {
            "backend": self.backend_name,
            "ok": True,
            "path": str(self.path),
            "records": len(self._read_records()) if self.path.exists() else 0,
        }

    def _read_records(self) -> list[dict]:
        if not self.path.exists():
            return []
        rows: list[dict] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
        return rows


class Mem0AntMemoryStore(AntMemoryStore):
    backend_name = "mem0"

    def __init__(self, fallback: JsonAntMemoryStore) -> None:
        self.fallback = fallback
        try:
            from mem0 import Memory  # type: ignore

            self.memory = Memory()
            self._available = True
            self._error = ""
        except Exception as exc:  # pragma: no cover - depends on optional package.
            self.memory = None
            self._available = False
            self._error = " ".join(str(exc).split())[:220]

    def recall(self, *, agent_id: str, query: str, limit: int, metadata: dict | None = None) -> dict:
        if not self._available:
            result = self.fallback.recall(agent_id=agent_id, query=query, limit=limit, metadata=metadata)
            result["backend"] = "json_fallback"
            result["fallback_reason"] = self._error
            return result
        try:
            payload = self.memory.search(query=query, filters={"user_id": agent_id}, top_k=limit)
            results = payload.get("results") if isinstance(payload, dict) else payload
            return {
                "agent_id": agent_id,
                "backend": self.backend_name,
                "query": query,
                "metadata": dict(metadata or {}),
                "results": results or [],
            }
        except Exception as exc:  # pragma: no cover - depends on optional package.
            result = self.fallback.recall(agent_id=agent_id, query=query, limit=limit, metadata=metadata)
            result["backend"] = "json_fallback"
            result["fallback_reason"] = " ".join(str(exc).split())[:220]
            return result

    def remember(self, *, agent_id: str, text: str, metadata: dict | None = None) -> dict:
        fallback_record = self.fallback.remember(agent_id=agent_id, text=text, metadata=metadata)
        if not self._available:
            fallback_record["backend"] = "json_fallback"
            fallback_record["fallback_reason"] = self._error
            return fallback_record
        try:
            self.memory.add(text, user_id=agent_id, metadata=dict(metadata or {}))
            return {**fallback_record, "backend": self.backend_name, "mirrored_to_json": True}
        except Exception as exc:  # pragma: no cover - depends on optional package.
            fallback_record["backend"] = "json_fallback"
            fallback_record["fallback_reason"] = " ".join(str(exc).split())[:220]
            return fallback_record

    def healthcheck(self) -> dict:
        return {
            "backend": self.backend_name if self._available else "json_fallback",
            "ok": True,
            "mem0_available": self._available,
            "fallback": self.fallback.healthcheck(),
            "error": self._error,
        }


def build_ant_memory_store() -> AntMemoryStore:
    backend = os.environ.get("COLONY_MEMORY_BACKEND", "mem0").strip().lower()
    path = Path(os.environ.get("COLONY_MEMORY_PATH", str(DEFAULT_MEMORY_PATH)))
    fallback = JsonAntMemoryStore(path)
    if backend in {"off", "none", "disabled"}:
        return fallback
    if backend == "json":
        return fallback
    return Mem0AntMemoryStore(fallback)


def recall_query_for_match(*, home_team: str, away_team: str, archetype: str) -> str:
    return (
        f"Survival Thesis V1 memories for {home_team} vs {away_team}; "
        f"risk sizing, thesis quality, debate influence, and mistakes for archetype {archetype}."
    )


def forecast_memory_signal(recall: dict) -> dict:
    values = []
    correct = 0
    for row in (recall or {}).get("results") or []:
        metadata = row.get("metadata") or {}
        result_side = str(metadata.get("result_side") or "")
        home_value = _result_home_value(result_side)
        if home_value is None:
            continue
        values.append(home_value)
        if str(metadata.get("side") or "") == result_side:
            correct += 1
    if not values:
        return {
            "available": False,
            "samples": 0,
            "home_probability": None,
            "confidence": 0.0,
            "self_correct_rate": None,
        }
    return {
        "available": True,
        "samples": len(values),
        "home_probability": round(mean(values), 4),
        "confidence": round(min(1.0, 0.45 + len(values) * 0.25), 4),
        "self_correct_rate": round(correct / len(values), 4),
    }


def forecast_memory_text(*, forecast: dict, mind: dict, result_side: str = "pending") -> str:
    outcome = result_side if result_side != "pending" else "not settled yet"
    risk_profile = forecast.get("risk_profile") or "unknown"
    return (
        f"Round {forecast.get('round_id', '')}: as {mind.get('label', mind.get('archetype', 'ant'))}, "
        f"I picked {forecast.get('side')} with risk profile {risk_profile}. "
        f"My reason was: {forecast.get('decision_reason', '')} "
        f"Settlement is {outcome}."
    )


def _score_memory(row: dict, query: str) -> int:
    text = f"{row.get('memory', '')} {json.dumps(row.get('metadata') or {}, sort_keys=True)}".lower()
    query_tokens = set(re.findall(r"[a-z0-9_]{3,}", query.lower()))
    if not query_tokens:
        return 1
    return sum(1 for token in query_tokens if token in text)


def _scoped_records(records: list[dict], metadata: dict) -> list[dict]:
    home_team = str(metadata.get("home_team") or "").strip()
    away_team = str(metadata.get("away_team") or "").strip()
    memory_version = str(metadata.get("memory_version") or "").strip()
    if not home_team or not away_team:
        scoped = records
    else:
        scoped = [
            row
            for row in records
            if (row.get("metadata") or {}).get("home_team") == home_team
            and (row.get("metadata") or {}).get("away_team") == away_team
        ]
    if not memory_version:
        return scoped
    return [
        row
        for row in scoped
        if (row.get("metadata") or {}).get("memory_version") == memory_version
    ]


def _result_home_value(result_side: str) -> float | None:
    if result_side == "home":
        return 1.0
    if result_side == "away":
        return 0.0
    if result_side == "draw":
        return 0.5
    return None
