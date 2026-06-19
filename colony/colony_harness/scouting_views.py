"""Agent-ready scouting artifact views.

These helpers project the full scouting KG into compact domain and workflow
views without changing the underlying graph builder.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .models import Finding, MatchContext, WorldEntity, WorldGraph
from .world_graph import KG_SCHEMA_VERSION


DOMAIN_GRAPH_ENTITY_TYPES = frozenset(
    {
        "match",
        "team",
        "team_match_profile",
        "player",
        "player_match_profile",
        "player_stat_line",
        "availability_event",
        "availability_status",
        "club",
        "position",
        "formation",
        "match_result",
        "venue",
        "group",
        "stage",
    }
)

KNOWLEDGE_VIEW_NAMES = (
    "team_snapshot",
    "player_watchlist",
    "availability_board",
    "scouting_gaps",
    "source_quality_summary",
)


def build_domain_graph_payload(graph: WorldGraph) -> dict[str, Any]:
    """Return a strict domain-only subgraph from the full scouting KG."""

    entities = [
        entity.to_dict()
        for entity in graph.entities
        if entity.entity_type in DOMAIN_GRAPH_ENTITY_TYPES
    ]
    entity_ids = {str(entity["entity_id"]) for entity in entities}
    relationships = [
        relationship.to_dict()
        for relationship in graph.relationships
        if relationship.source_id in entity_ids and relationship.target_id in entity_ids
    ]
    entity_counts = Counter(str(entity["entity_type"]) for entity in entities)
    relationship_counts = Counter(str(relationship["relation_type"]) for relationship in relationships)
    return {
        "schema_version": KG_SCHEMA_VERSION,
        "graph_id": f"domain_graph:{graph.round_id}",
        "source_graph_id": graph.graph_id,
        "round_id": graph.round_id,
        "filter": {
            "entity_types": sorted(DOMAIN_GRAPH_ENTITY_TYPES),
            "relationship_policy": "keep_only_edges_with_domain_endpoints",
        },
        "entity_count": len(entities),
        "relationship_count": len(relationships),
        "entity_counts": dict(sorted(entity_counts.items())),
        "relationship_counts": dict(sorted(relationship_counts.items())),
        "entities": entities,
        "relationships": relationships,
    }


def build_knowledge_views_payload(
    *,
    match: MatchContext,
    findings: list[Finding],
    graph: WorldGraph,
    source_summaries: list[dict[str, Any]],
    scout_targets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build stable, domain-first JSON views for downstream scouting agents."""

    entities_by_type = _entities_by_type(graph)
    claims = [claim for finding in findings for claim in finding.evidence_claims]
    team_topics = _team_topics(entities_by_type.get("team_scouting_topic", []))
    player_watchlist = _player_watchlist(entities_by_type)
    availability_board = _availability_board(entities_by_type)
    scouting_gaps = _scouting_gaps(entities_by_type.get("scouting_gap", []))
    return {
        "schema_version": KG_SCHEMA_VERSION,
        "round_id": match.round_id,
        "view_model": "agent_ready_scouting_views_v1",
        "view_names": list(KNOWLEDGE_VIEW_NAMES),
        "team_snapshot": _team_snapshot(match, entities_by_type, team_topics),
        "player_watchlist": player_watchlist,
        "availability_board": availability_board,
        "scouting_gaps": scouting_gaps,
        "source_quality_summary": _source_quality_summary(
            claims=claims,
            entities_by_type=entities_by_type,
            source_summaries=source_summaries,
            scout_targets=scout_targets,
        ),
    }


