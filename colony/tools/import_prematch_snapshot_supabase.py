#!/usr/bin/env python3
"""Import a local prematch scrape snapshot into Supabase benchmark tables."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


COLONY_DIR = Path(__file__).resolve().parents[1]
if str(COLONY_DIR) not in sys.path:
    sys.path.insert(0, str(COLONY_DIR))

from colony_harness.env import load_env_file  # noqa: E402
from colony_harness.supabase_client import (  # noqa: E402
    SupabaseRequestError,
    SupabaseSettings,
    request_json,
)


DEFAULT_SOURCE_DIR = COLONY_DIR / "runs" / "prematch_scrape" / "france_iraq_pre_kickoff_20260622"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import prematch scrape data into Supabase.")
    parser.add_argument("--env", default=str(COLONY_DIR / ".env"), help="Path to colony/.env.")
    parser.add_argument(
        "--source-dir",
        default=str(DEFAULT_SOURCE_DIR),
        help="Prematch scrape directory containing normalized/ and kg/ outputs.",
    )
    parser.add_argument("--snapshot-id", default=None, help="Stable snapshot id. Defaults to match/cutoff slug.")
    parser.add_argument("--competition", default="worldcup_2026")
    parser.add_argument("--match-id", default="", help="Optional external match id.")
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Do not delete existing child rows for this snapshot before upserting.",
    )
    parser.add_argument("--json", action="store_true", help="Print the written snapshot row after import.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print a summary without writing.")
    parser.add_argument("--batch-size", type=int, default=100, help="Rows per Supabase REST insert batch.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_dir = Path(args.source_dir).expanduser().resolve()
    snapshot, raw_sources, documents, claims = build_import_payload(
        source_dir=source_dir,
        competition=args.competition,
        match_id=args.match_id,
        snapshot_id=args.snapshot_id,
    )

    if args.dry_run:
        print(json.dumps(_dry_run_summary(snapshot, raw_sources, documents, claims), ensure_ascii=False, indent=2, sort_keys=True))
        return

    if args.batch_size < 1:
        raise SystemExit("--batch-size must be positive")

    try:
        settings = _load_writer_settings(args.env)
        written_snapshot = _write_snapshot(
            settings,
            snapshot=snapshot,
            raw_sources=raw_sources,
            documents=documents,
            claims=claims,
            replace_children=not args.keep_existing,
            batch_size=args.batch_size,
        )
    except SupabaseRequestError as exc:
        raise SystemExit(str(exc)) from exc

    print("Prematch snapshot imported.")
    print(f"snapshot_id={snapshot['snapshot_id']}")
    print(f"match={snapshot['home_team']} vs {snapshot['away_team']}")
    print(f"documents={len(documents)} claims={len(claims)} raw_sources={len(raw_sources)}")
    if args.json:
        print(json.dumps(written_snapshot, ensure_ascii=False, indent=2, sort_keys=True))


def build_import_payload(
    *,
    source_dir: Path,
    competition: str,
    match_id: str,
    snapshot_id: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    documents_path = source_dir / "normalized" / "prematch_documents.json"
    kg_source_path = source_dir / "kg" / "prematch_kg_source.json"
    if not documents_path.exists():
        raise SystemExit(f"Missing normalized documents: {documents_path}")
    if not kg_source_path.exists():
        raise SystemExit(f"Missing KG source: {kg_source_path}")

    documents_payload = _read_json(documents_path)
    kg_payload = _read_json(kg_source_path)
    match = _object_or_empty(documents_payload.get("match"))
    home_team = _required_text(match, "home_team")
    away_team = _required_text(match, "away_team")
    kickoff_utc = _required_text(match, "kickoff_utc")
    prediction_cutoff_utc = _required_text(match, "prediction_cutoff_utc")
    match_slug = f"{_slug(home_team)}_vs_{_slug(away_team)}"
    resolved_snapshot_id = snapshot_id or f"{competition}_{match_slug}_{_timestamp_slug(prediction_cutoff_utc)}"

    raw_sources_payload = documents_payload.get("raw_sources") if isinstance(documents_payload.get("raw_sources"), list) else []
    documents_payload_rows = documents_payload.get("documents") if isinstance(documents_payload.get("documents"), list) else []
    findings = kg_payload.get("findings") if isinstance(kg_payload.get("findings"), list) else []
    claim_payloads = [
        claim
        for finding in findings
        for claim in (finding.get("evidence_claims") if isinstance(finding.get("evidence_claims"), list) else [])
        if isinstance(claim, dict)
    ]

    snapshot = {
        "snapshot_id": resolved_snapshot_id,
        "match_id": match_id or "",
        "match_slug": match_slug,
        "competition": competition,
        "home_team": home_team,
        "away_team": away_team,
        "kickoff_utc": kickoff_utc,
        "prediction_cutoff_utc": prediction_cutoff_utc,
        "created_at_utc": _timestamp_or_none(documents_payload.get("created_at_utc")),
        "status": "ready",
        "document_count": len(documents_payload_rows),
        "claim_count": len(claim_payloads),
        "raw_source_count": len(raw_sources_payload),
        "source_dir": str(source_dir),
        "documents_path": str(documents_path),
        "kg_source_path": str(kg_source_path),
        "raw_storage_prefix": "",
        "summary": _object_or_empty(documents_payload.get("summary")),
        "metadata": {
            "schema_version": documents_payload.get("schema_version"),
            "policy": _object_or_empty(documents_payload.get("policy")),
            "rejected_document_count": len(documents_payload.get("rejected_documents") or []),
            "source_dir_name": source_dir.name,
            "kg_finding_ids": [
                str(finding.get("finding_id"))
                for finding in findings
                if isinstance(finding, dict) and finding.get("finding_id")
            ],
            "imported_with": "colony/tools/import_prematch_snapshot_supabase.py",
        },
    }

    raw_sources = [_raw_source_row(resolved_snapshot_id, source) for source in raw_sources_payload if isinstance(source, dict)]
    documents = [_document_row(resolved_snapshot_id, document) for document in documents_payload_rows if isinstance(document, dict)]
    claims = [
        _claim_row(resolved_snapshot_id, index, claim)
        for index, claim in enumerate(claim_payloads)
    ]
    return snapshot, raw_sources, documents, claims


def _write_snapshot(
    settings: SupabaseSettings,
    *,
    snapshot: dict[str, Any],
    raw_sources: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    replace_children: bool,
    batch_size: int,
) -> list[dict[str, Any]]:
    written_snapshot = request_json(
        settings,
        "prematch_snapshots?on_conflict=snapshot_id",
        method="POST",
        body=snapshot,
        prefer="resolution=merge-duplicates,return=representation",
    )
    if replace_children:
        _delete_snapshot_children(settings, snapshot["snapshot_id"])

    _upsert_rows(settings, "prematch_raw_sources", "snapshot_id,source_id", raw_sources, batch_size)
    _upsert_rows(settings, "prematch_documents", "snapshot_id,document_id", documents, batch_size)
    _upsert_rows(settings, "prematch_kg_claims", "snapshot_id,claim_id", claims, batch_size)
    return written_snapshot


def _delete_snapshot_children(settings: SupabaseSettings, snapshot_id: str) -> None:
    encoded = urllib.parse.quote(snapshot_id, safe="")
    for table in ("prematch_kg_claims", "prematch_documents", "prematch_raw_sources"):
        request_json(
            settings,
            f"{table}?snapshot_id=eq.{encoded}",
            method="DELETE",
            prefer="return=minimal",
        )


def _upsert_rows(
    settings: SupabaseSettings,
    table: str,
    on_conflict: str,
    rows: list[dict[str, Any]],
    batch_size: int,
) -> None:
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        if not batch:
            continue
        request_json(
            settings,
            f"{table}?on_conflict={on_conflict}",
            method="POST",
            body=batch,
            prefer="resolution=merge-duplicates,return=minimal",
        )


def _raw_source_row(snapshot_id: str, source: dict[str, Any]) -> dict[str, Any]:
    source_id = str(source.get("source_id") or _short_hash(source))
    return {
        "snapshot_id": snapshot_id,
        "source_id": source_id,
        "source_type": str(source.get("source_type") or ""),
        "locator": str(source.get("locator") or ""),
        "sha256": str(source.get("sha256") or ""),
        "bytes": _int_or_none(source.get("bytes")),
        "collected_at_utc": _timestamp_or_none(source.get("collected_at_utc")),
        "raw_source": source,
    }


def _document_row(snapshot_id: str, document: dict[str, Any]) -> dict[str, Any]:
    document_id = str(document.get("document_id") or _short_hash(document))
    return {
        "snapshot_id": snapshot_id,
        "document_id": document_id,
        "source_type": str(document.get("source_type") or ""),
        "adapter": str(document.get("adapter") or ""),
        "signal_type": str(document.get("signal_type") or ""),
        "title": str(document.get("title") or ""),
        "snippet": str(document.get("snippet") or ""),
        "url": str(document.get("url") or ""),
        "source_name": str(document.get("source_name") or ""),
        "source_snapshot_id": str(document.get("source_snapshot_id") or ""),
        "published_at_utc": _timestamp_or_none(
            document.get("published_at_utc") or document.get("published") or document.get("source_published")
        ),
        "available_at_utc": _timestamp_or_none(document.get("available_at_utc")),
        "timestamp_precision": str(document.get("timestamp_precision") or ""),
        "content_hash": str(document.get("content_hash") or ""),
        "sentiment": _object_or_empty(document.get("sentiment")),
        "raw_document": document,
    }


def _claim_row(snapshot_id: str, index: int, claim: dict[str, Any]) -> dict[str, Any]:
    metrics = _object_or_empty(claim.get("metrics"))
    basis = "|".join(
        [
            str(metrics.get("document_id") or ""),
            str(claim.get("claim_type") or ""),
            str(claim.get("claim") or ""),
            str(claim.get("source_url") or ""),
        ]
    )
    claim_id = f"{index:05d}:{hashlib.sha1(basis.encode('utf-8')).hexdigest()[:12]}"
    return {
        "snapshot_id": snapshot_id,
        "claim_id": claim_id,
        "team": str(claim.get("team") or ""),
        "player": str(claim.get("player") or ""),
        "subject": str(claim.get("subject") or ""),
        "claim_type": str(claim.get("claim_type") or ""),
        "claim": str(claim.get("claim") or ""),
        "impact": str(claim.get("impact") or ""),
        "confidence": _float_or_none(claim.get("confidence")),
        "source_kind": str(claim.get("source_kind") or ""),
        "source_domain": str(claim.get("source_domain") or ""),
        "source_title": str(claim.get("source_title") or ""),
        "source_url": str(claim.get("source_url") or ""),
        "source_published": _timestamp_or_none(claim.get("source_published")),
        "source_published_date": _date_or_none(claim.get("source_published_date")),
        "available_at_utc": _timestamp_or_none(claim.get("available_at_utc")),
        "source_quality": str(claim.get("source_quality") or ""),
        "extraction_method": str(claim.get("extraction_method") or ""),
        "metrics": metrics,
        "raw_claim": claim,
    }


def _load_writer_settings(env_path: str | Path) -> SupabaseSettings:
    load_env_file(env_path)
    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_SECRET_KEY")
        or os.environ.get("SUPABASE_SERVICE_KEY")
    )
    if not url:
        raise SupabaseRequestError("Missing SUPABASE_URL in colony/.env")
    if not key:
        raise SupabaseRequestError(
            "Missing SUPABASE_SERVICE_ROLE_KEY. Add it to colony/.env or prefix the import command with it."
        )
    return SupabaseSettings(url=url.rstrip("/"), key=key)


def _dry_run_summary(
    snapshot: dict[str, Any],
    raw_sources: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    claims: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "snapshot": snapshot,
        "raw_source_count": len(raw_sources),
        "document_count": len(documents),
        "claim_count": len(claims),
        "sample_raw_sources": raw_sources[:2],
        "sample_documents": [
            {
                "document_id": row["document_id"],
                "source_type": row["source_type"],
                "signal_type": row["signal_type"],
                "available_at_utc": row["available_at_utc"],
                "title": row["title"],
                "url": row["url"],
            }
            for row in documents[:3]
        ],
        "sample_claims": [
            {
                "claim_id": row["claim_id"],
                "claim_type": row["claim_type"],
                "available_at_utc": row["available_at_utc"],
                "source_kind": row["source_kind"],
                "claim": row["claim"],
            }
            for row in claims[:3]
        ],
    }


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected JSON object in {path}")
    return payload


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"Missing required match field: {key}")
    return value.strip()


def _object_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _timestamp_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _date_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return text
    if re.match(r"^\d{4}-\d{2}-\d{2}T", text):
        return text[:10]
    return None


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "unknown"


def _timestamp_slug(value: str) -> str:
    text = value.strip().replace("+00:00", "Z")
    parsed = None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    if parsed:
        parsed = parsed.astimezone(UTC)
        return parsed.strftime("%Y%m%dT%H%M%SZ")
    cleaned = re.sub(r"[^0-9A-Za-z]+", "", text)
    return cleaned or "unknown_cutoff"


def _short_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()[:16]


if __name__ == "__main__":
    main()
