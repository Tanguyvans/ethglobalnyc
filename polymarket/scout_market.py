#!/usr/bin/env python3
"""Read-only Polymarket market scout CLI.

Prints the same normalized findings payload that the MCP tool returns, so it can
be plugged into `colony/scout_to_kg.py` through a `cli:` source.
"""

from __future__ import annotations

import argparse
import json
import os

from mcp_server import DEFAULT_GAMMA_HOST, PolymarketMcpServer


def main() -> int:
    args = _parse_args()
    server = PolymarketMcpServer(
        gamma_host=args.gamma_host.rstrip("/"),
        offline=args.offline,
        timeout_seconds=args.timeout,
        default_limit=args.limit,
    )
    payload = server.scout_match_market(
        {
            "match": args.match,
            "home_team": args.home_team,
            "away_team": args.away_team,
            "query": args.query,
            "limit": args.limit,
            "offline": args.offline,
            "allow_offline_fallback": args.allow_offline_fallback,
        }
    )
    _mark_cli_provenance(payload)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read Polymarket markets and print KG-ready scout findings.")
    parser.add_argument("--match", default="Brazil vs Morocco")
    parser.add_argument("--home-team", default="Brazil")
    parser.add_argument("--away-team", default="Morocco")
    parser.add_argument("--query", default="")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--gamma-host", default=os.environ.get("POLYMARKET_GAMMA_HOST", DEFAULT_GAMMA_HOST))
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--allow-offline-fallback", action="store_true")
    return parser.parse_args()


def _mark_cli_provenance(payload: dict) -> None:
    for finding in payload.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        if finding.get("scout_name") == "polymarket_mcp_scout":
            finding["scout_name"] = "polymarket_cli_scout"
        for claim in finding.get("evidence_claims") or []:
            if not isinstance(claim, dict):
                continue
            claim["source_kind"] = "cli"
            claim["source_title"] = "Polymarket CLI market snapshot"
            claim["extraction_method"] = "polymarket_cli"


if __name__ == "__main__":
    raise SystemExit(main())