def build_scouting_run_summary_payload(
    *,
    mode: str,
    match: MatchContext,
    findings: list[Finding],
    graph: WorldGraph,
    source_summaries: list[dict[str, Any]],
    scout_targets: list[dict[str, Any]],
    manifest: dict[str, Any],
    validation: dict[str, Any],
    category_summary: dict[str, Any],
    domain_graph: dict[str, Any],
    knowledge_views: dict[str, Any],
) -> dict[str, Any]:
    """Summarize a local scouting KG export for agent handoff."""

    claims = [claim for finding in findings for claim in finding.evidence_claims]
    readiness = dict(manifest.get("readiness") or {})
    view_counts = {
        "team_snapshot_teams": len(
            (knowledge_views.get("team_snapshot") or {}).get("teams") or []
        ),
        "player_watchlist": len(knowledge_views.get("player_watchlist") or []),
        "availability_events": len(
            (knowledge_views.get("availability_board") or {}).get("events") or []
        ),
        "availability_players": len(
            (knowledge_views.get("availability_board") or {}).get("players") or []
        ),
        "scouting_gaps": len(knowledge_views.get("scouting_gaps") or []),
        "source_domains": len(
            (knowledge_views.get("source_quality_summary") or {}).get("top_domains") or []
        ),
    }
    return {
        "schema_version": KG_SCHEMA_VERSION,
        "round_id": match.round_id,
        "mode": mode,
        "kg_load_ready": bool(readiness.get("kg_load_ready")),
        "agent_ready": {
            "artifact_files": [
                "domain_graph.json",
                "knowledge_views.json",
                "scouting_run_summary.json",
            ],
            "view_names": list(knowledge_views.get("view_names") or []),
            "domain_entity_types": list(
                (domain_graph.get("filter") or {}).get("entity_types") or []
            ),
        },
        "match": _match_payload(match),
        "artifact_files": dict(manifest.get("files") or {}),
        "run_counts": {
            "findings": len(findings),
            "evidence_claims": len(claims),
            "sources": len(source_summaries),
            "scout_targets": len(scout_targets),
        },
        "full_graph": {
            "graph_id": graph.graph_id,
            "entity_count": len(graph.entities),
            "relationship_count": len(graph.relationships),
            "entity_counts": dict(
                sorted(Counter(entity.entity_type for entity in graph.entities).items())
            ),
        },
        "domain_graph": {
            "graph_id": domain_graph.get("graph_id"),
            "entity_count": domain_graph.get("entity_count", 0),
            "relationship_count": domain_graph.get("relationship_count", 0),
            "entity_counts": dict(domain_graph.get("entity_counts") or {}),
            "filter": dict(domain_graph.get("filter") or {}),
        },
        "knowledge_views": {
            "view_model": knowledge_views.get("view_model"),
            "view_names": list(knowledge_views.get("view_names") or []),
            "counts": view_counts,
        },
        "readiness": readiness,
        "validation": dict(validation or {}),
        "categories": {
            "category_names": sorted((category_summary.get("categories") or {}).keys()),
            "entity_counts": dict(category_summary.get("entity_counts") or {}),
        },
        "source_summaries": source_summaries,
        "scout_targets": scout_targets,
    }


def _entities_by_type(graph: WorldGraph) -> dict[str, list[WorldEntity]]:
    rows: dict[str, list[WorldEntity]] = defaultdict(list)
    for entity in graph.entities:
        rows[entity.entity_type].append(entity)
    return rows


