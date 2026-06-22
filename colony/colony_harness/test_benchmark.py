"""Tests for resolved-event benchmark datasets."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from colony.colony_harness.benchmark import (
    BenchmarkValidationError,
    load_benchmark_dataset,
    run_benchmark_dataset,
    validate_benchmark_dataset,
)


class BenchmarkDatasetTests(unittest.TestCase):
    def test_worldcup_pilot_dataset_has_temporal_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dataset_path = _write_benchmark_fixture(Path(tmp))
            dataset = load_benchmark_dataset(dataset_path)

        self.assertEqual(dataset.schema_version, 1)
        self.assertEqual(dataset.dataset_id, "worldcup_2026_pilot_v0")
        self.assertGreaterEqual(len(dataset.events), 3)
        for event in dataset.events:
            self.assertIsNotNone(event.resolution)
            self.assertTrue(event.available_evidence())
            prediction_match = event.to_prediction_match()
            self.assertEqual(prediction_match.score, "")
            self.assertEqual(prediction_match.round_id, event.event_id)
            self.assertGreaterEqual(len(prediction_match.findings), 4)
            self.assertTrue(
                {finding.source_type for finding in prediction_match.findings}
                & {"market", "odds", "stats", "news"}
            )

    def test_validation_rejects_evidence_after_cutoff(self) -> None:
        payload = _benchmark_payload()
        payload["events"][0]["evidence_items"][0]["available_at_utc"] = "2026-06-11T15:00:01Z"

        with self.assertRaises(BenchmarkValidationError):
            validate_benchmark_dataset(load_benchmark_dataset_from_payload(payload))

    def test_validation_rejects_resolution_before_cutoff(self) -> None:
        payload = _benchmark_payload()
        payload["events"][0]["resolution"]["available_at_utc"] = "2026-06-11T13:59:00Z"

        with self.assertRaises(BenchmarkValidationError):
            validate_benchmark_dataset(load_benchmark_dataset_from_payload(payload))

    def test_run_benchmark_discusses_then_scores_against_hidden_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dataset_path = _write_benchmark_fixture(Path(tmp))
            output_dir = Path(tmp) / "benchmark"
            payload = run_benchmark_dataset(
                dataset_path=dataset_path,
                population_size=8,
                speaker_slots=3,
                seed=13,
                output_dir=output_dir,
            )

            self.assertEqual(payload["summary"]["events"], len(payload["rows"]))
            self.assertTrue((output_dir / "benchmark_results.json").exists())
            self.assertTrue((output_dir / "benchmark_report.md").exists())
            for row in payload["rows"]:
                self.assertTrue(row["prediction_score_hidden"])
                self.assertNotEqual(row["result_side"], "pending")
                self.assertGreater(row["room_claims"], 0)
                self.assertIsNotNone(row["brier_home"])
                self.assertIsNotNone(row["side_accuracy"])
                self.assertGreaterEqual(row["evidence_items"], 4)


def load_benchmark_dataset_from_payload(payload: dict):
    from colony.colony_harness.benchmark import BenchmarkDataset

    return BenchmarkDataset.from_dict(payload)


def _write_benchmark_fixture(root: Path) -> Path:
    path = root / "worldcup_pilot.json"
    path.write_text(json.dumps(_benchmark_payload(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _benchmark_payload() -> dict:
    return {
        "schema_version": 1,
        "dataset_id": "worldcup_2026_pilot_v0",
        "title": "World Cup 2026 pilot benchmark dataset",
        "description": "Small resolved-event dataset for tests.",
        "created_at_utc": "2026-06-22T00:00:00Z",
        "sources": [],
        "events": [
            _event_payload(
                event_id="wc26_group_a_mexico_south_africa",
                home_team="Mexico",
                away_team="South Africa",
                starts_at_utc="2026-06-11T19:00:00Z",
                prediction_cutoff_utc="2026-06-11T14:00:00Z",
                result_side="home",
                score="2-0",
                market_home=0.58,
            ),
            _event_payload(
                event_id="wc26_group_a_south_korea_czechia",
                home_team="South Korea",
                away_team="Czechia",
                starts_at_utc="2026-06-12T02:00:00Z",
                prediction_cutoff_utc="2026-06-11T20:00:00Z",
                result_side="home",
                score="2-1",
                market_home=0.49,
            ),
            _event_payload(
                event_id="wc26_group_b_canada_bosnia",
                home_team="Canada",
                away_team="Bosnia & Herzegovina",
                starts_at_utc="2026-06-12T19:00:00Z",
                prediction_cutoff_utc="2026-06-12T13:00:00Z",
                result_side="draw",
                score="1-1",
                market_home=0.44,
            ),
        ],
    }


def _event_payload(
    *,
    event_id: str,
    home_team: str,
    away_team: str,
    starts_at_utc: str,
    prediction_cutoff_utc: str,
    result_side: str,
    score: str,
    market_home: float,
) -> dict:
    return {
        "event_id": event_id,
        "category": "sports",
        "sub_category": "football",
        "event_type": "three_way_match_result",
        "title": f"{home_team} vs {away_team}",
        "home_team": home_team,
        "away_team": away_team,
        "starts_at_utc": starts_at_utc,
        "prediction_cutoff_utc": prediction_cutoff_utc,
        "group_name": "Group Test",
        "stage_name": "Group Stage",
        "venue_name": "Test Stadium",
        "outcome_space": ["home", "draw", "away"],
        "baseline_probabilities": {
            "home": market_home,
            "draw": 0.26,
            "away": round(1.0 - market_home - 0.26, 4),
        },
        "evidence_items": [
            _evidence(event_id, "fixture_context", "fixture_snapshot", "other", None, 0.9, "Fixture context"),
            _evidence(event_id, "market_snapshot", "market_odds_snapshot", "market", market_home, 0.72, "Market baseline"),
            _evidence(event_id, "odds_snapshot", "odds_snapshot", "odds", market_home + 0.02, 0.78, "Odds snapshot"),
            _evidence(event_id, "form_snapshot", "team_form_snapshot", "stats", market_home - 0.03, 0.66, "Form snapshot"),
            _evidence(event_id, "news_snapshot", "news_snapshot", "news", market_home + 0.01, 0.55, "News snapshot"),
        ],
        "resolution": {
            "result_side": result_side,
            "score": score,
            "resolved_at_utc": starts_at_utc,
            "available_at_utc": starts_at_utc[:11] + "23:30:00Z",
            "source_name": "official_result_snapshot",
            "citations": [f"benchmark://results/{event_id}"],
        },
    }


def _evidence(
    event_id: str,
    evidence_id: str,
    source_name: str,
    source_type: str,
    home_probability: float | None,
    confidence: float,
    summary: str,
) -> dict:
    return {
        "evidence_id": evidence_id,
        "source_name": source_name,
        "source_type": source_type,
        "access_level": "public",
        "available_at_utc": "2026-06-11T12:00:00Z",
        "home_probability": None if home_probability is None else round(home_probability, 4),
        "confidence": confidence,
        "summary": summary,
        "citations": [f"benchmark://evidence/{event_id}/{evidence_id}"],
        "metadata": {"source_quality": "medium", "subject": source_type},
    }


if __name__ == "__main__":
    unittest.main()
