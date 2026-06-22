"""Tests for building a World Cup benchmark from resolved fixtures."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from colony.build_worldcup_benchmark import (
    attach_kg_scouting_evidence,
    attach_prematch_scrape_evidence,
    build_dataset,
    build_espn_dataset,
)
from colony.colony_harness.benchmark import BenchmarkDataset, validate_benchmark_dataset


SOURCE_CATALOG_PATH = Path(__file__).resolve().parents[1] / "config" / "scouting_source_catalog.json"


class WorldCupBenchmarkBuilderTests(unittest.TestCase):
    def test_builder_redacts_scores_from_prediction_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            openfootball_path = _write_openfootball_fixture(Path(tmp))
            output = Path(tmp) / "worldcup_benchmark.json"
            payload = build_dataset(
                openfootball_path=openfootball_path,
                manifest=None,
                dataset_id="test_worldcup_builder",
                limit=0,
                cutoff_hours=6.0,
                resolution_delay_minutes=135,
            )
            output.write_text(json.dumps(payload), encoding="utf-8")

            dataset = BenchmarkDataset.from_dict(payload)
            validate_benchmark_dataset(dataset)
            self.assertEqual(len(dataset.events), 4)
            for event in payload["events"]:
                resolution_score = event["resolution"]["score"]
                evidence_text = json.dumps(event["evidence_items"], ensure_ascii=False)
                self.assertNotIn(resolution_score, evidence_text)
                self.assertEqual(len(event["evidence_items"]), 2)
                self.assertEqual(event["evidence_items"][1]["source_name"], "benchmark_fixture_prior")
                self.assertLessEqual(
                    event["evidence_items"][0]["available_at_utc"],
                    event["prediction_cutoff_utc"],
                )
                self.assertGreater(
                    event["resolution"]["available_at_utc"],
                    event["prediction_cutoff_utc"],
                )

    def test_espn_builder_uses_opening_moneyline_without_score_leak(self) -> None:
        snapshot = {
            "collected_at_utc": "2026-06-22T19:00:22+00:00",
            "scoreboard": {
                "events": [
                    {
                        "id": "760415",
                        "date": "2026-06-11T19:00Z",
                        "name": "South Africa at Mexico",
                        "status": {"type": {"completed": True, "description": "Full Time"}},
                        "competitions": [
                            {
                                "date": "2026-06-11T19:00Z",
                                "venue": {"fullName": "Estadio Banorte"},
                                "competitors": [
                                    {
                                        "homeAway": "home",
                                        "score": "2",
                                        "team": {"displayName": "Mexico"},
                                    },
                                    {
                                        "homeAway": "away",
                                        "score": "0",
                                        "team": {"displayName": "South Africa"},
                                    },
                                ],
                            }
                        ],
                    }
                ]
            },
            "event_summaries": [
                {
                    "event_id": "760415",
                    "status": "ok",
                    "payload": {
                        "odds": [
                            {
                                "provider": {"name": "DraftKings"},
                                "moneyline": {
                                    "home": {"open": {"odds": "-170"}, "close": {"odds": "-230"}},
                                    "draw": {"open": {"odds": "+295"}, "close": {"odds": "+330"}},
                                    "away": {"open": {"odds": "+500"}, "close": {"odds": "+750"}},
                                },
                            }
                        ]
                    },
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "espn_worldcup_scoreboard_test.json"
            source.write_text(json.dumps(snapshot), encoding="utf-8")
            payload = build_espn_dataset(
                espn_snapshot_path=source,
                manifest=None,
                dataset_id="test_espn_worldcup_builder",
                limit=0,
                cutoff_hours=6.0,
                resolution_delay_minutes=135,
            )

            dataset = BenchmarkDataset.from_dict(payload)
            validate_benchmark_dataset(dataset)
            self.assertEqual(len(dataset.events), 1)
            event = payload["events"][0]
            evidence_text = json.dumps(event["evidence_items"], ensure_ascii=False)
            self.assertNotIn(event["resolution"]["score"], evidence_text)
            self.assertEqual(event["resolution"]["result_side"], "home")
            self.assertEqual(event["evidence_items"][1]["evidence_id"], "espn_moneyline_open")
            self.assertEqual(event["evidence_items"][1]["source_type"], "market")
            self.assertNotIn("-230", evidence_text)
            prediction_match = dataset.events[0].to_prediction_match()
            self.assertEqual(prediction_match.score, "")
            self.assertGreater(prediction_match.market_home_probability, 0.45)

    def test_kg_scouting_sources_attach_as_pre_match_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "espn_worldcup_scoreboard_test.json"
            source.write_text(json.dumps(_minimal_espn_snapshot()), encoding="utf-8")
            payload = build_espn_dataset(
                espn_snapshot_path=source,
                manifest=None,
                dataset_id="test_espn_worldcup_kg_sources",
                limit=0,
                cutoff_hours=6.0,
                resolution_delay_minutes=135,
            )

            payload = attach_kg_scouting_evidence(
                payload,
                modules=["fixture"],
                source_catalog=SOURCE_CATALOG_PATH,
                cutoff_hours=6.0,
                scouting_mode="fast",
                scouting_timeout=5,
            )

            dataset = BenchmarkDataset.from_dict(payload)
            validate_benchmark_dataset(dataset)
            event = payload["events"][0]
            kg_items = [item for item in event["evidence_items"] if item["evidence_id"].startswith("kg_")]
            self.assertGreaterEqual(len(kg_items), 1)
            evidence_text = json.dumps(kg_items, ensure_ascii=False)
            self.assertNotIn(event["resolution"]["score"], evidence_text)
            self.assertTrue(
                all(item["available_at_utc"] == event["prediction_cutoff_utc"] for item in kg_items)
            )

    def test_prematch_scrape_source_attaches_to_matching_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "espn_worldcup_scoreboard_test.json"
            source.write_text(json.dumps(_minimal_espn_snapshot()), encoding="utf-8")
            payload = build_espn_dataset(
                espn_snapshot_path=source,
                manifest=None,
                dataset_id="test_espn_worldcup_prematch_scrape",
                limit=0,
                cutoff_hours=6.0,
                resolution_delay_minutes=135,
            )
            scrape_dir = Path(tmp) / "mexico_south_africa"
            scrape_dir.mkdir()
            (scrape_dir / "prematch_documents.json").write_text(
                json.dumps(
                    {
                        "created_at_utc": "2026-06-22T20:00:00+00:00",
                        "match": {
                            "home_team": "Mexico",
                            "away_team": "South Africa",
                            "kickoff_utc": "2026-06-11T19:00:00Z",
                            "prediction_cutoff_utc": "2026-06-11T13:00:00Z",
                        },
                        "summary": {"usable": 1, "rejected": 0},
                    }
                ),
                encoding="utf-8",
            )
            (scrape_dir / "prematch_kg_source.json").write_text(
                json.dumps(
                    {
                        "findings": [
                            {
                                "finding_id": "prematch_news_scrape:mexico_vs_south_africa",
                                "scout_name": "prematch_news_scrape_scout",
                                "access_level": "public",
                                "source_type": "mixed_media_social",
                                "finding_name": "prematch_media_social_documents",
                                "home_probability": 0.51,
                                "confidence": 0.52,
                                "summary": "One pre-cutoff document.",
                                "citations": ["https://example.test/preview"],
                                "evidence_claims": [
                                    {
                                        "claim_type": "prematch_media_signal",
                                        "claim": "Mexico vs South Africa preview",
                                        "source_kind": "news",
                                        "source_quality": "medium",
                                        "source_url": "https://example.test/preview",
                                        "available_at_utc": "2026-06-10T12:00:00Z",
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            payload = attach_prematch_scrape_evidence(payload, sources=[scrape_dir])

            dataset = BenchmarkDataset.from_dict(payload)
            validate_benchmark_dataset(dataset)
            event = payload["events"][0]
            prematch_items = [
                item for item in event["evidence_items"] if item["evidence_id"].startswith("prematch_scrape_")
            ]
            self.assertEqual(len(prematch_items), 1)
            self.assertEqual(prematch_items[0]["source_type"], "news")
            self.assertLessEqual(prematch_items[0]["available_at_utc"], event["prediction_cutoff_utc"])
            self.assertEqual(len(prematch_items[0]["evidence_claims"]), 1)


def _write_openfootball_fixture(root: Path) -> Path:
    path = root / "worldcup_2026.json"
    path.write_text(
        json.dumps(
            {
                "matches": [
                    _openfootball_match(
                        date="2026-06-11",
                        time="13:00 UTC-6",
                        team1="Mexico",
                        team2="South Africa",
                        score=[2, 0],
                        ground="Mexico City",
                        group="Group A",
                    ),
                    _openfootball_match(
                        date="2026-06-11",
                        time="20:00 UTC-6",
                        team1="South Korea",
                        team2="Czechia",
                        score=[2, 1],
                        ground="Guadalajara",
                        group="Group A",
                    ),
                    _openfootball_match(
                        date="2026-06-12",
                        time="15:00 UTC-4",
                        team1="Canada",
                        team2="Bosnia & Herzegovina",
                        score=[1, 1],
                        ground="Toronto",
                        group="Group B",
                    ),
                    _openfootball_match(
                        date="2026-06-12",
                        time="19:00 UTC-4",
                        team1="Spain",
                        team2="Japan",
                        score=[3, 2],
                        ground="Boston",
                        group="Group C",
                    ),
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def _openfootball_match(
    *,
    date: str,
    time: str,
    team1: str,
    team2: str,
    score: list[int],
    ground: str,
    group: str,
) -> dict:
    return {
        "date": date,
        "time": time,
        "team1": team1,
        "team2": team2,
        "score": {"ft": score, "ht": [0, 0]},
        "ground": ground,
        "group": group,
        "round": "Matchday Test",
    }


def _minimal_espn_snapshot() -> dict:
    return {
        "collected_at_utc": "2026-06-22T19:00:22+00:00",
        "scoreboard": {
            "events": [
                {
                    "id": "760415",
                    "date": "2026-06-11T19:00Z",
                    "name": "South Africa at Mexico",
                    "status": {"type": {"completed": True, "description": "Full Time"}},
                    "competitions": [
                        {
                            "date": "2026-06-11T19:00Z",
                            "venue": {"fullName": "Estadio Banorte"},
                            "competitors": [
                                {
                                    "homeAway": "home",
                                    "score": "2",
                                    "team": {"displayName": "Mexico"},
                                },
                                {
                                    "homeAway": "away",
                                    "score": "0",
                                    "team": {"displayName": "South Africa"},
                                },
                            ],
                        }
                    ],
                }
            ]
        },
        "event_summaries": [
            {
                "event_id": "760415",
                "status": "ok",
                "payload": {
                    "odds": [
                        {
                            "provider": {"name": "DraftKings"},
                            "moneyline": {
                                "home": {"open": {"odds": "-170"}, "close": {"odds": "-230"}},
                                "draw": {"open": {"odds": "+295"}, "close": {"odds": "+330"}},
                                "away": {"open": {"odds": "+500"}, "close": {"odds": "+750"}},
                            },
                        }
                    ]
                },
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
