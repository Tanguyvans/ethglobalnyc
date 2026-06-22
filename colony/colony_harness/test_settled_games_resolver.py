"""Tests for resolving prematch scrapes with final scores."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from colony.resolve_settled_games import (
    discover_prematch_documents,
    load_prematch_matches,
    resolve_settled_games,
)


class SettledGamesResolverTests(unittest.TestCase):
    def test_resolves_completed_espn_event_without_touching_prematch_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _write_prematch_documents(
                root,
                home_team="Mexico",
                away_team="South Africa",
                kickoff_utc="2026-06-11T19:00:00Z",
            )
            before = source.read_text(encoding="utf-8")

            matches = load_prematch_matches(discover_prematch_documents(prematch_root=root))
            payload = resolve_settled_games(
                prematch_matches=matches,
                espn_snapshot=_espn_snapshot(
                    home_team="Mexico",
                    away_team="South Africa",
                    completed=True,
                    home_score=2,
                    away_score=0,
                ),
                espn_source={"collected_at_utc": "2026-06-22T19:00:22Z"},
                created_at_utc="2026-06-22T19:00:22Z",
            )

            self.assertEqual(source.read_text(encoding="utf-8"), before)
            self.assertEqual(payload["summary"]["settled"], 1)
            self.assertEqual(payload["summary"]["pending"], 0)
            self.assertEqual(payload["summary"]["unmatched"], 0)
            row = payload["settled_games"][0]
            self.assertEqual(row["score"], "2-0")
            self.assertEqual(row["result_side"], "home")
            self.assertEqual(row["available_at_utc"], "2026-06-11T21:15:00Z")
            self.assertEqual(row["source_event_orientation"], "normal")

    def test_marks_matched_event_pending_when_score_is_not_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_prematch_documents(
                root,
                home_team="England",
                away_team="Ghana",
                kickoff_utc="2026-06-23T19:00:00Z",
            )

            matches = load_prematch_matches(discover_prematch_documents(prematch_root=root))
            payload = resolve_settled_games(
                prematch_matches=matches,
                espn_snapshot=_espn_snapshot(
                    home_team="England",
                    away_team="Ghana",
                    kickoff_utc="2026-06-23T19:00Z",
                    completed=False,
                    home_score=0,
                    away_score=0,
                ),
                espn_source={"collected_at_utc": "2026-06-23T19:10:00Z"},
                created_at_utc="2026-06-23T19:10:00Z",
            )

            self.assertEqual(payload["summary"]["settled"], 0)
            self.assertEqual(payload["summary"]["pending"], 1)
            row = payload["pending_games"][0]
            self.assertEqual(row["reason"], "resolution_delay_not_elapsed")
            self.assertEqual(row["next_check_after_utc"], "2026-06-23T21:15:00Z")

    def test_reorders_score_when_espn_orientation_is_reversed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_prematch_documents(
                root,
                home_team="South Africa",
                away_team="Mexico",
                kickoff_utc="2026-06-11T19:00:00Z",
            )

            matches = load_prematch_matches(discover_prematch_documents(prematch_root=root))
            payload = resolve_settled_games(
                prematch_matches=matches,
                espn_snapshot=_espn_snapshot(
                    home_team="Mexico",
                    away_team="South Africa",
                    completed=True,
                    home_score=2,
                    away_score=0,
                ),
                espn_source={"collected_at_utc": "2026-06-22T19:00:22Z"},
                created_at_utc="2026-06-22T19:00:22Z",
            )

            row = payload["settled_games"][0]
            self.assertEqual(row["score"], "0-2")
            self.assertEqual(row["result_side"], "away")
            self.assertEqual(row["source_event_orientation"], "reversed")

    def test_team_aliases_match_espn_display_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_prematch_documents(
                root,
                home_team="Colombia",
                away_team="DR Congo",
                kickoff_utc="2026-06-24T19:00:00Z",
            )

            matches = load_prematch_matches(discover_prematch_documents(prematch_root=root))
            payload = resolve_settled_games(
                prematch_matches=matches,
                espn_snapshot=_espn_snapshot(
                    home_team="Colombia",
                    away_team="Congo DR",
                    kickoff_utc="2026-06-24T19:00Z",
                    completed=True,
                    home_score=1,
                    away_score=1,
                ),
                espn_source={"collected_at_utc": "2026-06-24T23:00:00Z"},
                created_at_utc="2026-06-24T23:00:00Z",
            )

            self.assertEqual(payload["summary"]["settled"], 1)
            self.assertEqual(payload["settled_games"][0]["result_side"], "draw")

    def test_prefers_closest_kickoff_when_teams_match_multiple_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_prematch_documents(
                root,
                home_team="Portugal",
                away_team="Uzbekistan",
                kickoff_utc="2026-06-23T17:00:00Z",
            )

            matches = load_prematch_matches(discover_prematch_documents(prematch_root=root))
            snapshot = _espn_snapshot(
                home_team="Portugal",
                away_team="Uzbekistan",
                kickoff_utc="2026-06-23T15:30Z",
                completed=True,
                home_score=0,
                away_score=1,
                event_id="too_early",
            )
            snapshot["scoreboard"]["events"].append(
                _espn_event(
                    home_team="Portugal",
                    away_team="Uzbekistan",
                    kickoff_utc="2026-06-23T17:00Z",
                    completed=True,
                    home_score=3,
                    away_score=1,
                    event_id="exact",
                )
            )

            payload = resolve_settled_games(
                prematch_matches=matches,
                espn_snapshot=snapshot,
                espn_source={"collected_at_utc": "2026-06-23T22:00:00Z"},
                created_at_utc="2026-06-23T22:00:00Z",
            )

            row = payload["settled_games"][0]
            self.assertEqual(row["source_event_id"], "exact")
            self.assertEqual(row["score"], "3-1")


def _write_prematch_documents(
    root: Path,
    *,
    home_team: str,
    away_team: str,
    kickoff_utc: str,
) -> Path:
    scrape_dir = root / f"{home_team.lower().replace(' ', '_')}_vs_{away_team.lower().replace(' ', '_')}"
    normalized = scrape_dir / "normalized"
    normalized.mkdir(parents=True)
    path = normalized / "prematch_documents.json"
    path.write_text(
        json.dumps(
            {
                "created_at_utc": "2026-06-22T10:00:00Z",
                "match": {
                    "home_team": home_team,
                    "away_team": away_team,
                    "kickoff_utc": kickoff_utc,
                    "prediction_cutoff_utc": "2026-06-11T13:00:00Z",
                },
                "documents": [],
                "summary": {"usable": 7, "rejected": 2},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _espn_snapshot(
    *,
    home_team: str,
    away_team: str,
    kickoff_utc: str = "2026-06-11T19:00Z",
    completed: bool,
    home_score: int,
    away_score: int,
    event_id: str = "760415",
) -> dict:
    return {
        "collected_at_utc": "2026-06-22T19:00:22Z",
        "scoreboard": {
            "events": [
                _espn_event(
                    home_team=home_team,
                    away_team=away_team,
                    kickoff_utc=kickoff_utc,
                    completed=completed,
                    home_score=home_score,
                    away_score=away_score,
                    event_id=event_id,
                )
            ]
        },
    }


def _espn_event(
    *,
    home_team: str,
    away_team: str,
    kickoff_utc: str,
    completed: bool,
    home_score: int,
    away_score: int,
    event_id: str,
) -> dict:
    return {
        "id": event_id,
        "date": kickoff_utc,
        "name": f"{away_team} at {home_team}",
        "status": {
            "type": {
                "completed": completed,
                "description": "Full Time" if completed else "Scheduled",
            }
        },
        "competitions": [
            {
                "date": kickoff_utc,
                "competitors": [
                    {
                        "homeAway": "home",
                        "score": str(home_score),
                        "team": {"displayName": home_team},
                    },
                    {
                        "homeAway": "away",
                        "score": str(away_score),
                        "team": {"displayName": away_team},
                    },
                ],
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
