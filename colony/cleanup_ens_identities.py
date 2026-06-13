#!/usr/bin/env python3
"""Deactivate or clear generated Colony ENS subname records for retesting.

Default mode is a dry-run. Add --broadcast to submit Sepolia transactions.
By default this deactivates records for the records in an identity JSON:

- com.colony.active -> false

Pass --clear-records to clear resolver data instead:

- addr -> 0x0000000000000000000000000000000000000000
- every text record key in the JSON -> ""

It intentionally does not unregister ENSv2 subnames. The stable subdomain is the agent's
identity; deployment_id/active records carry the current run state.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from eth_account import Account
from web3 import Web3

from colony_harness.env import load_env_file
from register_ens_identities import (
    ENS_REGISTRY_ABI,
    MAX_UINT64,
    NAME_WRAPPER_ABI,
    PUBLIC_RESOLVER_ABI,
    SEPOLIA_NAME_WRAPPER,
    SEPOLIA_PUBLIC_RESOLVER,
    SEPOLIA_REGISTRY,
    SEPOLIA_V2_FACTORY,
    SEPOLIA_V2_REGISTRY,
    V2_REGISTRY_ABI,
    V2_STATUS_REGISTERED,
    ZERO_ADDRESS,
    _assert_parent_authority,
    _assert_v2_parent_authority,
    _connect,
    _connect_public,
    _resolve_parent_status_auto,
    _resolve_v2_parent_status,
    _send_contract_tx,
    compute_proxy_address,
    default_owned_resolver_salt,
    label_id,
    namehash,
)


def main() -> None:
    args = parse_args()
    load_env_file(args.env)
    payload = json.loads(Path(args.identity_json).read_text(encoding="utf-8"))
    records = _filter_records(list(payload.get("records") or []), args)
    if not records:
        raise SystemExit("No ENS identity records selected.")
    parent = _resolve_ens_parent(args, payload)
    if not parent:
        raise SystemExit("Missing ENS parent. Set COLONY_ENS_PARENT, include ens_parent in JSON, or pass --ens-parent.")
    ens_version = _resolve_ens_version(args)

    print(f"Parent: {parent}")
    print(f"Records selected: {len(records)}")
    print(f"Action: {_action_label(args)}")

    if args.delete_local_identity:
        print(f"Local identity JSON will be deleted: {args.identity_json}")
    if args.delete_local_wallets:
        print(f"Local wallet store will be deleted: {args.wallet_store}")

    if not args.broadcast:
        _print_dry_run(records, args=args)
        print(f"\nDry-run only. Add --broadcast to {_action_label(args)} on Sepolia.")
        print("Local files are not deleted unless --broadcast is also passed.")
        return

    w3, account = _connect(args)
    registry = w3.eth.contract(address=Web3.to_checksum_address(args.registry), abi=ENS_REGISTRY_ABI)
    wrapper = w3.eth.contract(address=Web3.to_checksum_address(args.name_wrapper), abi=NAME_WRAPPER_ABI)
    v2_registry = w3.eth.contract(address=Web3.to_checksum_address(args.v2_registry), abi=V2_REGISTRY_ABI)
    parent_status = _resolve_parent_status_auto(registry, wrapper, v2_registry, parent, ens_version)

    if parent_status["version"] == "v2":
        _assert_v2_parent_authority(parent_status, account.address)
        parent_registry = w3.eth.contract(address=parent_status["subregistry"], abi=V2_REGISTRY_ABI)
        resolver_address = _v2_resolver_address(w3, account.address, args)
        if not w3.eth.get_code(resolver_address):
            raise SystemExit(f"ENSv2 resolver is not deployed at {resolver_address}; nothing safe to clear.")
        resolver = w3.eth.contract(address=resolver_address, abi=PUBLIC_RESOLVER_ABI)
        _update_v2_records(w3, account, parent_registry, resolver, records, args=args)
    else:
        _assert_parent_authority(registry, wrapper, parent_status, account.address)
        resolver = w3.eth.contract(address=Web3.to_checksum_address(args.resolver), abi=PUBLIC_RESOLVER_ABI)
        _update_resolver_records(w3, account, resolver, records, args=args)

    _delete_local_files(args)
    print("\nCleanup complete.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("identity_json", nargs="?", default="colony/data/ens-identities.deploy.json")
    parser.add_argument("--env", default="colony/.env", help="Path to .env containing PROJECT_ENS_PRIVATE_KEY/RPC.")
    parser.add_argument("--rpc-url", default=None, help="Sepolia RPC URL. Defaults to SEPOLIA_RPC_URL or public fallback.")
    parser.add_argument("--private-key-env", default="PROJECT_ENS_PRIVATE_KEY")
    parser.add_argument("--ens-parent", default=None, help="Override parent ENS name.")
    parser.add_argument("--ens-version", choices=["auto", "v1", "v2"], default=None)
    parser.add_argument("--registry", default=SEPOLIA_REGISTRY)
    parser.add_argument("--name-wrapper", default=SEPOLIA_NAME_WRAPPER)
    parser.add_argument("--resolver", default=SEPOLIA_PUBLIC_RESOLVER)
    parser.add_argument("--v2-registry", default=SEPOLIA_V2_REGISTRY)
    parser.add_argument("--v2-factory", default=SEPOLIA_V2_FACTORY)
    parser.add_argument("--v2-resolver-proxy-logic", default="0x917C561a74Df398646e06f3FFAA51DB8e8330C5A")
    parser.add_argument("--agent-id", action="append", default=[], help="Only clear this agent_id. Can be repeated.")
    parser.add_argument("--limit", type=int, default=None, help="Only clear the first N selected records.")
    parser.add_argument(
        "--clear-records",
        action="store_true",
        help="Clear addr and all text records instead of only setting com.colony.active=false.",
    )
    parser.add_argument("--broadcast", action="store_true", help="Submit Sepolia transactions.")
    parser.add_argument(
        "--delete-local-identity",
        action="store_true",
        help="After successful broadcast, delete the identity JSON file.",
    )
    parser.add_argument(
        "--delete-local-wallets",
        action="store_true",
        help="After successful broadcast, delete the local wallet store.",
    )
    parser.add_argument("--wallet-store", default="colony/secrets/agent-wallets.local.json")
    return parser.parse_args()


def _filter_records(records: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.agent_id:
        wanted = set(args.agent_id)
        records = [record for record in records if str(record.get("agent_id")) in wanted]
    if args.limit is not None:
        records = records[: args.limit]
    return records


def _print_dry_run(records: list[dict[str, Any]], *, args: argparse.Namespace) -> None:
    for index, record in enumerate(records, start=1):
        text_records = dict(record.get("text") or {})
        print(f"\n[{index}/{len(records)}] {record['ens_name']}")
        if args.clear_records:
            print("  addr -> 0x0000000000000000000000000000000000000000")
            print(f"  text -> clear {len(text_records)} keys")
        else:
            print("  com.colony.active -> false")


def _update_v2_records(
    w3: Web3,
    account: Any,
    parent_registry: Any,
    resolver: Any,
    records: list[dict[str, Any]],
    *,
    args: argparse.Namespace,
) -> None:
    selected = []
    for record in records:
        status = parent_registry.functions.getState(label_id(str(record["label"]))).call()
        if int(status[0]) != V2_STATUS_REGISTERED:
            print(f"\n- skip {record['ens_name']}: subname not registered")
            continue
        selected.append(record)
    _update_resolver_records(w3, account, resolver, selected, args=args)


def _update_resolver_records(
    w3: Web3,
    account: Any,
    resolver: Any,
    records: list[dict[str, Any]],
    *,
    args: argparse.Namespace,
) -> None:
    zero = Web3.to_checksum_address(ZERO_ADDRESS)
    for index, record in enumerate(records, start=1):
        ens_name = str(record["ens_name"])
        node = namehash(ens_name)
        text_records = dict(record.get("text") or {})
        print(f"\n[{index}/{len(records)}] {_action_label(args)} {ens_name}")
        if args.clear_records:
            calls = [resolver.functions.setAddr(node, zero)._encode_transaction_data()]
            for key in text_records:
                calls.append(resolver.functions.setText(node, str(key), "")._encode_transaction_data())
        else:
            calls = [resolver.functions.setText(node, "com.colony.active", "false")._encode_transaction_data()]
        _send_contract_tx(w3, account, resolver.functions.multicall(calls), f"{_action_label(args)} {ens_name}")


def _v2_resolver_address(w3: Web3, signer: str, args: argparse.Namespace) -> str:
    owner = Web3.to_checksum_address(signer)
    return compute_proxy_address(
        w3=w3,
        factory=Web3.to_checksum_address(args.v2_factory),
        proxy_logic=Web3.to_checksum_address(args.v2_resolver_proxy_logic),
        deployer=owner,
        salt=default_owned_resolver_salt(owner),
    )


def _delete_local_files(args: argparse.Namespace) -> None:
    if args.delete_local_identity:
        _delete_file(Path(args.identity_json))
    if args.delete_local_wallets:
        _delete_file(Path(args.wallet_store))


def _delete_file(path: Path) -> None:
    if not path.exists():
        print(f"Local file already absent: {path}")
        return
    path.unlink()
    print(f"Deleted local file: {path}")


def _action_label(args: argparse.Namespace) -> str:
    return "clear addr + text records" if args.clear_records else "deactivate records"


def _resolve_ens_parent(args: argparse.Namespace, payload: dict[str, Any]) -> str:
    return str(args.ens_parent or os.environ.get("COLONY_ENS_PARENT") or payload.get("ens_parent") or "").strip().lower().strip(".")


def _resolve_ens_version(args: argparse.Namespace) -> str:
    value = str(args.ens_version or os.environ.get("COLONY_ENS_VERSION") or "auto").strip().lower()
    if value not in {"auto", "v1", "v2"}:
        raise SystemExit(f"Unsupported COLONY_ENS_VERSION/--ens-version: {value}")
    return value


if __name__ == "__main__":
    main()