def _team_snapshot(
    match: MatchContext,
    entities_by_type: dict[str, list[WorldEntity]],
    team_topics: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    team_entities = {entity.name: entity for entity in entities_by_type.get("team", [])}
    profiles = {
        str(entity.attributes.get("team") or entity.name): entity
        for entity in entities_by_type.get("team_match_profile", [])
    }
    teams = []
    for team_name, side in ((match.home_team, "home"), (match.away_team, "away")):
        profile = profiles.get(team_name)
        team_entity = team_entities.get(team_name)
        attrs = dict(profile.attributes) if profile else {}
        topics = team_topics.get(team_name) or {}
        teams.append(
            {
                "team": team_name,
                "side": attrs.get("side") or side,
                "entity_id": team_entity.entity_id if team_entity else f"team:{_slug(team_name)}",
                "profile_entity_id": profile.entity_id if profile else "",
                "claim_count": int(attrs.get("claim_count") or 0),
                "player_count": int(attrs.get("player_count") or 0),
                "players": list(attrs.get("players") or []),
                "formations": list(attrs.get("formations") or []),
                "clubs": list(attrs.get("clubs") or []),
                "positions": list(attrs.get("positions") or []),
                "availability_status_counts": dict(attrs.get("availability_status_counts") or {}),
                "recent_form_summary": dict(attrs.get("recent_form_summary") or {}),
                "match_history_summary": dict(attrs.get("match_history_summary") or {}),
                "covered_required_claim_types": list(topics.get("covered_required_claim_types") or []),
                "missing_required_claim_types": list(topics.get("missing_required_claim_types") or []),
                "highest_confidence": attrs.get("highest_confidence", 0.0),
            }
        )
    return {
        "match": _match_payload(match),
        "teams": teams,
    }


def _player_watchlist(entities_by_type: dict[str, list[WorldEntity]]) -> list[dict[str, Any]]:
    rows = []
    for entity in entities_by_type.get("player_match_profile", []):
        attrs = dict(entity.attributes)
        row = {
            "entity_id": entity.entity_id,
            "player": attrs.get("player") or entity.name.replace(" match profile", ""),
            "team": attrs.get("team", ""),
            "claim_count": int(attrs.get("claim_count") or 0),
            "claim_types": dict(attrs.get("claim_types") or {}),
            "metric_keys": dict(attrs.get("metric_keys") or {}),
            "clubs": list(attrs.get("clubs") or []),
            "positions": list(attrs.get("positions") or []),
            "availability_statuses": list(attrs.get("availability_statuses") or []),
            "availability_status_counts": dict(attrs.get("availability_status_counts") or {}),
            "performance_summary": dict(attrs.get("performance_summary") or {}),
            "highest_confidence": attrs.get("highest_confidence", 0.0),
        }
        row["priority_score"] = _player_priority(row)
        rows.append(row)
    if not rows:
        for entity in entities_by_type.get("player", []):
            attrs = dict(entity.attributes)
            rows.append(
                {
                    "entity_id": entity.entity_id,
                    "player": entity.name,
                    "team": attrs.get("team", ""),
                    "claim_count": 0,
                    "claim_types": {},
                    "metric_keys": {},
                    "clubs": [],
                    "positions": [],
                    "availability_statuses": [],
                    "availability_status_counts": {},
                    "performance_summary": {},
                    "highest_confidence": 0.0,
                    "priority_score": 0.0,
                }
            )
    rows.sort(
        key=lambda row: (
            -float(row.get("priority_score") or 0.0),
            str(row.get("team") or ""),
            str(row.get("player") or ""),
        )
    )
    return rows[:40]


def _availability_board(entities_by_type: dict[str, list[WorldEntity]]) -> dict[str, Any]:
    events = []
    status_counts: Counter[str] = Counter()
    for entity in entities_by_type.get("availability_event", []):
        attrs = dict(entity.attributes)
        status = str(attrs.get("availability_status") or attrs.get("status") or "")
        if status:
            status_counts[status] += 1
        events.append(
            {
                "entity_id": entity.entity_id,
                "name": entity.name,
                "team": attrs.get("team", ""),
                "player": attrs.get("player", ""),
                "status": status,
                "body_part": attrs.get("body_part", ""),
                "claim_type": attrs.get("claim_type", ""),
                "confidence": attrs.get("confidence"),
            }
        )
    players = []
    for entity in entities_by_type.get("player_match_profile", []):
        attrs = dict(entity.attributes)
        statuses = list(attrs.get("availability_statuses") or [])
        counts = dict(attrs.get("availability_status_counts") or {})
        if not statuses and not counts:
            continue
        status_counts.update({str(key): int(value) for key, value in counts.items()})
        players.append(
            {
                "player": attrs.get("player") or entity.name.replace(" match profile", ""),
                "team": attrs.get("team", ""),
                "statuses": statuses,
                "status_counts": counts,
                "injury_body_parts": list(attrs.get("injury_body_parts") or []),
                "profile_entity_id": entity.entity_id,
            }
        )
    team_status_counts = {
        str(entity.attributes.get("team") or entity.name): dict(
            entity.attributes.get("availability_status_counts") or {}
        )
        for entity in entities_by_type.get("team_match_profile", [])
        if entity.attributes.get("availability_status_counts")
    }
    return {
        "status_counts": dict(sorted(status_counts.items())),
        "team_status_counts": team_status_counts,
        "events": sorted(
            events,
            key=lambda row: (
                str(row.get("team") or ""),
                str(row.get("player") or ""),
                str(row.get("status") or ""),
            ),
        )[:80],
        "players": sorted(players, key=lambda row: (str(row.get("team") or ""), str(row.get("player") or "")))[:80],
    }


def _scouting_gaps(gap_entities: list[WorldEntity]) -> list[dict[str, Any]]:
    rows = []
    for entity in gap_entities:
        attrs = dict(entity.attributes)
        rows.append(
            {
                "entity_id": entity.entity_id,
                "team": attrs.get("team", ""),
                "side": attrs.get("side", ""),
                "claim_type": attrs.get("claim_type", ""),
                "status": attrs.get("status", ""),
                "gap_reason": attrs.get("gap_reason", ""),
                "quality_status": attrs.get("quality_status", ""),
                "quality_reasons": list(attrs.get("quality_reasons") or []),
                "priority": int(attrs.get("priority") or 0),
                "recommended_scout": attrs.get("recommended_scout", ""),
                "query_focus": attrs.get("query_focus", ""),
                "target_entity_id": attrs.get("target_entity_id", ""),
                "acceptance_criteria": list(attrs.get("acceptance_criteria") or []),
            }
        )
    rows.sort(
        key=lambda row: (
            -int(row.get("priority") or 0),
            str(row.get("team") or ""),
            str(row.get("claim_type") or ""),
        )
    )
    return rows


def _source_quality_summary(
    *,
    claims: list[dict[str, Any]],
    entities_by_type: dict[str, list[WorldEntity]],
    source_summaries: list[dict[str, Any]],
    scout_targets: list[dict[str, Any]],
) -> dict[str, Any]:
    domain_profiles = []
    for entity in entities_by_type.get("source_domain_profile", []):
        attrs = dict(entity.attributes)
        domain_profiles.append(
            {
                "entity_id": entity.entity_id,
                "domain": attrs.get("domain") or entity.name.replace(" source profile", ""),
                "claim_count": int(attrs.get("claim_count") or 0),
                "claim_types": dict(attrs.get("claim_types") or {}),
                "teams": list(attrs.get("teams") or []),
                "players": list(attrs.get("players") or []),
                "unique_source_count": int(attrs.get("unique_source_count") or 0),
                "source_quality": dict(attrs.get("source_quality") or {}),
                "source_kind": dict(attrs.get("source_kind") or {}),
                "source_recency": dict(attrs.get("source_recency") or {}),
                "highest_confidence": attrs.get("highest_confidence", 0.0),
            }
        )
    source_quality = Counter(str(claim.get("source_quality") or "") for claim in claims if claim.get("source_quality"))
    source_kind = Counter(str(claim.get("source_kind") or "") for claim in claims if claim.get("source_kind"))
    source_recency = Counter(
        str(claim.get("source_recency_bucket") or "")
        for claim in claims
        if claim.get("source_recency_bucket")
    )
    return {
        "evidence_claim_count": len(claims),
        "source_count": len(entities_by_type.get("source", [])),
        "source_domain_count": len(entities_by_type.get("source_domain", [])),
        "source_quality_counts": dict(sorted(source_quality.items())),
        "source_kind_counts": dict(sorted(source_kind.items())),
        "source_recency_counts": dict(sorted(source_recency.items())),
        "strong_or_official_claim_count": sum(
            1
            for claim in claims
            if claim.get("source_quality") == "strong"
            or claim.get("source_kind") in {"official", "stats", "news", "reference"}
        ),
        "weak_claim_count": sum(1 for claim in claims if claim.get("source_quality") == "weak"),
        "top_domains": sorted(domain_profiles, key=lambda row: (-int(row["claim_count"]), str(row["domain"])))[:20],
        "source_runs": source_summaries,
        "scout_targets": scout_targets,
    }


def _team_topics(team_topic_entities: list[WorldEntity]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "covered_required_claim_types": [],
            "missing_required_claim_types": [],
        }
    )
    for entity in team_topic_entities:
        attrs = entity.attributes
        team = str(attrs.get("team") or "")
        claim_type = str(attrs.get("claim_type") or "")
        if not team or not claim_type or not attrs.get("required"):
            continue
        if attrs.get("coverage_status") == "covered":
            rows[team]["covered_required_claim_types"].append(claim_type)
        else:
            rows[team]["missing_required_claim_types"].append(claim_type)
    for row in rows.values():
        row["covered_required_claim_types"] = sorted(set(row["covered_required_claim_types"]))
        row["missing_required_claim_types"] = sorted(set(row["missing_required_claim_types"]))
    return rows


def _match_payload(match: MatchContext) -> dict[str, Any]:
    return {
        "round_id": match.round_id,
        "home_team": match.home_team,
        "away_team": match.away_team,
        "date": match.match_date,
        "time": match.match_time,
        "group": match.group_name,
        "stage": match.stage_name,
        "venue": match.venue_name,
        "score": match.score,
        "market_home_probability": match.market_home_probability,
    }


def _player_priority(row: dict[str, Any]) -> float:
    claim_count = int(row.get("claim_count") or 0)
    confidence = float(row.get("highest_confidence") or 0.0)
    availability_bonus = 1.0 if row.get("availability_statuses") else 0.0
    metric_bonus = min(len(row.get("metric_keys") or {}), 6) * 0.1
    return round(confidence + claim_count * 0.2 + availability_bonus + metric_bonus, 4)


def _slug(value: str) -> str:
    cleaned = []
    for char in str(value).lower():
        if char.isalnum():
            cleaned.append(char)
        elif char in {" ", "-", "_", "/", ":"}:
            cleaned.append("_")
    return "_".join(part for part in "".join(cleaned).split("_") if part) or "unknown"
