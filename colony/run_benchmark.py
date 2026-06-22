#!/usr/bin/env python3
"""Run Colony on a resolved-event benchmark dataset."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

try:  # Script mode: python3 colony/run_benchmark.py
    from colony_harness.benchmark import run_benchmark_dataset
except ImportError:  # Package mode
    from colony.colony_harness.benchmark import run_benchmark_dataset


DEFAULT_DATASET = Path(__file__).parent / "data" / "benchmarks" / "worldcup_pilot.json"
DEFAULT_OUTPUT_ROOT = Path("colony/runs/benchmarks")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="Benchmark dataset JSON path.")
    parser.add_argument("--agents", type=int, default=24, help="Population size.")
    parser.add_argument("--rooms", type=int, default=5, help="Debate room/speaker budget.")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic population seed.")
    parser.add_argument("--out-dir", type=Path, default=None, help="Output directory for report and JSON.")
    parser.add_argument(
        "--memory-influence",
        action="store_true",
        help="Allow same-match memories to influence forecasts when available.",
    )
    parser.add_argument(
        "--write-run-artifacts",
        action="store_true",
        help="Write compact per-event debate artifacts.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.agents < 1:
        raise SystemExit("--agents must be positive")
    if args.rooms < 1:
        raise SystemExit("--rooms must be positive")
    output_dir = args.out_dir or DEFAULT_OUTPUT_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = run_benchmark_dataset(
        dataset_path=args.dataset,
        population_size=args.agents,
        speaker_slots=args.rooms,
        seed=args.seed,
        output_dir=output_dir,
        memory_influence=args.memory_influence,
        write_run_artifacts=args.write_run_artifacts,
    )
    summary = payload["summary"]
    print(f"Benchmark complete: {output_dir}")
    print(
        "Summary: "
        f"events={summary['events']} "
        f"brier={_fmt(summary['avg_brier_home'])} "
        f"side_acc={_fmt(summary['avg_side_accuracy'])} "
        f"collective_acc={_fmt(summary['collective_accuracy'])} "
        f"roi={_fmt(summary['avg_normalized_roi'])}"
    )


def _fmt(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


if __name__ == "__main__":
    main()
