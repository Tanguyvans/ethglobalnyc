"""Tests for one-match pre-match scraping guards."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from colony.scrape_prematch_match import (
    MatchPilot,
    dedupe_documents,
    kg_claim_from_document,
    kg_source_payload,
    normalize_document,
    normalize_x_search_result,
    parse_utc,
    scrapecreators_x_queries,
)


class PrematchScraperTests(unittest.TestCase):
    def test_pre_match_document_is_usable(self) -> None:
        pilot = MatchPilot(
            home_team="Mexico",
            away_team="South Africa",
            kickoff_utc=parse_utc("2026-06-11T19:00:00Z"),
            cutoff_utc=parse_utc("2026-06-11T13:00:00Z"),
        )

        document = normalize_document(
            source_name="ESPN",
            source_type="news",
            adapter="test",
            title="Mexico vs. South Africa - Kick-off time, team news, how to watch FIFA World Cup opener",
            url="https://example.test/preview",
            snippet="",
            published_at=parse_utc("2026-06-10T12:00:00Z"),
            published_raw="2026-06-10T12:00:00Z",
            source_snapshot_id="test",
            source_url="https://example.test/rss",
            pilot=pilot,
            timestamp_precision="seen_datetime",
        )

        self.assertTrue(document["usable"])
        self.assertEqual(document["rejected_reasons"], [])
        self.assertEqual(document["published"], "2026-06-10T12:00:00Z")
        self.assertEqual(document["source_published"], "2026-06-10T12:00:00Z")

    def test_same_day_google_result_story_is_rejected(self) -> None:
        pilot = MatchPilot(
            home_team="Mexico",
            away_team="South Africa",
            kickoff_utc=parse_utc("2026-06-11T19:00:00Z"),
            cutoff_utc=parse_utc("2026-06-11T13:00:00Z"),
        )

        document = normalize_document(
            source_name="Example",
            source_type="news",
            adapter="google_news_rss",
            title="Mexico wins 2-0 over South Africa in opening match",
            url="https://example.test/result",
            snippet="",
            published_at=datetime(2026, 6, 11, 7, 0, tzinfo=timezone.utc),
            published_raw="Thu, 11 Jun 2026 07:00:00 GMT",
            source_snapshot_id="test",
            source_url="https://news.google.com/rss",
            pilot=pilot,
            timestamp_precision="date_level",
        )

        self.assertFalse(document["usable"])
        self.assertIn("same_day_date_level_timestamp", document["rejected_reasons"])
        self.assertIn("result_or_highlight_leak", document["rejected_reasons"])

    def test_two_team_names_without_match_context_is_rejected(self) -> None:
        pilot = MatchPilot(
            home_team="Mexico",
            away_team="South Africa",
            kickoff_utc=parse_utc("2026-06-11T19:00:00Z"),
            cutoff_utc=parse_utc("2026-06-11T13:00:00Z"),
        )

        document = normalize_document(
            source_name="@radio",
            source_type="social",
            adapter="test",
            title="Jamaica has named a 22-man squad for its friendly against South Africa in Mexico",
            url="https://x.com/radio/status/2062624378316005824",
            snippet="The friendly is scheduled for Saturday.",
            published_at=parse_utc("2026-06-04T19:55:48Z"),
            published_raw="",
            source_snapshot_id="test",
            source_url="https://api.scrapecreators.test/search",
            pilot=pilot,
            timestamp_precision="x_snowflake",
        )

        self.assertFalse(document["usable"])
        self.assertIn("missing_match_context", document["rejected_reasons"])

    def test_x_status_id_provides_exact_timestamp(self) -> None:
        pilot = MatchPilot(
            home_team="Mexico",
            away_team="South Africa",
            kickoff_utc=parse_utc("2026-06-11T19:00:00Z"),
            cutoff_utc=parse_utc("2026-06-11T13:00:00Z"),
        )

        document = normalize_x_search_result(
            {
                "title": "No Gilberto Mora in Mexico's XI, Fidalgo instead",
                "url": "https://x.com/herculezg/status/2062707986183733435",
                "description": "This could be Mexico's starting lineup against South Africa.",
            },
            source_id="test",
            source_url="https://api.scrapecreators.test/search",
            pilot=pilot,
        )

        self.assertTrue(document["usable"])
        self.assertEqual(document["timestamp_precision"], "x_snowflake")
        self.assertEqual(document["published_at_utc"], "2026-06-05T01:28:01Z")

    def test_prediction_language_does_not_look_like_result_leak(self) -> None:
        pilot = MatchPilot(
            home_team="Mexico",
            away_team="South Africa",
            kickoff_utc=parse_utc("2026-06-11T19:00:00Z"),
            cutoff_utc=parse_utc("2026-06-11T13:00:00Z"),
        )

        document = normalize_document(
            source_name="@analyst",
            source_type="social",
            adapter="test",
            title="Mexico wins 2-1 prediction vs South Africa",
            url="https://x.com/analyst/status/2062707986183733435",
            snippet="World Cup opener pick before kickoff.",
            published_at=parse_utc("2026-06-05T01:28:01Z"),
            published_raw="",
            source_snapshot_id="test",
            source_url="https://api.scrapecreators.test/search",
            pilot=pilot,
            timestamp_precision="x_snowflake",
        )

        self.assertTrue(document["usable"])
        self.assertEqual(document["signal_type"], "prediction_or_market")

    def test_dedupe_prefers_usable_exact_timestamp(self) -> None:
        stale = {
            "url": "https://x.com/example/status/2062707986183733435?utm=test",
            "usable": False,
            "timestamp_precision": "date_level",
            "available_at_utc": "",
        }
        exact = {
            "url": "https://x.com/example/status/2062707986183733435",
            "usable": True,
            "timestamp_precision": "x_snowflake",
            "available_at_utc": "2026-06-05T01:28:01Z",
        }

        documents, duplicate_count = dedupe_documents([stale, exact])

        self.assertEqual(duplicate_count, 1)
        self.assertEqual(len(documents), 1)
        self.assertTrue(documents[0]["usable"])

    def test_news_document_claim_is_not_social_signal(self) -> None:
        document = {
            "title": "Mexico vs. South Africa preview",
            "source_type": "news",
            "signal_type": "media_preview",
            "source_name": "Example News",
            "url": "https://example.test/preview",
            "sentiment": {"home_minus_away": 0.0},
        }

        claim = kg_claim_from_document(
            document,
            match={"home_team": "Mexico", "away_team": "South Africa"},
        )

        self.assertEqual(claim["claim_type"], "prematch_media_signal")
        self.assertEqual(claim["source_kind"], "news")

    def test_kg_source_does_not_invent_probability_from_title_sentiment(self) -> None:
        payload = {
            "match": {
                "home_team": "Mexico",
                "away_team": "South Africa",
            },
            "documents": [
                {
                    "title": "Mexico vs South Africa prediction",
                    "source_type": "news",
                    "signal_type": "prediction_or_market",
                    "source_name": "Example",
                    "url": "https://example.test/preview",
                    "sentiment": {"home_minus_away": 0.4},
                }
            ],
        }

        kg_payload = kg_source_payload(payload)
        finding = kg_payload["findings"][0]

        self.assertIsNone(finding["home_probability"])
        self.assertEqual(finding["confidence"], 0.5)

    def test_x_query_pack_contains_multiple_signal_families(self) -> None:
        pilot = MatchPilot(
            home_team="Mexico",
            away_team="South Africa",
            kickoff_utc=parse_utc("2026-06-11T19:00:00Z"),
            cutoff_utc=parse_utc("2026-06-11T13:00:00Z"),
        )

        queries = scrapecreators_x_queries(pilot=pilot, start_utc=parse_utc("2026-06-01T00:00:00Z"))
        combined = "\n".join(queries)

        self.assertGreaterEqual(len(queries), 8)
        self.assertIn("lineup", combined)
        self.assertIn("injury", combined)
        self.assertIn("odds", combined)
        self.assertNotIn("MEXRSA", combined)
        self.assertNotIn("Sudáfrica", combined)


if __name__ == "__main__":
    unittest.main()
