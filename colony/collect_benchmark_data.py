#!/usr/bin/env python3
"""Collect raw benchmark source snapshots with timestamps and hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import shutil
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_ROOT = Path("colony/runs/benchmark_collection")
DEFAULT_OPENFOOTBALL = Path("colony/data/openfootball/worldcup_2026.json")
GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
FOOTBALL_DATA_URL = "https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"
ESPN_WORLDCUP_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
ESPN_WORLDCUP_SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary"


@dataclass(frozen=True)
class CollectionSource:
    source_id: str
    source_type: str
    locator: str
    output_name: str
    kind: str
    description: str = ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=None, help="Directory for raw snapshots and manifest.")
    parser.add_argument(
        "--worldcup-openfootball",
        type=Path,
        default=None,
        help="Snapshot a local OpenFootball World Cup JSON file.",
    )
    parser.add_argument(
        "--football-data",
        action="append",
        default=[],
        metavar="SEASON/LEAGUE",
        help="Fetch a football-data.co.uk CSV, for example 2425/E0. Can be repeated.",
    )
    parser.add_argument(
        "--espn-worldcup-dates",
        default="",
        metavar="YYYYMMDD-YYYYMMDD",
        help="Fetch ESPN FIFA World Cup scoreboard plus per-event summaries for a date or date range.",
    )
    parser.add_argument(
        "--gdelt-query",
        action="append",
        default=[],
        help="Fetch a GDELT DOC 2.0 ArtList query. Can be repeated.",
    )
    parser.add_argument("--gdelt-start", default="", help="GDELT startdatetime, e.g. 20250601000000.")
    parser.add_argument("--gdelt-end", default="", help="GDELT enddatetime, e.g. 20250602000000.")
    parser.add_argument("--gdelt-max-records", type=int, default=25, help="Max GDELT article records per query.")
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        metavar="SOURCE_ID=URL",
        help="Fetch an arbitrary URL into a raw snapshot. Can be repeated.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    output_dir = args.out_dir or DEFAULT_OUTPUT_ROOT / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    sources = build_sources(args)
    if not sources:
        sources = [
            CollectionSource(
                source_id="openfootball_worldcup_2026",
                source_type="fixture",
                locator=str(DEFAULT_OPENFOOTBALL),
                output_name="openfootball_worldcup_2026.json",
                kind="local_file",
                description="Bundled OpenFootball World Cup fixture/result JSON.",
            )
        ]
    manifest = collect_sources(sources=sources, output_dir=output_dir)
    print(f"Collected {manifest['summary']['ok']} source(s), {manifest['summary']['failed']} failed: {output_dir}")


def build_sources(args: argparse.Namespace) -> list[CollectionSource]:
    sources: list[CollectionSource] = []
    if args.worldcup_openfootball:
        sources.append(
            CollectionSource(
                source_id="openfootball_worldcup_2026",
                source_type="fixture",
                locator=str(args.worldcup_openfootball),
                output_name="openfootball_worldcup_2026.json",
                kind="local_file",
                description="Local OpenFootball World Cup fixture/result JSON.",
            )
        )
    for value in args.football_data:
        season, league = _parse_football_data_code(value)
        url = FOOTBALL_DATA_URL.format(season=season, league=league)
        sources.append(
            CollectionSource(
                source_id=f"football_data_{season}_{league}",
                source_type="historical_results_odds",
                locator=url,
                output_name=f"football_data_{season}_{league}.csv",
                kind="http",
                description="Football-Data historical football results and betting odds CSV.",
            )
        )
    if args.espn_worldcup_dates:
        dates = str(args.espn_worldcup_dates).strip()
        sources.append(
            CollectionSource(
                source_id=f"espn_worldcup_scoreboard_{_safe_slug(dates)}",
                source_type="fixture_results",
                locator=dates,
                output_name=f"espn_worldcup_scoreboard_{_safe_slug(dates)}.json",
                kind="espn_worldcup_scoreboard",
                description="ESPN FIFA World Cup scoreboard with per-event summaries.",
            )
        )
    for index, query in enumerate(args.gdelt_query, start=1):
        url = _gdelt_doc_url(
            query=query,
            start=args.gdelt_start,
            end=args.gdelt_end,
            max_records=args.gdelt_max_records,
        )
        slug = _safe_slug(query)[:60] or f"query_{index}"
        sources.append(
            CollectionSource(
                source_id=f"gdelt_doc_{index}_{slug}",
                source_type="news",
                locator=url,
                output_name=f"gdelt_doc_{index}_{slug}.json",
                kind="http",
                description="GDELT DOC 2.0 article-list JSON snapshot.",
            )
        )
    for value in args.url:
        source_id, url = _parse_url_source(value)
        extension = _extension_for_url(url)
        sources.append(
            CollectionSource(
                source_id=source_id,
                source_type="generic",
                locator=url,
                output_name=f"{_safe_slug(source_id)}{extension}",
                kind="http",
                description="Generic raw URL snapshot.",
            )
        )
    return sources


def collect_sources(*, sources: list[CollectionSource], output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    collected_at = _utc_now()
    manifest: dict[str, Any] = {
        "schema_version": "benchmark-collection-v1",
        "created_at_utc": collected_at,
        "collection_policy": {
            "purpose": "raw source snapshots for later benchmark evidence construction",
            "timestamp_rule": "collected_at_utc is when this collector persisted the raw payload",
            "hash_rule": "sha256 is computed over the exact saved bytes",
        },
        "sources": [],
    }
    for source in sources:
        manifest["sources"].append(_collect_one(source=source, output_dir=output_dir, collected_at=collected_at))
    ok_count = sum(1 for row in manifest["sources"] if row.get("status") == "ok")
    manifest["summary"] = {
        "total": len(manifest["sources"]),
        "ok": ok_count,
        "failed": len(manifest["sources"]) - ok_count,
    }
    (output_dir / "collection_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _collect_one(*, source: CollectionSource, output_dir: Path, collected_at: str) -> dict[str, Any]:
    output_path = output_dir / source.output_name
    record: dict[str, Any] = {
        "source_id": source.source_id,
        "source_type": source.source_type,
        "kind": source.kind,
        "locator": source.locator,
        "description": source.description,
        "collected_at_utc": collected_at,
        "file": output_path.name,
    }
    try:
        if source.kind == "local_file":
            input_path = Path(source.locator)
            if not input_path.exists():
                raise FileNotFoundError(str(input_path))
            shutil.copyfile(input_path, output_path)
            stat = input_path.stat()
            record["source_filesystem_mtime_utc"] = datetime.fromtimestamp(
                stat.st_mtime,
                tz=timezone.utc,
            ).isoformat(timespec="seconds")
        elif source.kind == "http":
            request = urllib.request.Request(
                source.locator,
                headers={"User-Agent": "ColonyBenchmarkCollector/0.1"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
                output_path.write_bytes(payload)
                record["http_status"] = getattr(response, "status", None)
                record["content_type"] = response.headers.get("content-type", "")
                record["last_modified"] = response.headers.get("last-modified", "")
                record["etag"] = response.headers.get("etag", "")
        elif source.kind == "espn_worldcup_scoreboard":
            payload, metadata = _fetch_espn_worldcup_snapshot(dates=source.locator, collected_at=collected_at)
            output_path.write_bytes(payload)
            record.update(metadata)
        else:
            raise ValueError(f"Unsupported source kind: {source.kind}")
        payload = output_path.read_bytes()
        record.update(
            {
                "status": "ok",
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    except Exception as exc:  # noqa: BLE001 - manifest should preserve collection failures.
        record.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    return record


def _fetch_espn_worldcup_snapshot(*, dates: str, collected_at: str) -> tuple[bytes, dict[str, Any]]:
    scoreboard_url = ESPN_WORLDCUP_SCOREBOARD_URL + "?" + urllib.parse.urlencode(
        {"dates": dates, "limit": "300"}
    )
    scoreboard = _fetch_json(scoreboard_url)
    summaries = []
    for event in scoreboard.get("events") or []:
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            continue
        summary_url = ESPN_WORLDCUP_SUMMARY_URL + "?" + urllib.parse.urlencode({"event": event_id})
        try:
            summaries.append(
                {
                    "event_id": event_id,
                    "status": "ok",
                    "url": summary_url,
                    "payload": _fetch_json(summary_url),
                }
            )
        except Exception as exc:  # noqa: BLE001 - preserve partial collection.
            summaries.append(
                {
                    "event_id": event_id,
                    "status": "failed",
                    "url": summary_url,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    snapshot = {
        "source": "espn",
        "league": "fifa.world",
        "dates": dates,
        "collected_at_utc": collected_at,
        "scoreboard_url": scoreboard_url,
        "summary_endpoint": ESPN_WORLDCUP_SUMMARY_URL,
        "scoreboard": scoreboard,
        "event_summaries": summaries,
    }
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    return payload, {
        "scoreboard_url": scoreboard_url,
        "event_count": len(scoreboard.get("events") or []),
        "summary_count": len(summaries),
        "summary_ok": sum(1 for item in summaries if item.get("status") == "ok"),
        "summary_failed": sum(1 for item in summaries if item.get("status") != "ok"),
        "content_type": "application/json",
    }


def _fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ColonyBenchmarkCollector/0.1", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read()
    return json.loads(payload.decode("utf-8"))


def _gdelt_doc_url(*, query: str, start: str, end: str, max_records: int) -> str:
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": str(max(1, max_records)),
    }
    if start:
        params["startdatetime"] = start
    if end:
        params["enddatetime"] = end
    return GDELT_DOC_URL + "?" + urllib.parse.urlencode(params)


def _parse_football_data_code(value: str) -> tuple[str, str]:
    if "/" not in value:
        raise SystemExit("--football-data values must look like SEASON/LEAGUE, for example 2425/E0")
    season, league = value.split("/", 1)
    season = season.strip()
    league = league.strip().upper()
    if not season or not league:
        raise SystemExit("--football-data values must look like SEASON/LEAGUE, for example 2425/E0")
    return season, league


def _parse_url_source(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise SystemExit("--url values must look like SOURCE_ID=URL")
    source_id, url = value.split("=", 1)
    source_id = source_id.strip()
    url = url.strip()
    if not source_id or not url:
        raise SystemExit("--url values must look like SOURCE_ID=URL")
    return source_id, url


def _extension_for_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path
    guess = Path(path).suffix
    if guess:
        return guess
    mime = mimetypes.guess_type(url)[0]
    if mime == "application/json":
        return ".json"
    if mime == "text/csv":
        return ".csv"
    return ".raw"


def _safe_slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


if __name__ == "__main__":
    main()
