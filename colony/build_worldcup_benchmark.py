#!/usr/bin/env python3
"""Build a World Cup benchmark dataset from OpenFootball match data.

This builder intentionally redacts results from the prediction snapshot. The
source file may contain final scores, but generated evidence only includes
fixture context and an explicit low-information benchmark prior. Scores are
written only under `resolution`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:  # Script mode: python3 colony/build_worldcup_benchmark.py
    from colony_harness.benchmark import load_benchmark_dataset
except ImportError:  # Package mode
    from colony.colony_harness.benchmark import load_benchmark_dataset


DEFAULT_OPENFOOTBALL = Path("colony/data/openfootball/worldcup_2026.json")
DEFAULT_COLLECTION_DIR = Path("colony/runs/benchmark_collection/first_real_snapshot")
DEFAULT_OUT = Path("colony/data/benchmarks/worldcup_2026_latest_resolved.json")
DEFAULT_SOURCE_CATALOG = Path("colony/config/scouting_source_catalog.json")
HOST_TEAMS = {"Canada", "Mexico", "USA"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openfootball", type=Path, default=None, help="OpenFootball World Cup JSON path.")
    parser.add_argument("--espn-snapshot", type=Path, default=None, help="ESPN World Cup scoreboard snapshot JSON path.")
    parser.add_argument(
        "--collection-dir",
        type=Path,
        default=None,
        help="Collection directory containing openfootball_worldcup_2026.json and collection_manifest.json.",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output benchmark dataset path.")
    parser.add_argument("--limit", type=int, default=0, help="Keep only the latest N resolved matches. 0 means all.")
    parser.add_argument("--cutoff-hours", type=float, default=6.0, help="Prediction cutoff before kickoff.")
    parser.add_argument(
        "--resolution-delay-minutes",
        type=int,
        default=135,
        help="Estimated result availability after kickoff for this fixture-only builder.",
    )
    parser.add_argument("--dataset-id", default="worldcup_2026_latest_resolved_v1")
    parser.add_argument(
        "--kg-module",
        action="append",
        default=[],
        help="Reuse a scouting KG source module as pre-match benchmark evidence. Repeatable.",
    )
    parser.add_argument(
        "--prematch-source",
        action="append",
        type=Path,
        default=[],
        help="Attach a prematch scrape directory or prematch_documents.json/prematch_kg_source.json file as benchmark evidence. Repeatable.",
    )
    parser.add_argument("--source-catalog", type=Path, default=DEFAULT_SOURCE_CATALOG)
    parser.add_argument("--scouting-mode", choices=["fast", "deep"], default="fast")
    parser.add_argument("--scouting-timeout", type=int, default=20)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    source_path, manifest, source_kind = _resolve_source(args.openfootball, args.espn_snapshot, args.collection_dir)
    if source_kind == "espn":
        payload = build_espn_dataset(
            espn_snapshot_path=source_path,
            manifest=manifest,
            dataset_id=args.dataset_id,
            limit=args.limit,
            cutoff_hours=args.cutoff_hours,
            resolution_delay_minutes=args.resolution_delay_minutes,
        )
    else:
        payload = build_dataset(
            openfootball_path=source_path,
            manifest=manifest,
            dataset_id=args.dataset_id,
            limit=args.limit,
            cutoff_hours=args.cutoff_hours,
            resolution_delay_minutes=args.resolution_delay_minutes,
        )
    if args.kg_module:
        payload = attach_kg_scouting_evidence(
            payload,
            modules=args.kg_module,
            source_catalog=args.source_catalog,
            cutoff_hours=args.cutoff_hours,
            scouting_mode=args.scouting_mode,
            scouting_timeout=args.scouting_timeout,
        )
    if args.prematch_source:
        payload = attach_prematch_scrape_evidence(payload, sources=args.prematch_source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    load_benchmark_dataset(args.out)
    print(f"World Cup benchmark dataset written: {args.out}")
    print(f"Events: {len(payload['events'])}")


def build_espn_dataset(
    *,
    espn_snapshot_path: Path,
    manifest: dict[str, Any] | None,
    dataset_id: str,
    limit: int,
    cutoff_hours: float,
    resolution_delay_minutes: int,
) -> dict[str, Any]:
    raw_bytes = espn_snapshot_path.read_bytes()
    source_hash = hashlib.sha256(raw_bytes).hexdigest()
    source_record = _source_record(manifest, espn_snapshot_path.name)
    data = json.loads(raw_bytes.decode("utf-8"))
    events = [
        event
        for event in (data.get("scoreboard") or {}).get("events") or []
        if _espn_completed(event)
    ]
    events.sort(key=lambda event: _parse_utc(str(event.get("date"))))
    if limit > 0:
        events = events[-limit:]
    summary_by_event = {
        str(item.get("event_id")): item.get("payload") or {}
        for item in data.get("event_summaries") or []
        if item.get("status") == "ok"
    }
    source_collected_at = str((source_record or {}).get("collected_at_utc") or data.get("collected_at_utc") or "")
    source_snapshot_id = str((source_record or {}).get("source_id") or espn_snapshot_path.stem)
    benchmark_events = [
        _event_from_espn(
            event,
            summary=summary_by_event.get(str(event.get("id"))) or {},
            index=index,
            source_snapshot_id=source_snapshot_id,
            source_hash=source_hash,
            source_collected_at=source_collected_at,
            cutoff_hours=cutoff_hours,
            resolution_delay_minutes=resolution_delay_minutes,
        )
        for index, event in enumerate(events, start=1)
    ]
    return {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "title": "World Cup 2026 latest resolved ESPN matches",
        "description": (
            "Benchmark built from ESPN FIFA World Cup scoreboard summaries. Post-match facts are redacted "
            "from prediction evidence; only fixture context and opening moneyline odds are used."
        ),
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": [
            {
                "source_name": "espn_worldcup_scoreboard",
                "source_type": "fixture_results_odds",
                "file": str(espn_snapshot_path),
                "sha256": source_hash,
                "collected_at_utc": source_collected_at,
                "note": "Source contains scores, articles, leaders, boxscore and rosters; builder redacts post-match fields from evidence.",
            },
            {
                "source_name": "espn_moneyline_odds",
                "source_type": "historical_odds",
                "note": "Opening moneyline odds are injected when present; closing odds are intentionally not injected for a six-hour cutoff.",
            },
        ],
        "build_audit": {
            "source_kind": "espn",
            "input_events": len((data.get("scoreboard") or {}).get("events") or []),
            "resolved_events": len(events),
            "output_events": len(benchmark_events),
            "limit": limit,
            "cutoff_hours": cutoff_hours,
            "resolution_delay_minutes": resolution_delay_minutes,
            "included_pre_prediction_sources": ["fixture_context", "espn_moneyline_open"],
            "redacted_post_cutoff_sources": ["espn_moneyline_close"],
            "redacted_post_match_sources": ["boxscore", "leaders", "keyEvents", "commentary", "article", "news", "rosters", "standings"],
        },
        "events": benchmark_events,
    }


def build_dataset(
    *,
    openfootball_path: Path,
    manifest: dict[str, Any] | None,
    dataset_id: str,
    limit: int,
    cutoff_hours: float,
    resolution_delay_minutes: int,
) -> dict[str, Any]:
    raw_bytes = openfootball_path.read_bytes()
    source_hash = hashlib.sha256(raw_bytes).hexdigest()
    source_record = _source_record(manifest, openfootball_path.name)
    data = json.loads(raw_bytes.decode("utf-8"))
    matches = [
        match
        for match in data.get("matches") or []
        if _has_full_time_score(match)
    ]
    matches.sort(key=_kickoff_utc)
    if limit > 0:
        matches = matches[-limit:]

    source_collected_at = str((source_record or {}).get("collected_at_utc") or "")
    source_snapshot_id = str((source_record or {}).get("source_id") or openfootball_path.stem)
    events = [
        _event_from_match(
            match,
            index=index,
            source_snapshot_id=source_snapshot_id,
            source_hash=source_hash,
            source_collected_at=source_collected_at,
            cutoff_hours=cutoff_hours,
            resolution_delay_minutes=resolution_delay_minutes,
        )
        for index, match in enumerate(matches, start=1)
    ]
    return {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "title": "World Cup 2026 latest resolved matches",
        "description": (
            "Fixture-only benchmark built from OpenFootball World Cup 2026 rows with scores redacted "
            "from prediction evidence and stored only in resolution."
        ),
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": [
            {
                "source_name": "openfootball_worldcup_2026",
                "source_type": "fixture_and_resolution",
                "file": str(openfootball_path),
                "sha256": source_hash,
                "collected_at_utc": source_collected_at,
                "note": "Source contains final scores; builder redacts scores from pre-prediction evidence.",
            },
            {
                "source_name": "benchmark_fixture_prior",
                "source_type": "derived_prior",
                "note": "Low-information prior derived only from fixture metadata and host-team status; not bookmaker odds.",
            },
        ],
        "build_audit": {
            "input_matches": len(data.get("matches") or []),
            "resolved_matches": len(matches),
            "limit": limit,
            "cutoff_hours": cutoff_hours,
            "resolution_delay_minutes": resolution_delay_minutes,
            "excluded_sources": [
                "Google News RSS snapshot is not used here because it was collected after these resolved matches and contains post-match facts."
            ],
        },
        "events": events,
    }


def attach_kg_scouting_evidence(
    payload: dict[str, Any],
    *,
    modules: list[str],
    source_catalog: Path,
    cutoff_hours: float,
    scouting_mode: str,
    scouting_timeout: int,
) -> dict[str, Any]:
    try:  # Script mode: python3 colony/build_worldcup_benchmark.py
        from scouting_matrix import (
            _expanded_modules,
            _load_source_catalog,
            _needs_txline_second_pass,
            _pipeline_flags_for_modules,
            _sources_for_match,
            _txline_fixture_from_findings,
        )
        from colony_harness.scouting_pipeline import ScoutingRunLogger, build_local_scouting_result
    except ImportError:  # Package mode
        from colony.scouting_matrix import (
            _expanded_modules,
            _load_source_catalog,
            _needs_txline_second_pass,
            _pipeline_flags_for_modules,
            _sources_for_match,
            _txline_fixture_from_findings,
        )
        from colony.colony_harness.scouting_pipeline import ScoutingRunLogger, build_local_scouting_result

    catalog = _load_source_catalog(str(source_catalog))
    expanded_modules = [module for module in _expanded_modules(modules, catalog) if module != "existing_kg"]
    flags = _pipeline_flags_for_modules(expanded_modules, catalog)
    audit_rows: list[dict[str, Any]] = []
    for event in payload.get("events") or []:
        logger = ScoutingRunLogger(verbose=False)
        match_entity = _benchmark_event_to_match_entity(event)
        sources = _sources_for_match(
            match_entity,
            expanded_modules,
            catalog=catalog,
            cutoff_hours=cutoff_hours,
            logger=logger,
        )
        result = build_local_scouting_result(
            match_entity=match_entity,
            mode=scouting_mode,
            sources=sources,
            timeout_seconds=scouting_timeout,
            include_x=flags["include_x"],
            include_camel=flags["include_camel"],
            include_camel_deep=flags["include_camel_deep"],
            camel_agent_count=flags["camel_agent_count"],
            include_telegram=flags["include_telegram"],
            include_polygun=flags["include_polygun"],
            include_deepseek_scout=flags["include_deepseek_scout"],
            as_of_utc=str(event["prediction_cutoff_utc"]),
            logger=logger,
        )
        source_summaries = list(result.source_summaries)
        if _needs_txline_second_pass(expanded_modules, catalog):
            fixture = _txline_fixture_from_findings(result.findings)
            if fixture:
                sources = _sources_for_match(
                    match_entity,
                    expanded_modules,
                    catalog=catalog,
                    txline_fixture=fixture,
                    cutoff_hours=cutoff_hours,
                    logger=logger,
                )
                result = build_local_scouting_result(
                    match_entity=match_entity,
                    mode=scouting_mode,
                    sources=sources,
                    timeout_seconds=scouting_timeout,
                    include_x=flags["include_x"],
                    include_camel=flags["include_camel"],
                    include_camel_deep=flags["include_camel_deep"],
                    camel_agent_count=flags["camel_agent_count"],
                    include_telegram=flags["include_telegram"],
                    include_polygun=flags["include_polygun"],
                    include_deepseek_scout=flags["include_deepseek_scout"],
                    as_of_utc=str(event["prediction_cutoff_utc"]),
                    logger=logger,
                )
                source_summaries.extend(result.source_summaries)
        kg_evidence = _kg_findings_to_evidence_items(event=event, findings=result.findings)
        event["evidence_items"].extend(kg_evidence)
        audit_rows.append(
            {
                "event_id": event["event_id"],
                "source_count": len(sources),
                "finding_count": len(result.findings),
                "evidence_items_added": len(kg_evidence),
                "claim_count": sum(len(finding.evidence_claims) for finding in result.findings),
                "source_summaries": source_summaries,
            }
        )
    payload.setdefault("sources", []).append(
        {
            "source_name": "scouting_kg_pre_match_sources",
            "source_type": "kg_scouting",
            "source_catalog": str(source_catalog),
            "modules": expanded_modules,
            "note": "Findings are generated through the same scouting/KG source modules and filtered with as_of_utc=prediction_cutoff_utc.",
        }
    )
    payload.setdefault("build_audit", {})["kg_scouting"] = {
        "enabled": True,
        "requested_modules": modules,
        "expanded_modules": expanded_modules,
        "cutoff_hours": cutoff_hours,
        "scouting_mode": scouting_mode,
        "events": len(audit_rows),
        "total_evidence_items_added": sum(row["evidence_items_added"] for row in audit_rows),
        "total_claims": sum(row["claim_count"] for row in audit_rows),
        "events_with_findings": sum(1 for row in audit_rows if row["finding_count"]),
        "event_rows": audit_rows,
    }
    return payload


def attach_prematch_scrape_evidence(payload: dict[str, Any], *, sources: list[Path]) -> dict[str, Any]:
    audit_rows: list[dict[str, Any]] = []
    for source in sources:
        documents_path, kg_path = _prematch_source_paths(source)
        documents_payload = json.loads(documents_path.read_text(encoding="utf-8"))
        kg_payload = json.loads(kg_path.read_text(encoding="utf-8"))
        match = dict(documents_payload.get("match") or {})
        event = _find_event_for_prematch_scrape(payload, match)
        evidence_items = _prematch_kg_payload_to_evidence_items(
            event=event,
            documents_payload=documents_payload,
            kg_payload=kg_payload,
            source_path=documents_path,
        )
        event["evidence_items"].extend(evidence_items)
        audit_rows.append(
            {
                "event_id": event["event_id"],
                "documents_path": str(documents_path),
                "kg_path": str(kg_path),
                "usable_documents": int((documents_payload.get("summary") or {}).get("usable") or 0),
                "rejected_documents": int((documents_payload.get("summary") or {}).get("rejected") or 0),
                "evidence_items_added": len(evidence_items),
                "claim_count": sum(len(item.get("evidence_claims") or []) for item in evidence_items),
            }
        )
    payload.setdefault("sources", []).append(
        {
            "source_name": "prematch_scrape_sources",
            "source_type": "prematch_media_social",
            "files": [str(source) for source in sources],
            "note": "Strictly pre-cutoff media/social scrape artifacts attached to matching events.",
        }
    )
    payload.setdefault("build_audit", {})["prematch_scrapes"] = {
        "enabled": True,
        "sources": len(sources),
        "events_with_scrapes": len({row["event_id"] for row in audit_rows}),
        "total_evidence_items_added": sum(row["evidence_items_added"] for row in audit_rows),
        "total_claims": sum(row["claim_count"] for row in audit_rows),
        "event_rows": audit_rows,
    }
    return payload


def _prematch_source_paths(source: Path) -> tuple[Path, Path]:
    if source.is_dir():
        documents_path = first_existing_path(
            [
                source / "normalized" / "prematch_documents.json",
                source / "prematch_documents.json",
            ]
        )
        kg_path = first_existing_path(
            [
                source / "kg" / "prematch_kg_source.json",
                source / "prematch_kg_source.json",
            ]
        )
    elif source.name == "prematch_documents.json":
        documents_path = source
        kg_path = first_existing_path(
            [
                source.parent.parent / "kg" / "prematch_kg_source.json",
                source.parent / "prematch_kg_source.json",
            ]
        )
    elif source.name == "prematch_kg_source.json":
        documents_path = first_existing_path(
            [
                source.parent.parent / "normalized" / "prematch_documents.json",
                source.parent / "prematch_documents.json",
            ]
        )
        kg_path = source
    else:
        raise ValueError(f"Unsupported prematch source: {source}")
    if not documents_path.exists():
        raise FileNotFoundError(f"Missing prematch documents file: {documents_path}")
    if not kg_path.exists():
        raise FileNotFoundError(f"Missing prematch KG file: {kg_path}")
    return documents_path, kg_path


def first_existing_path(candidates: list[Path]) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _find_event_for_prematch_scrape(payload: dict[str, Any], match: dict[str, Any]) -> dict[str, Any]:
    home = str(match.get("home_team") or "")
    away = str(match.get("away_team") or "")
    kickoff_raw = str(match.get("kickoff_utc") or "")
    kickoff = _parse_utc(kickoff_raw) if kickoff_raw else None
    candidates = [
        event
        for event in payload.get("events") or []
        if str(event.get("home_team") or "") == home and str(event.get("away_team") or "") == away
    ]
    if kickoff is not None:
        exact = [
            event
            for event in candidates
            if _parse_utc(str(event.get("starts_at_utc") or "")).replace(microsecond=0)
            == kickoff.replace(microsecond=0)
        ]
        if len(exact) == 1:
            return exact[0]
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError(f"Could not match prematch scrape to a unique event: {home} vs {away} {kickoff_raw}")


def _prematch_kg_payload_to_evidence_items(
    *,
    event: dict[str, Any],
    documents_payload: dict[str, Any],
    kg_payload: dict[str, Any],
    source_path: Path,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cutoff = _parse_utc(str(event["prediction_cutoff_utc"]))
    summary = dict(documents_payload.get("summary") or {})
    for index, finding in enumerate(kg_payload.get("findings") or [], start=1):
        claims = _filter_prematch_claims(list(finding.get("evidence_claims") or []), cutoff=cutoff)
        if not claims:
            continue
        content_hash = hashlib.sha256(
            json.dumps(
                {"finding": finding, "summary": summary, "source_path": str(source_path)},
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        available_at = _max_claim_available_at(claims) or str(event["prediction_cutoff_utc"])
        items.append(
            {
                "evidence_id": f"prematch_scrape_{index:02d}_{_slug(source_path.parent.name)[:70]}",
                "source_name": str(finding.get("scout_name") or "prematch_scrape_scout"),
                "source_type": "news",
                "access_level": str(finding.get("access_level") or "public"),
                "available_at_utc": available_at,
                "seen_at_utc": available_at,
                "source_snapshot_id": f"prematch_scrape:{source_path}",
                "collected_at_utc": str(documents_payload.get("created_at_utc") or ""),
                "content_hash": f"sha256:{content_hash}",
                "home_probability": finding.get("home_probability"),
                "confidence": float(finding.get("confidence") or 0.5),
                "summary": str(finding.get("summary") or ""),
                "citations": [str(item) for item in finding.get("citations") or []],
                "evidence_claims": claims,
                "metadata": {
                    "finding_name": str(finding.get("finding_name") or "prematch_scrape"),
                    "claim_count": len(claims),
                    "source_quality": _dominant_claim_value(claims, "source_quality"),
                    "source_kind": _dominant_claim_value(claims, "source_kind"),
                    "source_type_original": str(finding.get("source_type") or ""),
                    "prematch_summary": summary,
                    "timestamp_basis": "prematch scrape temporal gate; each claim has available_at_utc <= prediction_cutoff_utc",
                },
            }
        )
    return items


def _filter_prematch_claims(claims: list[dict[str, Any]], *, cutoff: datetime) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for claim in claims:
        available_raw = str(claim.get("available_at_utc") or claim.get("source_published") or "")
        if not available_raw:
            continue
        if _parse_utc(available_raw) <= cutoff:
            filtered.append(claim)
    return filtered


def _max_claim_available_at(claims: list[dict[str, Any]]) -> str:
    values = [
        _parse_utc(str(claim.get("available_at_utc") or claim.get("source_published") or ""))
        for claim in claims
        if str(claim.get("available_at_utc") or claim.get("source_published") or "")
    ]
    if not values:
        return ""
    return _iso(max(values))


def _benchmark_event_to_match_entity(event: dict[str, Any]) -> dict[str, Any]:
    starts_at = _parse_utc(str(event["starts_at_utc"]))
    return {
        "entity_id": f"match:benchmark:{event['event_id']}",
        "entity_type": "match",
        "name": event.get("title") or f"{event['home_team']} vs {event['away_team']}",
        "attributes": {
            "team1": event["home_team"],
            "team2": event["away_team"],
            "date": starts_at.date().isoformat(),
            "time": f"{starts_at.hour:02d}:{starts_at.minute:02d} UTC+0",
            "group": event.get("group_name") or "",
            "round": event.get("stage_name") or "",
            "ground": event.get("venue_name") or "",
        },
    }


def _kg_findings_to_evidence_items(*, event: dict[str, Any], findings: list[Any]) -> list[dict[str, Any]]:
    evidence_items: list[dict[str, Any]] = []
    for index, finding in enumerate(findings, start=1):
        finding_dict = finding.to_dict()
        claim_count = len(finding.evidence_claims)
        if claim_count <= 0:
            continue
        content_hash = hashlib.sha256(
            json.dumps(finding_dict, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        evidence_items.append(
            {
                "evidence_id": f"kg_{index:02d}_{_slug(finding.finding_id)[:80]}",
                "source_name": finding.scout_name,
                "source_type": finding.source_type,
                "access_level": finding.access_level,
                "available_at_utc": event["prediction_cutoff_utc"],
                "source_snapshot_id": f"kg_scouting:{event['event_id']}:{index}",
                "collected_at_utc": "",
                "content_hash": f"sha256:{content_hash}",
                "home_probability": finding.home_probability,
                "confidence": finding.confidence,
                "summary": finding.summary,
                "citations": finding.citations,
                "evidence_claims": finding.evidence_claims,
                "metadata": {
                    "finding_name": finding.finding_name,
                    "claim_count": claim_count,
                    "source_quality": _dominant_claim_value(finding.evidence_claims, "source_quality"),
                    "source_kind": _dominant_claim_value(finding.evidence_claims, "source_kind"),
                    "timestamp_basis": "scouting pipeline temporal gate with as_of_utc=prediction_cutoff_utc",
                },
            }
        )
    return evidence_items


def _dominant_claim_value(claims: list[dict[str, Any]], key: str) -> str:
    counts: dict[str, int] = {}
    for claim in claims:
        value = str(claim.get(key) or "")
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    if not counts:
        return ""
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _event_from_match(
    match: dict[str, Any],
    *,
    index: int,
    source_snapshot_id: str,
    source_hash: str,
    source_collected_at: str,
    cutoff_hours: float,
    resolution_delay_minutes: int,
) -> dict[str, Any]:
    kickoff = _kickoff_utc(match)
    cutoff = kickoff - timedelta(hours=cutoff_hours)
    resolution_available = kickoff + timedelta(minutes=resolution_delay_minutes)
    home = str(match.get("team1") or "Home")
    away = str(match.get("team2") or "Away")
    score = match["score"]["ft"]
    result_side = _result_side(int(score[0]), int(score[1]))
    baseline = _fixture_prior(home_team=home, away_team=away)
    event_id = f"wc26_{match.get('date')}_{home}_vs_{away}"
    event_id = _slug(event_id)
    score_text = f"{int(score[0])}-{int(score[1])}"
    return {
        "event_id": event_id,
        "category": "sports",
        "sub_category": "football",
        "event_type": "three_way_match_result",
        "title": f"{home} vs {away}",
        "home_team": home,
        "away_team": away,
        "starts_at_utc": _iso(kickoff),
        "prediction_cutoff_utc": _iso(cutoff),
        "group_name": str(match.get("group") or ""),
        "stage_name": str(match.get("round") or "Group Stage"),
        "venue_name": str(match.get("ground") or ""),
        "outcome_space": ["home", "draw", "away"],
        "baseline_probabilities": baseline,
        "metadata": {
            "source_match_index": index,
            "source_date": match.get("date"),
            "source_time": match.get("time"),
            "score_redaction": "full-time and half-time scores are excluded from evidence_items",
        },
        "evidence_items": [
            {
                "evidence_id": "fixture_context",
                "source_name": "openfootball_worldcup_2026",
                "source_type": "other",
                "access_level": "public",
                "available_at_utc": _iso(cutoff),
                "source_snapshot_id": source_snapshot_id,
                "collected_at_utc": source_collected_at,
                "content_hash": f"sha256:{source_hash}",
                "home_probability": None,
                "confidence": 0.9,
                "summary": (
                    f"{home} vs {away}, {match.get('round', 'World Cup')} in "
                    f"{match.get('ground', 'unknown venue')} ({match.get('group', 'unknown group')})."
                ),
                "citations": [f"openfootball://worldcup_2026/{event_id}"],
                "metadata": {
                    "source_quality": "medium",
                    "source_kind": "fixture_dataset",
                    "timestamp_basis": "benchmark cutoff snapshot; raw source was collected after some resolutions",
                },
            },
            {
                "evidence_id": "fixture_prior",
                "source_name": "benchmark_fixture_prior",
                "source_type": "market",
                "access_level": "public",
                "available_at_utc": _iso(cutoff),
                "source_snapshot_id": "derived_fixture_prior",
                "collected_at_utc": source_collected_at,
                "content_hash": f"sha256:{source_hash}",
                "home_probability": baseline["home"],
                "confidence": 0.25,
                "summary": (
                    "Low-information prior from fixture metadata only; host-team status may nudge the home side. "
                    "This is not bookmaker odds."
                ),
                "citations": [f"derived://worldcup_2026_fixture_prior/{event_id}"],
                "metadata": {
                    "source_quality": "weak",
                    "source_kind": "derived_prior",
                    "timestamp_basis": "computed during dataset build from redacted fixture metadata",
                    "draw_probability": baseline["draw"],
                    "away_probability": baseline["away"],
                },
            },
        ],
        "resolution": {
            "result_side": result_side,
            "score": score_text,
            "resolved_at_utc": _iso(kickoff + timedelta(minutes=120)),
            "available_at_utc": _iso(resolution_available),
            "source_name": "openfootball_worldcup_2026",
            "citations": [f"openfootball://worldcup_2026/{event_id}/result"],
        },
    }


def _event_from_espn(
    event: dict[str, Any],
    *,
    summary: dict[str, Any],
    index: int,
    source_snapshot_id: str,
    source_hash: str,
    source_collected_at: str,
    cutoff_hours: float,
    resolution_delay_minutes: int,
) -> dict[str, Any]:
    competition = _espn_competition(event)
    home_row = _team_from_competitors(competition, "home")
    away_row = _team_from_competitors(competition, "away")
    home = str((home_row.get("team") or {}).get("displayName") or home_row.get("displayName") or "Home")
    away = str((away_row.get("team") or {}).get("displayName") or away_row.get("displayName") or "Away")
    home_score = int(home_row.get("score"))
    away_score = int(away_row.get("score"))
    kickoff = _parse_utc(str(event.get("date") or competition.get("date") or competition.get("startDate")))
    cutoff = kickoff - timedelta(hours=cutoff_hours)
    resolution_available = kickoff + timedelta(minutes=resolution_delay_minutes)
    result_side = _result_side(home_score, away_score)
    score_text = f"{home_score}-{away_score}"
    event_id = _slug(f"wc26_espn_{event.get('id')}_{home}_vs_{away}")
    venue = _espn_venue_name(event, competition)
    odds_entry = _espn_primary_odds(summary, competition)
    opening_probabilities = _moneyline_probabilities(odds_entry, basis="open") if odds_entry else None
    baseline = opening_probabilities or _fixture_prior(home_team=home, away_team=away)
    evidence_items = [
        {
            "evidence_id": "fixture_context",
            "source_name": "espn_worldcup_scoreboard",
            "source_type": "other",
            "access_level": "public",
            "available_at_utc": _iso(cutoff),
            "source_snapshot_id": source_snapshot_id,
            "collected_at_utc": source_collected_at,
            "content_hash": f"sha256:{source_hash}",
            "home_probability": None,
            "confidence": 0.9,
            "summary": f"{home} vs {away}, FIFA World Cup fixture at {venue or 'unknown venue'}.",
            "citations": [f"espn://fifa.world/events/{event.get('id')}"],
            "metadata": {
                "source_quality": "medium",
                "source_kind": "fixture_dataset",
                "timestamp_basis": "benchmark cutoff snapshot; raw ESPN source was collected after some resolutions",
            },
        }
    ]
    if opening_probabilities is not None:
        raw_open = _moneyline_raw_odds(odds_entry, basis="open")
        evidence_items.append(
            {
                "evidence_id": "espn_moneyline_open",
                "source_name": "espn_draftkings_opening_moneyline",
                "source_type": "market",
                "access_level": "public",
                "available_at_utc": _iso(cutoff),
                "source_snapshot_id": source_snapshot_id,
                "collected_at_utc": source_collected_at,
                "content_hash": f"sha256:{source_hash}",
                "home_probability": opening_probabilities["home"],
                "confidence": 0.72,
                "summary": (
                    "Opening three-way moneyline implied probability from ESPN/DraftKings, "
                    "normalized across home, draw, and away."
                ),
                "citations": [f"espn://fifa.world/events/{event.get('id')}/odds/moneyline/open"],
                "metadata": {
                    "source_quality": "strong",
                    "source_kind": "bookmaker_market",
                    "timestamp_basis": (
                        "ESPN summary exposes opening moneyline but not the exact open timestamp; "
                        "builder treats it as available at the benchmark prediction cutoff."
                    ),
                    "home_probability": opening_probabilities["home"],
                    "draw_probability": opening_probabilities["draw"],
                    "away_probability": opening_probabilities["away"],
                    "raw_american_odds": raw_open,
                    "provider": _odds_provider_name(odds_entry),
                },
            }
        )
    else:
        evidence_items.append(
            {
                "evidence_id": "fixture_prior",
                "source_name": "benchmark_fixture_prior",
                "source_type": "market",
                "access_level": "public",
                "available_at_utc": _iso(cutoff),
                "source_snapshot_id": "derived_fixture_prior",
                "collected_at_utc": source_collected_at,
                "content_hash": f"sha256:{source_hash}",
                "home_probability": baseline["home"],
                "confidence": 0.25,
                "summary": "Low-information prior from fixture metadata only; not bookmaker odds.",
                "citations": [f"derived://worldcup_2026_fixture_prior/{event_id}"],
                "metadata": {
                    "source_quality": "weak",
                    "source_kind": "derived_prior",
                    "timestamp_basis": "computed during dataset build from redacted fixture metadata",
                    "draw_probability": baseline["draw"],
                    "away_probability": baseline["away"],
                },
            }
        )
    return {
        "event_id": event_id,
        "category": "sports",
        "sub_category": "football",
        "event_type": "three_way_match_result",
        "title": f"{home} vs {away}",
        "home_team": home,
        "away_team": away,
        "starts_at_utc": _iso(kickoff),
        "prediction_cutoff_utc": _iso(cutoff),
        "group_name": "",
        "stage_name": "FIFA World Cup",
        "venue_name": venue,
        "outcome_space": ["home", "draw", "away"],
        "baseline_probabilities": baseline,
        "metadata": {
            "source_event_index": index,
            "source_event_id": str(event.get("id") or ""),
            "source_date": event.get("date"),
            "score_redaction": "competitor scores and live/post-match fields are excluded from evidence_items",
            "odds_redaction": "closing moneyline is not injected because it may be after the prediction cutoff",
        },
        "evidence_items": evidence_items,
        "resolution": {
            "result_side": result_side,
            "score": score_text,
            "resolved_at_utc": _iso(kickoff + timedelta(minutes=120)),
            "available_at_utc": _iso(resolution_available),
            "source_name": "espn_worldcup_scoreboard",
            "citations": [f"espn://fifa.world/events/{event.get('id')}/result"],
        },
    }


def _resolve_source(
    openfootball: Path | None,
    espn_snapshot: Path | None,
    collection_dir: Path | None,
) -> tuple[Path, dict[str, Any] | None, str]:
    if espn_snapshot is not None:
        return espn_snapshot, _manifest_for(collection_dir), "espn"
    if openfootball is not None:
        return openfootball, None, "openfootball"
    base = collection_dir or DEFAULT_COLLECTION_DIR
    manifest = _manifest_for(base)
    espn_files = sorted(base.glob("espn_worldcup_scoreboard_*.json"))
    if espn_files:
        return espn_files[-1], manifest, "espn"
    collected = base / "openfootball_worldcup_2026.json"
    if collected.exists():
        return collected, manifest, "openfootball"
    return DEFAULT_OPENFOOTBALL, None, "openfootball"


def _manifest_for(collection_dir: Path | None) -> dict[str, Any] | None:
    if collection_dir is None:
        return None
    manifest = collection_dir / "collection_manifest.json"
    return json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else None


def _source_record(manifest: dict[str, Any] | None, filename: str) -> dict[str, Any] | None:
    if not manifest:
        return None
    for row in manifest.get("sources") or []:
        if row.get("file") == filename:
            return dict(row)
    return None


def _has_full_time_score(match: dict[str, Any]) -> bool:
    ft = ((match.get("score") or {}).get("ft") or [])
    return len(ft) >= 2 and all(isinstance(value, int) for value in ft[:2])


def _espn_completed(event: dict[str, Any]) -> bool:
    status = event.get("status") or {}
    status_type = status.get("type") or {}
    if not bool(status_type.get("completed")):
        return False
    competition = _espn_competition(event)
    try:
        home = _team_from_competitors(competition, "home")
        away = _team_from_competitors(competition, "away")
        int(home.get("score"))
        int(away.get("score"))
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


def _espn_venue_name(event: dict[str, Any], competition: dict[str, Any]) -> str:
    for source in (competition.get("venue"), event.get("venue")):
        if not isinstance(source, dict):
            continue
        name = source.get("fullName") or source.get("displayName")
        if name:
            return str(name)
    return ""


def _espn_primary_odds(summary: dict[str, Any], competition: dict[str, Any]) -> dict[str, Any] | None:
    odds = summary.get("odds") or competition.get("odds") or []
    if isinstance(odds, dict):
        return odds
    if isinstance(odds, list) and odds:
        return dict(odds[0])
    return None


def _moneyline_probabilities(odds_entry: dict[str, Any], *, basis: str) -> dict[str, float] | None:
    raw = _moneyline_raw_odds(odds_entry, basis=basis)
    values = {
        side: _american_odds_to_probability(raw_value)
        for side, raw_value in raw.items()
        if raw_value not in ("", None)
    }
    if set(values) != {"home", "draw", "away"}:
        return None
    total = sum(values.values())
    if total <= 0:
        return None
    return {side: round(values[side] / total, 4) for side in ("home", "draw", "away")}


def _moneyline_raw_odds(odds_entry: dict[str, Any], *, basis: str) -> dict[str, Any]:
    moneyline = odds_entry.get("moneyline") or {}
    raw = {
        side: (((moneyline.get(side) or {}).get(basis) or {}).get("odds"))
        for side in ("home", "draw", "away")
    }
    if basis == "close":
        raw = {
            "home": raw.get("home") or (odds_entry.get("homeTeamOdds") or {}).get("moneyLine"),
            "draw": raw.get("draw") or (odds_entry.get("drawOdds") or {}).get("moneyLine"),
            "away": raw.get("away") or (odds_entry.get("awayTeamOdds") or {}).get("moneyLine"),
        }
    return raw


def _american_odds_to_probability(value: Any) -> float:
    text = str(value).strip().replace("+", "")
    number = float(text)
    if number < 0:
        return abs(number) / (abs(number) + 100.0)
    return 100.0 / (number + 100.0)


def _odds_provider_name(odds_entry: dict[str, Any]) -> str:
    provider = odds_entry.get("provider") or {}
    return str(provider.get("name") or "unknown")


def _kickoff_utc(match: dict[str, Any]) -> datetime:
    date_text = str(match.get("date") or "")
    time_text = str(match.get("time") or "")
    match_obj = re.match(r"^(\d{1,2}):(\d{2})\s+UTC([+-]\d{1,2})$", time_text)
    if not match_obj:
        raise ValueError(f"Unsupported match time: {time_text}")
    hour, minute, offset = match_obj.groups()
    tz = timezone(timedelta(hours=int(offset)))
    local = datetime.fromisoformat(f"{date_text}T{int(hour):02d}:{minute}:00").replace(tzinfo=tz)
    return local.astimezone(timezone.utc)


def _parse_utc(value: str) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _fixture_prior(*, home_team: str, away_team: str) -> dict[str, float]:
    draw = 0.27
    if home_team in HOST_TEAMS and away_team not in HOST_TEAMS:
        home = 0.56
    elif away_team in HOST_TEAMS and home_team not in HOST_TEAMS:
        home = 0.44
    else:
        home = 0.50
    away = round(1.0 - home - draw, 4)
    return {"home": round(home, 4), "draw": draw, "away": away}


def _result_side(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "home"
    if away_goals > home_goals:
        return "away"
    return "draw"


def _slug(value: str) -> str:
    value = value.replace("&", "and").replace("ç", "c").replace("Ç", "c")
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


if __name__ == "__main__":
    main()
