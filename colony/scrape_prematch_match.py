#!/usr/bin/env python3
"""Scrape and normalize pre-match documents for one benchmark match.

The output is intentionally conservative: same-day Google News RSS timestamps
are treated as date-level, because the feed can label post-match result stories
with a morning timestamp. Those items are rejected unless they are from a source
with a trustworthy exact timestamp in a later adapter.
"""

from __future__ import annotations

import argparse
import email.utils
import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
USER_AGENT = "ColonyPrematchScraper/0.1"


@dataclass(frozen=True)
class MatchPilot:
    home_team: str
    away_team: str
    kickoff_utc: datetime
    cutoff_utc: datetime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True)
    parser.add_argument("--away", required=True)
    parser.add_argument("--kickoff-utc", required=True)
    parser.add_argument("--cutoff-hours", type=float, default=6.0)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--google-news", action="store_true")
    parser.add_argument("--gdelt", action="store_true")
    parser.add_argument("--scrapecreators-x", action="store_true", help="Use ScrapeCreators Google Search filtered to X/Twitter.")
    parser.add_argument("--env-file", type=Path, default=Path("colony/.env"))
    parser.add_argument("--max-records", type=int, default=25)
    parser.add_argument("--x-max-queries", type=int, default=10, help="Maximum ScrapeCreators X search queries to run. 0 means all.")
    parser.add_argument("--x-query", action="append", default=[], help="Additional custom X/Google query. Repeatable.")
    parser.add_argument("--start-utc", default="", help="Collection window start. Defaults to 14 days before kickoff.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    kickoff = parse_utc(args.kickoff_utc)
    pilot = MatchPilot(
        home_team=args.home,
        away_team=args.away,
        kickoff_utc=kickoff,
        cutoff_utc=kickoff - timedelta(hours=args.cutoff_hours),
    )
    start = parse_utc(args.start_utc) if args.start_utc else kickoff - timedelta(days=14)
    paths = prematch_output_paths(args.out_dir)
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    documents: list[dict[str, Any]] = []
    raw_sources: list[dict[str, Any]] = []
    if args.google_news:
        docs, raws = scrape_google_news(pilot=pilot, start_utc=start, output_dir=paths["raw_google_news"])
        documents.extend(docs)
        raw_sources.extend(raws)
    if args.gdelt:
        docs, raws = scrape_gdelt(pilot=pilot, start_utc=start, output_dir=paths["raw_gdelt"], max_records=args.max_records)
        documents.extend(docs)
        raw_sources.extend(raws)
    if args.scrapecreators_x:
        load_env_file(args.env_file)
        docs, raws = scrape_scrapecreators_x(
            pilot=pilot,
            start_utc=start,
            output_dir=paths["raw_scrapecreators_x"],
            max_queries=args.x_max_queries,
            custom_queries=args.x_query,
        )
        documents.extend(docs)
        raw_sources.extend(raws)

    documents, duplicate_count = dedupe_documents(documents)
    usable_documents = [item for item in documents if item.get("usable")]
    rejected_documents = [item for item in documents if not item.get("usable")]
    payload = {
        "schema_version": "prematch-scrape-v1",
        "created_at_utc": utc_now(),
        "match": {
            "home_team": pilot.home_team,
            "away_team": pilot.away_team,
            "kickoff_utc": iso_utc(pilot.kickoff_utc),
            "prediction_cutoff_utc": iso_utc(pilot.cutoff_utc),
        },
        "policy": {
            "same_day_google_news": "rejected unless separately verified; Google RSS timestamps can be date-level",
            "result_leak_rule": "reject titles/snippets that appear to reveal final score, highlights, or post-match report",
        },
        "summary": summarize_documents(documents, duplicate_count=duplicate_count),
        "raw_sources": raw_sources,
        "documents": sorted(usable_documents, key=lambda item: (item.get("available_at_utc") or "", item.get("title") or "")),
        "rejected_documents": sorted(
            rejected_documents,
            key=lambda item: (item.get("available_at_utc") or "", item.get("title") or ""),
        ),
    }
    output = paths["normalized"] / "prematch_documents.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    kg_output = paths["kg"] / "prematch_kg_source.json"
    kg_output.write_text(
        json.dumps(kg_source_payload(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    quality_output = paths["reports"] / "prematch_quality_report.md"
    quality_output.write_text(quality_report(payload), encoding="utf-8")
    manifest_output = args.out_dir / "collection_manifest.json"
    manifest_output.write_text(
        json.dumps(
            collection_manifest_payload(
                payload=payload,
                start_utc=start,
                output=args.out_dir,
                documents_path=output,
                kg_path=kg_output,
                quality_path=quality_output,
            ),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Prematch scrape written: {output}")
    print(f"Prematch KG source written: {kg_output}")
    print(f"Prematch quality report written: {quality_output}")
    print(f"Prematch collection manifest written: {manifest_output}")
    print(
        "Summary: "
        f"total={payload['summary']['total']} usable={payload['summary']['usable']} "
        f"rejected={payload['summary']['rejected']} duplicates={payload['summary']['duplicates_removed']} "
        f"sources={payload['summary']['source_count']}"
    )


def scrape_google_news(*, pilot: MatchPilot, start_utc: datetime, output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    docs: list[dict[str, Any]] = []
    raws: list[dict[str, Any]] = []
    for language, region, query in google_news_queries(pilot, start_utc=start_utc):
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {
                "q": query,
                "hl": language,
                "gl": region,
                "ceid": f"{region}:{language.split('-')[0]}",
            }
        )
        raw = fetch_bytes(url)
        raw_name = f"google_news_{safe_slug(language)}_{safe_slug(query)[:70]}.xml"
        raw_path = output_dir / raw_name
        raw_path.write_bytes(raw)
        raws.append(raw_record(source_id=raw_name, source_type="google_news_rss", url=url, payload=raw, raw_file=raw_path))
        docs.extend(parse_google_news_rss(raw, source_id=raw_name, source_url=url, pilot=pilot))
    return docs, raws


def google_news_queries(pilot: MatchPilot, *, start_utc: datetime | None = None) -> list[tuple[str, str, str]]:
    start = (start_utc or (pilot.kickoff_utc - timedelta(days=14))).date().isoformat()
    before = pilot.kickoff_utc.date().isoformat()
    home = pilot.home_team
    away = pilot.away_team
    return [
        ("en-US", "US", f'"{home}" "{away}" "World Cup" before:{before} after:{start}'),
        ("en-US", "US", f'"{home} vs {away}" preview OR "team news" before:{before} after:{start}'),
        ("es-419", "MX", f'"{home}" "{away}" Mundial before:{before} after:{start}'),
    ]


def parse_google_news_rss(raw: bytes, *, source_id: str, source_url: str, pilot: MatchPilot) -> list[dict[str, Any]]:
    root = ET.fromstring(raw)
    docs: list[dict[str, Any]] = []
    for item in root.findall("./channel/item"):
        title = clean_text(item.findtext("title", ""))
        link = clean_text(item.findtext("link", ""))
        published_raw = clean_text(item.findtext("pubDate", ""))
        source_node = item.find("source")
        publisher = clean_text(source_node.text if source_node is not None else "")
        published = parse_rfc2822(published_raw)
        docs.append(
            normalize_document(
                source_name=publisher or "Google News",
                source_type="news",
                adapter="google_news_rss",
                title=title,
                url=link,
                snippet="",
                published_at=published,
                published_raw=published_raw,
                source_snapshot_id=source_id,
                source_url=source_url,
                pilot=pilot,
                timestamp_precision="date_level" if is_google_date_level(published) else "unknown",
            )
        )
    return docs


def scrape_gdelt(
    *,
    pilot: MatchPilot,
    start_utc: datetime,
    output_dir: Path,
    max_records: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    docs: list[dict[str, Any]] = []
    raws: list[dict[str, Any]] = []
    queries = [
        f'"{pilot.home_team}" "{pilot.away_team}" "World Cup"',
        f'"{pilot.home_team} vs {pilot.away_team}"',
    ]
    for query in queries:
        url = GDELT_DOC_URL + "?" + urllib.parse.urlencode(
            {
                "query": query,
                "mode": "artlist",
                "format": "json",
                "maxrecords": str(max_records),
                "startdatetime": gdelt_datetime(start_utc),
                "enddatetime": gdelt_datetime(pilot.cutoff_utc),
            }
        )
        try:
            raw = fetch_bytes(url)
        except urllib.error.HTTPError as exc:
            raw = json.dumps({"error": f"HTTPError: {exc.code}", "url": url}).encode("utf-8")
            status = "failed"
        else:
            status = "ok"
        raw_name = f"gdelt_{safe_slug(query)[:70]}.json"
        raw_path = output_dir / raw_name
        raw_path.write_bytes(raw)
        raws.append({**raw_record(source_id=raw_name, source_type="gdelt_doc", url=url, payload=raw, raw_file=raw_path), "status": status})
        if status != "ok":
            continue
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            raws[-1]["status"] = "failed"
            raws[-1]["error"] = "non_json_response"
            continue
        for article in payload.get("articles") or []:
            seen = parse_gdelt_seen_date(str(article.get("seendate") or ""))
            docs.append(
                normalize_document(
                    source_name=str(article.get("sourceCountry") or article.get("domain") or "GDELT"),
                    source_type="news",
                    adapter="gdelt_doc",
                    title=clean_text(article.get("title") or ""),
                    url=clean_text(article.get("url") or ""),
                    snippet=clean_text(article.get("snippet") or ""),
                    published_at=seen,
                    published_raw=str(article.get("seendate") or ""),
                    source_snapshot_id=raw_name,
                    source_url=url,
                    pilot=pilot,
                    timestamp_precision="seen_datetime",
                )
            )
    return docs, raws


def scrape_scrapecreators_x(
    *,
    pilot: MatchPilot,
    start_utc: datetime,
    output_dir: Path,
    max_queries: int = 10,
    custom_queries: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    endpoint = os.environ.get("SCRAPECREATORS_X_SEARCH_URL", "").strip() or os.environ.get("COLONY_X_SEARCH_URL", "").strip()
    api_key = os.environ.get("SCRAPECREATORS_API_KEY", "").strip() or os.environ.get("COLONY_X_API_KEY", "").strip()
    if not endpoint or not api_key:
        raise RuntimeError("Missing SCRAPECREATORS_X_SEARCH_URL/SCRAPECREATORS_API_KEY")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "x-api-key": api_key,
        "User-Agent": USER_AGENT,
    }
    queries = list(custom_queries or []) + scrapecreators_x_queries(pilot=pilot, start_utc=start_utc)
    queries = unique_strings(queries)
    if max_queries > 0:
        queries = queries[:max_queries]

    docs: list[dict[str, Any]] = []
    raws: list[dict[str, Any]] = []
    for index, query in enumerate(queries, start=1):
        if "{query}" in endpoint:
            url = endpoint.replace("{query}", urllib.parse.quote(query, safe=""))
            request = urllib.request.Request(url, headers=headers)
        else:
            url = endpoint
            data = json.dumps({"query": query}).encode("utf-8")
            request = urllib.request.Request(
                endpoint,
                data=data,
                headers={**headers, "Content-Type": "application/json"},
                method="POST",
            )
        raw_name = (
            f"scrapecreators_x_{safe_slug(pilot.home_team)}_{safe_slug(pilot.away_team)}_"
            f"{index:02d}_{safe_slug(query)[:44]}.json"
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
        except (OSError, urllib.error.HTTPError) as exc:
            raw = json.dumps({"error": f"{type(exc).__name__}: {exc}", "query": query}).encode("utf-8")
            status = "failed"
        else:
            status = "ok"
        raw_path = output_dir / raw_name
        raw_path.write_bytes(raw)
        raws.append(
            {
                **raw_record(source_id=raw_name, source_type="scrapecreators_x_search", url=url, payload=raw, raw_file=raw_path),
                "query": query,
                "status": status,
            }
        )
        if status != "ok":
            continue
        payload = json.loads(raw.decode("utf-8"))
        docs.extend(
            normalize_x_search_result(row, source_id=raw_name, source_url=url, pilot=pilot)
            for row in extract_payload_items(payload)
            if is_x_url(str(row.get("url") or row.get("link") or ""))
        )
    return docs, raws


def scrapecreators_x_queries(*, pilot: MatchPilot, start_utc: datetime) -> list[str]:
    """Build targeted Google queries for pre-match X/Twitter evidence."""

    home = pilot.home_team
    away = pilot.away_team
    after = start_utc.date().isoformat()
    before = (pilot.cutoff_utc + timedelta(days=1)).date().isoformat()
    site = "(site:x.com OR site:twitter.com)"
    return [
        f'"{home}" "{away}" "World Cup" {site} before:{before} after:{after}',
        f'"{home} vs {away}" prediction {site} before:{before} after:{after}',
        f'"{home}" "{away}" lineup OR XI {site} before:{before} after:{after}',
        f'"{home}" "{away}" injury OR injured OR doubt {site} before:{before} after:{after}',
        f'"{home}" "{away}" odds OR bet OR pick {site} before:{before} after:{after}',
        f'"{home}" "{away}" fans OR supporters OR sentiment {site} before:{before} after:{after}',
        f'"{home}" "{away}" squad OR roster OR training {site} before:{before} after:{after}',
        f'"{home}" "{away}" journalist OR report OR preview {site} before:{before} after:{after}',
        f'"{home}" "{away}" "#WorldCup2026" {site} before:{before} after:{after}',
    ]


def normalize_x_search_result(
    row: dict[str, Any],
    *,
    source_id: str,
    source_url: str,
    pilot: MatchPilot,
) -> dict[str, Any]:
    url = clean_text(row.get("url") or row.get("link") or "")
    title = clean_text(row.get("title") or "")
    snippet = clean_text(row.get("description") or row.get("snippet") or row.get("body") or "")
    published = x_snowflake_datetime(url) or parse_loose_date(snippet)
    precision = "x_snowflake" if x_snowflake_datetime(url) else "date_level"
    return normalize_document(
        source_name=x_handle(url) or "X/Twitter",
        source_type="social",
        adapter="scrapecreators_x_search",
        title=title,
        url=url,
        snippet=snippet,
        published_at=published,
        published_raw=snippet,
        source_snapshot_id=source_id,
        source_url=source_url,
        pilot=pilot,
        timestamp_precision=precision,
    )


def normalize_document(
    *,
    source_name: str,
    source_type: str,
    adapter: str,
    title: str,
    url: str,
    snippet: str,
    published_at: datetime | None,
    published_raw: str,
    source_snapshot_id: str,
    source_url: str,
    pilot: MatchPilot,
    timestamp_precision: str,
) -> dict[str, Any]:
    text = f"{title} {snippet}"
    rejected_reasons = rejection_reasons(
        text=text,
        published_at=published_at,
        timestamp_precision=timestamp_precision,
        pilot=pilot,
    )
    sentiment = sentiment_signal(text=text, pilot=pilot)
    available_at = published_at if published_at is not None else None
    return {
        "document_id": f"{adapter}:{hashlib.sha256((title + url).encode('utf-8')).hexdigest()[:16]}",
        "source_name": source_name,
        "source_type": source_type,
        "adapter": adapter,
        "title": title,
        "url": url,
        "snippet": snippet,
        "published_raw": published_raw,
        "published": iso_utc(published_at) if published_at else "",
        "source_published": iso_utc(published_at) if published_at else "",
        "published_at_utc": iso_utc(published_at) if published_at else "",
        "available_at_utc": iso_utc(available_at) if available_at else "",
        "timestamp_precision": timestamp_precision,
        "source_snapshot_id": source_snapshot_id,
        "source_query_url": source_url,
        "usable": not rejected_reasons,
        "rejected_reasons": rejected_reasons,
        "signal_type": document_signal_type(text=text, source_type=source_type),
        "sentiment": sentiment,
        "content_hash": "sha256:" + hashlib.sha256(json.dumps({"title": title, "snippet": snippet, "url": url}, sort_keys=True).encode("utf-8")).hexdigest(),
    }


def rejection_reasons(*, text: str, published_at: datetime | None, timestamp_precision: str, pilot: MatchPilot) -> list[str]:
    reasons: list[str] = []
    if published_at is None:
        reasons.append("missing_timestamp")
    elif published_at > pilot.cutoff_utc:
        reasons.append("after_prediction_cutoff")
    elif timestamp_precision == "date_level" and published_at.date() >= pilot.kickoff_utc.date():
        reasons.append("same_day_date_level_timestamp")
    if has_result_leak(text=text, pilot=pilot):
        reasons.append("result_or_highlight_leak")
    if not mentions_both_teams(text=text, pilot=pilot):
        reasons.append("missing_team_pair")
    elif not has_match_context(text=text, pilot=pilot):
        reasons.append("missing_match_context")
    return reasons


def has_result_leak(*, text: str, pilot: MatchPilot) -> bool:
    lowered = text.casefold()
    hard_leak_words = (
        "highlights",
        "full time",
        "full-time",
        "final score",
        "game analysis",
        "match report",
        "player ratings",
        "red card",
        "red cards",
    )
    if any(word in lowered for word in hard_leak_words):
        return True
    prediction_markers = (
        "prediction",
        "predict",
        "preview",
        "pick",
        "best bet",
        "odds",
        "pronóstico",
        "pronostico",
        "predicción",
        "prediccion",
        "will win",
        "to win",
    )
    if any(word in lowered for word in prediction_markers):
        return False
    result_words = (
        "beat",
        "beats",
        "defeat",
        "defeats",
        "win over",
        "wins over",
        "wins",
        "won",
        "victoria",
        "vence",
        "ganaron",
        "triunfo",
    )
    if any(word in lowered for word in result_words):
        return True
    return False


def mentions_both_teams(*, text: str, pilot: MatchPilot) -> bool:
    lowered = text.casefold()
    return pilot.home_team.casefold() in lowered and pilot.away_team.casefold() in lowered


def has_match_context(*, text: str, pilot: MatchPilot) -> bool:
    lowered = text.casefold()
    home = pilot.home_team.casefold()
    away = pilot.away_team.casefold()
    relation = r"(?:vs\.?|v\.?|against|takes?\s+on|faces?|hosts?)"
    direct_patterns = (
        rf"{re.escape(home)}.{{0,140}}\b{relation}\b.{{0,140}}{re.escape(away)}",
        rf"{re.escape(away)}.{{0,140}}\b{relation}\b.{{0,140}}{re.escape(home)}",
    )
    if any(re.search(pattern, lowered) for pattern in direct_patterns):
        return True
    context_markers = (
        " opener",
        " opening game",
        " opening match",
        " opening clash",
        " kick off",
        " kick-off",
        " fixture",
        " match",
        " game",
        " clash",
        " lineup",
        " lineups",
        " xi",
        " prediction",
        " predict",
        " odds",
        " pick",
        " bet",
        " preview",
        " team news",
        " pronóstico",
        " pronostico",
        " alineación",
        " alineacion",
    )
    home_positions = [match.start() for match in re.finditer(re.escape(home), lowered)]
    away_positions = [match.start() for match in re.finditer(re.escape(away), lowered)]
    for home_pos in home_positions:
        for away_pos in away_positions:
            if abs(home_pos - away_pos) > 260:
                continue
            start = max(min(home_pos, away_pos) - 80, 0)
            end = min(max(home_pos + len(home), away_pos + len(away)) + 120, len(lowered))
            window = f" {lowered[start:end]} "
            if any(marker in window for marker in context_markers):
                return True
            if "world cup" in window and "schedule" in window:
                return True
    return False


def sentiment_signal(*, text: str, pilot: MatchPilot) -> dict[str, Any]:
    lowered = text.casefold()
    positive = (
        "favorite",
        "favored",
        "favourite",
        "strong",
        "boost",
        "confident",
        "fit",
        "returns",
        "ilusion",
        "favorito",
        "favorita",
    )
    negative = (
        "injury",
        "injured",
        "doubt",
        "pressure",
        "concern",
        "ruled out",
        "without",
        "duda",
        "lesion",
        "lesión",
        "baja",
    )
    home_hits = team_window_score(lowered, pilot.home_team.casefold(), positive, negative)
    away_hits = team_window_score(lowered, pilot.away_team.casefold(), positive, negative)
    return {
        "home_score": home_hits,
        "away_score": away_hits,
        "home_minus_away": round(home_hits - away_hits, 4),
        "method": "tiny_title_lexicon_v1",
    }


def document_signal_type(*, text: str, source_type: str) -> str:
    lowered = text.casefold()
    if any(word in lowered for word in ("lineup", "starting xi", " xi ", "alineación", "alineacion")):
        return "lineup"
    if any(word in lowered for word in ("injury", "injured", "doubt", "ruled out", "lesion", "lesión", "baja")):
        return "injury_availability"
    if any(word in lowered for word in ("prediction", "predict", "pronóstico", "pronostico", "pick", "best bet", "odds", "betting")):
        return "prediction_or_market"
    if any(word in lowered for word in ("fans", "supporters", "sentiment", "hype", "buzz", "afición", "aficion")):
        return "fan_sentiment"
    if source_type == "news":
        return "media_preview"
    if source_type == "social":
        return "social_context"
    return "prematch_context"


def team_window_score(text: str, team: str, positive: tuple[str, ...], negative: tuple[str, ...]) -> float:
    score = 0.0
    for match in re.finditer(re.escape(team), text):
        window = text[max(match.start() - 80, 0) : match.end() + 80]
        score += sum(0.2 for word in positive if word in window)
        score -= sum(0.2 for word in negative if word in window)
    return round(score, 4)


def summarize_documents(documents: list[dict[str, Any]], *, duplicate_count: int = 0) -> dict[str, Any]:
    usable = [item for item in documents if item.get("usable")]
    rejected = [item for item in documents if not item.get("usable")]
    return {
        "total": len(documents),
        "usable": len(usable),
        "rejected": len(rejected),
        "duplicates_removed": duplicate_count,
        "source_count": len({item.get("source_name") for item in documents if item.get("source_name")}),
        "by_adapter": count_by(documents, "adapter"),
        "usable_by_adapter": count_by(usable, "adapter"),
        "by_source_type": count_by(documents, "source_type"),
        "usable_by_source_type": count_by(usable, "source_type"),
        "by_signal_type": count_by(documents, "signal_type"),
        "usable_by_signal_type": count_by(usable, "signal_type"),
        "rejection_reasons": sorted(
            {
                reason: sum(1 for item in rejected if reason in (item.get("rejected_reasons") or []))
                for reason in {reason for item in rejected for reason in (item.get("rejected_reasons") or [])}
            }.items()
        ),
    }


def kg_source_payload(payload: dict[str, Any]) -> dict[str, Any]:
    match = payload["match"]
    documents = payload.get("documents") or []
    claims = [kg_claim_from_document(document, match=match) for document in documents]
    return {
        "findings": [
            {
                "finding_id": f"prematch_news_scrape:{safe_slug(match['home_team'])}_vs_{safe_slug(match['away_team'])}",
                "scout_name": "prematch_news_scrape_scout",
                "access_level": "public",
                "source_type": "mixed_media_social",
                "finding_name": "prematch_media_social_documents",
                "home_probability": None,
                "confidence": 0.5 if documents else 0.0,
                "summary": (
                    f"Normalized {len(documents)} strictly pre-cutoff media/social documents for "
                    f"{match['home_team']} vs {match['away_team']}."
                ),
                "citations": sorted({document["url"] for document in documents if document.get("url")}),
                "evidence_claims": claims,
            }
        ]
        if claims
        else []
    }


def kg_claim_from_document(document: dict[str, Any], *, match: dict[str, Any]) -> dict[str, Any]:
    title = str(document.get("title") or "")
    sentiment = dict(document.get("sentiment") or {})
    source_type = str(document.get("source_type") or "")
    signal_type = str(document.get("signal_type") or "")
    return {
        "claim_type": kg_claim_type(source_type=source_type, signal_type=signal_type),
        "subject": f"{match['home_team']} vs {match['away_team']} pre-match coverage",
        "team": match["home_team"],
        "player": "",
        "claim": title,
        "impact": "context_home" if float(sentiment.get("home_minus_away") or 0.0) >= 0 else "context_away",
        "confidence": 0.5,
        "source_title": str(document.get("source_name") or "Prematch source"),
        "source_url": str(document.get("url") or ""),
        "source_domain": domain(str(document.get("url") or "")),
        "source_kind": "social" if source_type == "social" else "news",
        "source_quality": "medium",
        "source_published": str(document.get("source_published") or document.get("published") or ""),
        "source_published_date": str(document.get("published_at_utc") or "")[:10],
        "available_at_utc": str(document.get("available_at_utc") or ""),
        "extraction_method": "prematch_scrape_title_signal",
        "metrics": {
            "adapter": document.get("adapter"),
            "document_id": document.get("document_id"),
            "signal_type": signal_type,
            "timestamp_precision": document.get("timestamp_precision"),
            "home_sentiment_score": sentiment.get("home_score"),
            "away_sentiment_score": sentiment.get("away_score"),
            "home_minus_away": sentiment.get("home_minus_away"),
            "sentiment_method": sentiment.get("method"),
            "source_snapshot_id": document.get("source_snapshot_id"),
        },
    }


def kg_claim_type(*, source_type: str, signal_type: str) -> str:
    if signal_type in {"lineup", "injury_availability"}:
        return signal_type
    if signal_type == "prediction_or_market":
        return "market_signal"
    if signal_type == "fan_sentiment":
        return "social_signal"
    if source_type == "social":
        return "social_signal"
    if source_type == "news":
        return "prematch_media_signal"
    return "prematch_context"


def dedupe_documents(documents: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    by_key: dict[str, dict[str, Any]] = {}
    duplicates = 0
    for document in documents:
        key = canonical_document_key(document)
        current = by_key.get(key)
        if current is None:
            by_key[key] = document
            continue
        duplicates += 1
        by_key[key] = choose_better_document(current, document)
    return list(by_key.values()), duplicates


def choose_better_document(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_rank = document_rank(left)
    right_rank = document_rank(right)
    return right if right_rank > left_rank else left


def document_rank(document: dict[str, Any]) -> tuple[int, int, str]:
    usable = 1 if document.get("usable") else 0
    exact_timestamp = 1 if document.get("timestamp_precision") in {"x_snowflake", "seen_datetime"} else 0
    available_at = str(document.get("available_at_utc") or "")
    return usable, exact_timestamp, available_at


def canonical_document_key(document: dict[str, Any]) -> str:
    url = str(document.get("url") or "").strip()
    if url:
        parsed = urllib.parse.urlparse(url)
        normalized = parsed._replace(query="", fragment="").geturl().casefold()
        return f"url:{normalized}"
    return str(document.get("content_hash") or document.get("document_id") or "")


def count_by(documents: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for document in documents:
        key = str(document.get(field) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        normalized = re.sub(r"\s+", " ", value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def prematch_output_paths(out_dir: Path) -> dict[str, Path]:
    return {
        "raw_google_news": out_dir / "raw" / "google_news",
        "raw_gdelt": out_dir / "raw" / "gdelt",
        "raw_scrapecreators_x": out_dir / "raw" / "scrapecreators_x",
        "normalized": out_dir / "normalized",
        "kg": out_dir / "kg",
        "reports": out_dir / "reports",
    }


def collection_manifest_payload(
    *,
    payload: dict[str, Any],
    start_utc: datetime,
    output: Path,
    documents_path: Path,
    kg_path: Path,
    quality_path: Path,
) -> dict[str, Any]:
    return {
        "schema_version": "prematch-collection-manifest-v1",
        "created_at_utc": payload.get("created_at_utc") or utc_now(),
        "collection_window": {
            "start_utc": iso_utc(start_utc),
            "prediction_cutoff_utc": (payload.get("match") or {}).get("prediction_cutoff_utc", ""),
        },
        "match": payload.get("match") or {},
        "files": {
            "root": str(output),
            "raw": "raw/",
            "normalized_documents": str(documents_path),
            "kg_source": str(kg_path),
            "quality_report": str(quality_path),
        },
        "summary": payload.get("summary") or {},
        "raw_sources": payload.get("raw_sources") or [],
    }


def quality_report(payload: dict[str, Any]) -> str:
    match = payload["match"]
    summary = payload["summary"]
    lines = [
        "# Prematch Scrape Quality Report",
        "",
        f"Match: {match['home_team']} vs {match['away_team']}",
        f"Kickoff UTC: {match['kickoff_utc']}",
        f"Prediction cutoff UTC: {match['prediction_cutoff_utc']}",
        "",
        "## Summary",
        "",
        f"- Total unique documents: {summary['total']}",
        f"- Usable documents: {summary['usable']}",
        f"- Rejected documents: {summary['rejected']}",
        f"- Duplicates removed: {summary['duplicates_removed']}",
        f"- Distinct source names: {summary['source_count']}",
        "",
        "## Usable By Adapter",
        "",
    ]
    for key, value in summary.get("usable_by_adapter", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Usable By Signal Type", ""])
    for key, value in summary.get("usable_by_signal_type", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Rejection Reasons", ""])
    for reason, value in summary.get("rejection_reasons", []):
        lines.append(f"- {reason}: {value}")
    lines.extend(["", "## First Usable Documents", ""])
    for document in (payload.get("documents") or [])[:25]:
        lines.append(
            "- "
            f"{document.get('available_at_utc') or 'unknown'} "
            f"[{document.get('adapter')}/{document.get('signal_type')}] "
            f"{document.get('title') or document.get('url')}"
        )
    return "\n".join(lines) + "\n"


def domain(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return parsed.netloc.casefold()


def raw_record(*, source_id: str, source_type: str, url: str, payload: bytes, raw_file: Path) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_type": source_type,
        "locator": url,
        "raw_file": str(raw_file),
        "collected_at_utc": utc_now(),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def extract_payload_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("results", "organic_results", "items", "data", "tweets"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def is_x_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.casefold().removeprefix("www.")
    return host in {"x.com", "twitter.com", "mobile.twitter.com"} or host.endswith(".twitter.com")


def x_handle(url: str) -> str:
    match = re.search(r"https?://(?:www\.)?(?:x|twitter)\.com/([^/?#]+)/status/", url, re.I)
    return f"@{match.group(1)}" if match else ""


def x_snowflake_datetime(url: str) -> datetime | None:
    match = re.search(r"/status/(\d+)", url)
    if not match:
        return None
    snowflake = int(match.group(1))
    twitter_epoch_ms = 1_288_834_974_657
    timestamp = ((snowflake >> 22) + twitter_epoch_ms) / 1000.0
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def parse_loose_date(text: str) -> datetime | None:
    match = re.search(r"\b([A-Z][a-z]{2})\s+(\d{1,2}),\s+(20\d{2})\b", text)
    if not match:
        return None
    month, day, year = match.groups()
    try:
        return datetime.strptime(f"{month} {day} {year}", "%b %d %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(errors="replace").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def parse_utc(value: str) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_rfc2822(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return email.utils.parsedate_to_datetime(value).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def parse_gdelt_seen_date(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def is_google_date_level(value: datetime | None) -> bool:
    return bool(value and value.hour == 7 and value.minute == 0 and value.second == 0)


def gdelt_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")


def iso_utc(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_") or "source"


if __name__ == "__main__":
    main()
