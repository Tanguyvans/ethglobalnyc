#!/usr/bin/env python3
"""Read-only Polymarket MCP stdio server for local scouting.

This server intentionally exposes only discovery/scouting data. It never loads a
private key, signs orders, or calls trading endpoints.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from typing import Any


USER_AGENT = "ColonyPolymarketMCP/0.1 (read-only scouting)"
DEFAULT_GAMMA_HOST = "https://gamma-api.polymarket.com"


def main() -> int:
    args = _parse_args()
    server = PolymarketMcpServer(
        gamma_host=args.gamma_host.rstrip("/"),
        offline=args.offline,
        timeout_seconds=args.timeout,
        default_limit=args.limit,
    )
    server.serve()
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only Polymarket MCP server for Colony scouting.")
    parser.add_argument("--gamma-host", default=os.environ.get("POLYMARKET_GAMMA_HOST", DEFAULT_GAMMA_HOST))
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use a deterministic local sample instead of the public Gamma API.",
    )
    return parser.parse_args()


class PolymarketMcpServer:
    def __init__(self, *, gamma_host: str, offline: bool, timeout_seconds: int, default_limit: int) -> None:
        self.gamma_host = gamma_host
        self.offline = offline
        self.timeout_seconds = timeout_seconds
        self.default_limit = default_limit

    def serve(self) -> None:
        for line in sys.stdin:
            if not line.strip():
                continue
            message: dict[str, Any] = {}
            try:
                message = json.loads(line)
                response = self._handle(message)
            except Exception as exc:  # noqa: BLE001
                response = _error_response(message.get("id"), code=-32000, message=str(exc))
            if response is not None:
                print(json.dumps(response, ensure_ascii=False), flush=True)

    def _handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "colony-polymarket-scout", "version": "0.1.0"},
                },
            }
        if method == "notifications/initialized":
            return None
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "result": {
                    "tools": [
                        {
                            "name": "scout_match_market",
                            "description": "Read Polymarket market snapshots for a football match.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "match": {"type": "string"},
                                    "home_team": {"type": "string"},
                                    "away_team": {"type": "string"},
                                    "query": {"type": "string"},
                                    "limit": {"type": "integer"},
                                    "offline": {"type": "boolean"},
                                    "allow_offline_fallback": {"type": "boolean"},
                                },
                            },
                        }
                    ]
                },
            }
        if method == "tools/call":
            params = message.get("params") or {}
            if params.get("name") != "scout_match_market":
                return _error_response(message.get("id"), code=-32601, message=f"unknown tool: {params.get('name')}")
            arguments = params.get("arguments") or {}
            payload = self.scout_match_market(arguments)
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"Polymarket MCP mapped {len(payload['findings'][0]['evidence_claims']) if payload.get('findings') else 0} "
                                "market snapshot claims."
                            ),
                        }
                    ],
                    "structuredContent": payload,
                },
            }
        return _error_response(message.get("id"), code=-32601, message=f"unknown method: {method}")

    def scout_match_market(self, arguments: dict[str, Any]) -> dict[str, Any]:
        match = str(arguments.get("match") or "").strip()
        home_team, away_team = _teams_from_arguments(arguments, match)
        limit = int(arguments.get("limit") or self.default_limit)
        offline = bool(arguments.get("offline", self.offline))
        allow_fallback = bool(arguments.get("allow_offline_fallback", True))
        query = str(arguments.get("query") or match or f"{home_team} {away_team}").strip()

        source_note = "live_gamma"
        try:
            markets = _offline_markets(home_team, away_team) if offline else self._fetch_gamma_markets(query, limit=limit)
        except Exception as exc:  # noqa: BLE001
            if not allow_fallback:
                raise
            markets = _offline_markets(home_team, away_team)
            source_note = f"offline_fallback:{type(exc).__name__}"

        relevant = _filter_markets(markets, home_team=home_team, away_team=away_team, query=query)
        claims = _claims_from_markets(
            relevant[:limit],
            home_team=home_team,
            away_team=away_team,
            source_note=source_note if not offline else "offline_sample",
        )
        return {
            "findings": [
                {
                    "scout_name": "polymarket_mcp_scout",
                    "source_type": "market",
                    "finding_name": "polymarket_market_snapshot",
                    "confidence": 0.66 if offline or source_note.startswith("offline") else 0.72,
                    "citations": sorted({claim["source_url"] for claim in claims if claim.get("source_url")}),
                    "summary": (
                        f"Read {len(relevant[:limit])} Polymarket market row(s) for "
                        f"{home_team} vs {away_team} via MCP ({source_note if not offline else 'offline_sample'})."
                    ),
                    "evidence_claims": claims,
                }
            ]
        }

    def _fetch_gamma_markets(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        search_params = urllib.parse.urlencode(
            {
                "q": query,
                "limit_per_type": str(max(limit, 5)),
                "search_profiles": "false",
                "keep_closed_markets": "0",
            }
        )
        search_request = urllib.request.Request(
            f"{self.gamma_host}/public-search?{search_params}",
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(search_request, timeout=self.timeout_seconds) as response:
            search_payload = json.loads(response.read().decode("utf-8"))
        search_rows = _market_rows_from_payload(search_payload)
        if search_rows:
            return search_rows

        params = urllib.parse.urlencode(
            {
                "closed": "false",
                "active": "true",
                "limit": str(max(limit * 4, 20)),
                "order": "volume",
                "ascending": "false",
            }
        )
        request = urllib.request.Request(
            f"{self.gamma_host}/markets?{params}",
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        rows = _market_rows_from_payload(payload)
        query_key = _key(query)
        filtered = [row for row in rows if isinstance(row, dict) and _key(str(row.get("question") or "")).find(query_key) >= 0]
        return filtered or [row for row in rows if isinstance(row, dict)]


def _teams_from_arguments(arguments: dict[str, Any], match: str) -> tuple[str, str]:
    home_team = str(arguments.get("home_team") or "").strip()
    away_team = str(arguments.get("away_team") or "").strip()
    if (not home_team or not away_team) and " vs " in match.casefold():
        left, right = re.split(r"\s+vs\s+", match, maxsplit=1, flags=re.I)
        home_team = home_team or left.strip()
        away_team = away_team or right.strip()
    return home_team or "Home", away_team or "Away"


def _filter_markets(
    markets: list[dict[str, Any]],
    *,
    home_team: str,
    away_team: str,
    query: str,
) -> list[dict[str, Any]]:
    team_keys = [_key(home_team), _key(away_team)]
    query_key = _key(query)
    output = []
    for market in markets:
        question = str(market.get("question") or market.get("title") or "")
        haystack = _key(question)
        if all(team_key and team_key in haystack for team_key in team_keys):
            output.append(market)
            continue
        if query_key and query_key in haystack:
            output.append(market)
    return output


def _market_rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key in ("markets", "data", "results", "items"):
        values = payload.get(key)
        if isinstance(values, list):
            rows.extend(row for row in values if isinstance(row, dict))
    events = payload.get("events")
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            event_markets = event.get("markets")
            if isinstance(event_markets, list):
                for market in event_markets:
                    if isinstance(market, dict):
                        rows.append({**market, "eventSlug": market.get("eventSlug") or event.get("slug")})
    if any(key in payload for key in ("question", "conditionId", "clobTokenIds", "outcomePrices")):
        rows.append(payload)
    return rows


def _claims_from_markets(
    markets: list[dict[str, Any]],
    *,
    home_team: str,
    away_team: str,
    source_note: str,
) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for market in markets:
        question = str(market.get("question") or market.get("title") or "Polymarket market")
        slug = str(market.get("slug") or market.get("eventSlug") or "")
        outcomes = _json_list(market.get("outcomes"))
        token_ids = _json_list(market.get("clobTokenIds"))
        prices = _json_list(market.get("outcomePrices"))
        if not outcomes:
            outcomes = ["Yes", "No"]
        for index, outcome in enumerate(outcomes[:4]):
            outcome_text = str(outcome)
            token_id = str(token_ids[index]) if index < len(token_ids) else ""
            price = _float_or_text(prices[index]) if index < len(prices) else ""
            team = _team_from_outcome(outcome_text, home_team=home_team, away_team=away_team)
            source_url = _market_url(slug, market)
            claims.append(
                {
                    "claim_type": "market_snapshot",
                    "subject": f"Polymarket market: {question}",
                    "team": team or home_team,
                    "player": "",
                    "claim": (
                        f"Polymarket market '{question}' lists outcome '{outcome_text}'"
                        f"{f' at price {price}' if price != '' else ''}."
                    ),
                    "impact": _impact(team or home_team, home_team=home_team, away_team=away_team),
                    "confidence": 0.64 if source_note.startswith("offline") else 0.72,
                    "source_title": "Polymarket MCP market snapshot",
                    "source_url": source_url,
                    "source_kind": "mcp",
                    "source_quality": "strong",
                    "extraction_method": "polymarket_mcp",
                    "metrics": {
                        "polymarket_id": market.get("id") or market.get("conditionId") or "",
                        "condition_id": market.get("conditionId") or "",
                        "slug": slug,
                        "outcome": outcome_text,
                        "outcome_index": index,
                        "token_id": token_id,
                        "price": price,
                        "volume": _float_or_text(market.get("volume")),
                        "liquidity": _float_or_text(market.get("liquidity")),
                        "active": market.get("active"),
                        "closed": market.get("closed"),
                        "accepting_orders": market.get("acceptingOrders"),
                        "source_note": source_note,
                    },
                }
            )
    return claims


def _offline_markets(home_team: str, away_team: str) -> list[dict[str, Any]]:
    slug = f"{_slug(home_team)}-vs-{_slug(away_team)}"
    return [
        {
            "id": "offline-polymarket-brazil-morocco",
            "conditionId": "offline-condition-brazil-morocco",
            "question": f"Will {home_team} beat {away_team}?",
            "slug": slug,
            "outcomes": json.dumps([home_team, away_team]),
            "clobTokenIds": json.dumps(["offline-home-token", "offline-away-token"]),
            "outcomePrices": json.dumps(["0.58", "0.42"]),
            "volume": "125000",
            "liquidity": "21000",
            "active": True,
            "closed": False,
            "acceptingOrders": True,
        }
    ]


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return []
        return decoded if isinstance(decoded, list) else []
    return []


def _team_from_outcome(outcome: str, *, home_team: str, away_team: str) -> str:
    outcome_key = _key(outcome)
    if _key(home_team) and _key(home_team) in outcome_key:
        return home_team
    if _key(away_team) and _key(away_team) in outcome_key:
        return away_team
    return ""


def _impact(team: str, *, home_team: str, away_team: str) -> str:
    if _key(team) == _key(away_team):
        return "context_away"
    return "context_home"


def _market_url(slug: str, market: dict[str, Any]) -> str:
    url = str(market.get("url") or market.get("source_url") or "")
    if url:
        return url
    if slug:
        return f"https://polymarket.com/event/{slug}"
    market_id = str(market.get("id") or market.get("conditionId") or "market")
    return f"polymarket-mcp://market/{_slug(market_id)}"


def _float_or_text(value: Any) -> Any:
    if value in {None, ""}:
        return ""
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return str(value)


def _key(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).split())


def _slug(value: str) -> str:
    return "-".join(_key(value).split()) or "value"


def _error_response(message_id: Any, *, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


if __name__ == "__main__":
    raise SystemExit(main())
