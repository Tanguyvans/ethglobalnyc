#!/usr/bin/env python3
"""Local MiroFish-inspired lab for Colony multi-agent match runs.

The lab keeps the first-stage scope intentionally local:
- no ENS or wallet setup;
- selectable agent population size;
- mixed agent model species, personas, source weights, and strategies;
- KG-backed scouting followed by room debate and social interactions;
- persistent run artifacts and JSONL logs for later analysis.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field, replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


COLONY_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = COLONY_DIR.parent
if str(COLONY_DIR) not in sys.path:
    sys.path.insert(0, str(COLONY_DIR))

from colony_harness import ColonyHarness
from colony_harness.artifacts import write_compact_run_artifacts
from colony_harness.genes import LLM_MODEL_SPECIES
from colony_harness.models import DebateClaim, RoundResult
from colony_harness.scouting_pipeline import (
    ScoutingRunLogger,
    build_local_scouting_result,
    load_graph_for_local_scouting,
    select_match_entity,
    write_local_scouting_artifacts,
)
from colony_harness.voice import TemplateVoiceModel, llm_voice_model_from_env
from scouting_matrix import (  # type: ignore
    _expanded_modules,
    _load_source_catalog,
    _missing_module_env,
    _pipeline_flags_for_modules,
    _sources_for_match,
    _uses_existing_kg,
)


DEFAULT_KG = COLONY_DIR / "data" / "world_cup_kg.json"
DEFAULT_CATALOG = COLONY_DIR / "config" / "scouting_source_catalog.json"
DEFAULT_RUNS_DIR = COLONY_DIR / "runs" / "agent_lab"
DEFAULT_MODULES = ["existing_kg"]


@dataclass
class LabJob:
    job_id: str
    payload: dict[str, Any]
    run_root: Path
    status: str = "queued"
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    logs: list[str] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""


JOBS: dict[str, LabJob] = {}
JOBS_LOCK = threading.Lock()


class JobScoutingLogger(ScoutingRunLogger):
    def __init__(self, job: LabJob) -> None:
        super().__init__(verbose=False)
        self.job = job

    def event(self, event_type: str, **fields: Any) -> dict[str, Any]:
        row = super().event(event_type, **fields)
        _append_log(self.job, f"[scout] {event_type} {_inline_fields(fields)}".rstrip())
        return row


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve or run the local Colony multi-agent lab.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--kg", default=str(DEFAULT_KG))
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    parser.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    parser.add_argument("--once", action="store_true", help="Run one lab job and exit instead of serving the UI.")
    parser.add_argument("--match", default="Brazil vs Morocco")
    parser.add_argument("--match-id", default="")
    parser.add_argument("--agents", type=int, default=24)
    parser.add_argument("--rooms", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--mode", choices=["fast", "deep"], default="fast")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--voice-mode", choices=["template", "llm"], default="template")
    parser.add_argument("--camel-agents", type=int, default=0)
    parser.add_argument("--module", action="append", default=[], help="KG context or enrichment layer to enable. Repeatable.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    state = {
        "kg": Path(args.kg).resolve(),
        "catalog": Path(args.catalog).resolve(),
        "runs_dir": Path(args.runs_dir).resolve(),
    }
    state["runs_dir"].mkdir(parents=True, exist_ok=True)
    if args.once:
        payload = {
            "match": args.match,
            "match_id": args.match_id,
            "agents": args.agents,
            "rooms": args.rooms,
            "seed": args.seed,
            "mode": args.mode,
            "timeout": args.timeout,
            "voice_mode": args.voice_mode,
            "camel_agents": args.camel_agents,
            "modules": args.module or DEFAULT_MODULES,
        }
        job = _create_job(payload, state)
        _run_lab_job(job, state)
        print(json.dumps(_job_payload(job.job_id), ensure_ascii=False, indent=2, sort_keys=True))
        if job.status != "complete":
            raise SystemExit(1)
        return

    class Handler(LabHandler):
        lab_state = state

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Agent lab: http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


class LabHandler(BaseHTTPRequestHandler):
    lab_state: dict[str, Path]

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route == "/":
            self._send_html(LAB_HTML)
            return
        if route == "/api/config":
            self._send_json(_dashboard_config(self.lab_state))
            return
        if route.startswith("/api/jobs/"):
            job_id = route.rsplit("/", 1)[-1]
            self._send_json(_job_payload(job_id))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route != "/api/run":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
            payload = json.loads(raw.decode("utf-8") or "{}")
            job = _create_job(payload, self.lab_state)
            threading.Thread(target=_run_lab_job, args=(job, self.lab_state), daemon=True).start()
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"job_id": job.job_id, "status": job.status})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, payload: Any, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_html(self, html: str) -> None:
        raw = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _create_job(payload: dict[str, Any], state: dict[str, Path]) -> LabJob:
    cleaned = _clean_payload(payload)
    job_id = time.strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
    run_root = state["runs_dir"] / job_id
    run_root.mkdir(parents=True, exist_ok=False)
    job = LabJob(job_id=job_id, payload=cleaned, run_root=run_root)
    with JOBS_LOCK:
        JOBS[job_id] = job
    (run_root / "request.json").write_text(
        json.dumps(cleaned, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return job


def _clean_payload(payload: dict[str, Any]) -> dict[str, Any]:
    modules = payload.get("modules") or DEFAULT_MODULES
    if isinstance(modules, str):
        modules = [modules]
    normalized_modules = [_normalize_module_name(str(module)) for module in modules if str(module).strip()]
    if not normalized_modules:
        normalized_modules = list(DEFAULT_MODULES)
    agents = _clamp_int(payload.get("agents"), default=24, lower=2, upper=240)
    rooms = _clamp_int(payload.get("rooms"), default=max(2, agents // 6), lower=1, upper=max(1, agents))
    return {
        "match": str(payload.get("match") or "Brazil vs Morocco").strip(),
        "match_id": str(payload.get("match_id") or payload.get("matchId") or "").strip(),
        "agents": agents,
        "rooms": min(rooms, agents),
        "seed": _clamp_int(payload.get("seed"), default=42, lower=0, upper=999999),
        "mode": str(payload.get("mode") or "fast") if str(payload.get("mode") or "fast") in {"fast", "deep"} else "fast",
        "timeout": _clamp_int(payload.get("timeout"), default=20, lower=5, upper=180),
        "voice_mode": str(payload.get("voice_mode") or payload.get("voiceMode") or "template")
        if str(payload.get("voice_mode") or payload.get("voiceMode") or "template") in {"template", "llm"}
        else "template",
        "camel_agents": _clamp_int(payload.get("camel_agents") or payload.get("camelAgents"), default=0, lower=0, upper=8),
        "modules": list(dict.fromkeys(normalized_modules)),
    }


def _run_lab_job(job: LabJob, state: dict[str, Path]) -> None:
    job.status = "running"
    logger = JobScoutingLogger(job)
    try:
        _append_log(job, f"[lab] run_root {job.run_root}")
        graph = load_graph_for_local_scouting(kg_path=state["kg"], offline_sample=False)
        match_entity = select_match_entity(
            graph,
            match_id=job.payload["match_id"] or None,
            match_name=job.payload["match"],
        )
        _append_log(job, f"[kg] selected {match_entity.get('name')}")

        catalog = _load_source_catalog(str(state["catalog"]))
        modules = _lab_expanded_modules(job.payload["modules"], catalog)
        flags = _pipeline_flags_for_modules(
            modules,
            catalog,
            camel_agent_count_override=int(job.payload["camel_agents"]),
        )
        sources = _sources_for_match(match_entity, modules, catalog=catalog, logger=logger)
        existing_kg_paths = [state["kg"]] if _uses_existing_kg(modules, catalog) else []
        _append_log(job, f"[kg] context_layers={','.join(modules)} connector_specs={len(sources)}")

        scouting = build_local_scouting_result(
            match_entity=match_entity,
            mode=job.payload["mode"],
            sources=sources,
            existing_kg_paths=existing_kg_paths,
            merge_existing_kg=False,
            timeout_seconds=int(job.payload["timeout"]),
            include_x=bool(flags["include_x"]),
            include_camel=bool(flags["include_camel"]),
            camel_agent_count=int(flags["camel_agent_count"]),
            include_telegram=bool(flags["include_telegram"]),
            include_polygun=bool(flags["include_polygun"]),
            include_deepseek_scout=bool(flags["include_deepseek_scout"]),
            logger=logger,
        )
        scout_dir = job.run_root / "scouting"
        scout_artifacts = write_local_scouting_artifacts(
            out_dir=scout_dir,
            result=scouting,
            logger=logger,
            mode=job.payload["mode"],
        )
        _append_log(job, f"[kg] built entities={len(scouting.graph.entities)} claims={sum(len(f.evidence_claims) for f in scouting.findings)}")

        voice_model = llm_voice_model_from_env() if job.payload["voice_mode"] == "llm" else TemplateVoiceModel()
        harness = ColonyHarness(
            population_size=int(job.payload["agents"]),
            speaker_slots=int(job.payload["rooms"]),
            seed=int(job.payload["seed"]),
            voice_model=voice_model,
            create_agent_wallets=False,
            wallet_store_path=None,
        )
        _diversify_agent_genomes(harness, seed=int(job.payload["seed"]))
        _append_log(job, f"[agents] deployed {len(harness.agents)} mixed-model agents")

        result = harness.run_round(scouting.match)
        debate_dir = job.run_root / "debate"
        write_compact_run_artifacts(run_dir=debate_dir, match=scouting.match, result=result, debug=True)
        harness.write_jsonl(result, job.run_root / "events.full.jsonl")

        memory = _read_json(debate_dir / "conversation_memory.json", default={})
        manifest = _agent_manifest(harness, result, memory)
        interaction_events = _build_interaction_events(
            job=job,
            result=result,
            agent_manifest=manifest,
            scouting_logger=logger,
            scout_artifacts=scout_artifacts,
        )
        _write_json(job.run_root / "agent_manifest.json", manifest)
        _write_jsonl(job.run_root / "interaction_log.jsonl", interaction_events)
        summary = _run_summary(
            job=job,
            match=scouting.match.to_dict() if hasattr(scouting.match, "to_dict") else {
                "round_id": scouting.match.round_id,
                "home_team": scouting.match.home_team,
                "away_team": scouting.match.away_team,
            },
            result=result,
            scout_artifacts=scout_artifacts,
            agent_manifest=manifest,
            interaction_events=interaction_events,
            memory=memory,
        )
        _write_json(job.run_root / "run_summary.json", summary)
        (job.run_root / "run_report.md").write_text(_run_report(summary), encoding="utf-8")
        job.result = _public_result(summary, manifest, result, memory, interaction_events)
        job.status = "complete"
        _append_log(job, "[lab] complete")
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)
        _append_log(job, f"[error] {type(exc).__name__}: {exc}")
    finally:
        job.ended_at = time.time()
        (job.run_root / "agent_lab_log.jsonl").write_text(
            "".join(json.dumps({"line": line}, ensure_ascii=False, sort_keys=True) + "\n" for line in job.logs),
            encoding="utf-8",
        )


def _dashboard_config(state: dict[str, Path]) -> dict[str, Any]:
    catalog = _load_source_catalog(str(state["catalog"]))
    graph = load_graph_for_local_scouting(kg_path=state["kg"], offline_sample=False)
    kg_inventory = _kg_inventory_by_match(graph)
    matches = [
        {
            "id": str(entity.get("entity_id") or ""),
            "name": str(entity.get("name") or ""),
            "date": str((entity.get("attributes") or {}).get("date") or ""),
            "group": str((entity.get("attributes") or {}).get("group") or ""),
            "venue": str((entity.get("attributes") or {}).get("ground") or (entity.get("attributes") or {}).get("venue") or ""),
            "kg": kg_inventory.get(str(entity.get("entity_id") or ""), {}),
        }
        for entity in graph.get("entities", [])
        if entity.get("entity_type") == "match"
    ]
    matches.sort(key=lambda item: (item["date"], item["name"]))
    modules = []
    for name, module in sorted((catalog.get("modules") or {}).items()):
        if not isinstance(module, dict):
            continue
        missing = _missing_module_env(module)
        modules.append(
            {
                "name": name,
                "description": module.get("description") or "",
                "family": module.get("source_family") or "",
                "status": module.get("status") or "",
                "claim_types": module.get("claim_types") or [],
                "missing_env": missing,
                "default": name in DEFAULT_MODULES,
            }
        )
    return {
        "matches": matches,
        "modules": modules,
        "defaults": {
            "modules": DEFAULT_MODULES,
            "agents": 24,
            "rooms": 5,
            "seed": 42,
            "mode": "fast",
            "timeout": 20,
            "voice_mode": "template",
        },
        "latest_runs": _latest_runs(state["runs_dir"]),
    }


def _kg_inventory_by_match(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    claims = [
        dict(entity.get("attributes") or {})
        for entity in graph.get("entities", [])
        if entity.get("entity_type") == "evidence_claim"
    ]
    by_match: dict[str, dict[str, Any]] = {}
    for entity in graph.get("entities", []):
        if entity.get("entity_type") != "match":
            continue
        match_id = str(entity.get("entity_id") or "")
        attrs = dict(entity.get("attributes") or {})
        teams = {str(attrs.get("team1") or "").casefold(), str(attrs.get("team2") or "").casefold()}
        teams.discard("")
        relevant = [
            claim
            for claim in claims
            if str(claim.get("match_id") or "") in {match_id, match_id.replace("match:", "", 1)}
            or str(claim.get("team") or "").casefold() in teams
            or str(claim.get("subject") or "").casefold() in teams
        ]
        sources = {
            str(claim.get("source_url") or claim.get("source_title") or claim.get("source_domain") or "")
            for claim in relevant
            if claim.get("source_url") or claim.get("source_title") or claim.get("source_domain")
        }
        domains = [
            domain
            for domain, _count in Counter(
                str(claim.get("source_domain") or "").strip()
                for claim in relevant
                if str(claim.get("source_domain") or "").strip()
            ).most_common(5)
        ]
        by_match[match_id] = {
            "evidence_claims": len(relevant),
            "sources": len(sources),
            "source_domains": domains,
        }
    return by_match


def _lab_expanded_modules(requested_modules: list[str], catalog: dict[str, Any]) -> list[str]:
    modules = _expanded_modules(requested_modules, catalog)
    requested = set(requested_modules)
    if "existing_kg" in requested and "fixture" not in requested and "deep_fixture" not in requested:
        modules = [module for module in modules if module != "fixture"]
    return modules


def _latest_runs(runs_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(runs_dir.glob("*/run_summary.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:8]:
        data = _read_json(path, default={})
        if not isinstance(data, dict):
            continue
        rows.append(
            {
                "job_id": path.parent.name,
                "run_root": str(path.parent),
                "match": data.get("match_label", ""),
                "agents": data.get("agent_count", 0),
                "rooms": data.get("room_count", 0),
                "decision": data.get("decision", {}).get("winner", ""),
                "created_at": data.get("created_at", ""),
            }
        )
    return rows


def _job_payload(job_id: str) -> dict[str, Any]:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return {"error": "job not found"}
    return {
        "job_id": job.job_id,
        "status": job.status,
        "payload": job.payload,
        "started_at": job.started_at,
        "ended_at": job.ended_at,
        "elapsed_seconds": round((job.ended_at or time.time()) - job.started_at, 1),
        "run_root": str(job.run_root),
        "logs": job.logs[-600:],
        "result": job.result,
        "error": job.error,
    }


def _diversify_agent_genomes(harness: ColonyHarness, *, seed: int) -> None:
    """Guarantee visible model diversity even in small local populations."""

    rng = random.Random(seed + 991)
    model_cycle = ["parametric", *LLM_MODEL_SPECIES]
    persona_cycle = [
        "cold probabilist",
        "market contrarian",
        "news-sensitive scout",
        "defensive skeptic",
        "model maximalist",
        "quiet value hunter",
    ]
    for index, agent in enumerate(harness.agents):
        model = model_cycle[index % len(model_cycle)]
        estimator = "poisson" if model == "parametric" else "llm"
        persona = persona_cycle[index % len(persona_cycle)]
        if rng.random() < 0.35:
            persona = agent.genome.persona
        agent.genome = replace(agent.genome, estimator=estimator, model=model, persona=persona)  # type: ignore[arg-type]


def _agent_manifest(harness: ColonyHarness, result: RoundResult, memory: dict[str, Any]) -> list[dict[str, Any]]:
    forecasts = {forecast.agent_id: forecast for forecast in result.forecasts}
    views = {view.agent_id: view for view in result.knowledge_views}
    memory_by_agent = {
        str(item.get("speaker_id")): item
        for item in memory.get("debaters", [])
        if isinstance(item, dict)
    }
    manifest = []
    for agent in harness.agents:
        forecast = forecasts.get(agent.agent_id)
        view = views.get(agent.agent_id)
        weights = agent.genome.source_weights.normalized().to_dict()
        memory_record = memory_by_agent.get(agent.agent_id, {})
        manifest.append(
            {
                "agent_id": agent.agent_id,
                "name": agent.name,
                "genome_id": agent.genome_id,
                "model": agent.genome.model,
                "estimator": agent.genome.estimator,
                "persona": agent.genome.persona,
                "strategy": _strategy_label(agent.genome.to_dict(), weights),
                "source_weights": {key: round(value, 4) for key, value in weights.items()},
                "risk_appetite": agent.genome.risk_appetite,
                "edge_threshold": agent.genome.edge_threshold,
                "herd_bias": agent.genome.herd_bias,
                "query_budget": agent.genome.query_budget,
                "access_tier": view.access_tier if view else "",
                "visible_findings": len(view.visible_findings) if view else 0,
                "visible_finding_ids": [finding.finding_id for finding in view.visible_findings] if view else [],
                "risk_profile": forecast.risk_profile if forecast else "",
                "activity_level": forecast.activity_level if forecast else "",
                "influence_weight": forecast.influence_weight if forecast else "",
                "pick": forecast.side if forecast else "",
                "home_probability": forecast.home_probability if forecast else None,
                "edge": forecast.edge if forecast else None,
                "memory": {
                    "claims": memory_record.get("claims", 0),
                    "rooms": memory_record.get("rooms", []),
                    "roles": memory_record.get("roles", []),
                    "disputes_made": memory_record.get("disputes_made", 0),
                    "disputes_received": memory_record.get("disputes_received", 0),
                    "activity_score": memory_record.get("debate_activity_score", 0),
                },
            }
        )
    return manifest


def _build_interaction_events(
    *,
    job: LabJob,
    result: RoundResult,
    agent_manifest: list[dict[str, Any]],
    scouting_logger: ScoutingRunLogger,
    scout_artifacts: dict[str, Any],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    def add(event_type: str, **fields: Any) -> None:
        events.append({"seq": len(events) + 1, "event_type": event_type, **fields})

    for agent in agent_manifest:
        add("agent_deployed", **agent)
    for scout_event in scouting_logger.events:
        scout_payload = dict(scout_event)
        scout_payload["scout_event_type"] = scout_payload.pop("event_type", "")
        add("scout_event", **scout_payload)
    validation = scout_artifacts.get("validation", {})
    add(
        "kg_ready",
        status=validation.get("status"),
        entities=validation.get("entity_count"),
        relationships=validation.get("relationship_count"),
        findings=len(result.findings),
        claims=sum(len(finding.evidence_claims) for finding in result.findings),
    )
    agents_by_id = {agent["agent_id"]: agent for agent in agent_manifest}
    for view in result.knowledge_views:
        add(
            "agent_query_kg",
            agent_id=view.agent_id,
            model=agents_by_id.get(view.agent_id, {}).get("model", ""),
            persona=agents_by_id.get(view.agent_id, {}).get("persona", ""),
            strategy=agents_by_id.get(view.agent_id, {}).get("strategy", ""),
            access_tier=view.access_tier,
            visible_findings=len(view.visible_findings),
            visible_finding_ids=[finding.finding_id for finding in view.visible_findings],
        )
    for room in result.rooms:
        add(
            "debate_room_opened",
            room_id=room.room_id,
            topic=room.evidence_focus,
            participants=len(room.participant_ids),
            representative_ids=room.representative_ids,
            synthesis_home_probability=room.synthesis_home_probability,
            synthesis=room.synthesis,
        )
        for claim in room.claims:
            add("agent_message", **_claim_event_fields(claim, agents_by_id))
    for claim in result.claims:
        add("final_synthesis", **_claim_event_fields(claim, agents_by_id))
    for action in result.social_actions:
        add("social_action", **action.to_dict())
    for forecast in result.forecasts:
        add(
            "agent_forecast",
            agent_id=forecast.agent_id,
            genome_id=forecast.genome_id,
            access_tier=forecast.access_tier,
            visible_findings=forecast.visible_findings,
            persona=forecast.persona,
            risk_profile=forecast.risk_profile,
            social_stance=forecast.social_stance,
            activity_level=forecast.activity_level,
            influence_weight=forecast.influence_weight,
            home_probability=forecast.home_probability,
            market_edge=forecast.market_edge,
            edge_threshold=forecast.edge_threshold,
            edge=forecast.edge,
            side=forecast.side,
            stake=forecast.stake,
            bankroll=forecast.bankroll,
            decision_reason=forecast.decision_reason,
        )
    decision = result.collective_decision
    add(
        "collective_decision",
        round_id=decision.round_id,
        match=decision.match,
        prediction=decision.prediction,
        recommendation=decision.recommendation,
        internal_metrics=decision.internal_metrics,
        vote_breakdown=decision.vote_breakdown,
        top_supporters=[_compact_supporter(item) for item in decision.top_supporters[:8]],
    )
    add("run_complete", job_id=job.job_id, run_root=str(job.run_root))
    return events


def _claim_event_fields(claim: DebateClaim, agents_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    agent = agents_by_id.get(claim.speaker_id, {})
    return {
        "round_id": claim.round_id,
        "room_id": claim.room_id,
        "phase": claim.debate_phase,
        "role": claim.debate_role,
        "speaker_id": claim.speaker_id,
        "speaker_name": claim.speaker_name,
        "model": claim.model,
        "persona": claim.persona,
        "strategy": agent.get("strategy", ""),
        "claim_type": claim.claim_type,
        "direction": claim.direction,
        "confidence": claim.confidence,
        "message": claim.message,
        "evidence_tags": claim.evidence_tags,
        "referenced_evidence": [_compact_evidence(item) for item in claim.referenced_evidence[:4]],
        "dispute": claim.dispute,
        "genome_id": claim.genome_id,
    }


def _compact_evidence(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "finding_id": item.get("finding_id", ""),
        "claim_type": item.get("claim_type", ""),
        "subject": item.get("subject") or item.get("team") or item.get("player") or "",
        "team": item.get("team", ""),
        "player": item.get("player", ""),
        "claim": item.get("claim", ""),
        "source_title": item.get("source_title") or item.get("scout_name") or "",
        "source_url": item.get("source_url", ""),
        "source_quality": item.get("source_quality", ""),
        "confidence": item.get("confidence"),
    }


def _compact_supporter(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent_id": item.get("agent_id", ""),
        "genome_id": item.get("genome_id", ""),
        "persona": item.get("persona", ""),
        "forecast_side": item.get("forecast_side", ""),
        "home_probability": item.get("home_probability"),
        "edge": item.get("edge"),
        "weight": item.get("weight"),
        "risk_profile": item.get("risk_profile", ""),
        "decision_reason": item.get("decision_reason", ""),
    }


def _run_summary(
    *,
    job: LabJob,
    match: dict[str, Any],
    result: RoundResult,
    scout_artifacts: dict[str, Any],
    agent_manifest: list[dict[str, Any]],
    interaction_events: list[dict[str, Any]],
    memory: dict[str, Any],
) -> dict[str, Any]:
    model_counts = Counter(str(agent["model"]) for agent in agent_manifest)
    persona_counts = Counter(str(agent["persona"]) for agent in agent_manifest)
    strategy_counts = Counter(str(agent["strategy"]) for agent in agent_manifest)
    decision = result.collective_decision.recommendation
    return {
        "job_id": job.job_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "run_root": str(job.run_root),
        "match_label": f"{result.collective_decision.match.get('home_team')} vs {result.collective_decision.match.get('away_team')}",
        "match": match,
        "modules": job.payload["modules"],
        "mode": job.payload["mode"],
        "agent_count": len(agent_manifest),
        "room_count": len(result.rooms),
        "finding_count": len(result.findings),
        "evidence_claim_count": sum(len(finding.evidence_claims) for finding in result.findings),
        "interaction_event_count": len(interaction_events),
        "model_counts": dict(model_counts.most_common()),
        "persona_counts": dict(persona_counts.most_common()),
        "strategy_counts": dict(strategy_counts.most_common()),
        "decision": {
            "side": decision.get("side"),
            "winner": decision.get("winner"),
            "confidence": result.collective_decision.prediction.get("confidence"),
            "sentence": result.collective_decision.prediction.get("sentence"),
            "value": result.collective_decision.prediction.get("value"),
        },
        "debate": {
            "rooms": len(result.rooms),
            "room_claims": sum(len(room.claims) for room in result.rooms),
            "final_claims": len(result.claims),
            "social_actions": len(result.social_actions),
            "disputes": result.summary.get("dispute_count", 0),
            "dispute_rate": result.summary.get("dispute_rate", 0.0),
        },
        "memory": memory.get("summary", {}),
        "artifacts": {
            "scouting": scout_artifacts.get("out_dir"),
            "debate": str(job.run_root / "debate"),
            "agent_manifest": str(job.run_root / "agent_manifest.json"),
            "interaction_log": str(job.run_root / "interaction_log.jsonl"),
            "full_events": str(job.run_root / "events.full.jsonl"),
            "conversation_memory": str(job.run_root / "debate" / "conversation_memory.json"),
            "summary": str(job.run_root / "run_summary.json"),
        },
    }


def _public_result(
    summary: dict[str, Any],
    manifest: list[dict[str, Any]],
    result: RoundResult,
    memory: dict[str, Any],
    interaction_events: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "summary": summary,
        "agents": manifest[:80],
        "rooms": [
            {
                "room_id": room.room_id,
                "topic": room.evidence_focus,
                "participants": len(room.participant_ids),
                "representative_ids": room.representative_ids,
                "synthesis_home_probability": room.synthesis_home_probability,
                "synthesis": room.synthesis,
            }
            for room in result.rooms
        ],
        "memory": {
            "summary": memory.get("summary", {}),
            "top_debaters": sorted(
                memory.get("debaters", []),
                key=lambda item: item.get("debate_activity_score", 0),
                reverse=True,
            )[:20]
            if isinstance(memory.get("debaters", []), list)
            else [],
        },
        "timeline": [
            event
            for event in interaction_events
            if event["event_type"] in {"scout_event", "kg_ready", "agent_query_kg", "debate_room_opened", "agent_message", "final_synthesis", "agent_forecast", "collective_decision"}
        ][:500],
    }


def _run_report(summary: dict[str, Any]) -> str:
    lines = [
        f"# Agent Lab Run: {summary['job_id']}",
        "",
        f"- Match: {summary['match_label']}",
        f"- Agents: {summary['agent_count']}",
        f"- Rooms: {summary['room_count']}",
        f"- Findings: {summary['finding_count']} findings, {summary['evidence_claim_count']} evidence claims",
        f"- Interactions: {summary['interaction_event_count']} logged events",
        f"- Decision: {summary['decision'].get('winner')} ({summary['decision'].get('confidence')})",
        "",
        "## Model Mix",
        "",
    ]
    lines.extend(f"- {model}: {count}" for model, count in summary["model_counts"].items())
    lines.extend(["", "## Artifacts", ""])
    lines.extend(f"- {name}: `{path}`" for name, path in summary["artifacts"].items())
    return "\n".join(lines) + "\n"


def _strategy_label(genome: dict[str, Any], weights: dict[str, float]) -> str:
    top_source = max(weights, key=weights.get)
    risk = float(genome.get("risk_appetite") or 0.0)
    herd_bias = float(genome.get("herd_bias") or 0.0)
    risk_label = "risk-on" if risk >= 0.13 else "capital-preserving" if risk <= 0.06 else "balanced"
    crowd_label = "contrarian" if herd_bias < -0.25 else "crowd-aware" if herd_bias > 0.35 else "independent"
    query_budget = float(genome.get("query_budget") or 0.0)
    query_label = "deep-query" if query_budget >= 1.5 else "selective-query" if query_budget >= 0.7 else "cheap-query"
    return f"{risk_label} {top_source} {crowd_label} {query_label}"


def _normalize_module_name(name: str) -> str:
    cleaned = name.strip().replace("-", "_")
    if cleaned == "deep_fixture":
        return "deep_fixture"
    return cleaned


def _clamp_int(value: Any, *, default: int, lower: int, upper: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(lower, min(upper, parsed))


def _inline_fields(fields: dict[str, Any]) -> str:
    parts = []
    for key, value in fields.items():
        if value in {None, ""}:
            continue
        text = str(value)
        if len(text) > 90:
            text = text[:87] + "..."
        parts.append(f"{key}={text}")
    return " ".join(parts)


def _append_log(job: LabJob, line: str) -> None:
    with JOBS_LOCK:
        job.logs.append(line)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _read_json(path: Path, *, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


LAB_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Colony Agent Interaction Lab</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f4;
      --ink: #1d2421;
      --muted: #607069;
      --line: #d9dfd7;
      --panel: #ffffff;
      --green: #1f7a58;
      --blue: #245f9d;
      --red: #9b3d36;
      --amber: #9a6a1f;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      padding: 16px 20px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfa;
      position: sticky;
      top: 0;
      z-index: 5;
    }
    h1 { font-size: 18px; line-height: 1.2; margin: 0; letter-spacing: 0; }
    h2 { font-size: 14px; margin: 0 0 10px; letter-spacing: 0; }
    main {
      display: grid;
      grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
      gap: 16px;
      padding: 16px;
      align-items: start;
    }
    section, aside {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    aside { padding: 14px; position: sticky; top: 72px; }
    .workspace { display: grid; gap: 16px; }
    .panel { padding: 14px; }
    label { display: grid; gap: 6px; color: var(--muted); font-size: 12px; margin-bottom: 12px; }
    select, input {
      width: 100%;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 6px;
      padding: 8px 9px;
      font: inherit;
      min-height: 36px;
    }
    .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .modules { max-height: 250px; overflow: auto; border: 1px solid var(--line); border-radius: 6px; padding: 8px; }
    .check {
      display: grid;
      grid-template-columns: 18px minmax(0, 1fr);
      gap: 8px;
      align-items: start;
      margin: 0 0 8px;
      color: var(--ink);
    }
    .check input { min-height: auto; margin-top: 2px; }
    .check small { display: block; color: var(--muted); line-height: 1.35; overflow-wrap: anywhere; }
    button {
      width: 100%;
      border: 0;
      border-radius: 6px;
      background: var(--green);
      color: #fff;
      padding: 10px 12px;
      font-weight: 700;
      cursor: pointer;
      min-height: 40px;
    }
    button:disabled { opacity: .55; cursor: not-allowed; }
    .status { color: var(--muted); font-size: 13px; }
    .metrics { display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 10px; }
    .metric { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfa; }
    .metric strong { display: block; font-size: 22px; line-height: 1; margin-bottom: 6px; }
    .metric span { color: var(--muted); font-size: 12px; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    th, td { border-bottom: 1px solid var(--line); padding: 8px; text-align: left; vertical-align: top; }
    th { color: var(--muted); font-weight: 700; background: #fbfcfa; position: sticky; top: 0; }
    .scroll { overflow: auto; max-height: 430px; border: 1px solid var(--line); border-radius: 6px; }
    .pill { display: inline-block; border-radius: 999px; padding: 2px 7px; background: #edf4ef; color: var(--green); font-size: 11px; font-weight: 700; }
    .pill.blue { background: #edf3fa; color: var(--blue); }
    .pill.red { background: #faeeee; color: var(--red); }
    .timeline { display: grid; gap: 8px; max-height: 500px; overflow: auto; }
    .event { border-left: 3px solid var(--line); padding: 8px 10px; background: #fbfcfa; border-radius: 0 6px 6px 0; }
    .event b { font-size: 12px; }
    .event p { margin: 5px 0 0; color: var(--muted); font-size: 12px; line-height: 1.4; overflow-wrap: anywhere; }
    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 11px;
      line-height: 1.45;
      max-height: 260px;
      overflow: auto;
      background: #202622;
      color: #edf3ee;
      border-radius: 6px;
      padding: 10px;
    }
    a { color: var(--blue); }
    @media (max-width: 900px) {
      main { grid-template-columns: 1fr; }
      aside { position: static; }
      .metrics { grid-template-columns: 1fr 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Colony Agent Interaction Lab</h1>
    <div id="topStatus" class="status">Idle</div>
  </header>
  <main>
    <aside>
      <h2>Run</h2>
      <label>Match <select id="match"></select></label>
      <div id="kgInfo" class="event" style="margin-bottom:12px"></div>
      <div class="grid2">
        <label>Agents <input id="agents" type="number" min="2" max="240"></label>
        <label>Rooms <input id="rooms" type="number" min="1" max="80"></label>
      </div>
      <div class="grid2">
        <label>Seed <input id="seed" type="number" min="0" max="999999"></label>
        <label>Timeout <input id="timeout" type="number" min="5" max="180"></label>
      </div>
      <div class="grid2">
        <label>Mode
          <select id="mode"><option value="fast">fast</option><option value="deep">deep</option></select>
        </label>
        <label>Voice
          <select id="voice"><option value="template">template</option><option value="llm">llm</option></select>
        </label>
      </div>
      <h2>KG Context</h2>
      <p class="status">Agents query the match KG first. These layers reuse or enrich that KG before the debate starts.</p>
      <div id="modules" class="modules"></div>
      <button id="run">Run pipeline</button>
      <p class="status" id="runRoot"></p>
    </aside>
    <div class="workspace">
      <section class="panel">
        <h2>Summary</h2>
        <div id="metrics" class="metrics"></div>
      </section>
      <section class="panel">
        <h2>Agents</h2>
        <div class="scroll"><table id="agentsTable"></table></div>
      </section>
      <section class="panel">
        <h2>Rooms</h2>
        <div class="scroll"><table id="roomsTable"></table></div>
      </section>
      <section class="panel">
        <h2>Interaction Timeline</h2>
        <div id="timeline" class="timeline"></div>
      </section>
      <section class="panel">
        <h2>Memory</h2>
        <div class="scroll"><table id="memoryTable"></table></div>
      </section>
      <section class="panel">
        <h2>Logs</h2>
        <pre id="logs"></pre>
      </section>
    </div>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    let currentJob = null;
    let pollTimer = null;

    async function init() {
      const cfg = await fetch('/api/config').then(r => r.json());
      window.__matches = cfg.matches;
      const defaultMatch = cfg.matches.find(m => (m.kg?.evidence_claims || 0) > 0) || cfg.matches[0] || {};
      $('match').innerHTML = cfg.matches.map(m => {
        const selected = m.name === defaultMatch.name ? 'selected' : '';
        return `<option value="${esc(m.name)}" ${selected}>${esc(m.date)} - ${esc(m.name)}</option>`;
      }).join('');
      const d = cfg.defaults;
      $('agents').value = d.agents;
      $('rooms').value = d.rooms;
      $('seed').value = d.seed;
      $('timeout').value = d.timeout;
      $('mode').value = d.mode;
      $('voice').value = d.voice_mode;
      $('modules').innerHTML = cfg.modules.map(m => {
        const checked = m.default ? 'checked' : '';
        const disabled = m.missing_env.length ? '' : '';
        const missing = m.missing_env.length ? `missing ${esc(m.missing_env.join(', '))}` : esc(m.family || m.status);
        const label = m.name === 'existing_kg' ? 'selected match KG' : m.name;
        return `<label class="check"><input type="checkbox" name="module" value="${esc(m.name)}" ${checked} ${disabled}><span>${esc(label)}<small>${missing}</small></span></label>`;
      }).join('');
      $('match').addEventListener('change', renderKgInfo);
      renderKgInfo();
      renderEmpty();
    }

    function renderKgInfo() {
      const selected = (window.__matches || []).find(m => m.name === $('match').value) || {};
      const kg = selected.kg || {};
      const domains = (kg.source_domains || []).join(', ') || 'no domains yet';
      $('kgInfo').innerHTML = `<b>KG inventory</b><p>${esc(kg.evidence_claims || 0)} evidence claims, ${esc(kg.sources || 0)} provenance sources. ${esc(domains)}</p>`;
    }

    $('run').addEventListener('click', async () => {
      const modules = [...document.querySelectorAll('#modules input:checked')].map(i => i.value);
      const payload = {
        match: $('match').value,
        agents: Number($('agents').value),
        rooms: Number($('rooms').value),
        seed: Number($('seed').value),
        timeout: Number($('timeout').value),
        mode: $('mode').value,
        voice_mode: $('voice').value,
        modules
      };
      $('run').disabled = true;
      const response = await fetch('/api/run', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      }).then(r => r.json());
      if (response.error) {
        $('topStatus').textContent = response.error;
        $('run').disabled = false;
        return;
      }
      currentJob = response.job_id;
      clearInterval(pollTimer);
      pollTimer = setInterval(poll, 1200);
      poll();
    });

    async function poll() {
      if (!currentJob) return;
      const job = await fetch(`/api/jobs/${currentJob}`).then(r => r.json());
      renderJob(job);
      if (job.status === 'complete' || job.status === 'failed') {
        clearInterval(pollTimer);
        $('run').disabled = false;
      }
    }

    function renderJob(job) {
      $('topStatus').textContent = `${job.status} - ${job.elapsed_seconds}s`;
      $('runRoot').textContent = job.run_root || '';
      $('logs').textContent = (job.logs || []).join('\n');
      const result = job.result || {};
      const summary = result.summary || {};
      renderMetrics(summary, job);
      renderAgents(result.agents || []);
      renderRooms(result.rooms || []);
      renderTimeline(result.timeline || []);
      renderMemory((result.memory || {}).top_debaters || []);
    }

    function renderEmpty() {
      renderMetrics({}, {status: 'idle'});
      renderAgents([]);
      renderRooms([]);
      renderTimeline([]);
      renderMemory([]);
      $('logs').textContent = '';
    }

    function renderMetrics(summary, job) {
      const d = summary.debate || {};
      const decision = summary.decision || {};
      const items = [
        ['Status', job.status || 'idle'],
        ['Agents', summary.agent_count || 0],
        ['Claims', summary.evidence_claim_count || 0],
        ['Events', summary.interaction_event_count || 0],
        ['Rooms', d.rooms || 0],
        ['Social', d.social_actions || 0],
        ['Disputes', d.disputes || 0],
        ['Decision', decision.winner || 'pending']
      ];
      $('metrics').innerHTML = items.map(([k, v]) => `<div class="metric"><strong>${esc(v)}</strong><span>${esc(k)}</span></div>`).join('');
    }

    function renderAgents(rows) {
      $('agentsTable').innerHTML = table(
        ['Agent', 'Model', 'Persona', 'Strategy', 'Access', 'Pick', 'Memory'],
        rows.map(a => [
          a.agent_id,
          `<span class="pill blue">${esc(a.model)}</span>`,
          a.persona,
          a.strategy,
          a.access_tier,
          `<span class="pill">${esc(a.pick || '')}</span> ${a.home_probability ?? ''}`,
          `claims ${a.memory?.claims || 0}, disputes ${a.memory?.disputes_made || 0}`
        ])
      );
    }

    function renderRooms(rows) {
      $('roomsTable').innerHTML = table(
        ['Room', 'Topic', 'Participants', 'Representatives', 'Synthesis'],
        rows.map(r => [r.room_id, r.topic, r.participants, (r.representative_ids || []).join(', '), r.synthesis])
      );
    }

    function renderTimeline(rows) {
      $('timeline').innerHTML = rows.slice(0, 220).map(ev => {
        const title = `${ev.seq || ''} ${ev.event_type} ${ev.speaker_id || ev.agent_id || ev.room_id || ''}`;
        const text = ev.message || ev.synthesis || ev.text || ev.status || ev.match || ev.decision?.sentence || '';
        const tag = ev.model ? `<span class="pill blue">${esc(ev.model)}</span> ` : '';
        return `<div class="event"><b>${esc(title)}</b> ${tag}<p>${esc(text)}</p></div>`;
      }).join('');
    }

    function renderMemory(rows) {
      $('memoryTable').innerHTML = table(
        ['Agent', 'Model', 'Persona', 'Claims', 'Made', 'Received', 'Score'],
        rows.map(r => [r.speaker_id, r.model, r.persona, r.claims, r.disputes_made, r.disputes_received, r.debate_activity_score])
      );
    }

    function table(headers, rows) {
      const head = `<thead><tr>${headers.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead>`;
      const body = `<tbody>${rows.map(row => `<tr>${row.map(cell => `<td>${cell == null ? '' : cell}</td>`).join('')}</tr>`).join('')}</tbody>`;
      return head + body;
    }

    function esc(value) {
      return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    }

    init().catch(err => { $('topStatus').textContent = err.message; });
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
