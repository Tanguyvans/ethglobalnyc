#!/usr/bin/env python3
"""Tiny local dashboard for running scouting plugins into KG artifacts.

This is intentionally not the full Colony app. It serves one local HTML page,
starts `scouting_matrix.py` jobs, streams/polls logs, and reads the generated KG
artifacts back for inspection.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

COLONY_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = COLONY_DIR.parent
if str(COLONY_DIR) not in sys.path:
    sys.path.insert(0, str(COLONY_DIR))

from colony_harness.env import load_env_file
from colony_harness.scouting_pipeline import KG_CATEGORY_ENTITY_TYPES, load_graph_for_local_scouting


DEFAULT_KG = COLONY_DIR / "data" / "world_cup_kg.json"
DEFAULT_ENV = COLONY_DIR / ".env"
DEFAULT_CATALOG = COLONY_DIR / "config" / "scouting_source_catalog.json"
DEFAULT_RUN_DIR = COLONY_DIR / "runs" / "scouting_kg" / "dashboard"
SCOUTING_MATRIX = COLONY_DIR / "scouting_matrix.py"
DEFAULT_DASHBOARD_MODULES = ["fixture", "polymarket_market_context"]


@dataclass
class DashboardJob:
    job_id: str
    command: list[str]
    run_root: Path
    status: str = "queued"
    returncode: int | None = None
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    logs: list[str] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""


JOBS: dict[str, DashboardJob] = {}
JOBS_LOCK = threading.Lock()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the local scouting KG dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--kg", default=str(DEFAULT_KG))
    parser.add_argument("--env", default=str(DEFAULT_ENV), help="Optional .env path for scouting provider settings.")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    parser.add_argument("--runs-dir", default=str(DEFAULT_RUN_DIR))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_env_file(args.env)
    state = {
        "kg": Path(args.kg),
        "env": Path(args.env),
        "catalog": Path(args.catalog),
        "runs_dir": Path(args.runs_dir),
    }
    state["runs_dir"].mkdir(parents=True, exist_ok=True)

    class Handler(DashboardHandler):
        dashboard_state = state

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Scouting dashboard: http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


class DashboardHandler(BaseHTTPRequestHandler):
    dashboard_state: dict[str, Path]

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route == "/":
            self._send_html(DASHBOARD_HTML)
            return
        if route == "/api/config":
            self._send_json(
                _dashboard_config(
                    self.dashboard_state["kg"],
                    self.dashboard_state["catalog"],
                    self.dashboard_state["runs_dir"],
                )
            )
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
            body = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
            payload = json.loads(body.decode("utf-8") or "{}")
            job = _start_job(payload, self.dashboard_state)
        except Exception as exc:  # pragma: no cover - returned to local UI
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"job_id": job.job_id, "status": job.status})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, payload: Any, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
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


def _dashboard_config(kg_path: Path, catalog_path: Path, runs_dir: Path) -> dict[str, Any]:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    graph = load_graph_for_local_scouting(kg_path=kg_path, offline_sample=False)
    matches = [
        {
            "id": str(entity.get("entity_id") or ""),
            "name": str(entity.get("name") or ""),
            "date": str((entity.get("attributes") or {}).get("date") or ""),
            "group": str((entity.get("attributes") or {}).get("group") or ""),
            "venue": str((entity.get("attributes") or {}).get("ground") or (entity.get("attributes") or {}).get("venue") or ""),
        }
        for entity in graph.get("entities", [])
        if entity.get("entity_type") == "match"
    ]
    matches.sort(key=lambda item: (item["date"], item["name"]))
    catalog_modules = catalog.get("modules") or {}
    modules = []
    for name, module in catalog_modules.items():
        if not isinstance(module, dict):
            continue
        if module.get("ui_hidden"):
            continue
        env_status = _module_env_status(name, catalog_modules)
        modules.append(
            {
                "name": name,
                "display_name": module.get("display_name") or name,
                "status": module.get("status") or "",
                "family": module.get("source_family") or "",
                "description": module.get("description") or "",
                "docs_url": module.get("docs_url") or "",
                "setup_url": module.get("setup_url") or "",
                "setup_hint": module.get("setup_hint") or "",
                "claim_types": module.get("claim_types") or [],
                "requires_env": module.get("requires_env") or [],
                "requires_any_env": module.get("requires_any_env") or [],
                "env_ready": env_status["ready"],
                "missing_env": env_status["missing"],
                "includes": module.get("includes") or [],
                "ui_order": int(module.get("ui_order") or 999),
            }
        )
    modules.sort(key=lambda item: (item["ui_order"], item["display_name"], item["name"]))
    return {
        "matches": matches,
        "modules": modules,
        "datasources": catalog.get("datasources") or [],
        "categories": {key: list(value) for key, value in KG_CATEGORY_ENTITY_TYPES.items()},
        "defaults": {"modules": DEFAULT_DASHBOARD_MODULES, "mode": "fast"},
        "latest_results": _latest_disk_results(runs_dir),
    }


def _module_env_status(module_name: str, modules: dict[str, Any]) -> dict[str, Any]:
    missing: list[str] = []
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        module = modules.get(name)
        if not isinstance(module, dict):
            return
        required = module.get("requires_env") or []
        if isinstance(required, str):
            required = [required]
        for env_name in required:
            env_key = str(env_name)
            if env_key and not os.getenv(env_key):
                missing.append(env_key)
        for group in module.get("requires_any_env") or []:
            group_names = [
                str(env_name)
                for env_name in (group if isinstance(group, list) else [group])
                if str(env_name)
            ]
            if group_names and not any(os.getenv(env_name) for env_name in group_names):
                missing.append("one_of(" + "|".join(group_names) + ")")
        for included in module.get("includes") or []:
            visit(str(included))

    visit(module_name)
    return {"ready": not missing, "missing": sorted(dict.fromkeys(missing))}


def _latest_disk_results(runs_dir: Path) -> dict[str, Any] | None:
    result_files = sorted(
        [path for path in runs_dir.glob("**/matrix_results.json") if "/smoke/" not in str(path)],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not result_files:
        return None
    run_root = result_files[0].parent
    logs = []
    for log_path in sorted(run_root.glob("*/scouting_log.jsonl")):
        try:
            logs.extend(log_path.read_text(encoding="utf-8").splitlines())
        except OSError:
            continue
    return {
        "run_root": str(run_root),
        "logs": logs[-500:],
        "results": _read_job_results(run_root),
    }


def _start_job(payload: dict[str, Any], state: dict[str, Path]) -> DashboardJob:
    match_name = str(payload.get("match") or "").strip()
    if not match_name:
        raise ValueError("Choose a match first.")
    modules = [str(item).strip() for item in payload.get("modules") or [] if str(item).strip()]
    if not modules:
        modules = list(DEFAULT_DASHBOARD_MODULES)
    mode = str(payload.get("mode") or "fast")
    if mode not in {"fast", "deep"}:
        raise ValueError("mode must be fast or deep")
    timeout = int(payload.get("timeout") or 30)
    timeout = max(5, min(timeout, 180))
    camel_agents = int(payload.get("camel_agents") or payload.get("camelAgents") or 4)
    camel_agents = max(1, min(camel_agents, 6))

    job_id = time.strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
    run_root = state["runs_dir"] / job_id
    command = [
        sys.executable,
        str(SCOUTING_MATRIX),
        "--kg",
        str(state["kg"]),
        "--env",
        str(state["env"]),
        "--source-catalog",
        str(state["catalog"]),
        "--match",
        match_name,
        "--mode",
        mode,
        "--timeout",
        str(timeout),
        "--camel-agents",
        str(camel_agents),
        "--out-dir",
        str(run_root),
    ]
    for module in modules:
        command.extend(["--module", module])

    job = DashboardJob(job_id=job_id, command=command, run_root=run_root)
    with JOBS_LOCK:
        JOBS[job_id] = job
    threading.Thread(target=_run_job, args=(job,), daemon=True).start()
    return job


def _run_job(job: DashboardJob) -> None:
    job.status = "running"
    job.logs.append("$ " + " ".join(job.command))
    try:
        process = subprocess.Popen(
            job.command,
            cwd=str(WORKSPACE_DIR),
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            job.logs.append(line.rstrip())
        job.returncode = process.wait()
        job.status = "complete" if job.returncode == 0 else "failed"
    except Exception as exc:  # pragma: no cover - surfaced in local UI
        job.status = "failed"
        job.error = str(exc)
        job.logs.append(f"dashboard_error: {exc}")
    finally:
        job.ended_at = time.time()
        job.results = _read_job_results(job.run_root)


def _job_payload(job_id: str) -> dict[str, Any]:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return {"error": "job not found"}
    if job.status in {"complete", "failed"} and not job.results:
        job.results = _read_job_results(job.run_root)
    return {
        "job_id": job.job_id,
        "status": job.status,
        "returncode": job.returncode,
        "started_at": job.started_at,
        "ended_at": job.ended_at,
        "elapsed_seconds": round((job.ended_at or time.time()) - job.started_at, 1),
        "run_root": str(job.run_root),
        "logs": job.logs[-500:],
        "results": job.results,
        "error": job.error,
    }


def _read_job_results(run_root: Path) -> list[dict[str, Any]]:
    results_path = run_root / "matrix_results.json"
    if not results_path.exists():
        return []
    try:
        rows = json.loads(results_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    enriched = []
    for row in rows:
        out_dir = Path(str(row.get("out_dir") or ""))
        item = dict(row)
        item["summary_path"] = str(out_dir / "summary.md")
        item["categories"] = _graph_categories(out_dir / "world_graph.json") or _safe_json(out_dir / "kg_categories.json")
        item["audit"] = _safe_json(out_dir / "scouting_audit.json")
        item["graph_preview"] = _graph_preview(out_dir / "world_graph.json")
        item["finding_preview"] = _finding_preview(out_dir / "findings.json")
        item["market_context"] = _market_context_preview(out_dir / "findings.json")
        item["structure_audit"] = _structure_audit(out_dir / "world_graph.json", out_dir / "findings.json")
        item["views"] = _artifact_views(out_dir, item)
        enriched.append(item)
    return enriched


def _safe_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _artifact_views(out_dir: Path, matrix_row: dict[str, Any]) -> dict[str, Any]:
    domain_graph_path = out_dir / "domain_graph.json"
    knowledge_views_path = out_dir / "knowledge_views.json"
    summary_path = out_dir / "scouting_run_summary.json"
    world_graph_path = out_dir / "world_graph.json"
    findings_path = out_dir / "findings.json"
    audit_path = out_dir / "scouting_audit.json"

    domain_graph = _safe_json(domain_graph_path)
    knowledge_views = _safe_json(knowledge_views_path)
    run_summary = _safe_json(summary_path)
    world_graph = _safe_json(world_graph_path)
    findings_value = _safe_json(findings_path)
    audit_value = _safe_json(audit_path)

    findings = findings_value if isinstance(findings_value, list) else []
    audit = audit_value if isinstance(audit_value, dict) else {}
    artifacts = {
        "domain_graph": _artifact_state(domain_graph_path),
        "knowledge_views": _artifact_state(knowledge_views_path),
        "scouting_run_summary": _artifact_state(summary_path),
        "world_graph": _artifact_state(world_graph_path),
        "findings": _artifact_state(findings_path),
        "scouting_audit": _artifact_state(audit_path),
    }
    return {
        "artifacts": artifacts,
        "knowledge_views": _knowledge_views_summary(knowledge_views),
        "summary": _run_summary_preview(run_summary),
        "domain": _domain_artifact_view(domain_graph, world_graph),
        "evidence": _evidence_artifact_view(knowledge_views, findings),
        "provenance": _provenance_artifact_view(knowledge_views, run_summary, findings, audit, matrix_row),
        "gaps": _gaps_artifact_view(run_summary, audit, matrix_row),
    }


def _artifact_state(path: Path) -> dict[str, Any]:
    return {"path": str(path), "available": path.exists()}


def _knowledge_views_summary(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "available": True,
            "shape": "object",
            "keys": sorted(str(key) for key in value.keys())[:24],
        }
    if isinstance(value, list):
        sample_keys = []
        for item in value[:5]:
            if isinstance(item, dict):
                sample_keys.append(sorted(str(key) for key in item.keys())[:12])
        return {
            "available": True,
            "shape": "list",
            "count": len(value),
            "sample_keys": sample_keys,
        }
    return {"available": False, "shape": "missing"}


def _run_summary_preview(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    preferred = [
        "status",
        "match",
        "mode",
        "modules",
        "findings",
        "claims",
        "entities",
        "relationships",
        "scouting_complete",
        "kg_load_ready",
    ]
    preview = {key: _preview_value(key, value.get(key)) for key in preferred if key in value}
    for key, item in value.items():
        if len(preview) >= 14:
            break
        if key not in preview and not isinstance(item, (dict, list)):
            preview[str(key)] = _shorten(item, 180)
    return preview


def _normal_graph(graph: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(graph, dict):
        return [], []
    raw_entities = graph.get("entities")
    if not isinstance(raw_entities, list):
        raw_entities = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    raw_relationships = graph.get("relationships")
    if not isinstance(raw_relationships, list):
        raw_relationships = graph.get("edges") if isinstance(graph.get("edges"), list) else []

    entities = []
    for entity in raw_entities:
        if not isinstance(entity, dict):
            continue
        entity_id = entity.get("entity_id") or entity.get("id") or entity.get("node_id")
        entity_type = entity.get("entity_type") or entity.get("type") or entity.get("kind") or "unknown"
        if not entity_id:
            continue
        attrs = entity.get("attributes")
        if not isinstance(attrs, dict):
            attrs = {
                str(key): value
                for key, value in entity.items()
                if key not in {"entity_id", "id", "node_id", "entity_type", "type", "kind", "name", "label"}
            }
        entities.append(
            {
                "entity_id": str(entity_id),
                "entity_type": str(entity_type),
                "name": entity.get("name") or entity.get("label") or str(entity_id),
                "attributes": attrs,
            }
        )

    relationships = []
    for relationship in raw_relationships:
        if not isinstance(relationship, dict):
            continue
        source_id = _relation_endpoint(relationship.get("source_id") or relationship.get("source"))
        target_id = _relation_endpoint(relationship.get("target_id") or relationship.get("target"))
        if not source_id or not target_id:
            continue
        relationships.append(
            {
                "source_id": source_id,
                "target_id": target_id,
                "relation_type": relationship.get("relation_type") or relationship.get("type") or "related_to",
                "weight": relationship.get("weight"),
                "attributes": relationship.get("attributes") if isinstance(relationship.get("attributes"), dict) else {},
            }
        )
    return entities, relationships


def _relation_endpoint(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("entity_id") or value.get("id") or value.get("node_id") or "")
    return str(value or "")


DOMAIN_ENTITY_TYPES = {
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
    "body_part",
    "formation",
    "match_result",
    "venue",
    "group",
    "stage",
    "country",
}

PROVENANCE_ENTITY_TYPES = {
    "source",
    "source_domain",
    "source_domain_profile",
    "source_kind",
    "source_quality",
    "source_recency",
    "scout",
    "scout_match_profile",
}

EVIDENCE_ENTITY_TYPES = {
    "finding",
    "evidence_claim",
    "claim_type",
    "claim_impact",
    "claim_quality",
    "metric",
    "scouting_topic",
    "team_scouting_topic",
    "scouting_gap",
}


def _domain_artifact_view(domain_graph: Any, world_graph: Any) -> dict[str, Any]:
    domain_entities, domain_relationships = _normal_graph(domain_graph)
    if domain_entities:
        source = "domain_graph.json"
        selected_entities = domain_entities
        selected_relationships = domain_relationships
    else:
        source = "world_graph.json fallback"
        world_entities, world_relationships = _normal_graph(world_graph)
        selected_entities = [
            entity for entity in world_entities if str(entity.get("entity_type") or "") in DOMAIN_ENTITY_TYPES
        ]
        selected_ids = {str(entity.get("entity_id") or "") for entity in selected_entities}
        selected_relationships = [
            relationship
            for relationship in world_relationships
            if str(relationship.get("source_id") or "") in selected_ids
            and str(relationship.get("target_id") or "") in selected_ids
        ]

    entity_type_counts = Counter(str(entity.get("entity_type") or "unknown") for entity in selected_entities)
    relationship_type_counts = Counter(
        str(relationship.get("relation_type") or "unknown") for relationship in selected_relationships
    )
    by_type: dict[str, list[dict[str, Any]]] = {}
    for entity in selected_entities:
        entity_type = str(entity.get("entity_type") or "unknown")
        by_type.setdefault(entity_type, [])
        if len(by_type[entity_type]) < 12:
            by_type[entity_type].append(_entity_card(entity))
    return {
        "source": source,
        "entity_count": len(selected_entities),
        "relationship_count": len(selected_relationships),
        "entity_type_counts": dict(entity_type_counts.most_common()),
        "relationship_type_counts": dict(relationship_type_counts.most_common()),
        "sample_by_type": by_type,
        "network": _network_preview(selected_entities, selected_relationships, max_nodes=150, max_links=320),
    }


def _entity_card(entity: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entity.get("entity_id"),
        "type": entity.get("entity_type"),
        "name": entity.get("name"),
        "attributes": _attributes_preview(entity.get("attributes") or {}, max_items=8),
    }


def _evidence_artifact_view(knowledge_views: Any, findings: list[Any]) -> dict[str, Any]:
    claims = _flatten_claims(findings)
    claim_type_counts = Counter(str(claim.get("claim_type") or "unknown") for claim in claims)
    team_counts = Counter(str(claim.get("team") or "unknown") for claim in claims if claim.get("team"))
    quality_counts = Counter(str(claim.get("source_quality") or "unknown") for claim in claims)
    metric_claim_count = sum(1 for claim in claims if isinstance(claim.get("metrics"), dict) and claim.get("metrics"))
    rows = []
    for claim in claims[:160]:
        rows.append(
            {
                "claim_type": claim.get("claim_type"),
                "team": claim.get("team"),
                "player": claim.get("player"),
                "subject": claim.get("subject"),
                "claim": _shorten(claim.get("claim"), 420),
                "confidence": claim.get("confidence"),
                "impact": claim.get("impact"),
                "source_title": claim.get("source_title"),
                "source_url": claim.get("source_url"),
                "source_domain": claim.get("source_domain"),
                "source_quality": claim.get("source_quality"),
                "finding_name": claim.get("_finding_name"),
                "scout_name": claim.get("_scout_name"),
                "metrics": _preview_value("metrics", claim.get("metrics") or {}),
            }
        )
    return {
        "source": "knowledge_views.json" if _has_named_knowledge_view(knowledge_views, "evidence") else "findings.json fallback",
        "finding_count": len([item for item in findings if isinstance(item, dict)]),
        "claim_count": len(claims),
        "metric_claim_count": metric_claim_count,
        "claim_type_counts": dict(claim_type_counts.most_common()),
        "team_counts": dict(team_counts.most_common()),
        "quality_counts": dict(quality_counts.most_common()),
        "claims": rows,
        "findings": _finding_preview_from_value(findings),
    }


def _flatten_claims(findings: list[Any]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        for claim in finding.get("evidence_claims") or []:
            if not isinstance(claim, dict):
                continue
            item = dict(claim)
            item["_finding_id"] = finding.get("finding_id")
            item["_finding_name"] = finding.get("finding_name")
            item["_scout_name"] = finding.get("scout_name")
            item["_source_type"] = finding.get("source_type")
            claims.append(item)
    return claims


def _finding_preview_from_value(findings: list[Any]) -> list[dict[str, Any]]:
    preview = []
    for finding in findings[:24]:
        if not isinstance(finding, dict):
            continue
        claims = finding.get("evidence_claims") or []
        preview.append(
            {
                "scout_name": finding.get("scout_name"),
                "finding_name": finding.get("finding_name"),
                "source_type": finding.get("source_type"),
                "confidence": finding.get("confidence"),
                "summary": _shorten(finding.get("summary"), 360),
                "claim_count": len(claims),
            }
        )
    return preview


def _provenance_artifact_view(
    knowledge_views: Any,
    run_summary: Any,
    findings: list[Any],
    audit: dict[str, Any],
    matrix_row: dict[str, Any],
) -> dict[str, Any]:
    claims = _flatten_claims(findings)
    source_counts: Counter[str] = Counter()
    source_quality_counts: Counter[str] = Counter()
    source_kind_counts: Counter[str] = Counter()
    source_domain_counts: Counter[str] = Counter()
    sources: dict[str, dict[str, Any]] = {}
    for claim in claims:
        url = str(claim.get("source_url") or "")
        domain = str(claim.get("source_domain") or "")
        title = str(claim.get("source_title") or "")
        key = url or domain or title or "unknown"
        source_counts[key] += 1
        if claim.get("source_quality"):
            source_quality_counts[str(claim.get("source_quality"))] += 1
        if claim.get("source_kind"):
            source_kind_counts[str(claim.get("source_kind"))] += 1
        if domain:
            source_domain_counts[domain] += 1
        row = sources.setdefault(
            key,
            {
                "title": title or domain or url or "unknown source",
                "url": url,
                "domain": domain,
                "kind": claim.get("source_kind"),
                "quality": claim.get("source_quality"),
                "claim_count": 0,
            },
        )
        row["claim_count"] += 1

    scouts: Counter[str] = Counter()
    access_levels: Counter[str] = Counter()
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        if finding.get("scout_name"):
            scouts[str(finding.get("scout_name"))] += 1
        if finding.get("access_level"):
            access_levels[str(finding.get("access_level"))] += 1

    if isinstance(audit.get("access_levels"), dict):
        access_levels.update({str(key): int(value) for key, value in audit.get("access_levels", {}).items()})

    summary_sources = matrix_row.get("source_summaries") if isinstance(matrix_row.get("source_summaries"), list) else []
    return {
        "source": "knowledge_views.json" if _has_named_knowledge_view(knowledge_views, "provenance") else "findings/scouting_audit fallback",
        "source_summaries": summary_sources,
        "source_count": len(sources),
        "sources": sorted(sources.values(), key=lambda item: (-int(item.get("claim_count") or 0), str(item.get("title") or "")))[:80],
        "source_domain_counts": dict(source_domain_counts.most_common()),
        "source_quality_counts": dict(source_quality_counts.most_common()),
        "source_kind_counts": dict(source_kind_counts.most_common()),
        "scout_counts": dict(scouts.most_common()),
        "access_levels": dict(access_levels.most_common()),
        "run_summary": _run_summary_preview(run_summary),
    }


def _gaps_artifact_view(run_summary: Any, audit: dict[str, Any], matrix_row: dict[str, Any]) -> dict[str, Any]:
    coverage = audit.get("coverage") if isinstance(audit.get("coverage"), dict) else {}
    quality = coverage.get("required_claim_type_quality") if isinstance(coverage.get("required_claim_type_quality"), dict) else {}
    required_types = coverage.get("required_claim_types") if isinstance(coverage.get("required_claim_types"), list) else []
    if not required_types:
        required_types = sorted(str(key) for key in quality.keys())
    rows = []
    for claim_type in required_types:
        item = quality.get(claim_type) if isinstance(quality.get(claim_type), dict) else {}
        rows.append(
            {
                "claim_type": claim_type,
                "coverage_status": item.get("coverage_status") or ("covered" if item.get("claim_count") else "missing"),
                "quality_status": item.get("quality_status") or "",
                "claim_count": item.get("claim_count", 0),
                "metric_claim_count": item.get("metric_claim_count", 0),
                "quality_reasons": item.get("quality_reasons") or [],
            }
        )

    summary_gaps = []
    if isinstance(run_summary, dict):
        for key in ("gaps", "missing_required_claim_types", "backlog", "scouting_gaps"):
            value = run_summary.get(key)
            if isinstance(value, list):
                summary_gaps.extend(_shorten(item, 220) for item in value[:20])
            elif value:
                summary_gaps.append(_shorten(value, 220))

    missing = coverage.get("missing_required_claim_types") if isinstance(coverage.get("missing_required_claim_types"), list) else []
    present = coverage.get("present_required_claim_types") if isinstance(coverage.get("present_required_claim_types"), list) else []
    return {
        "source": "scouting_run_summary.json" if isinstance(run_summary, dict) else "scouting_audit.json fallback",
        "scouting_complete": matrix_row.get("scouting_complete"),
        "kg_load_ready": matrix_row.get("kg_load_ready"),
        "status": matrix_row.get("status"),
        "required_claim_type_coverage": coverage.get("required_claim_type_coverage"),
        "missing_required_claim_types": missing,
        "present_required_claim_types": present,
        "rows": rows,
        "summary_gaps": summary_gaps,
        "coverage": {
            "claims_with_metrics": coverage.get("claims_with_metrics"),
            "dated_claim_count": coverage.get("dated_claim_count"),
            "recent_30d_claim_count": coverage.get("recent_30d_claim_count"),
            "strong_or_official_claim_count": coverage.get("strong_or_official_claim_count"),
            "weak_claim_count": coverage.get("weak_claim_count"),
            "unique_source_domains": coverage.get("unique_source_domains"),
        },
    }


def _has_named_knowledge_view(value: Any, name: str) -> bool:
    if isinstance(value, dict):
        return name in value or f"{name}_view" in value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and str(item.get("name") or item.get("view") or "").casefold() == name:
                return True
    return False


def _market_context_preview(path: Path) -> list[dict[str, Any]]:
    findings = _safe_json(path)
    if not isinstance(findings, list):
        return []
    rows: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        for claim in finding.get("evidence_claims") or []:
            if not isinstance(claim, dict) or claim.get("claim_type") != "market_snapshot":
                continue
            metrics = claim.get("metrics") if isinstance(claim.get("metrics"), dict) else {}
            rows.append(
                {
                    "question": metrics.get("question") or claim.get("subject") or claim.get("claim") or "Polymarket market",
                    "outcome": metrics.get("outcome"),
                    "gamma_price": metrics.get("price"),
                    "clob_midpoint": metrics.get("clob_midpoint"),
                    "best_bid": metrics.get("clob_best_bid"),
                    "best_ask": metrics.get("clob_best_ask"),
                    "spread": metrics.get("clob_spread"),
                    "bid_depth": metrics.get("clob_bid_depth"),
                    "ask_depth": metrics.get("clob_ask_depth"),
                    "volume": metrics.get("volume"),
                    "liquidity": metrics.get("liquidity"),
                    "active": metrics.get("active"),
                    "closed": metrics.get("closed"),
                    "accepting_orders": metrics.get("accepting_orders"),
                    "source_url": claim.get("source_url"),
                }
            )
    return rows[:18]


def _graph_preview(path: Path) -> dict[str, Any]:
    graph = _safe_json(path)
    if not isinstance(graph, dict):
        return {}
    entities = graph.get("entities") or []
    relationships = graph.get("relationships") or []
    entity_type_counts = Counter(str(entity.get("entity_type") or "unknown") for entity in entities)
    relationship_type_counts = Counter(str(relationship.get("relation_type") or "unknown") for relationship in relationships)
    by_type: dict[str, list[dict[str, Any]]] = {}
    for entity in entities:
        entity_type = str(entity.get("entity_type") or "unknown")
        by_type.setdefault(entity_type, [])
        if len(by_type[entity_type]) < 5:
            by_type[entity_type].append(
                {
                    "id": entity.get("entity_id"),
                    "type": entity_type,
                    "name": entity.get("name"),
                }
            )
    return {
        "entity_count": len(entities),
        "relationship_count": len(relationships),
        "entity_type_counts": dict(entity_type_counts.most_common()),
        "relationship_type_counts": dict(relationship_type_counts.most_common()),
        "sample_by_type": by_type,
        "sample_relationships": relationships[:20],
        "network": _network_preview(entities, relationships),
    }


def _graph_categories(path: Path) -> dict[str, Any] | None:
    graph = _safe_json(path)
    if not isinstance(graph, dict):
        return None
    entities = graph.get("entities") or []
    if not isinstance(entities, list):
        return None
    by_type: dict[str, list[dict[str, Any]]] = {}
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        by_type.setdefault(str(entity.get("entity_type") or "unknown"), []).append(entity)
    categories: dict[str, dict[str, Any]] = {}
    for category, entity_types in KG_CATEGORY_ENTITY_TYPES.items():
        category_entities = [entity for entity_type in entity_types for entity in by_type.get(entity_type, [])]
        type_counts = {
            entity_type: len(by_type.get(entity_type, []))
            for entity_type in entity_types
            if by_type.get(entity_type)
        }
        categories[category] = {
            "entity_count": len(category_entities),
            "entity_type_counts": type_counts,
            "entity_types": list(entity_types),
            "sample_entities": [
                {
                    "entity_id": entity.get("entity_id"),
                    "entity_type": entity.get("entity_type"),
                    "name": entity.get("name"),
                }
                for entity in category_entities[:12]
            ],
        }
    return {"categories": categories}


def _network_preview(
    entities: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    *,
    max_nodes: int = 180,
    max_links: int = 380,
) -> dict[str, Any]:
    if not entities:
        return {"nodes": [], "links": [], "total_nodes": 0, "total_links": 0}

    by_id = {str(entity.get("entity_id") or ""): entity for entity in entities if entity.get("entity_id")}
    hidden_preview_types = {"metric"}
    quota_by_type = {
        "match": 4,
        "team": 8,
        "team_match_profile": 8,
        "player": 64,
        "player_match_profile": 64,
        "player_stat_line": 32,
        "availability_event": 24,
        "availability_status": 12,
        "club": 40,
        "position": 24,
        "finding": 18,
        "evidence_claim": 56,
        "source": 12,
        "scout": 8,
        "claim_type": 16,
        "metric": 0,
        "venue": 4,
        "group": 4,
        "stage": 4,
        "country": 8,
    }
    priority_by_type = {
        "match": 0,
        "team": 1,
        "team_match_profile": 2,
        "player": 3,
        "player_match_profile": 4,
        "player_stat_line": 5,
        "availability_event": 6,
        "club": 7,
        "position": 7,
        "finding": 8,
        "evidence_claim": 9,
        "source": 10,
        "scout": 10,
        "claim_type": 11,
        "metric": 99,
        "venue": 13,
        "group": 13,
        "stage": 13,
        "country": 13,
    }
    selected: list[str] = []
    selected_set: set[str] = set()
    used_by_type: Counter[str] = Counter()

    def add_entity(entity_id: str) -> bool:
        if entity_id in selected_set or entity_id not in by_id or len(selected) >= max_nodes:
            return False
        entity_type = str(by_id[entity_id].get("entity_type") or "unknown")
        if entity_type in hidden_preview_types:
            return False
        selected_set.add(entity_id)
        selected.append(entity_id)
        used_by_type[entity_type] += 1
        return True

    sorted_entities = sorted(
        by_id.values(),
        key=lambda entity: (
            priority_by_type.get(str(entity.get("entity_type") or "unknown"), 20),
            str(entity.get("name") or entity.get("entity_id") or ""),
        ),
    )
    for entity in sorted_entities:
        entity_type = str(entity.get("entity_type") or "unknown")
        quota = quota_by_type.get(entity_type, 4)
        if used_by_type[entity_type] < quota:
            add_entity(str(entity.get("entity_id") or ""))

    for relationship in relationships:
        if len(selected) >= max_nodes:
            break
        source_id = str(relationship.get("source_id") or "")
        target_id = str(relationship.get("target_id") or "")
        if str(relationship.get("relation_type") or "") == "has_metric":
            continue
        if source_id in selected_set and target_id not in selected_set:
            add_entity(target_id)
        if target_id in selected_set and source_id not in selected_set:
            add_entity(source_id)

    links = []
    for relationship in relationships:
        source_id = str(relationship.get("source_id") or "")
        target_id = str(relationship.get("target_id") or "")
        if source_id not in selected_set or target_id not in selected_set:
            continue
        if str(relationship.get("relation_type") or "") == "has_metric":
            continue
        links.append(
            {
                "source": source_id,
                "target": target_id,
                "type": relationship.get("relation_type") or "related_to",
                "weight": relationship.get("weight"),
            }
        )
        if len(links) >= max_links:
            break

    degree: Counter[str] = Counter()
    for link in links:
        degree[str(link["source"])] += 1
        degree[str(link["target"])] += 1

    nodes = []
    for entity_id in selected:
        entity = by_id[entity_id]
        nodes.append(
            {
                "id": entity_id,
                "type": entity.get("entity_type") or "unknown",
                "label": entity.get("name") or entity_id,
                "degree": degree[entity_id],
                "attributes": _attributes_preview(entity.get("attributes") or {}),
            }
        )

    return {
        "nodes": nodes,
        "links": links,
        "total_nodes": len(entities),
        "total_links": len(relationships),
        "entity_type_counts": dict(Counter(str(entity.get("entity_type") or "unknown") for entity in entities)),
    }


def _attributes_preview(attributes: dict[str, Any], *, max_items: int = 18) -> dict[str, Any]:
    preview: dict[str, Any] = {}
    preferred_keys = [
        "claim",
        "claim_type",
        "subject",
        "team",
        "player",
        "confidence",
        "impact",
        "source_title",
        "source_url",
        "source_domain",
        "source_kind",
        "source_quality",
        "metrics",
        "date",
        "time",
        "venue",
        "group",
        "stage",
        "home_probability",
        "home_delta",
        "market_home_probability",
        "summary",
        "citations",
        "evidence_claims",
    ]
    ordered_keys = [key for key in preferred_keys if key in attributes]
    ordered_keys.extend(key for key in attributes if key not in ordered_keys)
    for key in ordered_keys:
        if len(preview) >= max_items:
            break
        preview[key] = _preview_value(key, attributes.get(key))
    return preview


def _preview_value(key: str, value: Any) -> Any:
    if key == "evidence_claims" and isinstance(value, list):
        return [
            {
                "claim_type": claim.get("claim_type"),
                "team": claim.get("team"),
                "player": claim.get("player"),
                "claim": _shorten(claim.get("claim"), 260),
                "source_title": claim.get("source_title"),
                "source_url": claim.get("source_url"),
                "confidence": claim.get("confidence"),
            }
            for claim in value[:5]
            if isinstance(claim, dict)
        ]
    if isinstance(value, dict):
        return {str(k): _shorten(v, 180) for k, v in list(value.items())[:16]}
    if isinstance(value, list):
        return [_shorten(item, 180) for item in value[:8]]
    return _shorten(value, 320)


def _shorten(value: Any, max_chars: int) -> Any:
    if not isinstance(value, str):
        return value
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3] + "..."


def _structure_audit(graph_path: Path, findings_path: Path) -> dict[str, Any]:
    graph = _safe_json(graph_path)
    findings = _safe_json(findings_path)
    if not isinstance(graph, dict):
        return {}
    if not isinstance(findings, list):
        findings = []
    entities = graph.get("entities") or []
    relationships = graph.get("relationships") or []
    entity_ids = {str(entity.get("entity_id") or "") for entity in entities}
    degree: Counter[str] = Counter()
    missing_targets = []
    for relationship in relationships:
        source_id = str(relationship.get("source_id") or "")
        target_id = str(relationship.get("target_id") or "")
        if source_id not in entity_ids or target_id not in entity_ids:
            missing_targets.append(relationship)
        degree[source_id] += 1
        degree[target_id] += 1
    isolated = [entity for entity in entities if degree[str(entity.get("entity_id") or "")] == 0]
    entity_counts = Counter(str(entity.get("entity_type") or "unknown") for entity in entities)
    claims = [
        claim
        for finding in findings
        if isinstance(finding, dict)
        for claim in finding.get("evidence_claims", [])
        if isinstance(claim, dict)
    ]
    noisy_terms = (
        "american football",
        "women",
        "usl super league",
        "olympic",
        "olympics",
        "score prediction",
        "predictions",
        "best bets",
        "betting",
        "tips",
        "picks",
    )
    noisy_claims = []
    for claim in claims:
        text = " ".join(str(claim.get(key) or "") for key in ("claim", "source_title", "source_url")).casefold()
        if any(term in text for term in noisy_terms):
            noisy_claims.append(
                {
                    "claim_type": claim.get("claim_type"),
                    "team": claim.get("team"),
                    "claim": claim.get("claim"),
                    "source_title": claim.get("source_title"),
                }
            )
    context_count = sum(
        entity_counts.get(entity_type, 0)
        for entity_type in (
            "finding",
            "evidence_claim",
            "source",
            "source_domain",
            "source_domain_profile",
            "source_kind",
            "source_quality",
            "source_recency",
            "scout",
            "scout_match_profile",
            "claim_type",
            "claim_impact",
            "claim_quality",
            "metric",
        )
    )
    total_entities = max(len(entities), 1)
    warnings: list[str] = []
    if missing_targets:
        warnings.append(f"{len(missing_targets)} relationships point to missing entities.")
    if isolated:
        warnings.append(f"{len(isolated)} isolated entities have no relationships.")
    if entity_counts.get("player", 0) == 0 and any(claim.get("claim_type") == "player_form" for claim in claims):
        warnings.append("Player-form claims exist, but no player entities were created because claims lack a player field.")
    if context_count / total_entities > 0.7:
        warnings.append("Context/provenance nodes dominate the graph; domain facts should be separated from evidence/provenance views.")
    if noisy_claims:
        warnings.append(f"{len(noisy_claims)} claims look noisy or off-domain and should be filtered or downgraded.")
    if not warnings:
        warnings.append("No structural breakage detected.")
    return {
        "missing_relationship_targets": len(missing_targets),
        "isolated_entities": len(isolated),
        "claims_with_player_field": sum(1 for claim in claims if claim.get("player")),
        "noisy_claim_count": len(noisy_claims),
        "noisy_claim_samples": noisy_claims[:6],
        "context_entity_ratio": round(context_count / total_entities, 3),
        "warnings": warnings,
    }


def _finding_preview(path: Path) -> list[dict[str, Any]]:
    findings = _safe_json(path)
    if not isinstance(findings, list):
        return []
    preview = []
    for finding in findings[:8]:
        claims = finding.get("evidence_claims") or []
        preview.append(
            {
                "scout_name": finding.get("scout_name"),
                "finding_name": finding.get("finding_name"),
                "source_type": finding.get("source_type"),
                "claim_count": len(claims),
                "sample_claims": [
                    {
                        "claim_type": claim.get("claim_type"),
                        "team": claim.get("team"),
                        "player": claim.get("player"),
                        "claim": claim.get("claim"),
                        "source_title": claim.get("source_title"),
                    }
                    for claim in claims[:4]
                    if isinstance(claim, dict)
                ],
            }
        )
    return preview


DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Scouting KG Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #1b1f24;
      --muted: #687282;
      --line: #d8dde6;
      --blue: #2f6fed;
      --green: #20825b;
      --orange: #a75f00;
      --red: #bf2b2b;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
      letter-spacing: 0;
    }
    header {
      padding: 18px 22px;
      border-bottom: 1px solid var(--line);
      background: #fff;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    h1 { font-size: 20px; margin: 0; }
    h2 { font-size: 15px; margin: 0 0 12px; }
    main {
      display: grid;
      grid-template-columns: minmax(260px, 330px) minmax(0, 1fr);
      gap: 16px;
      padding: 16px;
      min-height: calc(100vh - 62px);
    }
    section, aside {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-width: 0;
    }
    aside {
      align-self: start;
      position: sticky;
      top: 12px;
    }
    label {
      display: block;
      font-size: 12px;
      color: var(--muted);
      margin: 12px 0 6px;
    }
    select, input {
      width: 100%;
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      background: #fff;
      color: var(--ink);
      font: inherit;
    }
    button {
      min-height: 38px;
      border: 0;
      border-radius: 6px;
      padding: 9px 12px;
      background: var(--blue);
      color: #fff;
      font-weight: 650;
      cursor: pointer;
      width: 100%;
      margin-top: 14px;
    }
    button:disabled { opacity: 0.55; cursor: not-allowed; }
    .module-list {
      display: grid;
      grid-template-columns: 1fr;
      gap: 8px;
      margin-top: 8px;
      max-height: 330px;
      overflow: auto;
      padding-right: 4px;
    }
    .module {
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 9px;
      display: grid;
      grid-template-columns: 20px 1fr;
      gap: 8px;
      align-items: start;
    }
    .module input { width: 16px; min-height: 16px; margin-top: 2px; }
    .module strong { display: block; font-size: 13px; }
    .module span { display: block; color: var(--muted); font-size: 11px; line-height: 1.35; margin-top: 3px; }
    .module a { color: var(--blue); text-decoration: none; }
    .module .setup-hint { color: #6d5a00; }
    .grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 10px;
      min-height: 66px;
    }
    .metric b { font-size: 22px; display: block; }
    .metric span { color: var(--muted); font-size: 12px; }
    .market-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 10px;
      margin: 12px 0;
    }
    .market-card {
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fbfcff;
      padding: 10px;
    }
    .market-card strong {
      display: block;
      font-size: 12px;
      line-height: 1.35;
      margin-bottom: 8px;
    }
    .market-row {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      border-top: 1px solid #edf1f6;
      padding-top: 6px;
      margin-top: 6px;
      font-size: 12px;
    }
    .market-row b { font-size: 16px; }
    .market-row span { color: var(--muted); }
    .tabs {
      display: flex;
      gap: 8px;
      margin: 12px 0;
      flex-wrap: wrap;
    }
    .view-tabs {
      display: flex;
      gap: 8px;
      margin: 14px 0;
      flex-wrap: wrap;
      border-bottom: 1px solid var(--line);
      padding-bottom: 8px;
    }
    .view-tab {
      width: auto;
      min-height: 34px;
      margin: 0;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--muted);
      border-radius: 6px;
      padding: 7px 10px;
      font-weight: 700;
    }
    .view-tab.is-active {
      background: var(--blue);
      border-color: var(--blue);
      color: #fff;
    }
    .view-panel[hidden] { display: none; }
    .result-switcher {
      display: flex;
      align-items: end;
      gap: 10px;
      margin: 4px 0 12px;
      flex-wrap: wrap;
    }
    .result-switcher label {
      margin: 0;
      min-width: min(420px, 100%);
    }
    .artifact-line {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 12px;
      margin: 8px 0 12px;
    }
    .artifact-dot {
      width: 8px;
      height: 8px;
      border-radius: 99px;
      background: var(--green);
      display: inline-block;
    }
    .artifact-dot.fallback { background: var(--orange); }
    .detail-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 10px;
      margin: 12px 0;
    }
    .detail-card {
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 10px;
      background: #fff;
      min-width: 0;
    }
    .detail-card h3 {
      margin: 0 0 8px;
      font-size: 13px;
    }
    .detail-card p {
      margin: 4px 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.4;
    }
    .compact-list {
      display: grid;
      gap: 7px;
      margin-top: 8px;
    }
    .compact-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 7px 8px;
      font-size: 12px;
      min-width: 0;
    }
    .compact-row span { color: var(--muted); word-break: break-word; }
    .claim-list {
      display: grid;
      gap: 8px;
      margin-top: 10px;
    }
    .gap-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
      margin-top: 10px;
    }
    .gap-table th,
    .gap-table td {
      text-align: left;
      border-bottom: 1px solid #edf1f6;
      padding: 8px 6px;
      vertical-align: top;
    }
    .gap-table th { color: var(--muted); font-weight: 750; }
    .status-tag {
      display: inline-flex;
      border-radius: 999px;
      padding: 3px 7px;
      font-size: 11px;
      font-weight: 750;
      background: #edf1f6;
      color: var(--muted);
    }
    .status-tag.good { background: #e5f6ee; color: #126742; }
    .status-tag.bad { background: #fff1f1; color: #8a1d1d; }
    .status-tag.warn { background: #fff8e8; color: #6f4700; }
    .pill {
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 999px;
      padding: 5px 9px;
      color: var(--muted);
      font-size: 12px;
    }
    .status {
      color: var(--muted);
      font-size: 13px;
    }
    pre {
      background: #10141b;
      color: #dce7f5;
      border-radius: 8px;
      padding: 12px;
      overflow: auto;
      max-width: 100%;
      min-height: 190px;
      max-height: 330px;
      font-size: 12px;
      line-height: 1.45;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .result-card {
      border-top: 1px solid var(--line);
      padding-top: 14px;
      margin-top: 14px;
    }
    .categories {
      display: grid;
      grid-template-columns: repeat(4, minmax(110px, 1fr));
      gap: 10px;
    }
    .cat {
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 10px;
    }
    .cat b { display: block; font-size: 20px; }
    .cat span { color: var(--muted); font-size: 12px; }
    .bar {
      height: 7px;
      background: #edf1f6;
      border-radius: 99px;
      overflow: hidden;
      margin-top: 8px;
    }
    .bar i {
      display: block;
      height: 100%;
      width: 0%;
      background: var(--blue);
    }
    .claim {
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 8px;
      margin: 8px 0;
      font-size: 12px;
    }
    .claim .type { color: var(--blue); font-weight: 650; }
    .notice {
      border: 1px solid #f1c56b;
      background: #fff8e8;
      border-radius: 7px;
      padding: 9px;
      margin: 10px 0;
      color: #6f4700;
      font-size: 12px;
    }
    .warning {
      border-color: #f0a0a0;
      background: #fff1f1;
      color: #8a1d1d;
    }
    .type-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 8px;
    }
    .type-row {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 6px 8px;
      font-size: 12px;
    }
    .empty { color: var(--muted); padding: 16px; border: 1px dashed var(--line); border-radius: 8px; }
    .graph-meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 12px;
      flex-wrap: wrap;
    }
    .graph-legend {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .kg-chipbar {
      display: flex;
      gap: 7px;
      flex-wrap: wrap;
      margin: 8px 0 10px;
    }
    .kg-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border: 1px solid #33421f;
      background: #1d2612;
      color: #dfe8cb;
      border-radius: 999px;
      padding: 5px 9px;
      font-size: 11px;
      font-weight: 750;
      text-transform: uppercase;
      letter-spacing: 0;
    }
    .kg-chip i {
      width: 7px;
      height: 7px;
      border-radius: 99px;
      display: inline-block;
      box-shadow: 0 0 8px currentColor;
    }
    .legend-item {
      display: inline-flex;
      align-items: center;
      gap: 5px;
    }
    .legend-dot {
      width: 9px;
      height: 9px;
      border-radius: 99px;
      display: inline-block;
    }
    #graphViz svg {
      width: 100%;
      max-width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfe;
      display: block;
    }
    .kg-mini { height: 230px; }
    .kg-network { height: 520px; }
    .kg-football {
      min-height: 650px;
      height: auto;
    }
    .kg-cluster-map {
      min-height: 530px;
      height: auto;
    }
    .kg-node text { paint-order: stroke; stroke: rgba(7, 14, 6, 0.86); stroke-width: 3px; stroke-linejoin: round; }
    .kg-node { cursor: pointer; }
    .kg-cluster-map line,
    .kg-node circle {
      transition: opacity 0.15s ease, stroke-width 0.15s ease, filter 0.15s ease;
    }
    .kg-node:hover circle {
      stroke-width: 3;
      filter: drop-shadow(0 0 8px rgba(126, 215, 236, 0.72));
    }
    .kg-node.is-selected circle,
    .kg-node.is-selected rect {
      stroke-width: 4;
      filter: drop-shadow(0 2px 5px rgba(47, 111, 237, 0.35));
    }
    .kg-detail {
      margin-top: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 12px;
      font-size: 12px;
    }
    .kg-cluster-map + .kg-detail {
      border-color: #33421f;
      background: #10170c;
      color: #dfe8cb;
    }
    .kg-cluster-map + .kg-detail .node-id,
    .kg-cluster-map + .kg-detail .kv-row b {
      color: #9cae8c;
    }
    .kg-cluster-map + .kg-detail .kv-row {
      border-bottom-color: rgba(223, 232, 203, 0.12);
    }
    .kg-cluster-map + .kg-detail .stored-item {
      border-color: rgba(223, 232, 203, 0.16);
      background: rgba(255, 255, 255, 0.035);
    }
    .kg-cluster-map + .kg-detail .claim-text {
      background: rgba(255, 188, 101, 0.12);
      color: #f5e7c8;
    }
    .kg-cluster-map + .kg-detail a {
      color: #8fc4ff;
    }
    .kg-detail h3 {
      margin: 0 0 6px;
      font-size: 14px;
    }
    .kg-detail .node-id {
      color: var(--muted);
      word-break: break-word;
      margin-bottom: 10px;
    }
    .kg-detail-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.15fr) minmax(0, 0.85fr);
      gap: 12px;
    }
    .claim-text {
      border-left: 3px solid var(--orange);
      background: #fff8e8;
      padding: 9px 10px;
      border-radius: 6px;
      margin-bottom: 10px;
      line-height: 1.45;
    }
    .kv-row {
      display: grid;
      grid-template-columns: 138px minmax(0, 1fr);
      gap: 8px;
      padding: 5px 0;
      border-bottom: 1px solid #edf1f6;
    }
    .kv-row b { color: var(--muted); font-weight: 650; }
    .kv-row span { word-break: break-word; }
    .stored-list {
      display: grid;
      gap: 8px;
    }
    .stored-item {
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 8px;
      line-height: 1.35;
    }
    .stored-item b {
      display: block;
      margin-bottom: 3px;
    }
    .stored-item a {
      color: var(--blue);
      text-decoration: none;
      word-break: break-word;
    }
    .raw-fields {
      margin-top: 10px;
      border: 1px solid rgba(223, 232, 203, 0.14);
      border-radius: 7px;
      padding: 8px 10px;
      background: rgba(255, 255, 255, 0.025);
    }
    .raw-fields summary {
      cursor: pointer;
      color: #9cae8c;
      font-weight: 700;
    }
    .kg-relationships {
      max-height: 260px;
      overflow: auto;
    }
    @media (max-width: 900px) {
      main { grid-template-columns: 1fr; }
      aside { position: static; }
      .grid, .categories { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .result-switcher { align-items: stretch; }
      .kg-network { height: 430px; }
      .kg-football { min-height: 560px; }
      .kg-detail-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Scouting KG Dashboard</h1>
    <div class="status" id="headerStatus">loading config</div>
  </header>
  <main>
    <aside>
      <h2>Run Scouting</h2>
      <label for="matchSelect">Match</label>
      <select id="matchSelect"></select>

      <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px;">
        <div>
          <label for="modeSelect">Mode</label>
          <select id="modeSelect">
            <option value="fast">fast</option>
            <option value="deep">deep</option>
          </select>
        </div>
        <div>
          <label for="timeoutInput">Timeout</label>
          <input id="timeoutInput" type="number" min="5" max="180" value="45" />
        </div>
        <div>
          <label for="camelAgentsInput">CAMEL Agents</label>
          <input id="camelAgentsInput" type="number" min="1" max="6" value="4" />
        </div>
      </div>

      <label>Scouting Plugins / Datafeeds</label>
      <div class="module-list" id="moduleList"></div>
      <button id="runButton">Launch KG Run</button>
      <div class="status" id="runHint" style="margin-top:10px;">Choose plugins, then launch.</div>
    </aside>

    <section>
      <h2>Build Progress</h2>
      <div class="grid">
        <div class="metric"><b id="jobStatus">idle</b><span>job status</span></div>
        <div class="metric"><b id="entityCount">-</b><span>entities</span></div>
        <div class="metric"><b id="relationshipCount">-</b><span>relationships</span></div>
      </div>
      <div class="tabs" id="sourcePills"></div>
      <div id="notices"></div>
      <div class="view-tabs" id="viewTabs" role="tablist" aria-label="Scouting dashboard views">
        <button type="button" class="view-tab is-active" data-view="domain">Domain</button>
        <button type="button" class="view-tab" data-view="evidence">Evidence</button>
        <button type="button" class="view-tab" data-view="provenance">Provenance</button>
        <button type="button" class="view-tab" data-view="logs">Logs</button>
        <button type="button" class="view-tab" data-view="gaps">Gaps</button>
      </div>
      <div id="resultSwitcher"></div>

      <div id="domainView" class="view-panel">
        <h2>Domain</h2>
        <div class="categories" id="categoryCards"></div>
        <div style="margin-top:12px;" id="graphViz"></div>
        <div id="domainDetails"></div>
      </div>

      <div id="evidenceView" class="view-panel" hidden>
        <h2>Evidence</h2>
        <div id="evidenceDetails"></div>
      </div>

      <div id="provenanceView" class="view-panel" hidden>
        <h2>Provenance</h2>
        <div id="provenanceDetails"></div>
      </div>

      <div id="logsView" class="view-panel" hidden>
        <h2>Logs</h2>
        <div id="logSummary" class="status"></div>
        <pre id="logBox">No run yet.</pre>
      </div>

      <div id="gapsView" class="view-panel" hidden>
        <h2>Gaps</h2>
        <div id="gapsDetails"></div>
      </div>
    </section>
  </main>
  <script>
    const state = { config: null, jobId: null, poll: null, activeView: 'domain', currentJob: null, selectedResultIndex: 0 };
    const $ = (id) => document.getElementById(id);

    async function loadConfig() {
      const res = await fetch('/api/config');
      state.config = await res.json();
      $('headerStatus').textContent = `${state.config.matches.length} matches · ${state.config.modules.length} plugins`;
      renderMatches();
      renderModules();
      renderCategoryDefinitions();
      if (state.config.latest_results?.results?.length) {
        renderJob({
          status: 'loaded',
          logs: state.config.latest_results.logs || [`Loaded ${state.config.latest_results.run_root}`],
          results: state.config.latest_results.results,
        });
        $('runHint').textContent = `Loaded latest run: ${state.config.latest_results.run_root}`;
      }
    }

    function renderMatches() {
      $('matchSelect').innerHTML = state.config.matches.map((m) => {
        const label = `${m.date || 'no date'} · ${m.name}${m.group ? ' · ' + m.group : ''}`;
        return `<option value="${escapeHtml(m.name)}">${escapeHtml(label)}</option>`;
      }).join('');
    }

    function renderModules() {
      const defaults = new Set(state.config.defaults.modules);
      $('moduleList').innerHTML = state.config.modules.map((m) => {
        const checked = defaults.has(m.name) ? 'checked' : '';
        const claims = (m.claim_types || []).join(', ') || (m.includes || []).join(', ') || 'bundle';
        const displayName = m.display_name || m.name;
        const techName = displayName === m.name ? '' : ` <span style="display:inline;color:#8791a0;">${escapeHtml(m.name)}</span>`;
        const missing = (m.missing_env || []).length ? ` · needs ${escapeHtml((m.missing_env || []).join(', '))}` : '';
        const envClass = m.env_ready === false ? 'color:#a75f00;' : 'color:#687282;';
        const setupUrl = m.setup_url || m.docs_url || '';
        const setupLink = setupUrl ? `<span><a href="${escapeHtml(setupUrl)}" target="_blank" rel="noopener noreferrer">Setup / API key</a></span>` : '';
        const setupHint = m.setup_hint ? `<span class="setup-hint">${escapeHtml(m.setup_hint)}</span>` : '';
        return `<label class="module">
          <input type="checkbox" value="${escapeHtml(m.name)}" ${checked}>
          <div>
            <strong>${escapeHtml(displayName)}${techName} <span style="display:inline;${envClass}">${escapeHtml(m.family || '')}${missing}</span></strong>
            <span>${escapeHtml(claims)}</span>
            <span>${escapeHtml(m.description || '')}</span>
            ${setupLink}
            ${setupHint}
          </div>
        </label>`;
      }).join('');
    }

    function selectedModules() {
      return Array.from(document.querySelectorAll('#moduleList input:checked')).map((input) => input.value);
    }

    async function launchRun() {
      $('runButton').disabled = true;
      $('runHint').textContent = 'Starting job...';
      const payload = {
        match: $('matchSelect').value,
        modules: selectedModules(),
        mode: $('modeSelect').value,
        timeout: Number($('timeoutInput').value || 45),
        camel_agents: Number($('camelAgentsInput').value || 4),
      };
      const res = await fetch('/api/run', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (data.error) {
        $('runHint').textContent = data.error;
        $('runButton').disabled = false;
        return;
      }
      state.jobId = data.job_id;
      state.selectedResultIndex = 0;
      $('runHint').textContent = `Job ${state.jobId}`;
      clearInterval(state.poll);
      state.poll = setInterval(pollJob, 1000);
      await pollJob();
    }

    async function pollJob() {
      if (!state.jobId) return;
      const res = await fetch(`/api/jobs/${state.jobId}`);
      const job = await res.json();
      renderJob(job);
      if (job.status === 'complete' || job.status === 'failed') {
        clearInterval(state.poll);
        $('runButton').disabled = false;
      }
    }

    function renderJob(job) {
      state.currentJob = job;
      $('jobStatus').textContent = job.status || 'unknown';
      $('logBox').textContent = (job.logs || []).join('\n') || 'No logs yet.';
      $('logBox').scrollTop = $('logBox').scrollHeight;
      renderNotices(job);
      renderActiveView();
    }

    function currentResult() {
      const results = state.currentJob?.results || [];
      if (!results.length) return null;
      if (state.selectedResultIndex >= results.length) state.selectedResultIndex = 0;
      return results[state.selectedResultIndex] || results[0];
    }

    function renderActiveView() {
      const job = state.currentJob || {status: 'idle', logs: [], results: []};
      const result = currentResult();
      const live = livePreview(job.logs || []);
      updateViewTabs();
      renderResultSwitcher(job.results || []);
      if (!result) {
        renderLiveChrome(live);
        renderLiveView(job, live);
        return;
      }
      $('entityCount').textContent = result.entities ?? result.views?.domain?.entity_count ?? '-';
      $('relationshipCount').textContent = result.relationships ?? result.views?.domain?.relationship_count ?? '-';
      $('sourcePills').innerHTML = (result.source_summaries || []).map((s) => {
        const status = s.error_type ? ` · ${s.error_type}` : '';
        const duration = s.duration_seconds !== undefined ? ` · ${escapeHtml(formatSeconds(s.duration_seconds))}` : '';
        return `<span class="pill">${escapeHtml(s.source)} · ${s.finding_count || 0} findings · ${s.evidence_claim_count || 0} claims${duration}${escapeHtml(status)}</span>`;
      }).join('');
      showPanel(state.activeView);
      if (state.activeView === 'domain') renderDomainView(result);
      if (state.activeView === 'evidence') renderEvidenceView(result);
      if (state.activeView === 'provenance') renderProvenanceView(result);
      if (state.activeView === 'logs') renderLogsView(job);
      if (state.activeView === 'gaps') renderGapsView(result);
    }

    function renderLiveChrome(live) {
      $('entityCount').textContent = live.entities ?? live.estimated_entities ?? '-';
      $('relationshipCount').textContent = live.relationships ?? live.estimated_relationships ?? '-';
      $('sourcePills').innerHTML = live.sources.map((s) => {
        const status = s.error_type ? ` · ${s.error_type}` : ` · ${s.status}`;
        const duration = s.duration_seconds !== undefined ? ` · ${escapeHtml(formatSeconds(s.duration_seconds))}` : '';
        return `<span class="pill">${escapeHtml(s.source)} · ${s.finding_count || 0} findings · ${s.evidence_claim_count || 0} claims${duration}${escapeHtml(status)}</span>`;
      }).join('');
    }

    function renderLiveView(job, live) {
      showPanel(state.activeView);
      if (state.activeView === 'domain') {
        renderCategoryDefinitions();
        renderLiveGraph(live);
        $('domainDetails').innerHTML = '<div class="empty">Live KG preview is built from logs. Final Domain artifacts appear when the run finishes.</div>';
      }
      if (state.activeView === 'evidence') {
        $('evidenceDetails').innerHTML = renderLiveEvidence(live);
      }
      if (state.activeView === 'provenance') {
        $('provenanceDetails').innerHTML = renderLiveProvenance(live);
      }
      if (state.activeView === 'logs') {
        renderLogsView(job);
      }
      if (state.activeView === 'gaps') {
        $('gapsDetails').innerHTML = '<div class="empty">Coverage gaps are calculated from scouting_audit.json or scouting_run_summary.json after the run finishes.</div>';
      }
    }

    function updateViewTabs() {
      document.querySelectorAll('#viewTabs .view-tab').forEach((button) => {
        const active = button.dataset.view === state.activeView;
        button.classList.toggle('is-active', active);
        button.setAttribute('aria-selected', active ? 'true' : 'false');
      });
    }

    function showPanel(view) {
      ['domain', 'evidence', 'provenance', 'logs', 'gaps'].forEach((name) => {
        const panel = $(`${name}View`);
        if (panel) panel.hidden = name !== view;
      });
    }

    function renderResultSwitcher(results) {
      const container = $('resultSwitcher');
      if (!container) return;
      if (!results.length) {
        container.innerHTML = '';
        return;
      }
      if (state.selectedResultIndex >= results.length) state.selectedResultIndex = 0;
      if (results.length === 1) {
        const result = results[0];
        container.innerHTML = `<div class="result-switcher"><span class="pill">${escapeHtml(result.match || 'single result')}</span><span class="pill">${escapeHtml(result.out_dir || '')}</span></div>`;
        return;
      }
      container.innerHTML = `<div class="result-switcher">
        <label for="resultSelect">Result
          <select id="resultSelect">${results.map((result, index) =>
            `<option value="${index}" ${index === state.selectedResultIndex ? 'selected' : ''}>${escapeHtml(result.match || 'result ' + (index + 1))} · ${escapeHtml(result.status || '')}</option>`
          ).join('')}</select>
        </label>
        <span class="pill">${results.length} results</span>
      </div>`;
      $('resultSelect')?.addEventListener('change', (event) => {
        state.selectedResultIndex = Number(event.target.value || 0);
        renderActiveView();
      });
    }

    function livePreview(logs) {
      const sources = [];
      const bySource = new Map();
      let graphBuilt = null;
      for (const line of logs) {
        const fields = parseLogFields(line);
        if (!fields.event_type) continue;
        if (fields.event_type === 'source_start') {
          const source = fields.source || 'source';
          const row = bySource.get(source) || {source, status: 'running', finding_count: 0, evidence_claim_count: 0};
          row.status = 'running';
          if (!bySource.has(source)) {
            bySource.set(source, row);
            sources.push(row);
          }
        } else if (fields.event_type === 'source_complete') {
          const source = fields.source || 'source';
          const row = bySource.get(source) || {source};
          row.status = 'complete';
          row.finding_count = Number(fields.finding_count || 0);
          row.evidence_claim_count = Number(fields.evidence_claim_count || 0);
          row.duration_seconds = fields.duration_seconds;
          if (!bySource.has(source)) {
            bySource.set(source, row);
            sources.push(row);
          }
        } else if (fields.event_type === 'public_stage_complete') {
          const source = fields.source || 'public';
          const row = bySource.get(source) || {source, status: 'running', finding_count: 0, evidence_claim_count: 0};
          row.status = row.status || 'running';
          row.stage_metrics = row.stage_metrics || [];
          row.stage_metrics.push({
            stage: fields.stage || 'stage',
            duration_seconds: Number(fields.duration_seconds || 0),
            item_count: Number(fields.item_count || 0),
          });
          if (!bySource.has(source)) {
            bySource.set(source, row);
            sources.push(row);
          }
        } else if (fields.event_type === 'source_error') {
          const source = fields.source || 'source';
          const row = bySource.get(source) || {source};
          row.status = 'error';
          row.finding_count = 0;
          row.evidence_claim_count = 0;
          row.error_type = fields.error_type || 'error';
          if (!bySource.has(source)) {
            bySource.set(source, row);
            sources.push(row);
          }
        } else if (fields.event_type === 'graph_built') {
          graphBuilt = {
            entities: Number(fields.entities || 0),
            relationships: Number(fields.relationships || 0),
            findings: Number(fields.findings || 0),
          };
        }
      }
      const findingCount = sources.reduce((sum, s) => sum + Number(s.finding_count || 0), 0);
      const claimCount = sources.reduce((sum, s) => sum + Number(s.evidence_claim_count || 0), 0);
      const completeSources = sources.filter((s) => s.status === 'complete').length;
      const runningSources = sources.filter((s) => s.status === 'running').length;
      const errorSources = sources.filter((s) => s.status === 'error').length;
      return {
        sources,
        finding_count: graphBuilt?.findings ?? findingCount,
        evidence_claim_count: claimCount,
        complete_sources: completeSources,
        running_sources: runningSources,
        error_sources: errorSources,
        entities: graphBuilt?.entities,
        relationships: graphBuilt?.relationships,
        estimated_entities: sources.length ? Math.max(12, 24 + completeSources * 8 + findingCount * 6 + claimCount * 8) : null,
        estimated_relationships: sources.length ? Math.max(16, 40 + completeSources * 12 + findingCount * 10 + claimCount * 18) : null,
      };
    }

    function parseLogFields(line) {
      try {
        const parsed = JSON.parse(line);
        return parsed && typeof parsed === 'object' ? parsed : {};
      } catch {}
      const out = {};
      const eventMatch = String(line).match(new RegExp(String.raw`\[scout-kg\]\s+([a-zA-Z0-9_]+)`));
      if (eventMatch) out.event_type = eventMatch[1];
      const re = /([a-zA-Z_][a-zA-Z0-9_]*)=([^ ]+)/g;
      let match;
      while ((match = re.exec(String(line))) !== null) {
        out[match[1]] = match[2];
      }
      return out;
    }

    function renderNotices(job) {
      const logs = job.logs || [];
      const skipped = logs.filter((line) => line.includes('matrix_module_skipped'));
      $('notices').innerHTML = skipped.map((line) => {
        let module = 'module';
        let missing = line;
        try {
          const parsed = JSON.parse(line);
          module = parsed.module || module;
          missing = parsed.missing || parsed.reason || line;
        } catch {
          module = (line.match(/module=([^ ]+)/) || [])[1] || module;
          missing = (line.match(/missing=(.*)$/) || [])[1] || line;
        }
        return `<div class="notice warning"><strong>${escapeHtml(module)} skipped</strong><br>${escapeHtml(missing)}</div>`;
      }).join('');
    }

    function renderCategoryDefinitions() {
      $('categoryCards').innerHTML = Object.keys(state.config.categories || {}).map((name) =>
        `<div class="cat"><b>0</b><span>${escapeHtml(name)}</span><div class="bar"><i></i></div></div>`
      ).join('');
    }

    function renderCategories(result) {
      const categories = result.categories?.categories || {};
      const max = Math.max(1, ...Object.values(categories).map((row) => row.entity_count || 0));
      $('categoryCards').innerHTML = Object.entries(categories).map(([name, row]) => {
        const width = Math.round(((row.entity_count || 0) / max) * 100);
        const types = Object.entries(row.entity_type_counts || {}).map(([k, v]) => `${k}:${v}`).join(', ');
        return `<div class="cat"><b>${row.entity_count || 0}</b><span>${escapeHtml(name)}</span><div class="bar"><i style="width:${width}%"></i></div><span>${escapeHtml(types)}</span></div>`;
      }).join('');
    }

    function renderDomainView(result) {
      renderCategories(result);
      renderGraph(result);
      const view = result.views?.domain || {};
      const typeRows = Object.entries(view.entity_type_counts || {}).slice(0, 18);
      const relationshipRows = Object.entries(view.relationship_type_counts || {}).slice(0, 18);
      const sampleSections = Object.entries(view.sample_by_type || {}).slice(0, 10).map(([type, entities]) => {
        const rows = (entities || []).slice(0, 8).map((entity) =>
          `<div class="compact-row"><div><strong>${escapeHtml(entity.name || entity.id)}</strong><br><span>${escapeHtml(entity.id || '')}</span></div><b>${escapeHtml(entity.type || type)}</b></div>`
        ).join('');
        return `<div class="detail-card"><h3>${escapeHtml(type)}</h3><div class="compact-list">${rows || '<div class="empty">No entities.</div>'}</div></div>`;
      }).join('');
      $('domainDetails').innerHTML = `
        ${renderArtifactLine(result, 'domain', view.source || 'world_graph.json fallback')}
        <div class="detail-grid">
          <div class="detail-card"><h3>Domain counts</h3>
            <div class="compact-list">
              <div class="compact-row"><span>Domain entities</span><b>${view.entity_count ?? result.entities ?? '-'}</b></div>
              <div class="compact-row"><span>Domain relationships</span><b>${view.relationship_count ?? result.relationships ?? '-'}</b></div>
              <div class="compact-row"><span>Matrix status</span><b>${escapeHtml(result.status || '-')}</b></div>
            </div>
          </div>
          <div class="detail-card"><h3>Entity types</h3>${renderCountRows(typeRows)}</div>
          <div class="detail-card"><h3>Relationship types</h3>${renderCountRows(relationshipRows)}</div>
        </div>
        <div class="detail-grid">${sampleSections || '<div class="empty">No domain entities found in the selected artifacts.</div>'}</div>`;
    }

    function renderEvidenceView(result) {
      const view = result.views?.evidence || {};
      const claimRows = view.claims || [];
      const claimTypeRows = Object.entries(view.claim_type_counts || {}).slice(0, 18);
      const teamRows = Object.entries(view.team_counts || {}).slice(0, 18);
      const qualityRows = Object.entries(view.quality_counts || {}).slice(0, 12);
      const findingCards = (view.findings || []).slice(0, 12).map((finding) =>
        `<div class="detail-card"><h3>${escapeHtml(finding.finding_name || 'finding')}</h3>
          <p>${escapeHtml(finding.scout_name || '')} · ${escapeHtml(finding.source_type || '')} · ${finding.claim_count || 0} claims</p>
          ${finding.summary ? `<p>${escapeHtml(finding.summary)}</p>` : ''}
        </div>`
      ).join('');
      const claims = claimRows.slice(0, 80).map((claim) => `
        <div class="claim">
          <div><span class="type">${escapeHtml(claim.claim_type || 'claim')}</span>${claim.team ? ' · ' + escapeHtml(claim.team) : ''}${claim.player ? ' · ' + escapeHtml(claim.player) : ''}</div>
          <div style="margin-top:6px;">${escapeHtml(claim.claim || '')}</div>
          <div class="status" style="margin-top:6px;">${escapeHtml(claim.source_title || claim.source_domain || '')}${claim.confidence !== undefined ? ' · confidence ' + escapeHtml(claim.confidence) : ''}</div>
        </div>
      `).join('');
      $('evidenceDetails').innerHTML = `
        ${renderArtifactLine(result, 'evidence', view.source || 'findings.json fallback')}
        <div class="detail-grid">
          <div class="detail-card"><h3>Evidence totals</h3>
            <div class="compact-list">
              <div class="compact-row"><span>Findings</span><b>${view.finding_count ?? result.findings ?? 0}</b></div>
              <div class="compact-row"><span>Claims</span><b>${view.claim_count ?? result.claims ?? 0}</b></div>
              <div class="compact-row"><span>Claims with metrics</span><b>${view.metric_claim_count ?? '-'}</b></div>
            </div>
          </div>
          <div class="detail-card"><h3>Claim types</h3>${renderCountRows(claimTypeRows)}</div>
          <div class="detail-card"><h3>Teams</h3>${renderCountRows(teamRows)}</div>
          <div class="detail-card"><h3>Source quality</h3>${renderCountRows(qualityRows)}</div>
        </div>
        ${renderMarketContext(result.market_context || [])}
        <div class="detail-grid">${findingCards || '<div class="empty">No findings found.</div>'}</div>
        <div class="claim-list">${claims || '<div class="empty">No evidence claims found.</div>'}</div>`;
    }

    function renderProvenanceView(result) {
      const view = result.views?.provenance || {};
      const sources = (view.sources || []).slice(0, 80).map((source) => `
        <div class="compact-row">
          <div><strong>${escapeHtml(source.title || source.domain || source.url || 'source')}</strong><br>
            <span>${source.url ? `<a href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer">${escapeHtml(source.url)}</a>` : escapeHtml(source.domain || '')}</span>
          </div>
          <b>${source.claim_count || 0}</b>
        </div>
      `).join('');
      const sourceSummaries = (view.source_summaries || []).map((source) => {
        const stages = (source.stage_metrics || []).map((stage) =>
          `<span class="pill">${escapeHtml(stage.stage || '')} · ${escapeHtml(formatSeconds(stage.duration_seconds || 0))} · ${stage.item_count || 0} items</span>`
        ).join('');
        return `<div class="compact-row"><span>${escapeHtml(source.source || '')}${stages ? `<br>${stages}` : ''}</span><b>${source.finding_count || 0}/${source.evidence_claim_count || 0}${source.duration_seconds !== undefined ? `<br>${escapeHtml(formatSeconds(source.duration_seconds))}` : ''}</b></div>`;
      }).join('');
      $('provenanceDetails').innerHTML = `
        ${renderArtifactLine(result, 'provenance', view.source || 'findings/scouting_audit fallback')}
        <div class="detail-grid">
          <div class="detail-card"><h3>Run sources</h3>${sourceSummaries || '<div class="empty">No source summaries.</div>'}</div>
          <div class="detail-card"><h3>Domains</h3>${renderCountRows(Object.entries(view.source_domain_counts || {}).slice(0, 18))}</div>
          <div class="detail-card"><h3>Source kinds</h3>${renderCountRows(Object.entries(view.source_kind_counts || {}).slice(0, 12))}</div>
          <div class="detail-card"><h3>Source quality</h3>${renderCountRows(Object.entries(view.source_quality_counts || {}).slice(0, 12))}</div>
          <div class="detail-card"><h3>Scouts</h3>${renderCountRows(Object.entries(view.scout_counts || {}).slice(0, 18))}</div>
          <div class="detail-card"><h3>Access levels</h3>${renderCountRows(Object.entries(view.access_levels || {}).slice(0, 12))}</div>
        </div>
        <div class="detail-card"><h3>Source URLs</h3><div class="compact-list">${sources || '<div class="empty">No source URLs found.</div>'}</div></div>`;
    }

    function renderGapsView(result) {
      const view = result.views?.gaps || {};
      const structure = result.structure_audit || {};
      const rows = (view.rows || []).map((row) => `
        <tr>
          <td><strong>${escapeHtml(row.claim_type || '')}</strong></td>
          <td>${renderStatusTag(row.coverage_status)}</td>
          <td>${renderStatusTag(row.quality_status || row.coverage_status)}</td>
          <td>${row.claim_count ?? 0}</td>
          <td>${row.metric_claim_count ?? 0}</td>
          <td>${escapeHtml((row.quality_reasons || []).join(', '))}</td>
        </tr>
      `).join('');
      const warnings = (structure.warnings || []).map((warning) =>
        `<div class="notice ${String(warning).includes('No structural') ? '' : 'warning'}">${escapeHtml(warning)}</div>`
      ).join('');
      const summaryGaps = (view.summary_gaps || []).map((gap) => `<div class="compact-row"><span>${escapeHtml(gap)}</span><b>summary</b></div>`).join('');
      const noisy = (structure.noisy_claim_samples || []).map((claim) =>
        `<div class="claim"><div><span class="type">${escapeHtml(claim.claim_type || '')}</span> ${escapeHtml(claim.team || '')}</div><div>${escapeHtml(claim.claim || '')}</div></div>`
      ).join('');
      $('gapsDetails').innerHTML = `
        ${renderArtifactLine(result, 'gaps', view.source || 'scouting_audit.json fallback')}
        <div class="detail-grid">
          <div class="detail-card"><h3>Readiness</h3>
            <div class="compact-list">
              <div class="compact-row"><span>Status</span><b>${escapeHtml(view.status || result.status || '-')}</b></div>
              <div class="compact-row"><span>KG load ready</span><b>${escapeHtml(view.kg_load_ready ?? result.kg_load_ready ?? '-')}</b></div>
              <div class="compact-row"><span>Scouting complete</span><b>${escapeHtml(view.scouting_complete ?? result.scouting_complete ?? '-')}</b></div>
              <div class="compact-row"><span>Required coverage</span><b>${formatPercent(view.required_claim_type_coverage)}</b></div>
            </div>
          </div>
          <div class="detail-card"><h3>Missing topics</h3><p>${escapeHtml((view.missing_required_claim_types || []).join(', ') || 'None listed.')}</p></div>
          <div class="detail-card"><h3>Present topics</h3><p>${escapeHtml((view.present_required_claim_types || []).join(', ') || 'None listed.')}</p></div>
          <div class="detail-card"><h3>Coverage counters</h3>${renderCountRows(Object.entries(view.coverage || {}).filter(([, value]) => value !== null && value !== undefined))}</div>
        </div>
        ${warnings}
        ${summaryGaps ? `<div class="detail-card"><h3>Summary gaps</h3><div class="compact-list">${summaryGaps}</div></div>` : ''}
        <table class="gap-table">
          <thead><tr><th>Topic</th><th>Coverage</th><th>Quality</th><th>Claims</th><th>Metric claims</th><th>Reasons</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="6">No required topic audit found.</td></tr>'}</tbody>
        </table>
        ${noisy ? `<div class="notice warning"><strong>Noisy claim samples</strong>${noisy}</div>` : ''}`;
    }

    function renderLiveEvidence(live) {
      const rows = live.sources.map((source) =>
        `<div class="compact-row"><div><strong>${escapeHtml(source.source)}</strong><br><span>${escapeHtml(source.status || '')}</span></div><b>${source.evidence_claim_count || 0}</b></div>`
      ).join('');
      return `<div class="detail-grid">
        <div class="detail-card"><h3>Live evidence</h3>
          <div class="compact-list">
            <div class="compact-row"><span>Findings</span><b>${live.finding_count || 0}</b></div>
            <div class="compact-row"><span>Claims</span><b>${live.evidence_claim_count || 0}</b></div>
          </div>
        </div>
        <div class="detail-card"><h3>Sources producing claims</h3><div class="compact-list">${rows || '<div class="empty">No source events yet.</div>'}</div></div>
      </div>`;
    }

    function renderLiveProvenance(live) {
      const rows = live.sources.map((source) => {
        const stages = (source.stage_metrics || []).map((stage) =>
          `<span class="pill">${escapeHtml(stage.stage || '')} · ${escapeHtml(formatSeconds(stage.duration_seconds || 0))} · ${stage.item_count || 0} items</span>`
        ).join('');
        return `<div class="compact-row"><div><strong>${escapeHtml(source.source)}</strong><br><span>${escapeHtml(source.status || '')}${source.error_type ? ' · ' + escapeHtml(source.error_type) : ''}</span>${stages ? `<br>${stages}` : ''}</div><b>${source.finding_count || 0}</b></div>`;
      }).join('');
      return `<div class="detail-card"><h3>Live provenance</h3><div class="compact-list">${rows || '<div class="empty">No source events yet.</div>'}</div></div>`;
    }

    function renderLogsView(job) {
      const logs = job.logs || [];
      $('logSummary').textContent = `${logs.length} log lines · status ${job.status || 'idle'}${job.run_root ? ' · ' + job.run_root : ''}`;
      $('logBox').textContent = logs.join('\n') || 'No logs yet.';
      $('logBox').scrollTop = $('logBox').scrollHeight;
    }

    function renderArtifactLine(result, viewName, source) {
      const artifacts = result.views?.artifacts || {};
      const preferredByView = {
        domain: 'domain_graph',
        evidence: 'knowledge_views',
        provenance: 'knowledge_views',
        gaps: 'scouting_run_summary',
      };
      const preferred = preferredByView[viewName];
      const preferredAvailable = preferred ? artifacts[preferred]?.available : false;
      const fallback = !preferredAvailable || String(source || '').includes('fallback');
      const sourceText = source || 'artifact fallback';
      return `<div class="artifact-line"><span class="artifact-dot ${fallback ? 'fallback' : ''}"></span><strong>${escapeHtml(sourceText)}</strong><span>${fallback ? 'preferred artifact absent or empty; using fallback data' : 'preferred artifact loaded'}</span></div>`;
    }

    function renderCountRows(rows) {
      if (!rows.length) return '<div class="empty">No data.</div>';
      return `<div class="compact-list">${rows.map(([name, count]) => `<div class="compact-row"><span>${escapeHtml(name)}</span><b>${escapeHtml(count)}</b></div>`).join('')}</div>`;
    }

    function renderStatusTag(status) {
      const value = String(status || 'unknown');
      const kind = ['covered', 'usable', 'ready', 'complete'].includes(value) ? 'good' : (['missing', 'failed', 'error'].includes(value) ? 'bad' : 'warn');
      return `<span class="status-tag ${kind}">${escapeHtml(value)}</span>`;
    }

    function formatPercent(value) {
      const num = Number(value);
      if (!Number.isFinite(num)) return '-';
      return `${Math.round(num * 1000) / 10}%`;
    }

    function renderGraph(result) {
      const domainNetwork = result.views?.domain?.network;
      if ((domainNetwork?.nodes || []).length) {
        renderNetworkGraph(domainNetwork);
        return;
      }
      const preview = result.graph_preview || {};
      const network = preview.network || {};
      if ((network.nodes || []).length) {
        renderNetworkGraph(network);
        return;
      }
      const entityCounts = preview.entity_type_counts || {};
      if (!Object.keys(entityCounts).length) {
        $('graphViz').innerHTML = '';
        return;
      }
      const nodes = [
        ['source', entityCounts.source || 0, 62, 52],
        ['finding', entityCounts.finding || 0, 185, 52],
        ['evidence_claim', entityCounts.evidence_claim || 0, 318, 52],
        ['match', entityCounts.match || 0, 455, 52],
        ['team', entityCounts.team || 0, 455, 142],
        ['player', entityCounts.player || 0, 318, 142],
        ['claim_type', entityCounts.claim_type || 0, 185, 142],
        ['metric', entityCounts.metric || 0, 62, 142],
      ];
      const edges = [
        [62, 52, 185, 52], [185, 52, 318, 52], [318, 52, 455, 52],
        [318, 52, 455, 142], [318, 52, 318, 142], [318, 52, 185, 142],
        [318, 52, 62, 142],
      ].map(([x1, y1, x2, y2]) => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#aab6c7" stroke-width="2"></line>`).join('');
      const max = Math.max(1, ...nodes.map((n) => n[1]));
      const circles = nodes.map(([name, count, x, y]) => {
        const r = 18 + Math.round((Number(count) / max) * 24);
        const fill = count ? '#dbe8ff' : '#edf1f6';
        const stroke = count ? '#2f6fed' : '#aab6c7';
        return `<g><circle cx="${x}" cy="${y}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="2"></circle><text x="${x}" y="${y - 4}" text-anchor="middle" font-size="11" font-weight="700">${escapeHtml(name)}</text><text x="${x}" y="${y + 12}" text-anchor="middle" font-size="11">${count}</text></g>`;
      }).join('');
      $('graphViz').innerHTML = `<svg class="kg-mini" viewBox="0 0 520 205" role="img" aria-label="KG structure graph">${edges}${circles}</svg>`;
    }

    function renderNetworkGraph(network) {
      renderClusterMapGraph(network);
    }

    function renderClusterMapGraph(network) {
      const rawNodes = network.nodes || [];
      const rawLinks = network.links || [];
      const typeCounts = network.entity_type_counts || {};
      const graphWidth = 940;
      const graphHeight = 520;
      const groupDefs = [
        {key: 'matches', label: 'Matches', color: '#7db5ff', types: ['match', 'match_result', 'formation'], cx: 455, cy: 205, rx: 112, ry: 92, quota: 18},
        {key: 'teams', label: 'Teams', color: '#65c28b', types: ['team', 'team_match_profile'], cx: 250, cy: 222, rx: 138, ry: 112, quota: 28},
        {key: 'players', label: 'Players', color: '#7ed7ec', types: ['player'], cx: 646, cy: 188, rx: 96, ry: 72, quota: 64},
        {key: 'player_facts', label: 'Player facts', color: '#8bd37e', types: ['player_match_profile', 'player_stat_line', 'availability_event', 'availability_status', 'position'], cx: 686, cy: 334, rx: 128, ry: 96, quota: 72},
        {key: 'clubs', label: 'Clubs', color: '#c8a4ff', types: ['club'], cx: 354, cy: 364, rx: 88, ry: 76, quota: 18},
        {key: 'scouts', label: 'Scouts', color: '#b7c1d0', types: ['scout', 'scout_match_profile', 'finding'], cx: 545, cy: 116, rx: 92, ry: 70, quota: 28},
        {key: 'evidence', label: 'Evidence', color: '#ffbc65', types: ['evidence_claim', 'claim_type', 'claim_impact', 'claim_quality'], cx: 476, cy: 338, rx: 132, ry: 104, quota: 42},
        {key: 'sources', label: 'Sources', color: '#f2d36b', types: ['source', 'source_domain', 'source_domain_profile', 'source_kind', 'source_quality', 'source_recency'], cx: 168, cy: 358, rx: 98, ry: 82, quota: 36},
        {key: 'scouting', label: 'Scouting', color: '#d89cff', types: ['scouting_topic', 'team_scouting_topic', 'scouting_gap'], cx: 805, cy: 300, rx: 100, ry: 76, quota: 36},
        {key: 'context', label: 'Context', color: '#d3ce6d', types: ['venue', 'group', 'stage', 'country', 'body_part'], cx: 812, cy: 415, rx: 84, ry: 62, quota: 22},
      ];
      const groupForType = new Map();
      groupDefs.forEach((group) => group.types.forEach((type) => groupForType.set(type, group)));
      const byGroup = new Map(groupDefs.map((group) => [group.key, []]));
      rawNodes.forEach((node) => {
        const group = groupForType.get(node.type) || groupDefs[groupDefs.length - 1];
        byGroup.get(group.key).push(node);
      });
      const sortNodes = (items) => items.slice().sort((a, b) =>
        Number(b.degree || 0) - Number(a.degree || 0) || String(a.label || '').localeCompare(String(b.label || ''))
      );
      const nodes = [];
      const selectedIds = new Set();
      groupDefs.forEach((group) => {
        sortNodes(byGroup.get(group.key) || []).slice(0, group.quota).forEach((node) => {
          if (selectedIds.has(node.id)) return;
          selectedIds.add(node.id);
          nodes.push({...node, groupKey: group.key});
        });
      });
      if (!nodes.length) {
        $('graphViz').innerHTML = '<div class="empty">No graph nodes available for this run.</div>';
        return;
      }
      const nodeById = new Map(nodes.map((node) => [node.id, node]));
      const links = rawLinks.filter((link) => nodeById.has(link.source) && nodeById.has(link.target));
      const countForGroup = (group) => group.types.reduce((sum, type) => sum + Number(typeCounts[type] || 0), 0);
      const chips = groupDefs.map((group) =>
        `<span class="kg-chip"><i style="background:${group.color}; color:${group.color};"></i>${escapeHtml(group.label)} ${countForGroup(group)}</span>`
      ).join('');
      const placedByGroup = new Map();
      groupDefs.forEach((group) => placedByGroup.set(group.key, nodes.filter((node) => node.groupKey === group.key)));
      const strongRelationTypes = new Set(['member_of', 'has_match_profile', 'has_player_match_profile', 'about_player', 'about_team', 'plays_home_in', 'plays_away_in']);
      const importantLink = (link) => {
        const source = nodeById.get(link.source);
        const target = nodeById.get(link.target);
        const types = [source?.type, target?.type];
        return types.includes('player') || types.includes('team') || types.includes('match') || strongRelationTypes.has(link.type);
      };
      const setPoint = (node, x, y, r) => {
        node.x = x;
        node.y = y;
        node.r = r;
        node.vx = 0;
        node.vy = 0;
      };
      const radiusForNode = (node) => {
        const degreeLift = Math.min(2.1, Math.sqrt(Number(node.degree || 0)) * 0.16);
        if (node.type === 'match') return 8.6 + degreeLift;
        if (node.type === 'team') return 7.5 + degreeLift;
        if (node.type === 'player') return 5.8 + degreeLift;
        if (node.type === 'player_match_profile') return 4.7 + degreeLift;
        if (['evidence_claim', 'source', 'finding'].includes(node.type)) return 4.2 + degreeLift;
        return 3.6 + degreeLift;
      };
      const hashUnit = (value, salt = 0) => {
        let hash = 2166136261 + salt;
        const text = String(value || '');
        for (let index = 0; index < text.length; index += 1) {
          hash ^= text.charCodeAt(index);
          hash = Math.imul(hash, 16777619);
        }
        return ((hash >>> 0) % 10000) / 10000;
      };
      groupDefs.forEach((group) => {
        const groupNodes = placedByGroup.get(group.key) || [];
        const golden = Math.PI * (3 - Math.sqrt(5));
        groupNodes.forEach((node, index) => {
          const t = groupNodes.length <= 1 ? 0 : (index + 0.5) / Math.max(1, groupNodes.length);
          const ring = Math.sqrt(t) * (0.48 + hashUnit(node.id, 7) * 0.3);
          const angle = index * golden + hashUnit(node.id, 13) * Math.PI * 2;
          const jitter = (hashUnit(node.id, 29) - 0.5) * 8;
          setPoint(
            node,
            group.cx + Math.cos(angle) * group.rx * ring + jitter,
            group.cy + Math.sin(angle) * group.ry * ring - jitter,
            radiusForNode(node)
          );
        });
      });
      for (let tick = 0; tick < 86; tick += 1) {
        nodes.forEach((node) => {
          const group = groupDefs.find((item) => item.key === node.groupKey) || groupDefs[groupDefs.length - 1];
          const groupForce = node.type === 'match' ? 0.018 : 0.011;
          node.vx += (group.cx - node.x) * groupForce;
          node.vy += (group.cy - node.y) * groupForce;
        });
        links.forEach((link) => {
          const source = nodeById.get(link.source);
          const target = nodeById.get(link.target);
          if (!source || !target) return;
          const dx = target.x - source.x;
          const dy = target.y - source.y;
          const distance = Math.max(1, Math.hypot(dx, dy));
          const sameGroup = source.groupKey === target.groupKey;
          const desired = sameGroup ? 32 : (importantLink(link) ? 84 : 118);
          const strength = sameGroup ? 0.0028 : (importantLink(link) ? 0.004 : 0.0015);
          const pull = (distance - desired) * strength;
          const fx = (dx / distance) * pull;
          const fy = (dy / distance) * pull;
          source.vx += fx;
          source.vy += fy;
          target.vx -= fx;
          target.vy -= fy;
        });
        for (let left = 0; left < nodes.length; left += 1) {
          for (let right = left + 1; right < nodes.length; right += 1) {
            const a = nodes[left];
            const b = nodes[right];
            const dx = b.x - a.x;
            const dy = b.y - a.y;
            const distance = Math.max(0.1, Math.hypot(dx, dy));
            const closeRange = a.groupKey === b.groupKey ? 42 : 30;
            const minDistance = a.r + b.r + closeRange * (a.groupKey === b.groupKey ? 0.18 : 0.08);
            if (distance > minDistance) continue;
            const push = ((minDistance - distance) / distance) * 0.12;
            const fx = dx * push;
            const fy = dy * push;
            a.vx -= fx;
            a.vy -= fy;
            b.vx += fx;
            b.vy += fy;
          }
        }
        nodes.forEach((node) => {
          node.vx *= 0.68;
          node.vy *= 0.68;
          node.x = Math.max(30, Math.min(graphWidth - 30, node.x + node.vx));
          node.y = Math.max(50, Math.min(graphHeight - 30, node.y + node.vy));
        });
      }
      const styleForNode = (node) => {
        const group = groupDefs.find((item) => item.key === node.groupKey) || groupDefs[groupDefs.length - 1];
        if (node.type === 'match') return {fill: '#8fc4ff', stroke: '#e7f2ff'};
        if (node.type === 'team') return {fill: '#79d69d', stroke: '#e7f9ee'};
        if (node.type === 'player') return {fill: '#74e0f4', stroke: '#e6fbff'};
        if (node.type === 'evidence_claim') return {fill: '#ffc46d', stroke: '#fff1d9'};
        return {fill: group.color, stroke: '#fff8d8'};
      };
      const edgeSvg = links.map((link) => {
        const source = nodeById.get(link.source);
        const target = nodeById.get(link.target);
        if (!source || !target) return '';
        const strong = importantLink(link);
        return `<line x1="${source.x}" y1="${source.y}" x2="${target.x}" y2="${target.y}" stroke="${strong ? '#d7e9ff' : '#6f785e'}" stroke-width="${strong ? 1.5 : 0.8}" opacity="${strong ? 0.55 : 0.24}"><title>${escapeHtml(link.type || 'related_to')}</title></line>`;
      }).join('');
      const halos = groupDefs.map((group) => {
        const count = countForGroup(group);
        if (!count && group.key !== 'players') return '';
        return `<g>
          <ellipse cx="${group.cx}" cy="${group.cy}" rx="${group.rx}" ry="${group.ry}" fill="${group.color}" opacity="0.15" stroke="${group.color}" stroke-width="2"></ellipse>
          <text x="${group.cx}" y="${group.cy - group.ry - 12}" text-anchor="middle" font-size="11" font-weight="850" fill="${group.color}">${escapeHtml(group.label.toUpperCase())} · ${count}</text>
        </g>`;
      }).join('');
      const teamLabelCount = nodes.filter((item) => item.type === 'team').length;
      const labelVisible = (node) => node.type === 'match' || (node.type === 'team' && teamLabelCount <= 6);
      const truncate = (text, max) => {
        const value = String(text || '');
        return value.length > max ? value.slice(0, max - 3) + '...' : value;
      };
      const nodeSvg = nodes.map((node) => {
        const style = styleForNode(node);
        const label = truncate(node.label || node.id, node.type === 'player' ? 22 : 24);
        return `<g class="kg-node" data-node-id="${escapeHtml(node.id)}" tabindex="0">
          <circle cx="${node.x}" cy="${node.y}" r="${node.r}" fill="${style.fill}" stroke="${style.stroke}" stroke-width="1.5"></circle>
          ${labelVisible(node) ? `<text x="${node.x}" y="${node.y + node.r + 13}" text-anchor="middle" font-size="9.5" font-weight="750" fill="#e8edd9">${escapeHtml(label)}</text>` : ''}
          <title>${escapeHtml(node.type || 'unknown')} · ${escapeHtml(node.label || node.id)}\n${escapeHtml(node.id)}</title>
        </g>`;
      }).join('');
      const playerCount = Number(typeCounts.player || 0);
      const playerProfileCount = Number(typeCounts.player_match_profile || 0);
      const noPlayers = playerCount === 0;
      const notice = noPlayers
        ? '<div class="notice warning"><strong>0 player nodes in this run.</strong> Add <code>public</code>, <code>camel_deep_research</code>, or <code>wikidata_profiles</code> to create player nodes.</div>'
        : '';
      const background = `
        <defs>
          <radialGradient id="clusterBg" cx="48%" cy="42%" r="75%">
            <stop offset="0%" stop-color="#2a3315"></stop>
            <stop offset="65%" stop-color="#151b0c"></stop>
            <stop offset="100%" stop-color="#0b1007"></stop>
          </radialGradient>
          <filter id="dotGlow"><feGaussianBlur stdDeviation="2.5" result="blur"></feGaussianBlur><feMerge><feMergeNode in="blur"></feMergeNode><feMergeNode in="SourceGraphic"></feMergeNode></feMerge></filter>
        </defs>
        <rect x="0" y="0" width="${graphWidth}" height="${graphHeight}" rx="10" fill="url(#clusterBg)"></rect>
        <circle cx="470" cy="265" r="172" fill="none" stroke="#394420" stroke-width="1" stroke-dasharray="2 7"></circle>`;
      $('graphViz').innerHTML = `<div class="kg-chipbar">${chips}</div>${notice}<svg class="kg-cluster-map" viewBox="0 0 ${graphWidth} ${graphHeight}" role="img" aria-label="Knowledge graph cluster map">${background}${halos}${edgeSvg}<g filter="url(#dotGlow)">${nodeSvg}</g></svg><div class="kg-detail" id="kgDetail"></div>`;
      const defaultNode = nodes.find((node) => node.type === 'player') || nodes.find((node) => node.type === 'match') || nodes[0];
      bindGraphInspector(nodes, links, defaultNode?.id);
    }

    function renderRadialKgGraph(network) {
      const rawNodes = network.nodes || [];
      const rawLinks = network.links || [];
      const hasPlayers = rawNodes.some((node) => node.type === 'player');
      const quotas = hasPlayers ? {
        match: 2,
        team: 4,
        team_match_profile: 4,
        player: 42,
        player_match_profile: 42,
        player_stat_line: 26,
        availability_event: 22,
        availability_status: 8,
        club: 18,
        position: 18,
        formation: 6,
        match_result: 8,
        venue: 3,
        group: 3,
        stage: 3,
        evidence_claim: 0,
        finding: 0,
        source: 0,
        scout: 0,
        claim_type: 0,
      } : {
        match: 2,
        team: 4,
        team_match_profile: 4,
        evidence_claim: 34,
        finding: 10,
        source: 12,
        scout: 4,
        claim_type: 14,
        metric: 18,
        scouting_topic: 12,
        team_scouting_topic: 12,
        venue: 3,
        group: 3,
        stage: 3,
        formation: 4,
        match_result: 8,
      };
      const order = [
        'match', 'team', 'team_match_profile',
        'player', 'player_match_profile', 'player_stat_line', 'availability_event', 'availability_status', 'club', 'position',
        'formation', 'match_result', 'venue', 'group', 'stage',
        'evidence_claim', 'finding', 'source', 'scout', 'claim_type', 'metric', 'scouting_topic', 'team_scouting_topic'
      ];
      const selected = [];
      const selectedIds = new Set();
      const byType = new Map();
      rawNodes.forEach((node) => {
        if (!byType.has(node.type)) byType.set(node.type, []);
        byType.get(node.type).push(node);
      });
      const sortNodes = (items) => items.slice().sort((a, b) =>
        Number(b.degree || 0) - Number(a.degree || 0) || String(a.label || '').localeCompare(String(b.label || ''))
      );
      const addNode = (node) => {
        if (!node || selectedIds.has(node.id)) return;
        selectedIds.add(node.id);
        selected.push({...node});
      };
      order.forEach((type) => {
        sortNodes(byType.get(type) || []).slice(0, quotas[type] || 0).forEach(addNode);
      });
      if (!selected.length) {
        $('graphViz').innerHTML = '<div class="empty">No graph nodes available for this run.</div>';
        return;
      }
      const nodes = selected;
      const nodeById = new Map(nodes.map((node) => [node.id, node]));
      const links = rawLinks.filter((link) => nodeById.has(link.source) && nodeById.has(link.target));
      const matchNode = nodes.find((node) => node.type === 'match');
      const teams = nodes.filter((node) => node.type === 'team').sort((a, b) => {
        const sideRank = {home: 0, away: 1};
        return (sideRank[a.attributes?.side] ?? 9) - (sideRank[b.attributes?.side] ?? 9) || String(a.label || '').localeCompare(String(b.label || ''));
      });
      const homeTeam = teams.find((node) => node.attributes?.side === 'home') || teams[0];
      const awayTeam = teams.find((node) => node.attributes?.side === 'away') || teams.find((node) => node.id !== homeTeam?.id);
      const homeTeamName = homeTeam?.label || '';
      const awayTeamName = awayTeam?.label || '';
      const teamForNode = (node) => {
        if (node.attributes?.team) return String(node.attributes.team);
        if (node.type === 'team') return node.label;
        const direct = rawLinks.find((link) =>
          (link.source === node.id && String(link.target).startsWith('team:')) ||
          (link.target === node.id && String(link.source).startsWith('team:'))
        );
        if (!direct) return '';
        const teamId = String(direct.source).startsWith('team:') ? direct.source : direct.target;
        return rawNodes.find((candidate) => candidate.id === teamId)?.label || '';
      };
      const sideForNode = (node) => {
        const team = teamForNode(node);
        if (team && team === homeTeamName) return 'home';
        if (team && team === awayTeamName) return 'away';
        if (node.attributes?.side === 'home' || node.attributes?.side === 'away') return node.attributes.side;
        return 'neutral';
      };
      const graphWidth = 1180;
      const graphHeight = hasPlayers ? 780 : 700;
      const cx = graphWidth / 2;
      const cy = hasPlayers ? 355 : 335;
      const setNode = (node, x, y, r) => {
        if (!node) return;
        node.x = x;
        node.y = y;
        node.r = r;
      };
      const placeArc = (items, centerX, centerY, radius, startDeg, endDeg, nodeRadius) => {
        const count = items.length;
        if (!count) return;
        const span = endDeg - startDeg;
        items.forEach((node, index) => {
          const t = count === 1 ? 0.5 : index / (count - 1);
          const angle = (startDeg + span * t) * Math.PI / 180;
          setNode(node, centerX + Math.cos(angle) * radius, centerY + Math.sin(angle) * radius, nodeRadius);
        });
      };
      const placeRing = (items, centerX, centerY, radius, nodeRadius, startDeg = -90) => {
        const count = items.length;
        if (!count) return;
        items.forEach((node, index) => {
          const angle = (startDeg + 360 * index / count) * Math.PI / 180;
          setNode(node, centerX + Math.cos(angle) * radius, centerY + Math.sin(angle) * radius, nodeRadius);
        });
      };
      setNode(matchNode, cx, hasPlayers ? 130 : 190, 58);
      setNode(homeTeam, hasPlayers ? 260 : 350, hasPlayers ? 310 : 330, 50);
      setNode(awayTeam, hasPlayers ? 920 : 830, hasPlayers ? 310 : 330, 50);
      const contextNodes = nodes.filter((node) => ['venue', 'group', 'stage', 'formation', 'match_result'].includes(node.type));
      placeArc(contextNodes, cx, hasPlayers ? 150 : 190, hasPlayers ? 180 : 145, 15, 165, 22);
      const homePlayers = nodes.filter((node) => node.type === 'player' && sideForNode(node) === 'home');
      const awayPlayers = nodes.filter((node) => node.type === 'player' && sideForNode(node) === 'away');
      const homeProfiles = nodes.filter((node) => node.type === 'player_match_profile' && sideForNode(node) === 'home');
      const awayProfiles = nodes.filter((node) => node.type === 'player_match_profile' && sideForNode(node) === 'away');
      const homeFacts = nodes.filter((node) => ['player_stat_line', 'availability_event', 'availability_status', 'club', 'position'].includes(node.type) && sideForNode(node) === 'home');
      const awayFacts = nodes.filter((node) => ['player_stat_line', 'availability_event', 'availability_status', 'club', 'position'].includes(node.type) && sideForNode(node) === 'away');
      if (hasPlayers) {
        placeArc(homePlayers, 260, 435, 180, 140, 220, 36);
        placeArc(awayPlayers, 920, 435, 180, -40, 40, 36);
        placeArc(homeProfiles, 380, 430, 125, 120, 240, 24);
        placeArc(awayProfiles, 800, 430, 125, -60, 60, 24);
        placeArc(homeFacts, 520, 470, 150, 105, 255, 18);
        placeArc(awayFacts, 660, 470, 150, -75, 75, 18);
      }
      const claims = nodes.filter((node) => node.type === 'evidence_claim');
      const findings = nodes.filter((node) => node.type === 'finding');
      const sources = nodes.filter((node) => ['source', 'scout'].includes(node.type));
      const topics = nodes.filter((node) => ['claim_type', 'metric', 'scouting_topic', 'team_scouting_topic'].includes(node.type));
      if (hasPlayers) {
        placeArc(claims, cx, 430, 265, 205, 335, 14);
        placeArc(findings, cx, 95, 240, 200, 340, 18);
        placeArc(sources, cx, 95, 360, 205, 335, 16);
        placeArc(topics, cx, 540, 300, 20, 160, 13);
      } else {
        placeRing(claims, cx, cy, 205, 21, -110);
        placeArc(findings, cx, cy, 290, 205, 335, 22);
        placeArc(sources, cx, cy, 355, 205, 335, 18);
        placeArc(topics, cx, cy, 300, 20, 160, 15);
      }
      nodes.forEach((node, index) => {
        if (node.x !== undefined && node.y !== undefined) return;
        const angle = (-90 + 360 * index / nodes.length) * Math.PI / 180;
        setNode(node, cx + Math.cos(angle) * 310, cy + Math.sin(angle) * 310, 14);
      });
      const styleForNode = (node) => {
        if (node.type === 'match') return {fill: '#2f6fed', stroke: '#174da5', text: '#fff', icon: 'VS'};
        if (node.type === 'team') return {fill: '#20825b', stroke: '#0d6242', text: '#fff', icon: 'T'};
        if (node.type === 'player') return {fill: '#007a99', stroke: '#005d72', text: '#fff', icon: 'P'};
        if (node.type === 'player_match_profile') return {fill: '#e9f7ff', stroke: '#007a99', text: '#073f4d', icon: 'MP'};
        if (['player_stat_line', 'availability_event', 'availability_status', 'club', 'position'].includes(node.type)) return {fill: '#f2f7df', stroke: '#6f8500', text: '#344100', icon: _nodeIcon(node)};
        if (node.type === 'evidence_claim') return {fill: '#fff5db', stroke: '#a75f00', text: '#5d3600', icon: 'C'};
        if (node.type === 'finding') return {fill: '#dbe8ff', stroke: '#2f6fed', text: '#174da5', icon: 'F'};
        if (['source', 'scout'].includes(node.type)) return {fill: '#eef1f6', stroke: '#687282', text: '#354052', icon: 'S'};
        return {fill: '#f3efff', stroke: '#7357c8', text: '#392179', icon: '•'};
      };
      const importantLink = (link) => {
        const source = nodeById.get(link.source);
        const target = nodeById.get(link.target);
        const types = [source?.type, target?.type];
        return types.includes('player') || types.includes('team') || types.includes('match') ||
          ['member_of', 'has_match_profile', 'has_player_match_profile', 'about_player', 'about_team', 'plays_home_in', 'plays_away_in'].includes(link.type);
      };
      const edgeSvg = links.map((link) => {
        const source = nodeById.get(link.source);
        const target = nodeById.get(link.target);
        if (!source || !target) return '';
        const strong = importantLink(link);
        return `<line x1="${source.x}" y1="${source.y}" x2="${target.x}" y2="${target.y}" stroke="${strong ? '#53677f' : '#b8c4d3'}" stroke-width="${strong ? 2.2 : 1.1}" opacity="${strong ? 0.72 : 0.34}"><title>${escapeHtml(link.type || 'related_to')}</title></line>`;
      }).join('');
      const truncate = (text, max) => {
        const value = String(text || '');
        return value.length > max ? value.slice(0, max - 3) + '...' : value;
      };
      const labelVisible = (node) => ['match', 'team', 'player'].includes(node.type) || (!hasPlayers && ['evidence_claim', 'finding'].includes(node.type));
      const nodeSvg = nodes.map((node) => {
        const style = styleForNode(node);
        const label = truncate(node.label || node.id, node.type === 'player' ? 24 : 26);
        const iconSize = node.r > 30 ? 16 : 11;
        const labelSize = node.type === 'match' ? 16 : (node.type === 'team' || node.type === 'player' ? 13 : 11);
        const labelY = node.y + node.r + 18;
        return `<g class="kg-node" data-node-id="${escapeHtml(node.id)}" tabindex="0">
          <circle cx="${node.x}" cy="${node.y}" r="${node.r}" fill="${style.fill}" stroke="${style.stroke}" stroke-width="3"></circle>
          <text x="${node.x}" y="${node.y + 5}" text-anchor="middle" font-size="${iconSize}" font-weight="850" fill="${style.text}">${escapeHtml(style.icon)}</text>
          ${labelVisible(node) ? `<text x="${node.x}" y="${labelY}" text-anchor="middle" font-size="${labelSize}" font-weight="780" fill="#1b1f24">${escapeHtml(label)}</text>` : ''}
          <title>${escapeHtml(node.type || 'unknown')} · ${escapeHtml(node.label || node.id)}\n${escapeHtml(node.id)}</title>
        </g>`;
      }).join('');
      const background = `
        <defs>
          <radialGradient id="graphGlow" cx="50%" cy="45%" r="70%">
            <stop offset="0%" stop-color="#ffffff"></stop>
            <stop offset="60%" stop-color="#f6f9fb"></stop>
            <stop offset="100%" stop-color="#eef3f5"></stop>
          </radialGradient>
        </defs>
        <rect x="22" y="22" width="${graphWidth - 44}" height="${graphHeight - 44}" rx="28" fill="url(#graphGlow)" stroke="#d8dde6"></rect>
        <circle cx="${cx}" cy="${cy}" r="${hasPlayers ? 250 : 205}" fill="none" stroke="#d8dde6" stroke-width="1.4" stroke-dasharray="8 10"></circle>
        <circle cx="${cx}" cy="${cy}" r="${hasPlayers ? 355 : 315}" fill="none" stroke="#e3e8ef" stroke-width="1.2"></circle>
        ${hasPlayers ? `<text x="120" y="88" font-size="13" font-weight="850" fill="#20825b">HOME CLUSTER</text><text x="${graphWidth - 120}" y="88" text-anchor="end" font-size="13" font-weight="850" fill="#20825b">AWAY CLUSTER</text>` : ''}
        ${!hasPlayers ? `<text x="${cx}" y="76" text-anchor="middle" font-size="14" font-weight="800" fill="#a75f00">No player nodes in this run. Add public, camel_deep_research, or wikidata_profiles.</text>` : ''}`;
      const shownPlayers = nodes.filter((node) => node.type === 'player').length;
      const shownPlayerProfiles = nodes.filter((node) => node.type === 'player_match_profile').length;
      const totalPlayers = network.entity_type_counts?.player ?? shownPlayers;
      const totalPlayerProfiles = network.entity_type_counts?.player_match_profile ?? shownPlayerProfiles;
      const legendRows = hasPlayers ? [
        ['Match', '#2f6fed'],
        ['Team', '#20825b'],
        ['Player', '#007a99'],
        ['Fact', '#6f8500'],
      ] : [
        ['Match', '#2f6fed'],
        ['Team', '#20825b'],
        ['Player', '#007a99'],
        ['Claim', '#a75f00'],
        ['Source', '#687282'],
      ];
      const legendItems = legendRows.map(([name, color]) => `<span class="legend-item"><i class="legend-dot" style="background:${color}"></i>${name}</span>`).join('');
      $('graphViz').innerHTML = `<div class="graph-meta"><span>Graph view · ${nodes.length} nodes · ${links.length} links · players ${shownPlayers}/${totalPlayers} · profiles ${shownPlayerProfiles}/${totalPlayerProfiles}</span><span class="graph-legend">${legendItems}</span></div><svg class="kg-football" style="height:${graphHeight}px" viewBox="0 0 ${graphWidth} ${graphHeight}" role="img" aria-label="Knowledge graph node-link view">${background}${edgeSvg}${nodeSvg}</svg><div class="kg-detail" id="kgDetail"></div>`;
      const defaultNode = nodes.find((node) => node.type === 'player') || nodes.find((node) => node.type === 'match') || nodes[0];
      bindGraphInspector(nodes, links, defaultNode?.id);
    }

    function _nodeIcon(node) {
      if (node.type === 'player_stat_line') return 'ST';
      if (node.type === 'availability_event' || node.type === 'availability_status') return 'AV';
      if (node.type === 'club') return 'CL';
      if (node.type === 'position') return 'PO';
      return 'F';
    }

    function renderFootballNetworkGraph(network) {
      const rawNodes = network.nodes || [];
      const rawLinks = network.links || [];
      const visibleTypes = new Set([
        'match', 'team', 'team_match_profile', 'venue', 'group', 'stage', 'formation', 'match_result',
        'player', 'player_match_profile', 'player_stat_line', 'availability_event', 'availability_status',
        'club', 'position', 'body_part'
      ]);
      const nodes = rawNodes.filter((node) => visibleTypes.has(node.type)).map((node) => ({...node}));
      if (!nodes.length) {
        renderEvidenceGraph(network);
        return;
      }
      const nodeById = new Map(nodes.map((node) => [node.id, node]));
      const links = rawLinks.filter((link) => nodeById.has(link.source) && nodeById.has(link.target));
      const matchNode = nodes.find((node) => node.type === 'match');
      const teams = nodes.filter((node) => node.type === 'team').sort((a, b) => {
        const sideRank = {home: 0, away: 1};
        return (sideRank[a.attributes?.side] ?? 9) - (sideRank[b.attributes?.side] ?? 9) || String(a.label).localeCompare(String(b.label));
      });
      const homeTeam = teams.find((node) => node.attributes?.side === 'home') || teams[0];
      const awayTeam = teams.find((node) => node.attributes?.side === 'away') || teams.find((node) => node.id !== homeTeam?.id);
      const homeTeamName = homeTeam?.label || '';
      const awayTeamName = awayTeam?.label || '';
      const teamForNode = (node) => {
        if (node.attributes?.team) return String(node.attributes.team);
        if (node.type === 'team') return node.label;
        const direct = rawLinks.find((link) =>
          (link.source === node.id && String(link.target).startsWith('team:')) ||
          (link.target === node.id && String(link.source).startsWith('team:'))
        );
        if (!direct) return '';
        const teamId = String(direct.source).startsWith('team:') ? direct.source : direct.target;
        return rawNodes.find((candidate) => candidate.id === teamId)?.label || '';
      };
      const sideForNode = (node) => {
        const team = teamForNode(node);
        if (team && team === homeTeamName) return 'home';
        if (team && team === awayTeamName) return 'away';
        if (node.attributes?.side === 'home' || node.attributes?.side === 'away') return node.attributes.side;
        return 'neutral';
      };
      const byLabel = (a, b) => String(a.label || '').localeCompare(String(b.label || ''));
      const groups = {
        homePlayers: nodes.filter((node) => node.type === 'player' && sideForNode(node) === 'home').sort(byLabel),
        awayPlayers: nodes.filter((node) => node.type === 'player' && sideForNode(node) === 'away').sort(byLabel),
        homeProfiles: nodes.filter((node) => node.type === 'player_match_profile' && sideForNode(node) === 'home').sort(byLabel),
        awayProfiles: nodes.filter((node) => node.type === 'player_match_profile' && sideForNode(node) === 'away').sort(byLabel),
        homeFacts: nodes.filter((node) => ['player_stat_line', 'availability_event', 'availability_status', 'club', 'position', 'body_part'].includes(node.type) && sideForNode(node) === 'home').sort(byLabel),
        awayFacts: nodes.filter((node) => ['player_stat_line', 'availability_event', 'availability_status', 'club', 'position', 'body_part'].includes(node.type) && sideForNode(node) === 'away').sort(byLabel),
        context: nodes.filter((node) => ['venue', 'group', 'stage', 'formation', 'match_result'].includes(node.type)).sort(byLabel),
      };
      const maxRows = Math.max(
        4,
        groups.homePlayers.length,
        groups.awayPlayers.length,
        groups.homeProfiles.length,
        groups.awayProfiles.length,
        groups.homeFacts.length,
        groups.awayFacts.length
      );
      const graphWidth = 1180;
      const graphHeight = Math.max(780, 390 + maxRows * 84);
      const placeStack = (items, x, yStart, gap, radius) => {
        items.forEach((node, index) => {
          Object.assign(node, {x, y: yStart + index * gap, r: radius});
        });
      };
      if (matchNode) Object.assign(matchNode, {x: 590, y: 110, r: 58});
      if (homeTeam) Object.assign(homeTeam, {x: 260, y: 238, r: 50});
      if (awayTeam) Object.assign(awayTeam, {x: 920, y: 238, r: 50});
      nodes.filter((node) => node.type === 'team_match_profile').forEach((node) => {
        Object.assign(node, {x: sideForNode(node) === 'away' ? 920 : 260, y: 338, r: 28});
      });
      groups.context.forEach((node, index) => {
        const offset = index - (groups.context.length - 1) / 2;
        Object.assign(node, {x: 590 + offset * 104, y: 238, r: node.type === 'match_result' ? 26 : 22});
      });
      placeStack(groups.homePlayers, 120, 440, 92, 36);
      placeStack(groups.homeProfiles, 330, 440, 92, 25);
      placeStack(groups.homeFacts, 505, 420, 66, 20);
      placeStack(groups.awayFacts, 675, 420, 66, 20);
      placeStack(groups.awayProfiles, 850, 440, 92, 25);
      placeStack(groups.awayPlayers, 1060, 440, 92, 36);
      nodes.forEach((node, index) => {
        if (node.x !== undefined && node.y !== undefined) return;
        Object.assign(node, {x: 590, y: 420 + index * 54, r: 18});
      });
      const styleForNode = (node) => {
        if (node.type === 'match') return {fill: '#2f6fed', stroke: '#174da5', text: '#ffffff', icon: 'VS'};
        if (node.type === 'team') return {fill: '#20825b', stroke: '#0d6242', text: '#ffffff', icon: 'TM'};
        if (node.type === 'team_match_profile') return {fill: '#e6f7ed', stroke: '#20825b', text: '#123f2c', icon: 'TP'};
        if (node.type === 'player') return {fill: '#007a99', stroke: '#005d72', text: '#ffffff', icon: 'P'};
        if (node.type === 'player_match_profile') return {fill: '#e9f7ff', stroke: '#007a99', text: '#073f4d', icon: 'MP'};
        if (node.type === 'player_stat_line') return {fill: '#f2f7df', stroke: '#6f8500', text: '#344100', icon: 'ST'};
        if (node.type === 'availability_event' || node.type === 'availability_status') return {fill: '#fff5db', stroke: '#a75f00', text: '#5d3600', icon: 'AV'};
        if (node.type === 'club') return {fill: '#f3efff', stroke: '#7357c8', text: '#392179', icon: 'CL'};
        if (node.type === 'position') return {fill: '#f3efff', stroke: '#7357c8', text: '#392179', icon: 'PO'};
        return {fill: '#eef1f6', stroke: '#687282', text: '#1b1f24', icon: 'KG'};
      };
      const truncate = (text, max) => {
        const value = String(text || '');
        return value.length > max ? value.slice(0, max - 3) + '...' : value;
      };
      const pathFor = (source, target) => {
        const sx = source.x;
        const sy = source.y;
        const tx = target.x;
        const ty = target.y;
        const midX = (sx + tx) / 2;
        const bend = Math.max(35, Math.min(130, Math.abs(tx - sx) * 0.28));
        const c1x = sx < tx ? midX - bend : midX + bend;
        const c2x = sx < tx ? midX + bend : midX - bend;
        return `M${sx},${sy} C${c1x},${sy} ${c2x},${ty} ${tx},${ty}`;
      };
      const edgeSvg = links.map((link) => {
        const source = nodeById.get(link.source);
        const target = nodeById.get(link.target);
        if (!source || !target) return '';
        const playerLink = [source.type, target.type].includes('player') || [source.type, target.type].includes('player_match_profile');
        const important = playerLink || ['member_of', 'has_match_profile', 'has_player_match_profile', 'about_player', 'about_team'].includes(link.type);
        return `<path d="${pathFor(source, target)}" fill="none" stroke="${important ? '#52677f' : '#b8c4d3'}" stroke-width="${important ? 2.3 : 1.2}" opacity="${important ? 0.8 : 0.4}"><title>${escapeHtml(link.type || 'related_to')}</title></path>`;
      }).join('');
      const labelForNode = (node) => {
        if (node.type === 'match') return truncate(node.label, 30);
        if (node.type === 'team') return truncate(node.label, 20);
        if (node.type === 'player') return truncate(node.label, 24);
        if (node.type === 'player_match_profile') return truncate((node.attributes?.player || node.label || '').replace(' match profile', ''), 22);
        if (node.type === 'player_stat_line') return 'stats';
        if (node.type === 'availability_event') return truncate(node.attributes?.status || 'availability', 14);
        if (node.type === 'club') return truncate(node.label, 16);
        if (node.type === 'position') return truncate(node.label, 14);
        return truncate(node.label, 18);
      };
      const nodeSvg = nodes.map((node) => {
        const style = styleForNode(node);
        const label = labelForNode(node);
        const labelSize = node.type === 'match' ? 17 : (node.type === 'team' || node.type === 'player' ? 15 : 12);
        const labelOffset = node.r + (node.type === 'match' ? 24 : 20);
        return `<g class="kg-node" data-node-id="${escapeHtml(node.id)}" tabindex="0">
          <circle cx="${node.x}" cy="${node.y}" r="${node.r}" fill="${style.fill}" stroke="${style.stroke}" stroke-width="3"></circle>
          <text x="${node.x}" y="${node.y + 5}" text-anchor="middle" font-size="${node.r > 30 ? 15 : 11}" font-weight="800" fill="${style.text}">${escapeHtml(style.icon)}</text>
          <text x="${node.x}" y="${node.y + labelOffset}" text-anchor="middle" font-size="${labelSize}" font-weight="${node.type === 'player' || node.type === 'team' || node.type === 'match' ? 800 : 650}" fill="#1b1f24">${escapeHtml(label)}</text>
          <text x="${node.x}" y="${node.y + labelOffset + 15}" text-anchor="middle" font-size="10" fill="#687282">${escapeHtml(String(node.type || '').replaceAll('_', ' '))}</text>
          <title>${escapeHtml(node.type || 'unknown')} · ${escapeHtml(node.label || node.id)}\n${escapeHtml(node.id)}</title>
        </g>`;
      }).join('');
      const background = `
        <defs>
          <linearGradient id="kgField" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0%" stop-color="#f7fbff"></stop>
            <stop offset="55%" stop-color="#f5fbf7"></stop>
            <stop offset="100%" stop-color="#fffaf1"></stop>
          </linearGradient>
        </defs>
        <rect x="18" y="18" width="${graphWidth - 36}" height="${graphHeight - 36}" rx="24" fill="url(#kgField)" stroke="#d8dde6"></rect>
        <line x1="${graphWidth / 2}" y1="42" x2="${graphWidth / 2}" y2="${graphHeight - 42}" stroke="#d8dde6" stroke-width="1.4" stroke-dasharray="6 8"></line>
        <circle cx="${graphWidth / 2}" cy="238" r="92" fill="none" stroke="#d8dde6" stroke-width="1.4"></circle>
        <text x="82" y="64" font-size="13" font-weight="800" fill="#20825b">HOME</text>
        <text x="${graphWidth - 82}" y="64" font-size="13" font-weight="800" fill="#20825b" text-anchor="end">AWAY</text>
        <text x="120" y="382" font-size="13" font-weight="800" fill="#687282" text-anchor="middle">Players</text>
        <text x="330" y="382" font-size="13" font-weight="800" fill="#687282" text-anchor="middle">Profiles</text>
        <text x="${graphWidth / 2}" y="382" font-size="13" font-weight="800" fill="#687282" text-anchor="middle">Facts</text>
        <text x="850" y="382" font-size="13" font-weight="800" fill="#687282" text-anchor="middle">Profiles</text>
        <text x="1060" y="382" font-size="13" font-weight="800" fill="#687282" text-anchor="middle">Players</text>`;
      const shownPlayers = nodes.filter((node) => node.type === 'player').length;
      const shownPlayerProfiles = nodes.filter((node) => node.type === 'player_match_profile').length;
      const totalPlayers = network.entity_type_counts?.player ?? shownPlayers;
      const totalPlayerProfiles = network.entity_type_counts?.player_match_profile ?? shownPlayerProfiles;
      const legendItems = [
        ['Match', '#2f6fed'],
        ['Team', '#20825b'],
        ['Player', '#007a99'],
        ['Fact', '#6f8500'],
      ].map(([name, color]) => `<span class="legend-item"><i class="legend-dot" style="background:${color}"></i>${name}</span>`).join('');
      $('graphViz').innerHTML = `<div class="graph-meta"><span>Visual KG · players ${shownPlayers}/${totalPlayers} · profiles ${shownPlayerProfiles}/${totalPlayerProfiles} · ${links.length} links</span><span class="graph-legend">${legendItems}</span></div><svg class="kg-football" style="height:${graphHeight}px" viewBox="0 0 ${graphWidth} ${graphHeight}" role="img" aria-label="Football knowledge graph">${background}${edgeSvg}${nodeSvg}</svg><div class="kg-detail" id="kgDetail"></div>`;
      const defaultNode = nodes.find((node) => node.type === 'player') || nodes.find((node) => node.type === 'player_match_profile') || matchNode || nodes[0];
      bindGraphInspector(nodes, links, defaultNode?.id);
    }

    function renderFootballGraph(network) {
      const rawNodes = network.nodes || [];
      const rawLinks = network.links || [];
      const domainTypes = new Set([
        'match', 'team', 'team_match_profile', 'venue', 'group', 'stage', 'formation', 'match_result',
        'player', 'player_match_profile', 'player_stat_line', 'availability_event', 'availability_status',
        'club', 'position', 'body_part'
      ]);
      const nodes = rawNodes.filter((node) => domainTypes.has(node.type)).map((node) => ({...node}));
      if (!nodes.length) {
        renderEvidenceGraph(network);
        return;
      }
      const nodeById = new Map(nodes.map((node) => [node.id, node]));
      const links = rawLinks.filter((link) => nodeById.has(link.source) && nodeById.has(link.target));
      const matchNode = nodes.find((node) => node.type === 'match');
      const teams = nodes.filter((node) => node.type === 'team').sort((a, b) => {
        const sideRank = {home: 0, away: 1};
        return (sideRank[a.attributes?.side] ?? 9) - (sideRank[b.attributes?.side] ?? 9) || String(a.label).localeCompare(String(b.label));
      });
      const homeTeam = teams.find((node) => node.attributes?.side === 'home') || teams[0];
      const awayTeam = teams.find((node) => node.attributes?.side === 'away') || teams.find((node) => node.id !== homeTeam?.id);
      const teamForNode = (node) => {
        if (node.attributes?.team) return String(node.attributes.team);
        if (node.type === 'team') return node.label;
        const directTeamLink = rawLinks.find((link) =>
          (link.source === node.id && String(link.target).startsWith('team:')) ||
          (link.target === node.id && String(link.source).startsWith('team:'))
        );
        if (directTeamLink) {
          const teamId = String(directTeamLink.source).startsWith('team:') ? directTeamLink.source : directTeamLink.target;
          return rawNodes.find((candidate) => candidate.id === teamId)?.label || '';
        }
        return '';
      };
      const homeTeamName = homeTeam?.label || '';
      const awayTeamName = awayTeam?.label || '';
      const sideForNode = (node) => {
        const team = teamForNode(node);
        if (team && team === homeTeamName) return 'home';
        if (team && team === awayTeamName) return 'away';
        if (node.attributes?.side === 'home' || node.attributes?.side === 'away') return node.attributes.side;
        return 'neutral';
      };
      const layoutGroups = {
        homePlayers: nodes.filter((node) => node.type === 'player' && sideForNode(node) === 'home'),
        awayPlayers: nodes.filter((node) => node.type === 'player' && sideForNode(node) === 'away'),
        homeProfiles: nodes.filter((node) => node.type === 'player_match_profile' && sideForNode(node) === 'home'),
        awayProfiles: nodes.filter((node) => node.type === 'player_match_profile' && sideForNode(node) === 'away'),
        homeFacts: nodes.filter((node) => ['player_stat_line', 'availability_event', 'availability_status', 'club', 'position', 'body_part'].includes(node.type) && sideForNode(node) === 'home'),
        awayFacts: nodes.filter((node) => ['player_stat_line', 'availability_event', 'availability_status', 'club', 'position', 'body_part'].includes(node.type) && sideForNode(node) === 'away'),
        neutralFacts: nodes.filter((node) => ['venue', 'group', 'stage', 'formation', 'match_result'].includes(node.type)),
      };
      const maxRows = Math.max(
        6,
        layoutGroups.homePlayers.length,
        layoutGroups.awayPlayers.length,
        layoutGroups.homeProfiles.length,
        layoutGroups.awayProfiles.length,
        Math.ceil(layoutGroups.homeFacts.length / 2),
        Math.ceil(layoutGroups.awayFacts.length / 2)
      );
      const graphHeight = Math.max(700, 330 + maxRows * 62);
      const spreadY = (items, start, end) => {
        if (!items.length) return;
        const span = Math.max(1, end - start);
        const step = items.length === 1 ? 0 : span / (items.length - 1);
        items.forEach((node, index) => {
          node.y = items.length === 1 ? start + span / 2 : start + step * index;
        });
      };
      if (matchNode) Object.assign(matchNode, {x: 500, y: 72, w: 230, h: 56, role: 'match'});
      if (homeTeam) Object.assign(homeTeam, {x: 245, y: 170, w: 178, h: 50, role: 'team'});
      if (awayTeam) Object.assign(awayTeam, {x: 755, y: 170, w: 178, h: 50, role: 'team'});
      nodes.filter((node) => node.type === 'team_match_profile').forEach((node) => {
        const side = sideForNode(node);
        Object.assign(node, {x: side === 'away' ? 755 : 245, y: 242, w: 178, h: 42, role: 'profile'});
      });
      spreadY(layoutGroups.homePlayers, 335, graphHeight - 80);
      spreadY(layoutGroups.awayPlayers, 335, graphHeight - 80);
      spreadY(layoutGroups.homeProfiles, 335, graphHeight - 80);
      spreadY(layoutGroups.awayProfiles, 335, graphHeight - 80);
      layoutGroups.homePlayers.forEach((node) => Object.assign(node, {x: 115, w: 200, h: 48, role: 'player'}));
      layoutGroups.awayPlayers.forEach((node) => Object.assign(node, {x: 885, w: 200, h: 48, role: 'player'}));
      layoutGroups.homeProfiles.forEach((node) => Object.assign(node, {x: 315, w: 200, h: 42, role: 'profile'}));
      layoutGroups.awayProfiles.forEach((node) => Object.assign(node, {x: 685, w: 200, h: 42, role: 'profile'}));
      const layoutFacts = (items, x) => {
        items.forEach((node, index) => {
          Object.assign(node, {
            x,
            y: 332 + index * 56,
            w: 146,
            h: 38,
            role: 'fact',
          });
        });
      };
      layoutFacts(layoutGroups.homeFacts, 425);
      layoutFacts(layoutGroups.awayFacts, 575);
      layoutGroups.neutralFacts.forEach((node, index) => {
        Object.assign(node, {x: 500 + (index - (layoutGroups.neutralFacts.length - 1) / 2) * 108, y: 170, w: 124, h: 36, role: 'context'});
      });
      nodes.forEach((node, index) => {
        if (node.x !== undefined && node.y !== undefined) return;
        Object.assign(node, {x: 500, y: 300 + index * 44, w: 145, h: 34, role: 'other'});
      });
      const colorForNode = (node) => {
        if (node.type === 'match') return ['#e9efff', '#2f6fed'];
        if (node.type === 'team' || node.type === 'team_match_profile') return ['#e6f7ed', '#20825b'];
        if (node.type === 'player' || node.type === 'player_match_profile') return ['#e9f7ff', '#007a99'];
        if (['player_stat_line', 'availability_event', 'availability_status', 'club', 'position', 'body_part'].includes(node.type)) return ['#f2f7df', '#6f8500'];
        return ['#eef1f6', '#687282'];
      };
      const typeLabel = (type) => String(type || '').replaceAll('_', ' ');
      const truncate = (text, max) => {
        const value = String(text || '');
        return value.length > max ? value.slice(0, max - 3) + '...' : value;
      };
      const pathFor = (source, target) => {
        const dx = Math.abs(target.x - source.x);
        const curve = Math.max(40, Math.min(170, dx * 0.45));
        const c1 = source.x < target.x ? source.x + curve : source.x - curve;
        const c2 = source.x < target.x ? target.x - curve : target.x + curve;
        return `M${source.x},${source.y} C${c1},${source.y} ${c2},${target.y} ${target.x},${target.y}`;
      };
      const edgeSvg = links.map((link) => {
        const source = nodeById.get(link.source);
        const target = nodeById.get(link.target);
        if (!source || !target) return '';
        const strong = ['member_of', 'has_match_profile', 'has_player_match_profile', 'about_player', 'about_team'].includes(link.type);
        return `<g><path d="${pathFor(source, target)}" fill="none" stroke="${strong ? '#8091a8' : '#c8d0dc'}" stroke-width="${strong ? 1.8 : 1.1}" opacity="${strong ? 0.78 : 0.48}"></path><title>${escapeHtml(link.type || 'related_to')}</title></g>`;
      }).join('');
      const nodeSvg = nodes.map((node) => {
        const [fill, stroke] = colorForNode(node);
        const w = node.w || 150;
        const h = node.h || 38;
        const primary = truncate(node.label || node.id, node.type === 'player' ? 28 : 24);
        const secondary = truncate(typeLabel(node.type), 24);
        return `<g class="kg-node" data-node-id="${escapeHtml(node.id)}" tabindex="0" transform="translate(${node.x},${node.y})">
          <rect x="${-w / 2}" y="${-h / 2}" width="${w}" height="${h}" rx="8" fill="${fill}" stroke="${stroke}" stroke-width="2"></rect>
          <text x="0" y="${node.type === 'player' ? -3 : -4}" text-anchor="middle" font-size="${node.type === 'player' ? 14 : 13}" font-weight="750" fill="#1b1f24">${escapeHtml(primary)}</text>
          <text x="0" y="${node.type === 'player' ? 14 : 13}" text-anchor="middle" font-size="10" fill="#687282">${escapeHtml(secondary)}</text>
          <title>${escapeHtml(node.type || 'unknown')} · ${escapeHtml(node.label || node.id)}\n${escapeHtml(node.id)}</title>
        </g>`;
      }).join('');
      const laneLabels = [
        ['Home players', 115, 306],
        ['Home profiles', 315, 306],
        ['Facts', 500, 306],
        ['Away profiles', 685, 306],
        ['Away players', 885, 306],
      ].map(([label, x, y]) => `<text x="${x}" y="${y}" text-anchor="middle" font-size="13" fill="#687282" font-weight="700">${escapeHtml(label)}</text>`).join('');
      const legendItems = [
        ['Match', '#2f6fed'],
        ['Team', '#20825b'],
        ['Player', '#007a99'],
        ['Fact', '#6f8500'],
      ].map(([name, color]) => `<span class="legend-item"><i class="legend-dot" style="background:${color}"></i>${name}</span>`).join('');
      const shownPlayers = nodes.filter((node) => node.type === 'player').length;
      const shownPlayerProfiles = nodes.filter((node) => node.type === 'player_match_profile').length;
      const totalPlayers = network.entity_type_counts?.player ?? shownPlayers;
      const totalPlayerProfiles = network.entity_type_counts?.player_match_profile ?? shownPlayerProfiles;
      $('graphViz').innerHTML = `<div class="graph-meta"><span>Football graph · players ${shownPlayers}/${totalPlayers} · player profiles ${shownPlayerProfiles}/${totalPlayerProfiles} · ${links.length} visible links</span><span class="graph-legend">${legendItems}</span></div><svg class="kg-football" style="height:${graphHeight}px" viewBox="0 0 1000 ${graphHeight}" role="img" aria-label="Football knowledge graph">${edgeSvg}${laneLabels}${nodeSvg}</svg><div class="kg-detail" id="kgDetail"></div>`;
      const defaultNode = nodes.find((node) => node.type === 'player_match_profile') || nodes.find((node) => node.type === 'player') || matchNode || nodes[0];
      bindGraphInspector(nodes, links, defaultNode?.id);
    }

    function renderEvidenceGraph(network) {
      const rawNodes = network.nodes || [];
      const rawLinks = network.links || [];
      const nodes = rawNodes.map((node) => ({...node}));
      const links = rawLinks.filter((link) =>
        nodes.some((node) => node.id === link.source) && nodes.some((node) => node.id === link.target)
      );
      const nodeById = new Map(nodes.map((node) => [node.id, node]));
      const columns = [
        {name: 'Sources', x: 80, types: ['source', 'scout', 'source_domain', 'source_kind', 'source_quality', 'source_recency']},
        {name: 'Findings', x: 250, types: ['finding']},
        {name: 'Claims', x: 420, types: ['evidence_claim', 'claim_type', 'claim_impact', 'claim_quality']},
        {name: 'Match / Teams', x: 590, types: ['match', 'team', 'team_match_profile', 'country', 'venue', 'group', 'stage']},
        {name: 'Players', x: 760, types: ['player', 'player_match_profile']},
        {name: 'Facts', x: 930, types: ['player_stat_line', 'availability_event', 'availability_status', 'club', 'position', 'metric', 'scouting_topic', 'team_scouting_topic', 'unknown']},
      ];
      const fallbackColumn = columns.length - 1;
      const columnFor = (type) => {
        const index = columns.findIndex((column) => column.types.includes(type));
        return index >= 0 ? index : fallbackColumn;
      };
      const grouped = columns.map(() => []);
      for (const node of nodes) {
        grouped[columnFor(node.type || 'unknown')].push(node);
      }
      grouped.forEach((group) => group.sort((a, b) =>
        Number(b.degree || 0) - Number(a.degree || 0) || String(a.label).localeCompare(String(b.label))
      ));
      grouped.forEach((group, columnIndex) => {
        const height = 420;
        const top = 68;
        const step = group.length > 1 ? height / (group.length - 1) : 0;
        group.forEach((node, index) => {
          node.x = columns[columnIndex].x;
          node.y = group.length === 1 ? top + height / 2 : top + index * step;
        });
      });
      const colorForType = (type) => {
        if (['match', 'team', 'team_match_profile', 'country', 'venue', 'group', 'stage'].includes(type)) return ['#e6f7ed', '#20825b'];
        if (['player', 'player_match_profile'].includes(type)) return ['#e9f7ff', '#007a99'];
        if (['player_stat_line', 'availability_event', 'availability_status', 'club', 'position'].includes(type)) return ['#f2f7df', '#6f8500'];
        if (['source', 'scout', 'source_domain', 'source_kind', 'source_quality', 'source_recency'].includes(type)) return ['#eef1f6', '#687282'];
        if (type === 'finding') return ['#dbe8ff', '#2f6fed'];
        if (['evidence_claim', 'claim_type', 'claim_impact', 'claim_quality'].includes(type)) return ['#fff5db', '#a75f00'];
        return ['#f0eaff', '#7357c8'];
      };
      const truncate = (text, max) => {
        const value = String(text || '');
        return value.length > max ? value.slice(0, max - 3) + '...' : value;
      };
      const edgeSvg = links.map((link) => {
        const source = nodeById.get(link.source);
        const target = nodeById.get(link.target);
        if (!source || !target) return '';
        return `<g><line x1="${source.x}" y1="${source.y}" x2="${target.x}" y2="${target.y}" stroke="#bcc6d5" stroke-width="1.4" opacity="0.62"></line><title>${escapeHtml(link.type || 'related_to')}</title></g>`;
      }).join('');
      const nodeSvg = nodes.map((node) => {
        const [fill, stroke] = colorForType(node.type || 'unknown');
        const radius = Math.max(7, Math.min(17, 7 + Number(node.degree || 0) * 0.75));
        const label = truncate(node.label || node.id, node.type === 'evidence_claim' ? 18 : 22);
        const labelY = node.y + radius + 13;
        return `<g class="kg-node" data-node-id="${escapeHtml(node.id)}" tabindex="0"><circle cx="${node.x}" cy="${node.y}" r="${radius}" fill="${fill}" stroke="${stroke}" stroke-width="2"></circle><text x="${node.x}" y="${labelY}" text-anchor="middle" font-size="10" fill="#1b1f24">${escapeHtml(label)}</text><title>${escapeHtml(node.type || 'unknown')} · ${escapeHtml(node.label || node.id)}\n${escapeHtml(node.id)}</title></g>`;
      }).join('');
      const columnLabels = columns.map((column) =>
        `<text x="${column.x}" y="28" text-anchor="middle" font-size="12" fill="#687282" font-weight="700">${escapeHtml(column.name)}</text>`
      ).join('');
      const legendItems = [
        ['Match / Team', '#20825b'],
        ['Player', '#007a99'],
        ['Player Fact', '#6f8500'],
        ['Finding', '#2f6fed'],
        ['Claim', '#a75f00'],
        ['Source', '#687282'],
        ['Topic', '#7357c8'],
      ].map(([name, color]) => `<span class="legend-item"><i class="legend-dot" style="background:${color}"></i>${name}</span>`).join('');
      const shownPlayers = nodes.filter((node) => node.type === 'player').length;
      const shownPlayerProfiles = nodes.filter((node) => node.type === 'player_match_profile').length;
      const totalPlayers = network.entity_type_counts?.player ?? shownPlayers;
      const totalPlayerProfiles = network.entity_type_counts?.player_match_profile ?? shownPlayerProfiles;
      $('graphViz').innerHTML = `<div class="graph-meta"><span>Showing ${nodes.length}/${network.total_nodes || nodes.length} nodes · ${links.length}/${network.total_links || links.length} relationships · players ${shownPlayers}/${totalPlayers} · player profiles ${shownPlayerProfiles}/${totalPlayerProfiles}</span><span class="graph-legend">${legendItems}</span></div><svg class="kg-network" viewBox="0 0 1000 520" role="img" aria-label="Sampled knowledge graph network">${columnLabels}${edgeSvg}${nodeSvg}</svg><div class="kg-detail" id="kgDetail"></div>`;
      const defaultNode = nodes.find((node) => node.type === 'evidence_claim') || nodes.find((node) => node.type === 'match') || nodes[0];
      bindGraphInspector(nodes, links, defaultNode?.id);
    }

    function bindGraphInspector(nodes, links, selectedId) {
      const nodeById = new Map(nodes.map((node) => [node.id, node]));
      const selectNode = (nodeId) => {
        const node = nodeById.get(nodeId);
        if (!node) return;
        document.querySelectorAll('#graphViz .kg-node').forEach((el) => {
          el.classList.toggle('is-selected', el.dataset.nodeId === nodeId);
        });
        $('kgDetail').innerHTML = renderNodeDetail(node, links, nodeById);
      };
      document.querySelectorAll('#graphViz .kg-node').forEach((el) => {
        el.addEventListener('click', () => selectNode(el.dataset.nodeId));
        el.addEventListener('keydown', (event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            selectNode(el.dataset.nodeId);
          }
        });
      });
      if (selectedId) selectNode(selectedId);
    }

    function renderNodeDetail(node, links, nodeById) {
      const attrs = node.attributes || {};
      const claim = attrs.claim || '';
      const metrics = attrs.metrics && typeof attrs.metrics === 'object' && !Array.isArray(attrs.metrics) ? attrs.metrics : null;
      const evidenceClaims = Array.isArray(attrs.evidence_claims) ? attrs.evidence_claims : [];
      const hiddenKeys = new Set([
        'claim', 'metrics', 'evidence_claims',
        'home_probability', 'home_delta', 'market_home_probability',
        'delta_cost', 'internal_metrics'
      ]);
      const keyRows = Object.entries(attrs)
        .filter(([key, value]) => !hiddenKeys.has(key) && value !== '' && value !== null && value !== undefined)
        .slice(0, 18)
        .map(([key, value]) => `<div class="kv-row"><b>${escapeHtml(key)}</b><span>${formatValue(value)}</span></div>`)
        .join('');
      const metricRows = metrics ? Object.entries(metrics)
        .filter(([key]) => isScoutingMetric(key))
        .slice(0, 18)
        .map(([key, value]) => `<div class="kv-row"><b>${escapeHtml(key)}</b><span>${formatValue(value)}</span></div>`)
        .join('') : '';
      const rawMetricRows = metrics ? Object.entries(metrics)
        .filter(([key]) => !isScoutingMetric(key))
        .slice(0, 36)
        .map(([key, value]) => `<div class="kv-row"><b>${escapeHtml(key)}</b><span>${formatValue(value)}</span></div>`)
        .join('') : '';
      const rawMetricCount = metrics ? Object.keys(metrics).filter((key) => !isScoutingMetric(key)).length : 0;
      const storedClaims = evidenceClaims.map((item) => `<div class="stored-item"><b>${escapeHtml(item.claim_type || 'claim')}${item.team ? ' · ' + escapeHtml(item.team) : ''}</b><div>${escapeHtml(item.claim || '')}</div>${item.source_url ? `<a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(item.source_title || item.source_url)}</a>` : ''}</div>`).join('');
      const related = links
        .filter((link) => link.source === node.id || link.target === node.id)
        .slice(0, 32)
        .map((link) => {
          const outgoing = link.source === node.id;
          const neighbor = nodeById.get(outgoing ? link.target : link.source);
          const arrow = outgoing ? '→' : '←';
          return `<div class="kv-row"><b>${escapeHtml(link.type || 'related_to')} ${arrow}</b><span>${escapeHtml(neighbor?.label || (outgoing ? link.target : link.source))}<br><span style="color:#687282;">${escapeHtml(neighbor?.type || '')}</span></span></div>`;
        }).join('');
      const sourceLink = attrs.source_url ? `<div class="stored-item"><b>Source</b><a href="${escapeHtml(attrs.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(attrs.source_title || attrs.source_url)}</a></div>` : '';
      return `<h3>${escapeHtml(node.label || node.id)} <span class="pill">${escapeHtml(node.type || 'unknown')}</span></h3>
        <div class="node-id">${escapeHtml(node.id)}</div>
        ${claim ? `<div class="claim-text">${escapeHtml(claim)}</div>` : ''}
        <div class="kg-detail-grid">
          <div>
            <strong>Stored fields</strong>
            ${keyRows || '<div class="empty">No stored attributes on this node.</div>'}
            ${metricRows ? `<div style="margin-top:12px;"><strong>Scouting fields</strong>${metricRows}</div>` : ''}
            ${rawMetricRows ? `<details class="raw-fields"><summary>Raw provider/model fields (${rawMetricCount})</summary>${rawMetricRows}</details>` : ''}
            ${storedClaims ? `<div style="margin-top:12px;"><strong>Evidence claims kept in finding</strong><div class="stored-list">${storedClaims}</div></div>` : ''}
            ${sourceLink ? `<div style="margin-top:12px;" class="stored-list">${sourceLink}</div>` : ''}
          </div>
          <div>
            <strong>Relationships kept</strong>
            <div class="kg-relationships">${related || '<div class="empty">No sampled relationships for this node.</div>'}</div>
          </div>
        </div>`;
    }

    function isScoutingMetric(key) {
      const useful = new Set([
        'team', 'player', 'side', 'opponent', 'club', 'position',
        'availability_status', 'injury_body_part',
        'formation', 'lineup_signal', 'tactical_signal', 'roster_signal',
        'historical_result_signal', 'historical_record_signal',
        'goals', 'assists', 'goal_contributions', 'appearances', 'minutes', 'starts',
        'clean_sheets', 'blocked_shots', 'chances_created', 'key_passes_per_game',
        'shots_per_game', 'average_rating', 'pass_completion_pct', 'xg', 'xa',
        'international_caps', 'international_goals',
        'score_home', 'score_away', 'game_state',
        'bookmaker', 'odds_type', 'price_labels', 'prices', 'pct'
      ]);
      return useful.has(String(key || ''));
    }

    function formatValue(value) {
      if (Array.isArray(value)) {
        return value.map((item) => `<div>${formatValue(item)}</div>`).join('');
      }
      if (value && typeof value === 'object') {
        return Object.entries(value).map(([key, val]) => `<div><b>${escapeHtml(key)}:</b> ${formatValue(val)}</div>`).join('');
      }
      return escapeHtml(value ?? '');
    }

    function renderLiveGraph(live) {
      if (!live.sources.length) {
        $('graphViz').innerHTML = '<div class="empty">Launch a run to watch sources grow into findings and evidence claims.</div>';
        return;
      }
      const nodes = [
        ['sources', live.sources.length, 62, 52, live.error_sources ? '#fff1f1' : '#dbe8ff', live.error_sources ? '#d64040' : '#2f6fed'],
        ['complete', live.complete_sources, 185, 52, '#e6f7ed', '#279a55'],
        ['findings', live.finding_count, 318, 52, '#dbe8ff', '#2f6fed'],
        ['claims', live.evidence_claim_count, 455, 52, '#dbe8ff', '#2f6fed'],
        ['running', live.running_sources, 185, 142, '#fff7db', '#c68b00'],
        ['errors', live.error_sources, 318, 142, live.error_sources ? '#fff1f1' : '#edf1f6', live.error_sources ? '#d64040' : '#aab6c7'],
        ['entities', live.entities ?? live.estimated_entities ?? 0, 455, 142, '#edf1f6', '#687282'],
      ];
      const edges = [
        [62, 52, 185, 52], [185, 52, 318, 52], [318, 52, 455, 52],
        [62, 52, 185, 142], [185, 142, 318, 142], [455, 52, 455, 142],
      ].map(([x1, y1, x2, y2]) => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#aab6c7" stroke-width="2"></line>`).join('');
      const max = Math.max(1, ...nodes.map((n) => Number(n[1] || 0)));
      const circles = nodes.map(([name, count, x, y, fill, stroke]) => {
        const r = 18 + Math.round((Number(count || 0) / max) * 24);
        return `<g><circle cx="${x}" cy="${y}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="2"></circle><text x="${x}" y="${y - 4}" text-anchor="middle" font-size="11" font-weight="700">${escapeHtml(name)}</text><text x="${x}" y="${y + 12}" text-anchor="middle" font-size="11">${count}</text></g>`;
      }).join('');
      $('graphViz').innerHTML = `<svg class="kg-mini" viewBox="0 0 520 205" role="img" aria-label="Live KG growth preview">${edges}${circles}</svg>`;
    }

    function renderResults(results) {
      const target = $('results');
      if (!target) return;
      target.innerHTML = results.map((result) => {
        const audit = result.audit || {};
        const structure = result.structure_audit || {};
        const preview = result.graph_preview || {};
        const missing = audit.missing_required_claim_types || audit.readiness?.missing_required_claim_types || [];
        const findings = result.finding_preview || [];
        const entityTypes = Object.entries(preview.entity_type_counts || {}).slice(0, 16);
        const relationshipTypes = Object.entries(preview.relationship_type_counts || {}).slice(0, 16);
        return `<div class="result-card">
          <h2>${escapeHtml(result.match)} · ${escapeHtml(result.status)}</h2>
          <div class="tabs">
            <span class="pill">${result.findings} findings</span>
            <span class="pill">${result.claims} claims</span>
            <span class="pill">${escapeHtml(result.out_dir || '')}</span>
          </div>
          ${renderMarketContext(result.market_context || [])}
          ${missing.length ? `<div class="empty">Missing scouting topics: ${escapeHtml(missing.join(', '))}</div>` : ''}
          ${(structure.warnings || []).map((warning) => `<div class="notice ${warning.includes('No structural') ? '' : 'warning'}">${escapeHtml(warning)}</div>`).join('')}
          <div class="type-grid">
            <div>
              <strong style="font-size:12px;">Top entity types</strong>
              ${entityTypes.map(([name, count]) => `<div class="type-row"><span>${escapeHtml(name)}</span><b>${count}</b></div>`).join('')}
            </div>
            <div>
              <strong style="font-size:12px;">Top relationship types</strong>
              ${relationshipTypes.map(([name, count]) => `<div class="type-row"><span>${escapeHtml(name)}</span><b>${count}</b></div>`).join('')}
            </div>
          </div>
          ${(structure.noisy_claim_samples || []).length ? `<div class="notice warning"><strong>Noisy claim samples</strong>${structure.noisy_claim_samples.map((claim) => `<div style="margin-top:6px;">${escapeHtml(claim.claim_type || '')} · ${escapeHtml(claim.team || '')}<br>${escapeHtml(claim.claim || '')}</div>`).join('')}</div>` : ''}
          ${findings.map(renderFinding).join('')}
        </div>`;
      }).join('');
    }

    function renderMarketContext(rows) {
      if (!rows.length) return '';
      const byQuestion = new Map();
      rows.forEach((row) => {
        const key = row.question || 'Polymarket market';
        if (!byQuestion.has(key)) byQuestion.set(key, []);
        byQuestion.get(key).push(row);
      });
      const cards = Array.from(byQuestion.entries()).slice(0, 8).map(([question, outcomes]) => {
        const outcomeRows = outcomes.map((row) => {
          const price = row.clob_midpoint ?? row.gamma_price ?? '';
          const spread = row.spread ?? '';
          const bidAsk = row.best_bid !== undefined && row.best_ask !== undefined ? `${formatNumber(row.best_bid)} / ${formatNumber(row.best_ask)}` : '-';
          const depth = row.bid_depth !== undefined && row.ask_depth !== undefined ? `${formatNumber(row.bid_depth)} / ${formatNumber(row.ask_depth)}` : '-';
          return `<div class="market-row">
            <div><b>${escapeHtml(row.outcome || 'outcome')}</b><span> mid ${formatNumber(price)} · spread ${formatNumber(spread)}</span></div>
            <div style="text-align:right;"><span>bid/ask ${escapeHtml(bidAsk)}<br>depth ${escapeHtml(depth)}</span></div>
          </div>`;
        }).join('');
        const first = outcomes[0] || {};
        const meta = `volume ${formatNumber(first.volume)} · liquidity ${formatNumber(first.liquidity)}${first.accepting_orders === false ? ' · not accepting orders' : ''}`;
        return `<div class="market-card">
          <strong>${escapeHtml(question)}</strong>
          <div class="pill">${escapeHtml(meta)}</div>
          ${outcomeRows}
          ${first.source_url ? `<div style="margin-top:8px;"><a href="${escapeHtml(first.source_url)}" target="_blank" rel="noreferrer">Polymarket market</a></div>` : ''}
        </div>`;
      }).join('');
      return `<div><strong style="font-size:12px;">Polymarket market context</strong><div class="market-grid">${cards}</div></div>`;
    }

    function formatNumber(value) {
      if (value === undefined || value === null || value === '') return '-';
      const num = Number(value);
      if (!Number.isFinite(num)) return escapeHtml(value);
      if (Math.abs(num) >= 1000000) return (num / 1000000).toFixed(2).replace(/\\.00$/, '') + 'M';
      if (Math.abs(num) >= 1000) return (num / 1000).toFixed(1).replace(/\\.0$/, '') + 'k';
      if (Math.abs(num) < 1 && num !== 0) return num.toFixed(4).replace(/0+$/, '').replace(/\\.$/, '');
      return String(Math.round(num * 1000) / 1000);
    }

    function formatSeconds(value) {
      const num = Number(value);
      if (!Number.isFinite(num)) return '-';
      if (num >= 60) {
        const minutes = Math.floor(num / 60);
        const seconds = Math.round(num % 60);
        return `${minutes}m ${seconds}s`;
      }
      return `${Math.round(num * 10) / 10}s`;
    }

    function renderFinding(finding) {
      return `<div class="claim">
        <div><span class="type">${escapeHtml(finding.scout_name || '')}</span> · ${escapeHtml(finding.finding_name || '')} · ${finding.claim_count || 0} claims</div>
        ${(finding.sample_claims || []).map((claim) =>
          `<div style="margin-top:6px;"><span class="type">${escapeHtml(claim.claim_type || '')}</span> ${escapeHtml(claim.team || '')}${claim.player ? ' · ' + escapeHtml(claim.player) : ''}<br>${escapeHtml(claim.claim || '')}</div>`
        ).join('')}
      </div>`;
    }

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }

    document.querySelectorAll('#viewTabs .view-tab').forEach((button) => {
      button.addEventListener('click', () => {
        state.activeView = button.dataset.view || 'domain';
        renderActiveView();
      });
    });
    $('runButton').addEventListener('click', launchRun);
    loadConfig().catch((err) => {
      $('headerStatus').textContent = 'failed to load config';
      $('logBox').textContent = String(err);
    });
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
