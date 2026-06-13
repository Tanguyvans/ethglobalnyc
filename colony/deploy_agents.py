#!/usr/bin/env python3
"""Deploy a fresh Colony agent identity batch.

This orchestrates the real identity flow:

1. Generate/reuse agent wallets and deterministic ENS identity records.
2. Register selected agents with Worldcoin AgentKit.
3. Regenerate the identity records with premium World capabilities.
4. Optionally publish ENS subnames/records on Sepolia.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from colony_harness.env import load_env_file


DEFAULT_IDENTITY_OUT = "colony/data/ens-identities.deploy.json"


def main() -> None:
    args = parse_args()
    load_env_file(args.env)
    if not args.deployment_id:
        args.deployment_id = _default_deployment_id()
    world_agents = _resolve_world_agents(args)
    _print_plan(args, world_agents)
    if args.plan_only:
        return

    _generate_identities(args, world_agents=[])

    if world_agents and not args.skip_world:
        _register_world_agents(args, world_agents)

    if world_agents and not args.skip_world:
        _generate_identities(args, world_agents=world_agents)

    if not args.skip_ens:
        _publish_ens(args)

    print("\nDeploy complete.")
    print(f"Identity JSON: {args.identity_out}")
    if world_agents and not args.skip_world:
        print(f"World agents: {', '.join(world_agents)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default="colony/.env", help="Path to .env.")
    parser.add_argument("--agents", type=int, default=50, help="Number of agents to generate.")
    parser.add_argument("--rooms", type=int, default=1, help="Room budget used for the identity generation run.")
    parser.add_argument("--seed", type=int, default=None, help="Optional deterministic population seed.")
    parser.add_argument("--identity-out", default=DEFAULT_IDENTITY_OUT, help="Output ENS identity JSON.")
    parser.add_argument(
        "--deployment-id",
        default=None,
        help="Deployment/run id written into ENS records. Defaults to deploy_YYYYMMDD_HHMMSS.",
    )
    parser.add_argument(
        "--population-state",
        default=None,
        help="Optional population state. Use this if you want the same colony roster reused across deploy runs.",
    )
    parser.add_argument(
        "--wallet-store",
        default="colony/secrets/agent-wallets.local.json",
        help="Gitignored JSON store for agent wallet records.",
    )
    parser.add_argument(
        "--wallet-provider",
        choices=["local", "dynamic"],
        default=None,
        help="Wallet backend for generated agents. Defaults to COLONY_WALLET_PROVIDER or local.",
    )
    parser.add_argument(
        "--dynamic-env",
        default=None,
        help="Optional Dynamic .env path for --wallet-provider dynamic. Defaults to COLONY_DYNAMIC_ENV or dynamic/.env.",
    )
    parser.add_argument("--ens-parent", default=None, help="Parent ENS name. Defaults to COLONY_ENS_PARENT.")
    parser.add_argument("--profile-base-url", default=None, help="Base URL for ENS agent profile records.")
    parser.add_argument(
        "--world-count",
        type=int,
        default=0,
        help="Mark the first N generated agents as premium World agents, e.g. --world-count 5.",
    )
    parser.add_argument(
        "--world-agent",
        action="append",
        default=[],
        help="Specific agent_id or wallet to register as a premium World agent. Can be repeated.",
    )
    parser.add_argument(
        "--world-verifications",
        default=None,
        help="Gitignored local Worldcoin AgentKit receipt store. Defaults to COLONY_WORLD_VERIFICATIONS.",
    )
    parser.add_argument("--skip-world", action="store_true", help="Do not run Worldcoin AgentKit registration.")
    parser.add_argument("--skip-existing-world", action="store_true", default=True)
    parser.add_argument("--no-world-qr", action="store_true", help="Do not render QR codes for World App links.")
    parser.add_argument("--skip-ens", action="store_true", help="Do not run ENS publication.")
    parser.add_argument("--ens-broadcast", action="store_true", help="Submit ENS Sepolia transactions.")
    parser.add_argument("--ens-limit", type=int, default=None, help="Only publish/check the first N ENS records.")
    parser.add_argument(
        "--ens-agent",
        action="append",
        default=[],
        help="Only publish/check this ENS agent_id. Can be repeated.",
    )
    parser.add_argument("--plan-only", action="store_true", help="Print the deployment plan and exit.")
    return parser.parse_args()


def _resolve_world_agents(args: argparse.Namespace) -> list[str]:
    selected = [f"ant_{index:04d}" for index in range(args.world_count)]
    selected.extend(args.world_agent or [])
    deduped: list[str] = []
    seen: set[str] = set()
    for agent in selected:
        key = agent.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(agent)
    return deduped


def _print_plan(args: argparse.Namespace, world_agents: list[str]) -> None:
    print("Colony agent deploy plan")
    print(f"- agents: {args.agents}")
    print(f"- identity_out: {args.identity_out}")
    print(f"- deployment_id: {args.deployment_id}")
    print(f"- wallet_store: {args.wallet_store}")
    print(f"- wallet_provider: {args.wallet_provider or os.environ.get('COLONY_WALLET_PROVIDER') or 'local'}")
    print(f"- world_agents: {', '.join(world_agents) if world_agents else '(none)'}")
    if args.skip_world:
        print("- world: skipped")
    elif world_agents:
        print("- world: register selected agents with Worldcoin AgentKit")
    else:
        print("- world: no selected agents")
    if args.skip_ens:
        print("- ens: skipped")
    else:
        mode = "broadcast" if args.ens_broadcast else "dry-run"
        print(f"- ens: {mode}")
    sys.stdout.flush()


def _generate_identities(args: argparse.Namespace, *, world_agents: list[str]) -> None:
    cmd = [
        sys.executable,
        "colony/run_demo.py",
        "--agents",
        str(args.agents),
        "--rooms",
        str(args.rooms),
        "--no-run-log",
        "--agent-wallets",
        "--wallet-store",
        args.wallet_store,
        "--identity-out",
        args.identity_out,
        "--deployment-id",
        args.deployment_id,
        "--env",
        args.env,
    ]
    if args.seed is not None:
        cmd.extend(["--seed", str(args.seed)])
    if args.population_state:
        cmd.extend(["--population-state", args.population_state])
    if args.wallet_provider:
        cmd.extend(["--wallet-provider", args.wallet_provider])
    if args.dynamic_env:
        cmd.extend(["--dynamic-env", args.dynamic_env])
    if args.ens_parent:
        cmd.extend(["--ens-parent", args.ens_parent])
    if args.profile_base_url:
        cmd.extend(["--profile-base-url", args.profile_base_url])
    if args.world_verifications:
        cmd.extend(["--world-verifications", args.world_verifications])
    for agent in world_agents:
        cmd.extend(["--world-agent", agent])
    _run(cmd)


def _register_world_agents(args: argparse.Namespace, world_agents: list[str]) -> None:
    cmd = [
        sys.executable,
        "colony/register_world_agent.py",
        *world_agents,
        "--identity-json",
        args.identity_out,
        "--env",
        args.env,
    ]
    if args.world_verifications:
        cmd.extend(["--world-verifications", args.world_verifications])
    if args.skip_existing_world:
        cmd.append("--skip-existing")
    if args.no_world_qr:
        cmd.append("--no-qr")
    _run(cmd)


def _publish_ens(args: argparse.Namespace) -> None:
    cmd = [
        sys.executable,
        "colony/register_ens_identities.py",
        args.identity_out,
        "--env",
        args.env,
    ]
    if args.ens_parent:
        cmd.extend(["--ens-parent", args.ens_parent])
    for agent in args.ens_agent or []:
        cmd.extend(["--agent-id", agent])
    if args.ens_limit is not None:
        cmd.extend(["--limit", str(args.ens_limit)])
    if args.ens_broadcast:
        cmd.append("--broadcast")
    _run(cmd)


def _run(cmd: list[str]) -> None:
    print(f"\n$ {_format_cmd(cmd)}")
    sys.stdout.flush()
    env = os.environ.copy()
    process = subprocess.Popen(cmd, env=env)
    code = process.wait()
    if code != 0:
        raise SystemExit(code)


def _format_cmd(cmd: list[str]) -> str:
    return " ".join(_quote(part) for part in cmd)


def _quote(value: str) -> str:
    if not value or any(char.isspace() for char in value):
        return repr(value)
    return value


def _default_deployment_id() -> str:
    return datetime.now(timezone.utc).strftime("deploy_%Y%m%d_%H%M%S")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        raise SystemExit(130)
