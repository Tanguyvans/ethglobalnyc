#!/usr/bin/env python3
"""Collect pre-match snapshots for upcoming World Cup matches from the KG.

The batch intentionally selects only matches whose prediction cutoff has not
passed yet. That makes the saved raw data usable later as genuine pre-match
benchmark evidence.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:  # Script mode: python3 colony/collect_upcoming_prematch_batch.py
    from scouting_matrix import _iso_utc, _match_kickoff_utc, _safe_slug
except ImportError:  # Package mode
    from colony.scouting_matrix import _iso_utc, _match_kickoff_utc, _safe_slug


DEFAULT_KG = Path("colony/data/world_cup_kg.json")
DEFAULT_OUT_ROOT = Path("colony/runs/prematch_scrape")
POLYMARKET_GAMMA_SEARCH = "https://gamma-api.polymarket.com/public-search"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kg", type=Path, default=DEFAULT_KG)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--cutoff-hours", type=float, default=6.0)
    parser.add_argument("--window-days", type=int, default=21)
    parser.add_argument("--min-cutoff-margin-minutes", type=float, default=5.0)
    parser.add_argument("--max-records", type=int, default=30)
    parser.add_argument("--x-max-queries", type=int, default=11)
    parser.add_argument("--polymarket-timeout", type=int, default=30)
    parser.add_argument("--polymarket-raw-clob-limit", type=int, default=12)
    parser.add_argument("--env-file", type=Path, default=Path("colony/.env"))
    parser.add_argument("--skip-google-news", action="store_true")
    parser.add_argument("--skip-gdelt", action="store_true")
    parser.add_argument("--skip-scrapecreators-x", action="store_true")
    parser.add_argument("--skip-polymarket", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    now = datetime.now(timezone.utc)
    run_root = args.out_dir or DEFAULT_OUT_ROOT / f"upcoming_{now.strftime('%Y%m%d_%H%M%S')}"
    run_root.mkdir(parents=True, exist_ok=True)
    matches = select_matches(
        kg_path=args.kg,
        now=now,
        cutoff_hours=args.cutoff_hours,
        limit=args.limit,
        min_cutoff_margin=timedelta(minutes=args.min_cutoff_margin_minutes),
    )
    manifest: dict[str, Any] = {
        "schema_version": "upcoming-prematch-batch-v1",
        "created_at_utc": _iso_utc(now),
        "kg": str(args.kg),
        "cutoff_hours": args.cutoff_hours,
        "window_days": args.window_days,
        "limit": args.limit,
        "selected_matches": [match_summary(match) for match in matches],
        "rows": [],
    }
    write_manifest(run_root, manifest)
    if args.dry_run:
        print(f"Upcoming prematch batch dry-run: {run_root}")
        for match in matches:
            print(f"{match['name']}: kickoff={match['kickoff_utc']} cutoff={match['prediction_cutoff_utc']}")
        return

    for match in matches:
        row = collect_match(match=match, args=args, run_root=run_root)
        manifest["rows"].append(row)
        write_manifest(run_root, manifest)
        print(
            f"{match['name']}: scrape={row['prematch_status']} "
            f"polymarket={row['polymarket_status']} usable={row.get('usable_documents', 'n/a')}"
        )
    print(f"Upcoming prematch batch: {run_root}")


def select_matches(
    *,
    kg_path: Path,
    now: datetime,
    cutoff_hours: float,
    limit: int,
    min_cutoff_margin: timedelta,
) -> list[dict[str, Any]]:
    payload = json.loads(kg_path.read_text(encoding="utf-8"))
    matches: list[dict[str, Any]] = []
    for entity in payload.get("entities") or []:
        if entity.get("entity_type") != "match":
            continue
        attrs = dict(entity.get("attributes") or {})
        kickoff = _match_kickoff_utc(
            match_date=str(attrs.get("date") or ""),
            match_time=str(attrs.get("time") or ""),
        )
        if kickoff is None:
            continue
        cutoff = kickoff - timedelta(hours=cutoff_hours)
        if cutoff <= now + min_cutoff_margin:
            continue
        home = str(attrs.get("team1") or "").strip()
        away = str(attrs.get("team2") or "").strip()
        if not home or not away:
            continue
        matches.append(
            {
                "entity_id": str(entity.get("entity_id") or ""),
                "name": str(entity.get("name") or f"{home} vs {away}"),
                "home_team": home,
                "away_team": away,
                "kickoff": kickoff,
                "kickoff_utc": _iso_utc(kickoff),
                "prediction_cutoff": cutoff,
                "prediction_cutoff_utc": _iso_utc(cutoff),
                "ground": str(attrs.get("ground") or ""),
                "group": str(attrs.get("group") or ""),
                "round": str(attrs.get("round") or ""),
            }
        )
    matches.sort(key=lambda item: (item["prediction_cutoff"], item["name"]))
    return matches if limit <= 0 else matches[:limit]


def collect_match(*, match: dict[str, Any], args: argparse.Namespace, run_root: Path) -> dict[str, Any]:
    match_dir = run_root / f"{match['kickoff_utc'][:10]}_{_safe_slug(match['name'])}"
    match_dir.mkdir(parents=True, exist_ok=True)
    raw_polymarket_dir = match_dir / "raw" / "polymarket"
    raw_polymarket_dir.mkdir(parents=True, exist_ok=True)
    row: dict[str, Any] = {
        **match_summary(match),
        "out_dir": str(match_dir),
        "prematch_status": "skipped",
        "polymarket_status": "skipped",
    }

    scrape_cmd = [
        sys.executable,
        "colony/scrape_prematch_match.py",
        "--home",
        match["home_team"],
        "--away",
        match["away_team"],
        "--kickoff-utc",
        match["kickoff_utc"],
        "--cutoff-hours",
        str(args.cutoff_hours),
        "--out-dir",
        str(match_dir),
        "--env-file",
        str(args.env_file),
        "--max-records",
        str(args.max_records),
        "--x-max-queries",
        str(args.x_max_queries),
        "--start-utc",
        _iso_utc(match["kickoff"] - timedelta(days=args.window_days)),
    ]
    if not args.skip_google_news:
        scrape_cmd.append("--google-news")
    if not args.skip_gdelt:
        scrape_cmd.append("--gdelt")
    if not args.skip_scrapecreators_x:
        scrape_cmd.append("--scrapecreators-x")
    scrape_result = run_command(scrape_cmd)
    row["prematch_status"] = "ok" if scrape_result.returncode == 0 else "failed"
    row["prematch_command"] = redact_command(scrape_cmd)
    row["prematch_returncode"] = scrape_result.returncode
    row["prematch_stdout_tail"] = tail(scrape_result.stdout)
    row["prematch_stderr_tail"] = tail(scrape_result.stderr)
    documents_path = first_existing_path(
        [
            match_dir / "normalized" / "prematch_documents.json",
            match_dir / "prematch_documents.json",
        ]
    )
    if documents_path.exists():
        documents_payload = json.loads(documents_path.read_text(encoding="utf-8"))
        summary = documents_payload.get("summary") or {}
        row["usable_documents"] = int(summary.get("usable") or 0)
        row["rejected_documents"] = int(summary.get("rejected") or 0)
        row["usable_by_source_type"] = summary.get("usable_by_source_type") or {}
        row["usable_by_signal_type"] = summary.get("usable_by_signal_type") or {}

    if not args.skip_polymarket:
        row.update(
            collect_polymarket_raw(
                match=match,
                output_dir=raw_polymarket_dir,
                clob_limit=args.polymarket_raw_clob_limit,
            )
        )
        polymarket_dir = match_dir / "polymarket_kg"
        poly_cmd = [
            sys.executable,
            "colony/scouting_matrix.py",
            "--kg",
            str(args.kg),
            "--match",
            match["name"],
            "--module",
            "polymarket_market_context",
            "--limit",
            "1",
            "--mode",
            "fast",
            "--timeout",
            str(args.polymarket_timeout),
            "--cutoff-hours",
            str(args.cutoff_hours),
            "--out-dir",
            str(polymarket_dir),
            "--quiet",
        ]
        poly_result = run_command(poly_cmd)
        row["polymarket_status"] = "ok" if poly_result.returncode == 0 else "failed"
        row["polymarket_command"] = redact_command(poly_cmd)
        row["polymarket_returncode"] = poly_result.returncode
        row["polymarket_stdout_tail"] = tail(poly_result.stdout)
        row["polymarket_stderr_tail"] = tail(poly_result.stderr)
        row.update(polymarket_summary(polymarket_dir))
    return row


def collect_polymarket_raw(*, match: dict[str, Any], output_dir: Path, clob_limit: int = 12) -> dict[str, Any]:
    query = f"{match['home_team']} {match['away_team']}"
    url = POLYMARKET_GAMMA_SEARCH + "?" + urllib.parse.urlencode(
        {"q": query, "limit_per_type": 10, "search_profiles": "false", "keep_closed_markets": 0}
    )
    raw_path = output_dir / "gamma_public_search.json"
    started_at = datetime.now(timezone.utc)
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            raw = response.read()
    except OSError as exc:
        payload = {
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "query": query,
            "url": url,
            "collected_at_utc": _iso_utc(started_at),
        }
        raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {"polymarket_raw_status": "failed", "polymarket_raw_file": str(raw_path), "polymarket_raw_error": payload["error"]}
    raw_path.write_bytes(raw)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return {"polymarket_raw_status": "failed", "polymarket_raw_file": str(raw_path), "polymarket_raw_error": "non_json_response"}
    clob_rows = collect_polymarket_clob_raw(payload=payload, output_dir=output_dir, limit=clob_limit)
    return {
        "polymarket_raw_status": "ok",
        "polymarket_raw_file": str(raw_path),
        "polymarket_raw_sha256": sha256_bytes(raw),
        "polymarket_raw_collected_at_utc": _iso_utc(started_at),
        "polymarket_raw_event_count": len(payload.get("events") or []),
        "polymarket_raw_market_count": len(polymarket_market_rows(payload)),
        "polymarket_raw_clob_files": len(clob_rows),
    }


def collect_polymarket_clob_raw(*, payload: dict[str, Any], output_dir: Path, limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    token_ids = unique_token_ids(payload)[:limit]
    rows: list[dict[str, Any]] = []
    for token_id in token_ids:
        token_dir = output_dir / "clob" / safe_token_slug(token_id)
        token_dir.mkdir(parents=True, exist_ok=True)
        for endpoint in ("midpoint", "book"):
            url = f"https://clob.polymarket.com/{endpoint}?" + urllib.parse.urlencode({"token_id": token_id})
            output = token_dir / f"{endpoint}.json"
            collected_at = datetime.now(timezone.utc)
            try:
                with urllib.request.urlopen(url, timeout=10) as response:
                    raw = response.read()
            except OSError as exc:
                raw = json.dumps(
                    {
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                        "url": url,
                        "token_id": token_id,
                        "collected_at_utc": _iso_utc(collected_at),
                    },
                    sort_keys=True,
                ).encode("utf-8")
            output.write_bytes(raw)
            rows.append(
                {
                    "token_id": token_id,
                    "endpoint": endpoint,
                    "file": str(output),
                    "sha256": sha256_bytes(raw),
                    "bytes": len(raw),
                    "collected_at_utc": _iso_utc(collected_at),
                }
            )
    (output_dir / "clob_manifest.json").write_text(
        json.dumps({"files": rows}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return rows


def polymarket_market_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for market in payload.get("markets") or []:
        if isinstance(market, dict):
            rows.append(market)
    for event in payload.get("events") or []:
        if not isinstance(event, dict):
            continue
        for market in event.get("markets") or []:
            if isinstance(market, dict):
                rows.append(market)
    return rows


def unique_token_ids(payload: dict[str, Any]) -> list[str]:
    token_ids: list[str] = []
    seen: set[str] = set()
    for market in polymarket_market_rows(payload):
        for token_id in json_list(market.get("clobTokenIds") or market.get("tokenIds") or []):
            text = str(token_id).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            token_ids.append(text)
    return token_ids


def json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def safe_token_slug(value: str) -> str:
    text = "".join(ch if ch.isalnum() else "_" for ch in value)[:48]
    return text or "token"


def polymarket_summary(polymarket_dir: Path) -> dict[str, Any]:
    matrix_path = polymarket_dir / "matrix_results.json"
    if not matrix_path.exists():
        return {}
    rows = json.loads(matrix_path.read_text(encoding="utf-8"))
    if not rows:
        return {"polymarket_claims": 0, "polymarket_findings": 0}
    first = rows[0]
    return {
        "polymarket_claims": int(first.get("claims") or 0),
        "polymarket_findings": int(first.get("findings") or 0),
        "polymarket_kg_status": first.get("status"),
        "polymarket_out_dir": first.get("out_dir"),
    }


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def first_existing_path(candidates: list[Path]) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def sha256_bytes(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def match_summary(match: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_id": match["entity_id"],
        "name": match["name"],
        "home_team": match["home_team"],
        "away_team": match["away_team"],
        "kickoff_utc": match["kickoff_utc"],
        "prediction_cutoff_utc": match["prediction_cutoff_utc"],
        "ground": match.get("ground") or "",
        "group": match.get("group") or "",
        "round": match.get("round") or "",
    }


def write_manifest(run_root: Path, manifest: dict[str, Any]) -> None:
    (run_root / "batch_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def redact_command(command: list[str]) -> list[str]:
    redacted: list[str] = []
    skip_next = False
    for part in command:
        if skip_next:
            redacted.append("<redacted>")
            skip_next = False
            continue
        redacted.append(part)
        if part in {"--env-file"}:
            skip_next = True
    return redacted


def tail(value: str, *, max_chars: int = 1200) -> str:
    text = value.strip()
    return text[-max_chars:] if len(text) > max_chars else text


if __name__ == "__main__":
    main()
