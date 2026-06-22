#!/usr/bin/env python3
"""Resolve finished World Cup prematch scrapes with post-match scores.

This module is deliberately separate from the pre-match KG pipeline. Prematch
artifacts keep the information that was available before kickoff; this resolver
adds the observed outcome later so benchmark runs can be scored without leaking
results into agent context.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:  # Script mode: python3 colony/resolve_settled_games.py
    from collect_benchmark_data import _fetch_espn_worldcup_snapshot
except ImportError:  # Package mode
    from colony.collect_benchmark_data import _fetch_espn_worldcup_snapshot


DEFAULT_PREMATCH_ROOT = Path("colony/runs/prematch_scrape")
DEFAULT_SETTLED_ROOT = Path("colony/runs/settled_games")
DEFAULT_RESOLUTION_DELAY_MINUTES = 135
DEFAULT_MATCH_TOLERANCE_MINUTES = 180


@dataclass(frozen=True)
class PrematchMatch:
    source_dir: Path
    documents_path: Path
    created_at_utc: str
    home_team: str
    away_team: str
    kickoff_utc: str
    prediction_cutoff_utc: str
    usable_documents: int
    rejected_documents: int


@dataclass(frozen=True)
class EventMatch:
    event: dict[str, Any]
    orientation: str
    score: int
    kickoff_delta_seconds: int | None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prematch-root",
        type=Path,
        default=DEFAULT_PREMATCH_ROOT,
        help="Root containing prematch scrape directories.",
    )
    parser.add_argument(
        "--prematch-source",
        action="append",
        type=Path,
        default=[],
        help="Specific prematch scrape directory or prematch_documents.json. Repeatable.",
    )
    parser.add_argument(
        "--espn-snapshot",
        type=Path,
        default=None,
        help="Existing ESPN World Cup scoreboard snapshot JSON. If omitted, ESPN is fetched.",
    )
    parser.add_argument(
        "--dates",
        default="",
        help="ESPN dates parameter, e.g. 20260611 or 20260611-20260624. Defaults to prematch date range.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output settled games JSON. Defaults to a timestamped directory under colony/runs/settled_games.",
    )
    parser.add_argument(
        "--resolution-delay-minutes",
        type=int,
        default=DEFAULT_RESOLUTION_DELAY_MINUTES,
        help="Estimated score availability after kickoff.",
    )
    parser.add_argument(
        "--match-tolerance-minutes",
        type=int,
        default=DEFAULT_MATCH_TOLERANCE_MINUTES,
        help="Allowed kickoff timestamp drift when matching prematch records to ESPN events.",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Do not write a Markdown summary next to the JSON output.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    output_path = args.out or _default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    document_paths = discover_prematch_documents(
        prematch_root=args.prematch_root,
        sources=args.prematch_source,
    )
    prematch_matches = load_prematch_matches(document_paths)
    collected_at = _utc_now()

    if args.espn_snapshot is not None:
        snapshot_bytes = args.espn_snapshot.read_bytes()
        espn_snapshot = json.loads(snapshot_bytes.decode("utf-8"))
        espn_source = {
            "source_name": "espn_worldcup_scoreboard",
            "source_type": "fixture_results",
            "file": str(args.espn_snapshot),
            "sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
            "collected_at_utc": str(espn_snapshot.get("collected_at_utc") or collected_at),
            "fetch_mode": "local_snapshot",
        }
    else:
        dates = args.dates.strip() or infer_espn_dates(prematch_matches)
        snapshot_bytes, metadata = _fetch_espn_worldcup_snapshot(dates=dates, collected_at=collected_at)
        raw_dir = output_path.parent / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / f"espn_worldcup_scoreboard_{_slug(dates)}.json"
        raw_path.write_bytes(snapshot_bytes)
        espn_snapshot = json.loads(snapshot_bytes.decode("utf-8"))
        espn_source = {
            "source_name": "espn_worldcup_scoreboard",
            "source_type": "fixture_results",
            "file": str(raw_path),
            "sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
            "collected_at_utc": collected_at,
            "fetch_mode": "live_fetch",
            "dates": dates,
            **metadata,
        }

    payload = resolve_settled_games(
        prematch_matches=prematch_matches,
        espn_snapshot=espn_snapshot,
        espn_source=espn_source,
        created_at_utc=collected_at,
        resolution_delay_minutes=args.resolution_delay_minutes,
        match_tolerance_minutes=args.match_tolerance_minutes,
    )
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not args.no_report:
        report_path = output_path.with_suffix(".md")
        report_path.write_text(render_report(payload), encoding="utf-8")
    print(f"Settled games written: {output_path}")
    print(
        "Summary: "
        f"{payload['summary']['settled']} settled, "
        f"{payload['summary']['pending']} pending, "
        f"{payload['summary']['unmatched']} unmatched"
    )


def discover_prematch_documents(*, prematch_root: Path, sources: list[Path] | None = None) -> list[Path]:
    if sources:
        paths = [_prematch_documents_path(source) for source in sources]
        return _dedupe_paths(paths)

    by_source_dir: dict[Path, Path] = {}
    for path in sorted(prematch_root.rglob("prematch_documents.json")):
        source_dir = _prematch_source_dir(path)
        current = by_source_dir.get(source_dir)
        if current is None or path.parent.name == "normalized":
            by_source_dir[source_dir] = path
    return sorted(by_source_dir.values())


def load_prematch_matches(document_paths: list[Path]) -> list[PrematchMatch]:
    matches = [_load_prematch_match(path) for path in document_paths]
    matches.sort(key=lambda item: (item.kickoff_utc, item.home_team, item.away_team, str(item.documents_path)))
    return matches


def infer_espn_dates(prematch_matches: list[PrematchMatch]) -> str:
    if not prematch_matches:
        return datetime.now(timezone.utc).strftime("%Y%m%d")
    dates = sorted(_parse_utc(match.kickoff_utc).strftime("%Y%m%d") for match in prematch_matches)
    if dates[0] == dates[-1]:
        return dates[0]
    return f"{dates[0]}-{dates[-1]}"


def resolve_settled_games(
    *,
    prematch_matches: list[PrematchMatch],
    espn_snapshot: dict[str, Any],
    espn_source: dict[str, Any] | None = None,
    created_at_utc: str | None = None,
    resolution_delay_minutes: int = DEFAULT_RESOLUTION_DELAY_MINUTES,
    match_tolerance_minutes: int = DEFAULT_MATCH_TOLERANCE_MINUTES,
) -> dict[str, Any]:
    created_at = created_at_utc or _utc_now()
    source = dict(espn_source or {})
    source_collected_at = str(
        source.get("collected_at_utc")
        or espn_snapshot.get("collected_at_utc")
        or created_at
    )
    events = _espn_events(espn_snapshot)
    settled_games: list[dict[str, Any]] = []
    pending_games: list[dict[str, Any]] = []
    unmatched_games: list[dict[str, Any]] = []

    for prematch in prematch_matches:
        try:
            matched = _best_event_match(
                prematch,
                events,
                match_tolerance_minutes=match_tolerance_minutes,
            )
        except ValueError as exc:
            unmatched_games.append(_unmatched_row(prematch, reason=str(exc)))
            continue

        if matched is None:
            unmatched_games.append(_unmatched_row(prematch, reason="no_matching_espn_event"))
            continue

        if not _espn_completed(matched.event):
            pending_games.append(
                _pending_row(
                    prematch,
                    matched.event,
                    reason=_pending_reason(
                        prematch,
                        source_collected_at=source_collected_at,
                        resolution_delay_minutes=resolution_delay_minutes,
                    ),
                    resolution_delay_minutes=resolution_delay_minutes,
                )
            )
            continue

        settled_games.append(
            _settled_row(
                prematch,
                matched,
                source_collected_at=source_collected_at,
                resolution_delay_minutes=resolution_delay_minutes,
            )
        )

    summary = {
        "prematch_matches": len(prematch_matches),
        "espn_events": len(events),
        "settled": len(settled_games),
        "pending": len(pending_games),
        "unmatched": len(unmatched_games),
    }
    return {
        "schema_version": "settled-games-v1",
        "created_at_utc": created_at,
        "resolution_policy": {
            "prediction_leakage_rule": "Scores are stored only after prediction and must not be injected into prematch KG/evidence.",
            "primary_source": "espn_worldcup_scoreboard",
            "resolution_delay_minutes": resolution_delay_minutes,
            "match_tolerance_minutes": match_tolerance_minutes,
            "result_side_basis": "home/draw/away relative to the prematch scrape home_team and away_team fields.",
        },
        "sources": [source] if source else [],
        "summary": summary,
        "settled_games": settled_games,
        "pending_games": pending_games,
        "unmatched_games": unmatched_games,
    }


def render_report(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# Settled Games Report",
        "",
        f"- Created: {payload.get('created_at_utc', '')}",
        f"- Prematch matches: {summary.get('prematch_matches', 0)}",
        f"- Settled: {summary.get('settled', 0)}",
        f"- Pending: {summary.get('pending', 0)}",
        f"- Unmatched: {summary.get('unmatched', 0)}",
        "",
        "## Settled",
    ]
    for row in payload.get("settled_games") or []:
        lines.append(
            f"- {row['home_team']} vs {row['away_team']} ({row['kickoff_utc']}): "
            f"{row['score']} -> {row['result_side']} [{row['source_name']}:{row['source_event_id']}]"
        )
    lines.extend(["", "## Pending"])
    for row in payload.get("pending_games") or []:
        lines.append(
            f"- {row['home_team']} vs {row['away_team']} ({row['kickoff_utc']}): {row['reason']}"
        )
    lines.extend(["", "## Unmatched"])
    for row in payload.get("unmatched_games") or []:
        lines.append(
            f"- {row['home_team']} vs {row['away_team']} ({row['kickoff_utc']}): {row['reason']}"
        )
    return "\n".join(lines).rstrip() + "\n"


def _load_prematch_match(path: Path) -> PrematchMatch:
    payload = json.loads(path.read_text(encoding="utf-8"))
    match = dict(payload.get("match") or {})
    summary = dict(payload.get("summary") or {})
    required = ["home_team", "away_team", "kickoff_utc", "prediction_cutoff_utc"]
    missing = [key for key in required if not str(match.get(key) or "").strip()]
    if missing:
        raise ValueError(f"{path}: missing match fields: {', '.join(missing)}")
    kickoff_utc = _iso(_parse_utc(str(match["kickoff_utc"])))
    prediction_cutoff_utc = _iso(_parse_utc(str(match["prediction_cutoff_utc"])))
    return PrematchMatch(
        source_dir=_prematch_source_dir(path),
        documents_path=path,
        created_at_utc=str(payload.get("created_at_utc") or ""),
        home_team=str(match["home_team"]),
        away_team=str(match["away_team"]),
        kickoff_utc=kickoff_utc,
        prediction_cutoff_utc=prediction_cutoff_utc,
        usable_documents=int(summary.get("usable") or 0),
        rejected_documents=int(summary.get("rejected") or 0),
    )


def _prematch_documents_path(source: Path) -> Path:
    if source.is_dir():
        candidates = [
            source / "normalized" / "prematch_documents.json",
            source / "prematch_documents.json",
        ]
    elif source.name == "prematch_documents.json":
        candidates = [source]
    elif source.name == "prematch_kg_source.json":
        candidates = [
            source.parent.parent / "normalized" / "prematch_documents.json",
            source.parent / "prematch_documents.json",
        ]
    else:
        raise ValueError(f"Unsupported prematch source: {source}")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Missing prematch documents file for source: {source}")


def _prematch_source_dir(documents_path: Path) -> Path:
    if documents_path.parent.name == "normalized":
        return documents_path.parent.parent
    return documents_path.parent


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _espn_events(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    if "scoreboard" in snapshot:
        return list((snapshot.get("scoreboard") or {}).get("events") or [])
    return list(snapshot.get("events") or [])


def _best_event_match(
    prematch: PrematchMatch,
    events: list[dict[str, Any]],
    *,
    match_tolerance_minutes: int,
) -> EventMatch | None:
    candidates = [
        candidate
        for event in events
        for candidate in [_event_match_candidate(prematch, event, match_tolerance_minutes)]
        if candidate is not None
    ]
    if not candidates:
        return None
    candidates.sort(key=_event_match_rank, reverse=True)
    best = candidates[0]
    best_rank = _event_match_rank(best)
    tied = [item for item in candidates if _event_match_rank(item) == best_rank]
    if len(tied) > 1:
        event_ids = ", ".join(str(item.event.get("id") or "") for item in tied)
        raise ValueError(f"ambiguous_matching_espn_event:{event_ids}")
    return best


def _event_match_rank(match: EventMatch) -> tuple[int, int]:
    kickoff_closeness = -match.kickoff_delta_seconds if match.kickoff_delta_seconds is not None else -10**12
    return (match.score, kickoff_closeness)


def _event_match_candidate(
    prematch: PrematchMatch,
    event: dict[str, Any],
    match_tolerance_minutes: int,
) -> EventMatch | None:
    try:
        competition = _espn_competition(event)
        event_home = _team_from_competitors(competition, "home")
        event_away = _team_from_competitors(competition, "away")
    except (KeyError, ValueError):
        return None

    prematch_home = _team_key(prematch.home_team)
    prematch_away = _team_key(prematch.away_team)
    event_home_key = _team_key(_team_name(event_home))
    event_away_key = _team_key(_team_name(event_away))
    if event_home_key == prematch_home and event_away_key == prematch_away:
        orientation = "normal"
        team_score = 80
    elif event_home_key == prematch_away and event_away_key == prematch_home:
        orientation = "reversed"
        team_score = 70
    else:
        return None

    kickoff_score = 0
    kickoff_delta_seconds: int | None = None
    event_date = str(event.get("date") or competition.get("date") or "").strip()
    if event_date:
        try:
            delta = abs((_parse_utc(event_date) - _parse_utc(prematch.kickoff_utc)).total_seconds())
            kickoff_delta_seconds = int(delta)
            if delta <= match_tolerance_minutes * 60:
                kickoff_score = 25
            else:
                return None
        except ValueError:
            kickoff_score = 0

    return EventMatch(
        event=event,
        orientation=orientation,
        score=team_score + kickoff_score,
        kickoff_delta_seconds=kickoff_delta_seconds,
    )


def _settled_row(
    prematch: PrematchMatch,
    matched: EventMatch,
    *,
    source_collected_at: str,
    resolution_delay_minutes: int,
) -> dict[str, Any]:
    competition = _espn_competition(matched.event)
    event_home = _team_from_competitors(competition, "home")
    event_away = _team_from_competitors(competition, "away")
    event_home_score = int(event_home.get("score"))
    event_away_score = int(event_away.get("score"))
    if matched.orientation == "reversed":
        home_score = event_away_score
        away_score = event_home_score
    else:
        home_score = event_home_score
        away_score = event_away_score

    kickoff = _parse_utc(prematch.kickoff_utc)
    resolution_available = kickoff + timedelta(minutes=resolution_delay_minutes)
    return {
        "settled_game_id": _settled_game_id(prematch),
        "match_key": _match_key(prematch),
        "prematch_source_dir": str(prematch.source_dir),
        "prematch_documents_path": str(prematch.documents_path),
        "home_team": prematch.home_team,
        "away_team": prematch.away_team,
        "kickoff_utc": prematch.kickoff_utc,
        "prediction_cutoff_utc": prematch.prediction_cutoff_utc,
        "usable_documents": prematch.usable_documents,
        "rejected_documents": prematch.rejected_documents,
        "home_score": home_score,
        "away_score": away_score,
        "score": f"{home_score}-{away_score}",
        "result_side": _result_side(home_score, away_score),
        "resolved_at_utc": _iso(resolution_available),
        "available_at_utc": _iso(resolution_available),
        "source_collected_at_utc": _iso(_parse_utc(source_collected_at)),
        "source_name": "espn_worldcup_scoreboard",
        "source_event_id": str(matched.event.get("id") or ""),
        "source_event_name": str(matched.event.get("name") or ""),
        "source_event_orientation": matched.orientation,
        "source_status": dict(matched.event.get("status") or {}),
        "citations": [f"espn://fifa.world/events/{matched.event.get('id')}/result"],
    }


def _pending_row(
    prematch: PrematchMatch,
    event: dict[str, Any],
    *,
    reason: str,
    resolution_delay_minutes: int,
) -> dict[str, Any]:
    kickoff = _parse_utc(prematch.kickoff_utc)
    next_check = kickoff + timedelta(minutes=resolution_delay_minutes)
    return {
        "match_key": _match_key(prematch),
        "prematch_source_dir": str(prematch.source_dir),
        "prematch_documents_path": str(prematch.documents_path),
        "home_team": prematch.home_team,
        "away_team": prematch.away_team,
        "kickoff_utc": prematch.kickoff_utc,
        "prediction_cutoff_utc": prematch.prediction_cutoff_utc,
        "reason": reason,
        "next_check_after_utc": _iso(next_check),
        "source_name": "espn_worldcup_scoreboard",
        "source_event_id": str(event.get("id") or ""),
        "source_event_name": str(event.get("name") or ""),
        "source_status": dict(event.get("status") or {}),
    }


def _unmatched_row(prematch: PrematchMatch, *, reason: str) -> dict[str, Any]:
    return {
        "match_key": _match_key(prematch),
        "prematch_source_dir": str(prematch.source_dir),
        "prematch_documents_path": str(prematch.documents_path),
        "home_team": prematch.home_team,
        "away_team": prematch.away_team,
        "kickoff_utc": prematch.kickoff_utc,
        "prediction_cutoff_utc": prematch.prediction_cutoff_utc,
        "reason": reason,
    }


def _pending_reason(
    prematch: PrematchMatch,
    *,
    source_collected_at: str,
    resolution_delay_minutes: int,
) -> str:
    expected_resolution = _parse_utc(prematch.kickoff_utc) + timedelta(minutes=resolution_delay_minutes)
    collected = _parse_utc(source_collected_at)
    if collected < expected_resolution:
        return "resolution_delay_not_elapsed"
    return "espn_event_not_completed"


def _espn_completed(event: dict[str, Any]) -> bool:
    status = event.get("status") or {}
    status_type = status.get("type") or {}
    if not bool(status_type.get("completed")):
        return False
    try:
        competition = _espn_competition(event)
        int(_team_from_competitors(competition, "home").get("score"))
        int(_team_from_competitors(competition, "away").get("score"))
    except (KeyError, TypeError, ValueError):
        return False
    return True


def _espn_competition(event: dict[str, Any]) -> dict[str, Any]:
    competitions = event.get("competitions") or []
    if not competitions:
        raise ValueError(f"ESPN event has no competition: {event.get('id')}")
    return dict(competitions[0])


def _team_from_competitors(competition: dict[str, Any], home_away: str) -> dict[str, Any]:
    for competitor in competition.get("competitors") or []:
        if competitor.get("homeAway") == home_away:
            return dict(competitor)
    raise KeyError(f"Missing {home_away} competitor")


def _team_name(competitor: dict[str, Any]) -> str:
    team = competitor.get("team") or {}
    for key in ("displayName", "shortDisplayName", "name", "location", "abbreviation"):
        value = team.get(key)
        if value:
            return str(value)
    return str(competitor.get("displayName") or competitor.get("name") or "")


def _team_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text).lower().strip()
    text = re.sub(r"\s+", "_", text)
    aliases = {
        "u_s_a": "united_states",
        "usa": "united_states",
        "us": "united_states",
        "united_states": "united_states",
        "united_states_of_america": "united_states",
        "bosnia_and_herzegovina": "bosnia_herzegovina",
        "bosnia_herzegovina": "bosnia_herzegovina",
        "bosnia_hercegovina": "bosnia_herzegovina",
        "dr_congo": "dr_congo",
        "congo_dr": "dr_congo",
        "d_r_congo": "dr_congo",
        "democratic_republic_of_congo": "dr_congo",
        "congo_democratic_republic": "dr_congo",
        "korea_republic": "south_korea",
        "republic_of_korea": "south_korea",
        "south_korea": "south_korea",
        "czech_republic": "czechia",
        "czechia": "czechia",
        "cote_d_ivoire": "ivory_coast",
        "cote_divoire": "ivory_coast",
        "ivory_coast": "ivory_coast",
    }
    return aliases.get(text, text)


def _settled_game_id(prematch: PrematchMatch) -> str:
    return f"worldcup_2026:{_match_key(prematch)}"


def _match_key(prematch: PrematchMatch) -> str:
    date = _parse_utc(prematch.kickoff_utc).strftime("%Y_%m_%d")
    return f"{_slug(prematch.home_team)}_vs_{_slug(prematch.away_team)}_{date}"


def _result_side(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "home"
    if away_goals > home_goals:
        return "away"
    return "draw"


def _parse_utc(value: str) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _utc_now() -> str:
    return _iso(datetime.now(timezone.utc))


def _slug(value: str) -> str:
    value = value.replace("&", "and")
    text = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _default_output_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return DEFAULT_SETTLED_ROOT / stamp / "settled_games.json"


if __name__ == "__main__":
    main()
