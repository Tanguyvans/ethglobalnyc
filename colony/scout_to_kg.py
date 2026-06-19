#!/usr/bin/env python3
"""Run local scouting sources into a validated KG bundle.

This intentionally does not run the Colony debate app. It selects one match,
executes simple pluggable dataset sources, builds a scouting KG, and validates
the generated run directory with the same ingestion checks as export_scouting_kg.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from colony_harness.env import load_env_file
from colony_harness.scouting_pipeline import (
    DEFAULT_LOCAL_RUNS_DIR,
    ScoutingRunLogger,
    build_local_scouting_result,
    create_default_run_dir,
    default_sources_for_mode,
    load_graph_for_local_scouting,
    parse_source_spec,
    select_match_entity,
    write_local_scouting_artifacts,
)


DEFAULT_KG = Path(__file__).parent / "data" / "world_cup_kg.json"
DEFAULT_ENV = Path(__file__).parent / ".env"
DEFAULT_OPENFOOTBALL_CACHE = Path(__file__).parent / "data" / "openfootball" / "worldcup_2026.json"
DEFAULT_LIVE_CACHE = Path(__file__).parent / "data" / "live_scouts"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a local scouting KG without running the full app.")
    parser.add_argument("--kg", default=str(DEFAULT_KG), help="Tournament KG used to select the match.")
    parser.add_argument("--env", default=str(DEFAULT_ENV), help="Optional .env path for scouting provider settings.")
    parser.add_argument("--match-id", default=None, help="Exact match entity id from the tournament KG.")
    parser.add_argument("--match", default="Brazil vs Morocco", help='Match name, for example "Brazil vs Morocco".')
    parser.add_argument(
        "--mode",
        choices=["fast", "deep"],
        default="fast",
        help="fast uses fixture/context scouting; deep adds the public-data scout.",
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help=(
            "Dataset source plugin. Repeatable. Supported: fixture, deep-fixture, "
            "public, public:/cache/dir, json:/path, mcp:/path, cli:'command', "
            "mcp-stdio:/path/config.json, api:https://..., url:https://..., or a plain https:// URL"
        ),
    )
    parser.add_argument(
        "--source-manifest",
        action="append",
        default=[],
        help="JSON file listing sources, existing_kg, scout_focus, or rescout_from_audit entries. Repeatable.",
    )
    parser.add_argument(
        "--existing-kg",
        action="append",
        default=[],
        help="Existing KG JSON to reuse as scouting input. Repeatable.",
    )
    parser.add_argument(
        "--merge-existing-kg",
        action="store_true",
        help="Also merge entities/relationships from --existing-kg into the generated graph.",
    )
    parser.add_argument(
        "--offline-sample",
        action="store_true",
        help="Use the tiny built-in World Cup sample schedule instead of reading/fetching the tournament KG.",
    )
    parser.add_argument(
        "--refresh-openfootball",
        action="store_true",
        help="Refetch OpenFootball if --kg is missing and the cache is used.",
    )
    parser.add_argument(
        "--openfootball-cache",
        default=str(DEFAULT_OPENFOOTBALL_CACHE),
        help="Cache path used only when --kg is missing and --offline-sample is disabled.",
    )
    parser.add_argument("--out-dir", default=None, help="Exact output directory for generated KG artifacts.")
    parser.add_argument(
        "--runs-dir",
        default=str(DEFAULT_LOCAL_RUNS_DIR),
        help="Base directory for timestamped output when --out-dir is omitted.",
    )
    parser.add_argument("--timeout", type=int, default=20, help="Per-source timeout for cli/api sources.")
    parser.add_argument(
        "--live-cache-dir",
        default=str(DEFAULT_LIVE_CACHE),
        help="Cache directory for public-data scout fetches.",
    )
    parser.add_argument(
        "--refresh-data",
        action="store_true",
        help="Refetch public-data scout sources instead of using cached pages where available.",
    )
    parser.add_argument("--include-x", action="store_true", help="Include the optional X availability scout.")
    parser.add_argument("--include-camel", action="store_true", help="Include the optional CAMEL research scout.")
    parser.add_argument(
        "--camel-agents",
        type=int,
        default=4,
        help="Number of focused CAMEL/DDGS research agents to run when --include-camel is set.",
    )
    parser.add_argument("--include-telegram", action="store_true", help="Include the optional Telegram scout.")
    parser.add_argument("--include-polygun", action="store_true", help="Include the optional PolyGun market scout.")
    parser.add_argument(
        "--include-deepseek-scout",
        action="store_true",
        help="Include the optional structured DeepSeek/OpenRouter scouting agent.",
    )
    parser.add_argument(
        "--scout-focus",
        action="append",
        default=[],
        metavar="TEAM:CLAIM_TYPE",
        help="Focused public re-scout target such as 'Morocco:lineup'. Repeatable.",
    )
    parser.add_argument(
        "--rescout-from-audit",
        action="append",
        default=[],
        help="Read scouting_audit.json backlog items and add them as focused public re-scout targets. Repeatable.",
    )
    parser.add_argument("--quiet", action="store_true", help="Do not print progress log lines.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_env_file(args.env)
    manifests = _load_source_manifests(args.source_manifest)
    logger = ScoutingRunLogger(verbose=not args.quiet)
    graph = load_graph_for_local_scouting(
        kg_path=args.kg,
        offline_sample=args.offline_sample,
        openfootball_cache=args.openfootball_cache,
        refresh=args.refresh_openfootball,
    )
    match_entity = select_match_entity(graph, match_id=args.match_id, match_name=args.match)
    template_context = _match_template_context(match_entity)
    source_values = [
        _render_manifest_value(value, template_context)
        for value in _manifest_values(manifests, "sources") + list(args.source)
    ]
    source_specs = [parse_source_spec(raw) for raw in source_values] if source_values else default_sources_for_mode(args.mode)
    existing_kg_paths = [
        str(_render_manifest_value(value, template_context))
        for value in _manifest_values(manifests, "existing_kg") + list(args.existing_kg)
    ]
    rescout_targets = _rescout_targets_from_inputs(
        rescout_from_audit=[
            str(_render_manifest_value(value, template_context))
            for value in _manifest_values(manifests, "rescout_from_audit") + list(args.rescout_from_audit)
        ],
        scout_focus=[
            str(_render_manifest_value(value, template_context))
            for value in _manifest_values(manifests, "scout_focus") + list(args.scout_focus)
        ],
    )
    result = build_local_scouting_result(
        match_entity=match_entity,
        mode=args.mode,
        sources=source_specs,
        existing_kg_paths=existing_kg_paths,
        merge_existing_kg=args.merge_existing_kg,
        timeout_seconds=args.timeout,
        public_cache_dir=args.live_cache_dir,
        refresh_public_data=args.refresh_data,
        include_x=args.include_x,
        include_camel=args.include_camel,
        camel_agent_count=args.camel_agents,
        include_telegram=args.include_telegram,
        include_polygun=args.include_polygun,
        include_deepseek_scout=args.include_deepseek_scout,
        rescout_targets=rescout_targets,
        logger=logger,
    )
    out_dir = Path(args.out_dir) if args.out_dir else create_default_run_dir(args.runs_dir, result.match.round_id, mode=args.mode)
    artifact_result = write_local_scouting_artifacts(
        out_dir=out_dir,
        result=result,
        logger=logger,
        mode=args.mode,
    )
    validation = artifact_result["validation"]
    readiness = artifact_result["manifest"]["readiness"]
    categories = artifact_result["categories"]["categories"]
    print("")
    print(f"Local scouting KG: {artifact_result['out_dir']}")
    print(f"Validation: {'passes' if validation['passes'] else 'fails'} ({validation['status']})")
    print(f"KG load ready: {validation['kg_load_ready']}")
    print(f"Scouting complete: {validation['scouting_complete']}")
    print(f"Entities: {validation['entity_count']}")
    print(f"Relationships: {validation['relationship_count']}")
    print(
        "Categories: "
        + ", ".join(f"{name}={row['entity_count']}" for name, row in sorted(categories.items()))
    )
    if readiness.get("scouting_backlog_count"):
        print(f"Scouting backlog: {readiness['scouting_backlog_count']}")
    if rescout_targets:
        print("Focused re-scout targets: " + ", ".join(f"{target['team']}:{target['claim_type']}" for target in rescout_targets))
    print("Source summaries:")
    for source in artifact_result["manifest"]["scouting_run"]["source_summaries"]:
        print(json.dumps(source, sort_keys=True))


def _load_source_manifests(paths: list[str]) -> list[dict]:
    manifests = []
    for raw_path in paths:
        path = Path(raw_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise SystemExit(f"Source manifest not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid source manifest JSON: {path}") from exc
        if not isinstance(payload, dict):
            raise SystemExit(f"Source manifest must be a JSON object: {path}")
        manifests.append(payload)
    return manifests


def _manifest_values(manifests: list[dict], key: str) -> list[Any]:
    values: list[Any] = []
    for manifest in manifests:
        raw = manifest.get(key)
        if raw is None:
            continue
        if isinstance(raw, str):
            values.append(raw)
        elif isinstance(raw, list):
            values.extend(raw)
        else:
            raise SystemExit(f"Source manifest field '{key}' must be a string or list")
    return values


_TEMPLATE_TOKEN_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _match_template_context(match_entity: dict[str, Any]) -> dict[str, str]:
    attrs = match_entity.get("attributes", {})
    team1 = str(attrs.get("team1") or attrs.get("home_team") or "").strip()
    team2 = str(attrs.get("team2") or attrs.get("away_team") or "").strip()
    match_name = str(match_entity.get("name") or f"{team1} vs {team2}").strip()
    match_date = str(attrs.get("date") or "").strip()
    return {
        "match_id": str(match_entity.get("entity_id") or ""),
        "match_name": match_name,
        "match_slug": _safe_slug(match_name),
        "team1": team1,
        "team2": team2,
        "home_team": team1,
        "away_team": team2,
        "match_date": match_date,
    }


def _render_manifest_value(value: Any, context: dict[str, str]) -> Any:
    if isinstance(value, str):
        return _TEMPLATE_TOKEN_RE.sub(lambda match: context.get(match.group(1), match.group(0)), value)
    if isinstance(value, list):
        return [_render_manifest_value(item, context) for item in value]
    if isinstance(value, dict):
        return {str(key): _render_manifest_value(item, context) for key, item in value.items()}
    return value


def _safe_slug(value: str) -> str:
    return "_".join(_team_key(value).split())[:80] or "match"


def _team_key(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _rescout_targets_from_inputs(*, rescout_from_audit: list[str], scout_focus: list[str]) -> list[dict]:
    targets: list[dict] = []
    for raw_path in rescout_from_audit:
        audit_path = Path(raw_path)
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise SystemExit(f"Scouting audit not found: {audit_path}") from exc
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid scouting audit JSON: {audit_path}") from exc
        for item in audit.get("scouting_backlog", {}).get("items", []):
            if item.get("status") not in {"needs_rescout", "needs_fresh_rescout"}:
                continue
            team = str(item.get("team") or "").strip()
            claim_type = str(item.get("claim_type") or "").strip()
            if not team or not claim_type:
                continue
            targets.append(
                {
                    "team": team,
                    "claim_type": claim_type,
                    "source": str(audit_path),
                    "target_entity_id": str(item.get("target_entity_id") or ""),
                    "status": str(item.get("status") or ""),
                    "quality_status": str(item.get("quality_status") or ""),
                    "quality_reasons": list(item.get("quality_reasons") or []),
                }
            )
    for spec in scout_focus:
        if ":" in spec:
            team, claim_type = spec.split(":", 1)
        elif "=" in spec:
            team, claim_type = spec.split("=", 1)
        else:
            raise SystemExit("--scout-focus must be shaped as TEAM:CLAIM_TYPE")
        team = team.strip()
        claim_type = claim_type.strip()
        if not team or not claim_type:
            raise SystemExit("--scout-focus must include both team and claim type")
        targets.append({"team": team, "claim_type": claim_type, "source": "cli"})

    deduped: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for target in targets:
        key = (str(target.get("team") or "").casefold(), str(target.get("claim_type") or "").casefold())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(target)
    return deduped


if __name__ == "__main__":
    main()
