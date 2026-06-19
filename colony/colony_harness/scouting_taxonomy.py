"""Shared scouting topic taxonomy and re-scout recipes."""

from __future__ import annotations

SCOUTING_REQUIRED_CLAIM_TYPES = (
    "team_profile",
    "recent_form",
    "player_form",
    "key_players",
    "squad_roster",
    "injury_availability",
    "injury_return",
    "lineup",
    "match_history",
    "coach_form",
    "player_ratings",
    "attacking_profile",
    "defensive_profile",
    "tactical",
    "social_signal",
)

SCOUTING_FRESHNESS_REQUIRED_CLAIM_TYPES = (
    "injury_availability",
    "injury_return",
    "lineup",
    "social_signal",
)

SCOUTING_RESCOUT_RECIPES = {
    "team_profile": {
        "priority": 50,
        "recommended_scout": "team_profile_scout",
        "query_focus": "official team profile, federation profile, FIFA profile",
        "acceptance_criteria": [
            "source is official, reference, or strong news/stat source",
            "claim names the team explicitly",
        ],
    },
    "recent_form": {
        "priority": 70,
        "recommended_scout": "recent_form_scout",
        "query_focus": "recent fixtures, recent results, last matches, form table",
        "acceptance_criteria": [
            "source is stats, official, or strong news",
            "claim names the team and contains a concrete fixture, result, or form record",
        ],
    },
    "player_form": {
        "priority": 74,
        "recommended_scout": "player_form_scout",
        "query_focus": "key player season form, goals, assists, appearances, ratings",
        "acceptance_criteria": [
            "claim names a player tied to the team",
            "claim contains at least one concrete performance metric",
        ],
    },
    "key_players": {
        "priority": 76,
        "recommended_scout": "key_player_scout",
        "query_focus": "key players, star players, creators, finishers, defensive leaders, likely difference makers",
        "acceptance_criteria": [
            "claim names a player tied to the team",
            "claim explains why the player matters for this matchup",
        ],
    },
    "squad_roster": {
        "priority": 65,
        "recommended_scout": "squad_roster_scout",
        "query_focus": "current squad, official squad list, roster positions and clubs",
        "acceptance_criteria": [
            "source is official or reference-quality",
            "claim names a player and includes roster context such as position, club, caps, or goals",
        ],
    },
    "injury_availability": {
        "priority": 88,
        "recommended_scout": "availability_scout",
        "query_focus": "injury report, suspension, doubtful, ruled out, squad availability",
        "acceptance_criteria": [
            "source is dated or recent enough for match context",
            "claim contains an explicit availability status",
        ],
    },
    "injury_return": {
        "priority": 86,
        "recommended_scout": "availability_scout",
        "query_focus": "returning from injury, back in training, match fitness, minutes restriction",
        "acceptance_criteria": [
            "claim names a player tied to the team",
            "claim states the player returned, is back in training, or is being managed after injury",
        ],
    },
    "lineup": {
        "priority": 82,
        "recommended_scout": "squad_depth_scout",
        "query_focus": "predicted XI, lineup, squad depth, starting roles",
        "acceptance_criteria": [
            "source is match-specific",
            "claim contains lineup, role, or predicted-XI context rather than generic squad text",
        ],
    },
    "match_history": {
        "priority": 90,
        "recommended_scout": "match_history_scout",
        "query_focus": "head-to-head, previous meetings, team result archive, recent match history",
        "acceptance_criteria": [
            "claim names the team explicitly",
            "scorelines are admitted only when both teams and the score are explicit",
        ],
    },
    "coach_form": {
        "priority": 68,
        "recommended_scout": "coach_form_scout",
        "query_focus": "coach, manager, recent wins, losses, unbeaten streak, tactical changes under coach",
        "acceptance_criteria": [
            "claim names the team or coach explicitly",
            "claim contains a streak, recent record, or coach-specific tactical/status context",
        ],
    },
    "player_ratings": {
        "priority": 72,
        "recommended_scout": "player_rating_scout",
        "query_focus": "recent player ratings, match ratings, average rating, SofaScore, FotMob, WhoScored",
        "acceptance_criteria": [
            "claim names a player tied to the team",
            "claim contains a rating, player grade, or recent match-rating signal",
        ],
    },
    "attacking_profile": {
        "priority": 80,
        "recommended_scout": "attacking_profile_scout",
        "query_focus": "chance creation, xG, shots, goals for, attacking style, final-third threat",
        "acceptance_criteria": [
            "claim names the team explicitly",
            "claim contains attack metrics or concrete attacking style evidence",
        ],
    },
    "defensive_profile": {
        "priority": 80,
        "recommended_scout": "defensive_profile_scout",
        "query_focus": "defensive solidity, clean sheets, goals conceded, xGA, low block, pressing, defensive transitions",
        "acceptance_criteria": [
            "claim names the team explicitly",
            "claim contains defensive metrics or concrete defensive style evidence",
        ],
    },
    "tactical": {
        "priority": 78,
        "recommended_scout": "tactical_scout",
        "query_focus": "formation, pressing, transitions, set pieces, tactical matchup",
        "acceptance_criteria": [
            "claim names the team or matchup explicitly",
            "claim contains a formation, role, tactical phase, or matchup detail",
        ],
    },
    "social_signal": {
        "priority": 58,
        "recommended_scout": "social_signal_scout",
        "query_focus": "social sentiment, fan/journalist chatter, training reports, lineup leaks, injury rumors",
        "acceptance_criteria": [
            "claim is treated as low-confidence signal unless corroborated",
            "claim includes source/channel context and a concrete rumor/sentiment topic",
        ],
    },
}


