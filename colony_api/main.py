"""FastAPI wrapper around the Colony CLI pipeline.

The first deployment goal is intentionally narrow: keep the existing harness as
the source of truth, run it as a managed subprocess, and expose run artifacts and
an SSE stream to the frontend or demo tooling.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_ROOT = REPO_ROOT / "colony" / "runs" / "api"
RUNS_ROOT = Path(os.environ.get("COLONY_API_RUNS_DIR", str(DEFAULT_RUNS_ROOT))).resolve()
RUN_DEMO = REPO_ROOT / "colony" / "run_demo.py"


class DemoRunRequest(BaseModel):
    agents: int = Field(default=200, ge=1, le=500)
    rooms: int = Field(default=12, ge=1, le=50)
    seed: int | None = Field(default=205, ge=0)
    voice_mode: Literal["template", "llm"] = "llm"
    debug: bool = False
    agent_wallets: bool = True
    wallet_provider: Literal["local", "dynamic"] | None = "dynamic"
    wallet_store: str | None = "colony/data/agent-wallets.dynamic.200.public.json"


class RunRecord(BaseModel):
    id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    returncode: int | None = None
    command: list[str]
    run_dir: str
    events_path: str
    compact_runs_dir: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_dir(run_id: str) -> Path:
    return RUNS_ROOT / run_id


def _metadata_path(run_id: str) -> Path:
    return _run_dir(run_id) / "metadata.json"


def _read_metadata(run_id: str) -> dict:
    path = _metadata_path(run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_metadata(run_id: str, payload: dict) -> None:
    path = _metadata_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _safe_artifact_path(run_id: str, relative_path: str) -> Path:
    base = _run_dir(run_id).resolve()
    target = (base / relative_path).resolve()
    if target != base and base not in target.parents:
        raise HTTPException(status_code=400, detail="Artifact path escapes run directory")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"Artifact not found: {relative_path}")
    return target


def _latest_compact_dir(run_id: str) -> Path | None:
    compact_root = _run_dir(run_id) / "compact"
    if not compact_root.exists():
        return None
    children = [path for path in compact_root.iterdir() if path.is_dir()]
    if not children:
        return None
    return sorted(children)[-1]


def _read_events(run_id: str) -> list[dict]:
    path = _safe_artifact_path(run_id, "events.jsonl")
    events: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _build_command(request: DemoRunRequest, run_dir: Path) -> list[str]:
    command = [
        sys.executable,
        str(RUN_DEMO),
        "--agents",
        str(request.agents),
        "--rooms",
        str(request.rooms),
        "--out",
        str(run_dir / "events.jsonl"),
        "--runs-dir",
        str(run_dir / "compact"),
        "--voice-mode",
        request.voice_mode,
    ]
    if request.seed is not None:
        command.extend(["--seed", str(request.seed)])
    if request.debug:
        command.append("--debug")
    if request.agent_wallets:
        command.append("--agent-wallets")
        if request.wallet_provider:
            command.extend(["--wallet-provider", request.wallet_provider])
        if request.wallet_store:
            command.extend(["--wallet-store", request.wallet_store])
    return command


def _execute_run(run_id: str, command: list[str]) -> None:
    metadata = _read_metadata(run_id)
    metadata["status"] = "running"
    metadata["started_at"] = _utc_now()
    _write_metadata(run_id, metadata)

    run_dir = _run_dir(run_id)
    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{REPO_ROOT / 'colony'}{os.pathsep}{env.get('PYTHONPATH', '')}"

    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        completed = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            env=env,
            stdout=stdout,
            stderr=stderr,
            check=False,
        )

    metadata = _read_metadata(run_id)
    metadata["completed_at"] = _utc_now()
    metadata["returncode"] = completed.returncode
    metadata["status"] = "succeeded" if completed.returncode == 0 else "failed"
    latest = _latest_compact_dir(run_id)
    if latest is not None:
        metadata["latest_compact_dir"] = str(latest)
    _write_metadata(run_id, metadata)


def _cors_origins() -> list[str]:
    raw = os.environ.get("COLONY_API_CORS_ORIGINS", "*")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app = FastAPI(title="Colony Pipeline API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "colony-api",
        "runs_root": str(RUNS_ROOT),
        "run_demo_exists": RUN_DEMO.exists(),
    }


@app.get("/config")
def get_config() -> dict:
    wallet_provider = os.environ.get("COLONY_API_DEFAULT_WALLET_PROVIDER") or os.environ.get(
        "COLONY_WALLET_PROVIDER",
        "dynamic",
    )
    return {
        "service": "colony-api",
        "endpoints": {
            "health": "/health",
            "config": "/config",
            "start_demo_run": "/runs/demo",
            "list_runs": "/runs",
            "run": "/runs/{run_id}",
            "events": "/runs/{run_id}/events",
            "stream": "/runs/{run_id}/stream",
            "agents": "/runs/{run_id}/agents",
            "rooms": "/runs/{run_id}/rooms",
        },
        "defaults": {
            "agents": _env_int("COLONY_API_DEFAULT_AGENTS", 200),
            "rooms": _env_int("COLONY_API_DEFAULT_ROOMS", 12),
            "seed": _env_int("COLONY_API_DEFAULT_SEED", 205),
            "voice_mode": os.environ.get("COLONY_API_DEFAULT_VOICE_MODE", "llm"),
            "agent_wallets": _env_bool("COLONY_API_DEFAULT_AGENT_WALLETS", True),
            "wallet_provider": wallet_provider,
            "wallet_store": os.environ.get(
                "COLONY_API_DEFAULT_WALLET_STORE",
                "colony/data/agent-wallets.dynamic.200.public.json",
            ),
        },
        "limits": {
            "agents": {"min": 1, "max": 500},
            "rooms": {"min": 1, "max": 50},
            "voice_modes": ["template", "llm"],
            "wallet_providers": ["local", "dynamic"],
        },
        "identity_fields": [
            "agent_id",
            "name",
            "ens_name",
            "wallet_address",
            "world_status",
            "world_access_tier",
            "genome_id",
            "lineage_id",
        ],
    }


@app.post("/runs/demo", response_model=RunRecord, status_code=202)
def start_demo_run(request: DemoRunRequest, background_tasks: BackgroundTasks) -> dict:
    if not RUN_DEMO.exists():
        raise HTTPException(status_code=500, detail="colony/run_demo.py is missing")

    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    run_dir = _run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=False)
    command = _build_command(request, run_dir)
    metadata = {
        "id": run_id,
        "status": "queued",
        "created_at": _utc_now(),
        "started_at": None,
        "completed_at": None,
        "returncode": None,
        "command": command,
        "run_dir": str(run_dir),
        "events_path": str(run_dir / "events.jsonl"),
        "compact_runs_dir": str(run_dir / "compact"),
    }
    _write_metadata(run_id, metadata)
    background_tasks.add_task(_execute_run, run_id, command)
    return metadata


@app.get("/runs")
def list_runs() -> dict:
    if not RUNS_ROOT.exists():
        return {"runs": []}
    runs = []
    for path in sorted(RUNS_ROOT.iterdir(), reverse=True):
        if not path.is_dir():
            continue
        metadata_path = path / "metadata.json"
        if metadata_path.exists():
            runs.append(json.loads(metadata_path.read_text(encoding="utf-8")))
    return {"runs": runs}


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    metadata = _read_metadata(run_id)
    latest = _latest_compact_dir(run_id)
    metadata["artifacts"] = {
        "events": f"/runs/{run_id}/events",
        "stream": f"/runs/{run_id}/stream",
        "stdout": f"/runs/{run_id}/artifacts/stdout.log",
        "stderr": f"/runs/{run_id}/artifacts/stderr.log",
    }
    if latest is not None:
        relative = latest.relative_to(_run_dir(run_id))
        metadata["artifacts"].update(
            {
                "summary": f"/runs/{run_id}/artifacts/{relative}/summary.md",
                "decision": f"/runs/{run_id}/artifacts/{relative}/decision.compact.json",
                "social_feed": f"/runs/{run_id}/artifacts/{relative}/social_feed.md",
            }
        )
    return metadata


@app.get("/runs/{run_id}/events", response_class=PlainTextResponse)
def get_events(run_id: str) -> PlainTextResponse:
    path = _safe_artifact_path(run_id, "events.jsonl")
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="application/x-ndjson")


@app.get("/runs/{run_id}/agents")
def get_run_agents(run_id: str) -> dict:
    metadata = _read_metadata(run_id)
    events = _read_events(run_id)
    agents = [event for event in events if event.get("event_type") == "agent_record"]
    forecasts_by_agent = {
        event.get("agent_id"): event
        for event in events
        if event.get("event_type") == "forecast" and event.get("agent_id")
    }
    for agent in agents:
        forecast = forecasts_by_agent.get(agent.get("agent_id"))
        if forecast:
            agent["latest_forecast"] = {
                "side": forecast.get("side"),
                "stake": forecast.get("stake"),
                "home_probability": forecast.get("home_probability"),
                "edge": forecast.get("edge"),
                "prediction": forecast.get("prediction"),
            }
    return {
        "run_id": run_id,
        "status": metadata["status"],
        "count": len(agents),
        "agents": agents,
    }


@app.get("/runs/{run_id}/rooms")
def get_run_rooms(run_id: str) -> dict:
    metadata = _read_metadata(run_id)
    events = _read_events(run_id)
    rooms = [event for event in events if event.get("event_type") == "debate_room"]
    return {
        "run_id": run_id,
        "status": metadata["status"],
        "count": len(rooms),
        "rooms": rooms,
    }


@app.get("/runs/{run_id}/stream")
async def stream_run(run_id: str) -> StreamingResponse:
    _read_metadata(run_id)

    async def event_source():
        offset = 0
        last_status_payload = ""
        while True:
            metadata = _read_metadata(run_id)
            status_payload = json.dumps(metadata, sort_keys=True)
            if status_payload != last_status_payload:
                last_status_payload = status_payload
                yield f"event: status\ndata: {status_payload}\n\n"

            events_path = _run_dir(run_id) / "events.jsonl"
            if events_path.exists():
                with events_path.open("r", encoding="utf-8") as handle:
                    handle.seek(offset)
                    for line in handle:
                        line = line.strip()
                        if line:
                            yield f"event: colony_event\ndata: {line}\n\n"
                    offset = handle.tell()

            if metadata["status"] in {"succeeded", "failed"}:
                yield f"event: done\ndata: {status_payload}\n\n"
                break

            yield "event: heartbeat\ndata: {}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(event_source(), media_type="text/event-stream")


@app.get("/runs/{run_id}/artifacts/{relative_path:path}")
def get_artifact(run_id: str, relative_path: str) -> FileResponse:
    path = _safe_artifact_path(run_id, relative_path)
    return FileResponse(path)
