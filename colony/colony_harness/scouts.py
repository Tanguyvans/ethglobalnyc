"""Mock scout findings for local Colony simulations."""

from __future__ import annotations

from .models import Finding


def mock_findings_from_config(data: dict) -> list[Finding]:
    """Build deterministic fake scout findings until real data sources are connected."""
    match = data["match"]
    round_id = data["round_id"]
    home_team = str(match["home_team"])
    away_team = str(match["away_team"])
    market = float(match["market_home_probability"])
    stats = float(match["stats_home_signal"])
    odds = float(match["odds_home_signal"])
    news = float(match["news_home_signal"])

    lineup = _clamp((stats + news) / 2.0 - 0.015)
    social = _clamp((market + news) / 2.0 + 0.01)
    weather = _clamp(market - 0.005)

    return [
        _finding(
            round_id=round_id,
            key="market",
            scout_name="market_baseline_scout",
            access_level="public",
            source_type="market",
            finding_name="market_home_probability",
            home_probability=market,
            market=market,
            confidence=0.8,
            summary=f"Consensus market baseline for {home_team} vs {away_team}.",
            citations=["mock://market/closing-consensus"],
        ),
        _finding(
            round_id=round_id,
            key="stats",
            scout_name="ratings_scout",
            access_level="public",
            source_type="stats",
            finding_name="stats_home_signal",
            home_probability=stats,
            market=market,
            confidence=0.65,
            summary=(
                "Synthetic ratings scout combining team strength, recent form, and venue adjustment. "
                "This is a placeholder for a real stats datasource."
            ),
            citations=["mock://stats/team-strength-index", "mock://stats/recent-form"],
        ),
        _finding(
            round_id=round_id,
            key="odds",
            scout_name="odds_scout",
            access_level="public",
            source_type="odds",
            finding_name="odds_home_signal",
            home_probability=odds,
            market=market,
            confidence=0.7,
            summary="Synthetic odds scout normalizing a second market view into home-win probability.",
            citations=["mock://odds/exchange-book", "mock://odds/bookmaker-consensus"],
        ),
        _finding(
            round_id=round_id,
            key="news",
            scout_name="news_scout",
            access_level="public",
            source_type="news",
            finding_name="news_home_signal",
            home_probability=news,
            market=market,
            confidence=0.55,
            summary="Synthetic news scout standing in for CAMEL retrieval or ScrapeCreators summaries.",
            citations=["mock://news/team-notes", "mock://news/press-roundup"],
        ),
        _finding(
            round_id=round_id,
            key="lineup",
            scout_name="lineup_scout",
            access_level="shared",
            source_type="lineup",
            finding_name="lineup_availability_read",
            home_probability=lineup,
            market=market,
            confidence=0.5,
            summary="Shared mock lineup read. It is logged but not yet access-controlled by predictor budgets.",
            citations=["mock://lineup/projected-xi"],
        ),
        _finding(
            round_id=round_id,
            key="social",
            scout_name="social_scout",
            access_level="shared",
            source_type="social",
            finding_name="public_sentiment_read",
            home_probability=social,
            market=market,
            confidence=0.42,
            summary="Shared mock social sentiment read. Useful later for debate pressure and noise testing.",
            citations=["mock://social/reddit-twitter-sample"],
        ),
        _finding(
            round_id=round_id,
            key="weather",
            scout_name="weather_scout",
            access_level="private",
            source_type="weather",
            finding_name="weather_disruption_read",
            home_probability=weather,
            market=market,
            confidence=0.35,
            cost=0.02,
            summary="Private mock weather read. This is a placeholder for paid scout data later.",
            citations=["mock://weather/matchday-forecast"],
        ),
    ]


def _finding(
    *,
    round_id: str,
    key: str,
    scout_name: str,
    access_level: str,
    source_type: str,
    finding_name: str,
    home_probability: float,
    market: float,
    confidence: float,
    summary: str,
    citations: list[str],
    cost: float = 0.0,
) -> Finding:
    return Finding(
        finding_id=f"{round_id}:{key}",
        scout_name=scout_name,
        access_level=access_level,  # type: ignore[arg-type]
        source_type=source_type,  # type: ignore[arg-type]
        finding_name=finding_name,
        home_probability=round(home_probability, 4),
        home_delta=round(home_probability - market, 4),
        confidence=confidence,
        cost=cost,
        citations=citations,
        summary=summary,
    )


def _clamp(value: float) -> float:
    return min(max(value, 0.01), 0.99)
