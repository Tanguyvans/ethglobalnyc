"""Generic resolved-event benchmark support for Colony.

The benchmark format is intentionally stricter than the live match config:
agents receive only evidence that was available before the prediction cutoff,
while the resolution is kept outside the `MatchContext` used for debate.
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from .artifacts import create_run_dir, write_compact_run_artifacts
from .harness import ColonyHarness
from .models import Finding, Forecast, MatchContext, ResultSide


BENCHMARK_SCHEMA_VERSION = 1


class BenchmarkValidationError(ValueError):
    """Raised when a benchmark dataset can leak future information."""


@dataclass(frozen=True)
class BenchmarkEvidence:
    evidence_id: str
    source_name: str
    source_type: str
    access_level: str
    available_at_utc: str
    home_probability: float | None
    confidence: float
    summary: str
    citations: list[str] = field(default_factory=list)
    evidence_claims: list[dict[str, Any]] = field(default_factory=list)
    source_snapshot_id: str = ""
    published_at_utc: str = ""
    seen_at_utc: str = ""
    collected_at_utc: str = ""
    content_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BenchmarkEvidence":
        return cls(
            evidence_id=str(data["evidence_id"]),
            source_name=str(data["source_name"]),
            source_type=str(data["source_type"]),
            access_level=str(data.get("access_level") or "public"),
            available_at_utc=str(data["available_at_utc"]),
            home_probability=(
                None
                if data.get("home_probability") is None
                else float(data["home_probability"])
            ),
            confidence=float(data.get("confidence", 0.5)),
            summary=str(data.get("summary") or ""),
            citations=[str(item) for item in data.get("citations") or []],
            evidence_claims=list(data.get("evidence_claims") or []),
            source_snapshot_id=str(data.get("source_snapshot_id") or ""),
            published_at_utc=str(data.get("published_at_utc") or ""),
            seen_at_utc=str(data.get("seen_at_utc") or ""),
            collected_at_utc=str(data.get("collected_at_utc") or ""),
            content_hash=str(data.get("content_hash") or ""),
            metadata=dict(data.get("metadata") or {}),
        )

    def to_finding(self, *, event: "BenchmarkEvent", market_home_probability: float) -> Finding:
        home_delta = (
            None
            if self.home_probability is None
            else round(self.home_probability - market_home_probability, 4)
        )
        return Finding(
            finding_id=f"{event.event_id}:{self.evidence_id}",
            scout_name=self.source_name,
            access_level=self.access_level,  # type: ignore[arg-type]
            source_type=self.source_type,  # type: ignore[arg-type]
            finding_name=str(self.metadata.get("finding_name") or self.evidence_id),
            home_probability=self.home_probability,
            home_delta=home_delta,
            confidence=self.confidence,
            cost=float(self.metadata.get("cost") or 0.0),
            citations=self.citations,
            summary=self.summary,
            evidence_claims=self.evidence_claims
            or [
                {
                    "claim": self.summary,
                    "subject": self.metadata.get("subject") or self.source_type,
                    "source_title": self.source_name,
                    "source_quality": self.metadata.get("source_quality") or "medium",
                    "available_at_utc": self.available_at_utc,
                }
            ],
        )


@dataclass(frozen=True)
class BenchmarkResolution:
    result_side: ResultSide
    score: str
    resolved_at_utc: str
    available_at_utc: str
    source_name: str = ""
    citations: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BenchmarkResolution":
        return cls(
            result_side=str(data["result_side"]),  # type: ignore[arg-type]
            score=str(data.get("score") or ""),
            resolved_at_utc=str(data["resolved_at_utc"]),
            available_at_utc=str(data["available_at_utc"]),
            source_name=str(data.get("source_name") or ""),
            citations=[str(item) for item in data.get("citations") or []],
        )


@dataclass(frozen=True)
class BenchmarkEvent:
    event_id: str
    category: str
    sub_category: str
    event_type: str
    title: str
    home_team: str
    away_team: str
    starts_at_utc: str
    prediction_cutoff_utc: str
    outcome_space: list[str]
    baseline_probabilities: dict[str, float]
    evidence_items: list[BenchmarkEvidence]
    resolution: BenchmarkResolution | None = None
    group_name: str = ""
    stage_name: str = ""
    venue_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BenchmarkEvent":
        resolution = data.get("resolution")
        return cls(
            event_id=str(data["event_id"]),
            category=str(data.get("category") or "sports"),
            sub_category=str(data.get("sub_category") or "football"),
            event_type=str(data.get("event_type") or "match_result"),
            title=str(data.get("title") or data["event_id"]),
            home_team=str(data["home_team"]),
            away_team=str(data["away_team"]),
            starts_at_utc=str(data["starts_at_utc"]),
            prediction_cutoff_utc=str(data["prediction_cutoff_utc"]),
            outcome_space=[str(item) for item in data.get("outcome_space") or []],
            baseline_probabilities={
                str(key): float(value)
                for key, value in (data.get("baseline_probabilities") or {}).items()
            },
            evidence_items=[
                BenchmarkEvidence.from_dict(item)
                for item in data.get("evidence_items") or []
            ],
            resolution=BenchmarkResolution.from_dict(resolution) if resolution else None,
            group_name=str(data.get("group_name") or ""),
            stage_name=str(data.get("stage_name") or ""),
            venue_name=str(data.get("venue_name") or ""),
            metadata=dict(data.get("metadata") or {}),
        )

    def available_evidence(self) -> list[BenchmarkEvidence]:
        cutoff = parse_utc(self.prediction_cutoff_utc)
        return [
            item
            for item in self.evidence_items
            if parse_utc(item.available_at_utc) <= cutoff
        ]

    def to_prediction_match(self) -> MatchContext:
        """Build the no-leak match view used by the ants before resolution."""
        available = self.available_evidence()
        market_home_probability = self._source_probability({"market"}, fallback=self._home_baseline())
        stats_home_signal = self._source_probability({"stats", "lineup"}, fallback=market_home_probability)
        odds_home_signal = self._source_probability({"odds"}, fallback=market_home_probability)
        news_home_signal = self._source_probability(
            {"news", "social", "retrieval", "weather"},
            fallback=market_home_probability,
        )
        return MatchContext(
            round_id=self.event_id,
            home_team=self.home_team,
            away_team=self.away_team,
            market_home_probability=market_home_probability,
            stats_home_signal=stats_home_signal,
            odds_home_signal=odds_home_signal,
            news_home_signal=news_home_signal,
            match_date=self.starts_at_utc[:10],
            match_time=self.starts_at_utc[11:16],
            group_name=self.group_name,
            stage_name=self.stage_name,
            venue_name=self.venue_name,
            score="",
            findings=[
                item.to_finding(event=self, market_home_probability=market_home_probability)
                for item in available
            ],
        )

    def _home_baseline(self) -> float:
        value = self.baseline_probabilities.get("home")
        if value is None:
            raise BenchmarkValidationError(f"{self.event_id}: missing baseline_probabilities.home")
        return _clamp_probability(value)

    def _source_probability(self, source_types: set[str], *, fallback: float) -> float:
        weighted_total = 0.0
        weight = 0.0
        for item in self.available_evidence():
            if item.source_type not in source_types or item.home_probability is None:
                continue
            confidence = max(item.confidence, 0.01)
            weighted_total += item.home_probability * confidence
            weight += confidence
        if weight <= 0:
            return _clamp_probability(fallback)
        return _clamp_probability(round(weighted_total / weight, 4))


@dataclass(frozen=True)
class BenchmarkDataset:
    dataset_id: str
    title: str
    description: str
    created_at_utc: str
    events: list[BenchmarkEvent]
    schema_version: int = BENCHMARK_SCHEMA_VERSION
    sources: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BenchmarkDataset":
        return cls(
            schema_version=int(data.get("schema_version") or 0),
            dataset_id=str(data["dataset_id"]),
            title=str(data.get("title") or data["dataset_id"]),
            description=str(data.get("description") or ""),
            created_at_utc=str(data.get("created_at_utc") or ""),
            sources=list(data.get("sources") or []),
            events=[BenchmarkEvent.from_dict(item) for item in data.get("events") or []],
        )


def load_benchmark_dataset(path: str | Path) -> BenchmarkDataset:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    dataset = BenchmarkDataset.from_dict(payload)
    validate_benchmark_dataset(dataset)
    return dataset


def validate_benchmark_dataset(dataset: BenchmarkDataset) -> None:
    if dataset.schema_version != BENCHMARK_SCHEMA_VERSION:
        raise BenchmarkValidationError(
            f"Unsupported schema_version {dataset.schema_version}; expected {BENCHMARK_SCHEMA_VERSION}"
        )
    if not dataset.events:
        raise BenchmarkValidationError("Benchmark dataset must contain at least one event")

    event_ids: set[str] = set()
    for event in dataset.events:
        if event.event_id in event_ids:
            raise BenchmarkValidationError(f"Duplicate event_id: {event.event_id}")
        event_ids.add(event.event_id)
        _validate_event_temporal_contract(event)
        _validate_event_probabilities(event)
        _validate_evidence_contract(event)


def _validate_event_temporal_contract(event: BenchmarkEvent) -> None:
    cutoff = parse_utc(event.prediction_cutoff_utc)
    starts_at = parse_utc(event.starts_at_utc)
    if cutoff > starts_at:
        raise BenchmarkValidationError(
            f"{event.event_id}: prediction_cutoff_utc must be <= starts_at_utc"
        )
    if event.resolution is None:
        return
    resolved_at = parse_utc(event.resolution.resolved_at_utc)
    resolution_available = parse_utc(event.resolution.available_at_utc)
    if resolved_at < starts_at:
        raise BenchmarkValidationError(f"{event.event_id}: resolution is before event start")
    if resolution_available <= cutoff:
        raise BenchmarkValidationError(
            f"{event.event_id}: resolution is available before prediction cutoff"
        )


def _validate_event_probabilities(event: BenchmarkEvent) -> None:
    if "home" not in event.baseline_probabilities:
        raise BenchmarkValidationError(f"{event.event_id}: baseline_probabilities.home is required")
    for key, value in event.baseline_probabilities.items():
        if not 0.0 <= value <= 1.0:
            raise BenchmarkValidationError(f"{event.event_id}: invalid baseline probability {key}={value}")


def _validate_evidence_contract(event: BenchmarkEvent) -> None:
    cutoff = parse_utc(event.prediction_cutoff_utc)
    seen_ids: set[str] = set()
    for item in event.evidence_items:
        if item.evidence_id in seen_ids:
            raise BenchmarkValidationError(f"{event.event_id}: duplicate evidence_id {item.evidence_id}")
        seen_ids.add(item.evidence_id)
        if parse_utc(item.available_at_utc) > cutoff:
            raise BenchmarkValidationError(
                f"{event.event_id}/{item.evidence_id}: evidence available after prediction cutoff"
            )
        if item.source_type == "result":
            raise BenchmarkValidationError(
                f"{event.event_id}/{item.evidence_id}: result evidence cannot be visible pre-prediction"
            )
        if item.access_level not in {"public", "shared", "private"}:
            raise BenchmarkValidationError(
                f"{event.event_id}/{item.evidence_id}: invalid access_level {item.access_level}"
            )
        if item.home_probability is not None and not 0.0 <= item.home_probability <= 1.0:
            raise BenchmarkValidationError(
                f"{event.event_id}/{item.evidence_id}: invalid home_probability"
            )
        if not 0.0 <= item.confidence <= 1.0:
            raise BenchmarkValidationError(
                f"{event.event_id}/{item.evidence_id}: invalid confidence"
            )
        for label, value in (
            ("published_at_utc", item.published_at_utc),
            ("seen_at_utc", item.seen_at_utc),
            ("collected_at_utc", item.collected_at_utc),
        ):
            if value:
                try:
                    parse_utc(value)
                except BenchmarkValidationError as exc:
                    raise BenchmarkValidationError(
                        f"{event.event_id}/{item.evidence_id}: invalid {label}"
                    ) from exc


def run_benchmark_dataset(
    *,
    dataset_path: str | Path,
    population_size: int,
    speaker_slots: int,
    seed: int,
    output_dir: str | Path,
    memory_influence: bool = False,
    write_run_artifacts: bool = False,
) -> dict[str, Any]:
    dataset = load_benchmark_dataset(dataset_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    memory_path = output / "benchmark_memory.jsonl"
    if memory_path.exists():
        memory_path.unlink()

    old_backend = os.environ.get("COLONY_MEMORY_BACKEND")
    old_path = os.environ.get("COLONY_MEMORY_PATH")
    os.environ["COLONY_MEMORY_BACKEND"] = "json"
    os.environ["COLONY_MEMORY_PATH"] = str(memory_path)
    rows: list[dict[str, Any]] = []
    run_artifacts: list[str] = []
    try:
        harness = ColonyHarness(
            population_size=population_size,
            speaker_slots=speaker_slots,
            seed=seed,
            memory_influence=memory_influence,
        )
        for index, event in enumerate(dataset.events, start=1):
            match = event.to_prediction_match()
            if match.score:
                raise BenchmarkValidationError(f"{event.event_id}: prediction match leaked score")
            result = harness.run_round(match)
            row = _benchmark_row(event=event, result=result.to_dict(), forecasts=result.forecasts)
            row["event_index"] = index
            row["memory_influence"] = memory_influence
            rows.append(row)
            if write_run_artifacts:
                run_dir = create_run_dir(output / "runs", result.round_id)
                write_compact_run_artifacts(run_dir=run_dir, match=match, result=result, debug=False)
                run_artifacts.append(str(run_dir))
    finally:
        _restore_env("COLONY_MEMORY_BACKEND", old_backend)
        _restore_env("COLONY_MEMORY_PATH", old_path)

    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset_path": str(dataset_path),
        "dataset": {
            "dataset_id": dataset.dataset_id,
            "title": dataset.title,
            "schema_version": dataset.schema_version,
            "events": len(dataset.events),
            "sources": dataset.sources,
        },
        "population_size": population_size,
        "speaker_slots": speaker_slots,
        "seed": seed,
        "memory_influence": memory_influence,
        "memory_path": str(memory_path),
        "summary": summarize_benchmark_rows(rows),
        "rows": rows,
        "run_artifacts": run_artifacts,
    }
    (output / "benchmark_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "benchmark_report.md").write_text(_benchmark_markdown_report(payload), encoding="utf-8")
    return payload


def score_benchmark_forecasts(
    forecasts: list[Forecast],
    *,
    result_side: ResultSide,
) -> dict[str, Any]:
    if result_side == "pending":
        return {
            "forecast_count": len(forecasts),
            "brier_home": None,
            "side_accuracy": None,
            "normalized_roi": None,
            "total_staked": round(sum(max(forecast.stake, 0.0) for forecast in forecasts), 4),
            "side_counts": dict(Counter(forecast.side for forecast in forecasts)),
        }
    target = target_home_probability(result_side)
    total_staked = round(sum(max(forecast.stake, 0.0) for forecast in forecasts), 4)
    correct_count = sum(1 for forecast in forecasts if forecast.side == result_side)
    net = sum(forecast.stake if forecast.side == result_side else -forecast.stake for forecast in forecasts)
    return {
        "forecast_count": len(forecasts),
        "brier_home": round(mean((forecast.home_probability - target) ** 2 for forecast in forecasts), 6),
        "side_accuracy": round(correct_count / len(forecasts), 6) if forecasts else None,
        "normalized_roi": None if total_staked <= 0 else round(net / total_staked, 6),
        "total_staked": total_staked,
        "side_counts": dict(sorted(Counter(forecast.side for forecast in forecasts).items())),
    }


def target_home_probability(result_side: ResultSide) -> float:
    if result_side == "home":
        return 1.0
    if result_side == "away":
        return 0.0
    return 0.5


def summarize_benchmark_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_category[str(row.get("category") or "unknown")].append(row)
    return {
        "events": len(rows),
        "avg_brier_home": _avg(rows, "brier_home"),
        "avg_side_accuracy": _avg(rows, "side_accuracy"),
        "avg_normalized_roi": _avg(rows, "normalized_roi"),
        "collective_accuracy": (
            round(sum(1 for row in rows if row.get("collective_correct")) / len(rows), 6)
            if rows
            else None
        ),
        "total_claims": sum(int(row.get("room_claims") or 0) for row in rows),
        "total_evidence_items": sum(int(row.get("evidence_items") or 0) for row in rows),
        "source_names": sorted(
            {
                source
                for row in rows
                for source in row.get("source_names", [])
            }
        ),
        "categories": {
            category: {
                "events": len(category_rows),
                "avg_brier_home": _avg(category_rows, "brier_home"),
                "avg_side_accuracy": _avg(category_rows, "side_accuracy"),
                "collective_accuracy": (
                    round(
                        sum(1 for row in category_rows if row.get("collective_correct"))
                        / len(category_rows),
                        6,
                    )
                    if category_rows
                    else None
                ),
            }
            for category, category_rows in sorted(by_category.items())
        },
        "notes": [
            "Prediction MatchContext.score is intentionally blank; resolution is scored after the debate run.",
            "Every evidence_item must have available_at_utc <= prediction_cutoff_utc.",
            "Every resolution must have available_at_utc > prediction_cutoff_utc.",
            "normalized_roi is a simple +stake/-stake toy payout until real odds settlement is connected.",
        ],
    }


def parse_utc(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise BenchmarkValidationError("Missing UTC datetime")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise BenchmarkValidationError(f"Datetime must include timezone: {value}")
    return parsed.astimezone(timezone.utc)


def _benchmark_row(*, event: BenchmarkEvent, result: dict[str, Any], forecasts: list[Forecast]) -> dict[str, Any]:
    resolution = event.resolution
    result_side = resolution.result_side if resolution is not None else "pending"
    scores = score_benchmark_forecasts(forecasts, result_side=result_side)
    collective_side = str((result.get("collective_decision") or {}).get("recommendation", {}).get("side") or "")
    available_evidence = event.available_evidence()
    row = {
        "event_id": event.event_id,
        "event_index": None,
        "category": event.category,
        "sub_category": event.sub_category,
        "event_type": event.event_type,
        "title": event.title,
        "prediction_cutoff_utc": event.prediction_cutoff_utc,
        "starts_at_utc": event.starts_at_utc,
        "resolution_available_at_utc": resolution.available_at_utc if resolution else "",
        "resolution_score": resolution.score if resolution else "",
        "result_side": result_side,
        "collective_side": collective_side,
        "collective_correct": collective_side == result_side if result_side != "pending" else None,
        "prediction_score_hidden": not bool(result.get("score")),
        "evidence_items": len(available_evidence),
        "source_names": sorted({item.source_name for item in available_evidence}),
        "source_types": dict(Counter(item.source_type for item in available_evidence)),
        "access_levels": dict(Counter(item.access_level for item in available_evidence)),
        "room_count": (result.get("summary") or {}).get("room_count", 0),
        "room_claims": (result.get("summary") or {}).get("room_claims", 0),
        "debate_home_probability": (result.get("summary") or {}).get("debate_home_probability"),
        "memory_recalls": (result.get("summary") or {}).get("memory_recalls", 0),
        "memory_writes": (result.get("summary") or {}).get("memory_writes", 0),
    }
    row.update(scores)
    return row


def _benchmark_markdown_report(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Colony Benchmark Report",
        "",
        f"- Created: {payload['created_at']}",
        f"- Dataset: `{payload['dataset']['dataset_id']}`",
        f"- Events: {summary['events']}",
        f"- Population: {payload['population_size']}",
        f"- Rooms: {payload['speaker_slots']}",
        f"- Seed: {payload['seed']}",
        f"- Memory influence: {payload['memory_influence']}",
        f"- Sources: {', '.join(summary['source_names']) or 'n/a'}",
        "",
        "## Summary",
        "",
        "| Brier | Side accuracy | Collective accuracy | ROI | Claims | Evidence items |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
        (
            f"| {_fmt(summary['avg_brier_home'])} | {_fmt(summary['avg_side_accuracy'])} | "
            f"{_fmt(summary['collective_accuracy'])} | {_fmt(summary['avg_normalized_roi'])} | "
            f"{summary['total_claims']} | {summary['total_evidence_items']} |"
        ),
        "",
        "## Events",
        "",
        "| Event | Result | Collective | Brier | Side accuracy | ROI | Evidence | Claims | Cutoff | Resolution seen |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in payload["rows"]:
        lines.append(
            f"| {row['event_id']} | {row['result_side']} | {row['collective_side']} | "
            f"{_fmt(row['brier_home'])} | {_fmt(row['side_accuracy'])} | "
            f"{_fmt(row['normalized_roi'])} | {row['evidence_items']} | {row['room_claims']} | "
            f"{row['prediction_cutoff_utc']} | {row['resolution_available_at_utc']} |"
        )
    lines.extend(["", "## Temporal Contract", ""])
    for note in summary["notes"]:
        lines.append(f"- {note}")
    if payload.get("run_artifacts"):
        lines.extend(["", "## Run Artifacts", ""])
        for artifact in payload["run_artifacts"]:
            lines.append(f"- `{artifact}`")
    return "\n".join(lines) + "\n"


def _avg(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [row.get(key) for row in rows if isinstance(row.get(key), int | float)]
    if not values:
        return None
    return round(mean(float(value) for value in values), 6)


def _clamp_probability(value: float) -> float:
    return min(max(float(value), 0.01), 0.99)


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _restore_env(key: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value