def scouting_topic_quality(
    claim_type: str,
    *,
    claim_count: int,
    metric_claim_count: int = 0,
    player_count: int = 0,
    recent_30d_claim_count: int = 0,
    strong_or_official_claim_count: int = 0,
    claim_quality_counts: dict | None = None,
) -> tuple[str, list[str]]:
    """Return whether a topic has useful evidence for KG coverage."""

    if claim_count <= 0:
        return "missing", ["missing_claim"]

    qualities = claim_quality_counts or {}
    reasons: list[str] = []
    if claim_type in SCOUTING_REQUIRED_CLAIM_TYPES and strong_or_official_claim_count <= 0:
        reasons.append("needs_stronger_source")

    if claim_type == "recent_form":
        if metric_claim_count <= 0 and int(qualities.get("recent_results_window") or 0) <= 0:
            reasons.append("needs_recent_results_window")
    elif claim_type == "player_form":
        if player_count <= 0:
            reasons.append("needs_player")
        if metric_claim_count <= 0 and int(qualities.get("season_output") or 0) <= 0:
            reasons.append("needs_player_season_metric")
    elif claim_type == "key_players":
        if player_count <= 0:
            reasons.append("needs_key_player")
    elif claim_type == "squad_roster":
        if player_count <= 0:
            reasons.append("needs_roster_player")
    elif claim_type == "injury_availability":
        if int(qualities.get("availability_status") or 0) <= 0:
            reasons.append("needs_availability_status")
        if recent_30d_claim_count <= 0:
            reasons.append("needs_recent_source")
    elif claim_type == "injury_return":
        if player_count <= 0:
            reasons.append("needs_returning_player")
        if recent_30d_claim_count <= 0:
            reasons.append("needs_recent_source")
    elif claim_type == "lineup":
        if (
            metric_claim_count <= 0
            and int(qualities.get("formation_signal") or 0) <= 0
            and int(qualities.get("lineup_signal") or 0) <= 0
        ):
            reasons.append("needs_lineup_or_role_signal")
        if recent_30d_claim_count <= 0:
            reasons.append("needs_recent_source")
    elif claim_type == "match_history":
        if (
            metric_claim_count <= 0
            and int(qualities.get("explicit_score") or 0) <= 0
            and int(qualities.get("h2h_record") or 0) <= 0
        ):
            reasons.append("needs_match_history_metric")
    elif claim_type == "coach_form":
        if metric_claim_count <= 0 and int(qualities.get("recent_results_window") or 0) <= 0:
            reasons.append("needs_coach_record_or_streak")
    elif claim_type == "player_ratings":
        if player_count <= 0:
            reasons.append("needs_player")
        if metric_claim_count <= 0:
            reasons.append("needs_rating_metric")
    elif claim_type == "attacking_profile":
        if metric_claim_count <= 0 and int(qualities.get("season_output") or 0) <= 0:
            reasons.append("needs_attack_metric")
    elif claim_type == "defensive_profile":
        if metric_claim_count <= 0 and int(qualities.get("recent_results_window") or 0) <= 0:
            reasons.append("needs_defense_metric")
    elif claim_type == "tactical":
        if metric_claim_count <= 0 and int(qualities.get("formation_signal") or 0) <= 0:
            reasons.append("needs_tactical_detail")
    elif claim_type == "social_signal":
        if recent_30d_claim_count <= 0:
            reasons.append("needs_recent_social_source")

    return ("needs_better_evidence", reasons) if reasons else ("usable", [])
