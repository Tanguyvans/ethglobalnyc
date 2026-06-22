#!/usr/bin/env python3
"""Evaluate Colony forecasting behavior on deterministic synthetic scenarios.

The goal is not to prove football accuracy. It is to catch whether debate,
memory, personas, and staking change behavior in measurable ways instead of
only producing plausible logs.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

try:  # Script mode: python3 colony/evaluate_colony.py
    from colony_harness import ColonyHarness
    from colony_harness.artifacts import create_run_dir, write_compact_run_artifacts
    from colony_harness.decision import build_collective_decision
    from colony_harness.economy import EconomyLedger, build_paid_knowledge_views, market_spec_for_match
    from colony_harness.models import Finding, Forecast, MatchContext, ResultSide
except ImportError:  # Package mode: python3 -m unittest ...
    from colony.colony_harness import ColonyHarness
    from colony.colony_harness.artifacts import create_run_dir, write_compact_run_artifacts
    from colony.colony_harness.decision import build_collective_decision
    from colony.colony_harness.economy import EconomyLedger, build_paid_knowledge_views, market_spec_for_match
    from colony.colony_harness.models import Finding, Forecast, MatchContext, ResultSide


DEFAULT_OUTPUT_ROOT = Path("colony/runs/evaluations")


@dataclass(frozen=True)
class EvaluationScenario:
    scenario_id: str
    description: str
    home_team: str
    away_team: str
    market_home_probability: float
    stats_home_signal: float
    odds_home_signal: float
    news_home_signal: float
    result_side: ResultSide
    expected_winner_reason: str

    def to_match(self, *, repeat: int) -> MatchContext:
        return MatchContext(
            round_id=f"eval_{self.scenario_id}_r{repeat:02d}",
            home_team=self.home_team,
            away_team=self.away_team,
            market_home_probability=self.market_home_probability,
            stats_home_signal=self.stats_home_signal,
            odds_home_signal=self.odds_home_signal,
            news_home_signal=self.news_home_signal,
            group_name="Evaluation Group",
            stage_name="Group Stage",
            score=_score_for_result(self.result_side),
            findings=_findings_for_scenario(self),
        )


@dataclass
class VariantRun:
    row: dict[str, Any]
    forecasts: list[Forecast]


def default_scenarios() -> list[EvaluationScenario]:
    return [
        EvaluationScenario(
            scenario_id="odds_reliable",
            description="Odds and market are useful; sentiment is a mild distraction.",
            home_team="France",
            away_team="Senegal",
            market_home_probability=0.56,
            stats_home_signal=0.53,
            odds_home_signal=0.62,
            news_home_signal=0.49,
            result_side="home",
            expected_winner_reason="pricing was the cleanest signal",
        ),
        EvaluationScenario(
            scenario_id="sentiment_trap",
            description="News sentiment likes home, but pricing and stats point away.",
            home_team="Brazil",
            away_team="Morocco",
            market_home_probability=0.47,
            stats_home_signal=0.43,
            odds_home_signal=0.41,
            news_home_signal=0.67,
            result_side="away",
            expected_winner_reason="sentiment overreacted",
        ),
        EvaluationScenario(
            scenario_id="contrarian_room",
            description="Most public signals lean home, but the correct move is away.",
            home_team="Spain",
            away_team="Japan",
            market_home_probability=0.51,
            stats_home_signal=0.63,
            odds_home_signal=0.44,
            news_home_signal=0.61,
            result_side="away",
            expected_winner_reason="consensus home signal was crowded and wrong",
        ),
        EvaluationScenario(
            scenario_id="draw_knife_edge",
            description="All signals are close enough that draw discipline should matter.",
            home_team="USA",
            away_team="Wales",
            market_home_probability=0.50,
            stats_home_signal=0.51,
            odds_home_signal=0.50,
            news_home_signal=0.49,
            result_side="draw",
            expected_winner_reason="low edge should favor draw/preservation",
        ),
        EvaluationScenario(
            scenario_id="source_audit",
            description="A noisy news spike conflicts with steadier stats and odds.",
            home_team="Argentina",
            away_team="Croatia",
            market_home_probability=0.54,
            stats_home_signal=0.58,
            odds_home_signal=0.57,
            news_home_signal=0.39,
            result_side="home",
            expected_winner_reason="audited hard signals beat a weak narrative",
        ),
    ]


def run_evaluation(
    *,
    population_size: int,
    speaker_slots: int,
    seed: int,
    repeats: int,
    output_dir: Path,
    write_run_artifacts: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    memory_paths = {
        "debate_memory_log": output_dir / "ant_memory_log.jsonl",
        "debate_memory_injected": output_dir / "ant_memory_injected.jsonl",
    }
    for memory_path in memory_paths.values():
        if memory_path.exists():
            memory_path.unlink()
    scenarios = default_scenarios()
    rows: list[dict[str, Any]] = []
    run_artifacts: list[str] = []

    for repeat in range(1, repeats + 1):
        for scenario_index, scenario in enumerate(scenarios):
            scenario_seed = seed + scenario_index * 101
            match = scenario.to_match(repeat=repeat)
            no_debate = _run_no_debate(
                match=match,
                scenario=scenario,
                population_size=population_size,
                speaker_slots=speaker_slots,
                seed=scenario_seed,
                repeat=repeat,
            )
            debate = _run_debate(
                variant="debate_memory_log",
                match=match,
                scenario=scenario,
                population_size=population_size,
                speaker_slots=speaker_slots,
                seed=scenario_seed,
                repeat=repeat,
                output_dir=output_dir,
                memory_path=memory_paths["debate_memory_log"],
                memory_influence=False,
                write_run_artifacts=write_run_artifacts,
            )
            injected = _run_debate(
                variant="debate_memory_injected",
                match=match,
                scenario=scenario,
                population_size=population_size,
                speaker_slots=speaker_slots,
                seed=scenario_seed,
                repeat=repeat,
                output_dir=output_dir,
                memory_path=memory_paths["debate_memory_injected"],
                memory_influence=True,
                write_run_artifacts=write_run_artifacts,
            )
            _attach_baseline_comparison(debate.row, debate.forecasts, no_debate.forecasts)
            _attach_baseline_comparison(injected.row, injected.forecasts, no_debate.forecasts)
            _attach_memory_comparison(injected.row, injected.forecasts, debate.forecasts)
            rows.append(no_debate.row)
            rows.append(debate.row)
            rows.append(injected.row)
            for variant_run in (debate, injected):
                if variant_run.row.get("run_artifact_dir"):
                    run_artifacts.append(str(variant_run.row["run_artifact_dir"]))

    summary = _summarize_rows(rows)
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "population_size": population_size,
        "speaker_slots": speaker_slots,
        "seed": seed,
        "repeats": repeats,
        "memory_paths": {key: str(path) for key, path in memory_paths.items()},
        "scenarios": [asdict(scenario) for scenario in scenarios],
        "summary": summary,
        "rows": rows,
        "run_artifacts": run_artifacts,
    }
    (output_dir / "evaluation_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "evaluation_report.md").write_text(_markdown_report(payload), encoding="utf-8")
    return payload


def run_evaluation_matrix(
    *,
    agent_counts: list[int],
    room_counts: list[int],
    seeds: list[int],
    repeats: int,
    output_dir: Path,
    write_run_artifacts: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    configs = []
    for agents in agent_counts:
        for rooms in room_counts:
            for seed in seeds:
                config_dir = output_dir / f"agents_{agents}_rooms_{rooms}_seed_{seed}"
                payload = run_evaluation(
                    population_size=agents,
                    speaker_slots=rooms,
                    seed=seed,
                    repeats=repeats,
                    output_dir=config_dir,
                    write_run_artifacts=write_run_artifacts,
                )
                configs.append(
                    {
                        "agents": agents,
                        "rooms": rooms,
                        "seed": seed,
                        "repeats": repeats,
                        "report_path": str(config_dir / "evaluation_report.md"),
                        "results_path": str(config_dir / "evaluation_results.json"),
                        "summary": payload["summary"],
                    }
                )

    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "agent_counts": agent_counts,
        "room_counts": room_counts,
        "seeds": seeds,
        "repeats": repeats,
        "config_count": len(configs),
        "summary": summarize_matrix(configs),
        "configs": configs,
    }
    (output_dir / "matrix_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "matrix_report.md").write_text(_matrix_markdown_report(payload), encoding="utf-8")
    return payload


def score_forecasts(forecasts: list[Forecast], *, result_side: ResultSide) -> dict[str, Any]:
    if not forecasts:
        return {
            "forecast_count": 0,
            "brier_home": None,
            "side_accuracy": None,
            "normalized_roi": None,
            "total_staked": 0.0,
            "side_counts": {},
        }
    target = target_home_probability(result_side)
    total_staked = round(sum(max(forecast.stake, 0.0) for forecast in forecasts), 4)
    side_counts = Counter(forecast.side for forecast in forecasts)
    correct_count = sum(1 for forecast in forecasts if forecast.side == result_side)
    net = sum(
        forecast.stake if forecast.side == result_side else -forecast.stake
        for forecast in forecasts
    )
    return {
        "forecast_count": len(forecasts),
        "brier_home": round(mean((forecast.home_probability - target) ** 2 for forecast in forecasts), 6),
        "side_accuracy": round(correct_count / len(forecasts), 6),
        "normalized_roi": None if total_staked <= 0 else round(net / total_staked, 6),
        "total_staked": total_staked,
        "side_counts": dict(sorted(side_counts.items())),
    }


def target_home_probability(result_side: ResultSide) -> float:
    if result_side == "home":
        return 1.0
    if result_side == "away":
        return 0.0
    return 0.5


def parse_int_list(value: str | None, *, default: list[int], name: str) -> list[int]:
    if value is None or not str(value).strip():
        return list(default)
    parsed = []
    for raw in str(value).split(","):
        item = raw.strip()
        if not item:
            continue
        try:
            parsed.append(int(item))
        except ValueError as exc:
            raise ValueError(f"{name} must be a comma-separated list of integers") from exc
    if not parsed:
        raise ValueError(f"{name} must contain at least one integer")
    if any(item < 1 for item in parsed):
        raise ValueError(f"{name} values must be positive")
    return parsed


def summarize_matrix(configs: list[dict[str, Any]]) -> dict[str, Any]:
    variant_names = sorted(
        {
            variant
            for config in configs
            for variant in (config.get("summary") or {}).get("variants", {})
        }
    )
    variants = {}
    for variant in variant_names:
        variant_rows = [
            (config.get("summary") or {}).get("variants", {}).get(variant, {})
            for config in configs
            if variant in (config.get("summary") or {}).get("variants", {})
        ]
        variants[variant] = {
            "configs": len(variant_rows),
            "avg_brier_home": _avg(variant_rows, "avg_brier_home"),
            "avg_side_accuracy": _avg(variant_rows, "avg_side_accuracy"),
            "avg_normalized_roi": _avg(variant_rows, "avg_normalized_roi"),
            "avg_collective_accuracy": _avg(variant_rows, "collective_accuracy"),
            "avg_memory_recall_results": _avg(variant_rows, "avg_memory_recall_results"),
            "avg_memory_relevant_results": _avg(variant_rows, "avg_memory_relevant_results"),
            "avg_memory_irrelevant_results": _avg(variant_rows, "avg_memory_irrelevant_results"),
            "avg_memory_side_changes_vs_log": _avg(variant_rows, "avg_memory_side_changes_vs_log"),
            "avg_memory_shift_mean_abs_vs_log": _avg(variant_rows, "avg_memory_shift_mean_abs_vs_log"),
        }
    return {
        "variants": variants,
        "win_counts": {
            "brier": _matrix_win_counts(configs, "avg_brier_home", lower_is_better=True),
            "side_accuracy": _matrix_win_counts(configs, "avg_side_accuracy", lower_is_better=False),
            "roi": _matrix_win_counts(configs, "avg_normalized_roi", lower_is_better=False),
            "collective_accuracy": _matrix_win_counts(configs, "collective_accuracy", lower_is_better=False),
        },
        "best_by_brier": _best_variant(variants, "avg_brier_home", lower_is_better=True),
        "best_by_side_accuracy": _best_variant(variants, "avg_side_accuracy", lower_is_better=False),
        "best_by_roi": _best_variant(variants, "avg_normalized_roi", lower_is_better=False),
    }


def _run_no_debate(
    *,
    match: MatchContext,
    scenario: EvaluationScenario,
    population_size: int,
    speaker_slots: int,
    seed: int,
    repeat: int,
) -> VariantRun:
    harness = ColonyHarness(population_size=population_size, speaker_slots=speaker_slots, seed=seed)
    market_spec = market_spec_for_match(match)
    ledger = EconomyLedger(match.round_id)
    views = build_paid_knowledge_views(match, harness.agents, ledger)
    allow_draw = market_spec.market_type == "three_way"
    forecasts = [
        agent.forecast(
            views[agent.agent_id].to_match_context(match),
            debate_home_probability=None,
            access_tier=views[agent.agent_id].access_tier,
            visible_findings=len(views[agent.agent_id].visible_findings),
            allow_draw=allow_draw,
        )
        for agent in harness.agents
    ]
    decision = build_collective_decision(match=match, agents=harness.agents, forecasts=forecasts)
    row = _base_row(
        variant="no_debate",
        scenario=scenario,
        repeat=repeat,
        seed=seed,
        forecasts=forecasts,
        decision=decision.to_dict(),
        result_side=market_spec.result_side,
    )
    row.update(
        {
            "memory_recalls": 0,
            "memory_writes": 0,
            "memory_recall_results": 0,
            "memory_relevant_results": 0,
            "memory_irrelevant_results": 0,
            "avg_memory_recall_count": 0.0,
            "debate_home_probability": None,
            "room_count": 0,
            "room_claims": 0,
            "disputes": 0,
            "debate_shift_mean_abs_vs_no_debate": 0.0,
            "side_changes_vs_no_debate": 0,
            "memory_side_changes_vs_log": 0,
            "memory_shift_mean_abs_vs_log": 0.0,
        }
    )
    return VariantRun(row=row, forecasts=forecasts)


def _run_debate(
    *,
    variant: str,
    match: MatchContext,
    scenario: EvaluationScenario,
    population_size: int,
    speaker_slots: int,
    seed: int,
    repeat: int,
    output_dir: Path,
    memory_path: Path,
    memory_influence: bool,
    write_run_artifacts: bool,
) -> VariantRun:
    old_backend = os.environ.get("COLONY_MEMORY_BACKEND")
    old_path = os.environ.get("COLONY_MEMORY_PATH")
    os.environ["COLONY_MEMORY_BACKEND"] = "json"
    os.environ["COLONY_MEMORY_PATH"] = str(memory_path)
    try:
        harness = ColonyHarness(
            population_size=population_size,
            speaker_slots=speaker_slots,
            seed=seed,
            memory_influence=memory_influence,
        )
        result = harness.run_round(match)
    finally:
        _restore_env("COLONY_MEMORY_BACKEND", old_backend)
        _restore_env("COLONY_MEMORY_PATH", old_path)
    run_artifact_dir = ""
    if write_run_artifacts:
        run_root = output_dir / "runs"
        run_artifact_path = create_run_dir(run_root, result.round_id)
        write_compact_run_artifacts(run_dir=run_artifact_path, match=match, result=result, debug=False)
        run_artifact_dir = str(run_artifact_path)
    row = _base_row(
        variant=variant,
        scenario=scenario,
        repeat=repeat,
        seed=seed,
        forecasts=result.forecasts,
        decision=result.collective_decision.to_dict(),
        result_side=result.market_spec.result_side,
    )
    memory_counts = _memory_result_counts(result.memory_recall, match)
    row.update(
        {
            "memory_recalls": result.summary.get("memory_recalls", 0),
            "memory_writes": result.summary.get("memory_writes", 0),
            "memory_recall_results": memory_counts["total"],
            "memory_relevant_results": memory_counts["relevant"],
            "memory_irrelevant_results": memory_counts["irrelevant"],
            "avg_memory_recall_count": round(
                mean(forecast.memory_recall_count for forecast in result.forecasts),
                4,
            ),
            "debate_home_probability": result.summary.get("debate_home_probability"),
            "room_count": result.summary.get("room_count", 0),
            "room_claims": result.summary.get("room_claims", 0),
            "disputes": result.summary.get("dispute_count", 0),
            "memory_influence": memory_influence,
            "memory_side_changes_vs_log": 0,
            "memory_shift_mean_abs_vs_log": 0.0,
            "archetypes": result.summary.get("archetypes", {}),
            "social_classes": result.summary.get("social_classes", {}),
            "run_artifact_dir": run_artifact_dir,
        }
    )
    return VariantRun(row=row, forecasts=result.forecasts)


def _base_row(
    *,
    variant: str,
    scenario: EvaluationScenario,
    repeat: int,
    seed: int,
    forecasts: list[Forecast],
    decision: dict[str, Any],
    result_side: ResultSide,
) -> dict[str, Any]:
    scores = score_forecasts(forecasts, result_side=result_side)
    collective_side = str((decision.get("recommendation") or {}).get("side") or "")
    collective_home_probability = (decision.get("internal_metrics") or {}).get("weighted_home_probability")
    row = {
        "scenario_id": scenario.scenario_id,
        "scenario_description": scenario.description,
        "expected_winner_reason": scenario.expected_winner_reason,
        "repeat": repeat,
        "variant": variant,
        "seed": seed,
        "result_side": result_side,
        "target_home_probability": target_home_probability(result_side),
        "collective_side": collective_side,
        "collective_correct": collective_side == result_side,
        "collective_home_probability": collective_home_probability,
    }
    row.update(scores)
    return row


def _attach_baseline_comparison(
    row: dict[str, Any],
    forecasts: list[Forecast],
    baseline_forecasts: list[Forecast],
) -> None:
    baseline_by_agent = {forecast.agent_id: forecast for forecast in baseline_forecasts}
    probability_deltas = []
    side_changes = 0
    for forecast in forecasts:
        baseline = baseline_by_agent.get(forecast.agent_id)
        if baseline is None:
            continue
        probability_deltas.append(abs(forecast.home_probability - baseline.home_probability))
        if forecast.side != baseline.side:
            side_changes += 1
    row["debate_shift_mean_abs_vs_no_debate"] = (
        round(mean(probability_deltas), 6) if probability_deltas else 0.0
    )
    row["side_changes_vs_no_debate"] = side_changes


def _attach_memory_comparison(
    row: dict[str, Any],
    forecasts: list[Forecast],
    log_only_forecasts: list[Forecast],
) -> None:
    log_by_agent = {forecast.agent_id: forecast for forecast in log_only_forecasts}
    probability_deltas = []
    side_changes = 0
    for forecast in forecasts:
        baseline = log_by_agent.get(forecast.agent_id)
        if baseline is None:
            continue
        probability_deltas.append(abs(forecast.home_probability - baseline.home_probability))
        if forecast.side != baseline.side:
            side_changes += 1
    row["memory_shift_mean_abs_vs_log"] = (
        round(mean(probability_deltas), 6) if probability_deltas else 0.0
    )
    row["memory_side_changes_vs_log"] = side_changes


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_variant[str(row["variant"])].append(row)

    variant_summary = {}
    for variant, variant_rows in sorted(by_variant.items()):
        variant_summary[variant] = {
            "runs": len(variant_rows),
            "avg_brier_home": _avg(variant_rows, "brier_home"),
            "avg_side_accuracy": _avg(variant_rows, "side_accuracy"),
            "avg_normalized_roi": _avg(variant_rows, "normalized_roi"),
            "collective_accuracy": round(
                sum(1 for row in variant_rows if row.get("collective_correct")) / len(variant_rows),
                6,
            ),
            "avg_memory_recall_results": _avg(variant_rows, "memory_recall_results"),
            "avg_memory_relevant_results": _avg(variant_rows, "memory_relevant_results"),
            "avg_memory_irrelevant_results": _avg(variant_rows, "memory_irrelevant_results"),
            "avg_memory_side_changes_vs_log": _avg(variant_rows, "memory_side_changes_vs_log"),
            "avg_memory_shift_mean_abs_vs_log": _avg(variant_rows, "memory_shift_mean_abs_vs_log"),
            "avg_side_changes_vs_no_debate": _avg(variant_rows, "side_changes_vs_no_debate"),
            "avg_debate_shift_mean_abs": _avg(variant_rows, "debate_shift_mean_abs_vs_no_debate"),
        }

    scenario_rows = []
    for scenario_id in sorted({str(row["scenario_id"]) for row in rows}):
        scenario_rows.append(
            {
                "scenario_id": scenario_id,
                "variants": {
                    variant: {
                        "avg_brier_home": _avg(
                            [row for row in rows if row["scenario_id"] == scenario_id and row["variant"] == variant],
                            "brier_home",
                        ),
                        "avg_side_accuracy": _avg(
                            [row for row in rows if row["scenario_id"] == scenario_id and row["variant"] == variant],
                            "side_accuracy",
                        ),
                        "collective_correct_count": sum(
                            1
                            for row in rows
                            if row["scenario_id"] == scenario_id
                            and row["variant"] == variant
                            and row.get("collective_correct")
                        ),
                    }
                    for variant in sorted(by_variant)
                },
            }
        )

    return {
        "variants": variant_summary,
        "scenarios": scenario_rows,
            "notes": [
            "Lower brier_home is better.",
            "normalized_roi uses a simple +stake/-stake toy payout, not real market odds.",
            "debate_memory_log measures memory recall/write plumbing without using it for forecasts.",
            "debate_memory_injected lets settled same-match memories nudge each ant's forecast.",
        ],
    }


def _markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Colony Evaluation Report",
        "",
        f"- Created: {payload['created_at']}",
        f"- Population: {payload['population_size']}",
        f"- Rooms: {payload['speaker_slots']}",
        f"- Seed: {payload['seed']}",
        f"- Repeats: {payload['repeats']}",
        f"- Memory paths: `{payload['memory_paths']}`",
        "",
        "## Variant Summary",
        "",
        "| Variant | Runs | Brier | Side accuracy | Collective accuracy | ROI | Memory hits | Relevant hits | Irrelevant hits | Memory side changes | Memory shift | Side changes | Debate shift |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for variant, summary in payload["summary"]["variants"].items():
        lines.append(
            "| "
            f"{variant} | {summary['runs']} | {_fmt(summary['avg_brier_home'])} | "
            f"{_fmt(summary['avg_side_accuracy'])} | {_fmt(summary['collective_accuracy'])} | "
            f"{_fmt(summary['avg_normalized_roi'])} | {_fmt(summary['avg_memory_recall_results'])} | "
            f"{_fmt(summary['avg_memory_relevant_results'])} | "
            f"{_fmt(summary['avg_memory_irrelevant_results'])} | "
            f"{_fmt(summary['avg_memory_side_changes_vs_log'])} | {_fmt(summary['avg_memory_shift_mean_abs_vs_log'])} | "
            f"{_fmt(summary['avg_side_changes_vs_no_debate'])} | {_fmt(summary['avg_debate_shift_mean_abs'])} |"
        )

    lines.extend(
        [
            "",
            "## Scenario Results",
            "",
            "| Scenario | Variant | Brier | Side accuracy | Collective correct |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for scenario in payload["summary"]["scenarios"]:
        for variant, values in scenario["variants"].items():
            lines.append(
                f"| {scenario['scenario_id']} | {variant} | "
                f"{_fmt(values['avg_brier_home'])} | {_fmt(values['avg_side_accuracy'])} | "
                f"{values['collective_correct_count']} |"
            )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `no_debate` is the control: same synthetic scenario and population seed, but no debate signal.",
            "- `debate_memory_log` is the current log-only memory path: debate affects forecasts and memory is recalled/written.",
            "- `debate_memory_injected` lets settled same-match memories nudge later forecasts.",
            "- If memory hits rise without metric movement, memory is still log-only rather than decision-useful.",
            "- If side changes rise while Brier/accuracy worsens, debate is socially active but not epistemically useful.",
            "",
            "## Notes",
            "",
        ]
    )
    for note in payload["summary"]["notes"]:
        lines.append(f"- {note}")
    if payload.get("run_artifacts"):
        lines.extend(["", "## Run Artifacts", ""])
        for path in payload["run_artifacts"]:
            lines.append(f"- `{path}`")
    return "\n".join(lines) + "\n"


def _matrix_markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Colony Evaluation Matrix Report",
        "",
        f"- Created: {payload['created_at']}",
        f"- Agent counts: {', '.join(str(value) for value in payload['agent_counts'])}",
        f"- Room counts: {', '.join(str(value) for value in payload['room_counts'])}",
        f"- Seeds: {', '.join(str(value) for value in payload['seeds'])}",
        f"- Repeats: {payload['repeats']}",
        f"- Configs: {payload['config_count']}",
        "",
        "## Aggregate Variant Summary",
        "",
        "| Variant | Configs | Brier | Side accuracy | Collective accuracy | ROI | Relevant hits | Irrelevant hits | Memory side changes | Memory shift |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for variant, summary in payload["summary"]["variants"].items():
        lines.append(
            "| "
            f"{variant} | {summary['configs']} | {_fmt(summary['avg_brier_home'])} | "
            f"{_fmt(summary['avg_side_accuracy'])} | {_fmt(summary['avg_collective_accuracy'])} | "
            f"{_fmt(summary['avg_normalized_roi'])} | {_fmt(summary['avg_memory_relevant_results'])} | "
            f"{_fmt(summary['avg_memory_irrelevant_results'])} | "
            f"{_fmt(summary['avg_memory_side_changes_vs_log'])} | "
            f"{_fmt(summary['avg_memory_shift_mean_abs_vs_log'])} |"
        )

    lines.extend(
        [
            "",
            "## Winners",
            "",
            f"- Best Brier: `{payload['summary']['best_by_brier'] or 'n/a'}`",
            f"- Best side accuracy: `{payload['summary']['best_by_side_accuracy'] or 'n/a'}`",
            f"- Best toy ROI: `{payload['summary']['best_by_roi'] or 'n/a'}`",
            "",
            "## Win Counts",
            "",
            "| Metric | Winners by config |",
            "| --- | --- |",
        ]
    )
    for metric, counts in payload["summary"]["win_counts"].items():
        count_text = ", ".join(f"{variant}={count}" for variant, count in sorted(counts.items())) or "n/a"
        lines.append(f"| {metric} | {count_text} |")

    lines.extend(
        [
            "",
            "## Config Details",
            "",
            "| Agents | Rooms | Seed | Variant | Brier | Side accuracy | Collective accuracy | ROI | Report |",
            "| ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for config in payload["configs"]:
        variants = config["summary"]["variants"]
        for variant, summary in variants.items():
            lines.append(
                f"| {config['agents']} | {config['rooms']} | {config['seed']} | {variant} | "
                f"{_fmt(summary.get('avg_brier_home'))} | {_fmt(summary.get('avg_side_accuracy'))} | "
                f"{_fmt(summary.get('collective_accuracy'))} | {_fmt(summary.get('avg_normalized_roi'))} | "
                f"`{config['report_path']}` |"
            )
    return "\n".join(lines) + "\n"


def _findings_for_scenario(scenario: EvaluationScenario) -> list[Finding]:
    return [
        _finding(scenario, "market", "public", "market", scenario.market_home_probability, 0.72),
        _finding(scenario, "stats", "public", "stats", scenario.stats_home_signal, 0.70),
        _finding(scenario, "odds", "shared", "odds", scenario.odds_home_signal, 0.78),
        _finding(scenario, "news", "private", "news", scenario.news_home_signal, 0.60),
    ]


def _finding(
    scenario: EvaluationScenario,
    suffix: str,
    access_level: str,
    source_type: str,
    home_probability: float,
    confidence: float,
) -> Finding:
    return Finding(
        finding_id=f"{scenario.scenario_id}:{suffix}",
        scout_name=f"eval_{suffix}_scout",
        access_level=access_level,  # type: ignore[arg-type]
        source_type=source_type,  # type: ignore[arg-type]
        finding_name=f"{suffix} signal",
        home_probability=home_probability,
        home_delta=round(home_probability - scenario.market_home_probability, 4),
        confidence=confidence,
        cost=0.0,
        citations=[f"eval://{scenario.scenario_id}/{suffix}"],
        summary=(
            f"{suffix} signal for {scenario.home_team} vs {scenario.away_team}: "
            f"{home_probability:.2f} home probability."
        ),
        evidence_claims=[
            {
                "claim": f"{suffix} signal points to {_lean_label(home_probability)}",
                "subject": suffix,
                "source_quality": "strong" if suffix in {"market", "odds", "stats"} else "medium",
                "source_title": f"eval {suffix} scout",
            }
        ],
    )


def _score_for_result(result_side: ResultSide) -> str:
    if result_side == "home":
        return "2-1"
    if result_side == "away":
        return "1-2"
    if result_side == "draw":
        return "1-1"
    return ""


def _memory_result_counts(memory_recall: list[dict], match: MatchContext) -> dict[str, int]:
    total = 0
    relevant = 0
    for item in memory_recall:
        results = (item.get("recall") or {}).get("results") or []
        total += len(results)
        for result in results:
            metadata = result.get("metadata") or {}
            if (
                metadata.get("home_team") == match.home_team
                and metadata.get("away_team") == match.away_team
            ):
                relevant += 1
    return {"total": total, "relevant": relevant, "irrelevant": max(0, total - relevant)}


def _lean_label(home_probability: float) -> str:
    if home_probability >= 0.54:
        return "home"
    if home_probability <= 0.46:
        return "away"
    return "draw/knife-edge"


def _avg(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [row.get(key) for row in rows if isinstance(row.get(key), int | float)]
    if not values:
        return None
    return round(mean(float(value) for value in values), 6)


def _best_variant(variants: dict[str, dict[str, Any]], key: str, *, lower_is_better: bool) -> str:
    candidates = [
        (variant, values.get(key))
        for variant, values in variants.items()
        if isinstance(values.get(key), int | float)
    ]
    if not candidates:
        return ""
    return str(
        min(candidates, key=lambda item: float(item[1]))[0]
        if lower_is_better
        else max(candidates, key=lambda item: float(item[1]))[0]
    )


def _matrix_win_counts(configs: list[dict[str, Any]], key: str, *, lower_is_better: bool) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for config in configs:
        variants = (config.get("summary") or {}).get("variants", {})
        candidates = [
            (variant, values.get(key))
            for variant, values in variants.items()
            if isinstance(values.get(key), int | float)
        ]
        if not candidates:
            continue
        best_value = (
            min(float(value) for _variant, value in candidates)
            if lower_is_better
            else max(float(value) for _variant, value in candidates)
        )
        for variant, value in candidates:
            if abs(float(value) - best_value) <= 1e-12:
                counts[variant] += 1
    return dict(sorted(counts.items()))


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _restore_env(key: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value


def _default_output_dir() -> Path:
    return DEFAULT_OUTPUT_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agents", type=int, default=40, help="Population size per scenario.")
    parser.add_argument("--rooms", type=int, default=6, help="Debate room/speaker budget.")
    parser.add_argument("--seed", type=int, default=42, help="Base deterministic seed.")
    parser.add_argument(
        "--agent-counts",
        default=None,
        help="Comma-separated population sizes for matrix mode, for example 12,32,64.",
    )
    parser.add_argument(
        "--room-counts",
        default=None,
        help="Comma-separated debate room budgets for matrix mode, for example 4,6,8.",
    )
    parser.add_argument(
        "--seeds",
        default=None,
        help="Comma-separated base seeds for matrix mode, for example 5,77,123.",
    )
    parser.add_argument("--repeats", type=int, default=2, help="Repeat count per scenario.")
    parser.add_argument("--out-dir", type=Path, default=None, help="Directory for evaluation_report.md and JSON.")
    parser.add_argument(
        "--write-run-artifacts",
        action="store_true",
        help="Also write compact per-round artifacts for debate variants.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.agents < 1:
        raise SystemExit("--agents must be positive")
    if args.rooms < 1:
        raise SystemExit("--rooms must be positive")
    if args.repeats < 1:
        raise SystemExit("--repeats must be positive")
    output_dir = args.out_dir or _default_output_dir()
    matrix_mode = bool(args.agent_counts or args.room_counts or args.seeds)
    if matrix_mode:
        try:
            agent_counts = parse_int_list(args.agent_counts, default=[args.agents], name="--agent-counts")
            room_counts = parse_int_list(args.room_counts, default=[args.rooms], name="--room-counts")
            seeds = parse_int_list(args.seeds, default=[args.seed], name="--seeds")
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        payload = run_evaluation_matrix(
            agent_counts=agent_counts,
            room_counts=room_counts,
            seeds=seeds,
            repeats=args.repeats,
            output_dir=output_dir,
            write_run_artifacts=args.write_run_artifacts,
        )
        print(f"Evaluation matrix complete: {output_dir}")
        print("Aggregate variant summary:")
        for variant, summary in payload["summary"]["variants"].items():
            print(
                f"- {variant}: brier={_fmt(summary['avg_brier_home'])} "
                f"side_acc={_fmt(summary['avg_side_accuracy'])} "
                f"collective_acc={_fmt(summary['avg_collective_accuracy'])} "
                f"roi={_fmt(summary['avg_normalized_roi'])}"
            )
        return

    payload = run_evaluation(
        population_size=args.agents,
        speaker_slots=args.rooms,
        seed=args.seed,
        repeats=args.repeats,
        output_dir=output_dir,
        write_run_artifacts=args.write_run_artifacts,
    )
    print(f"Evaluation complete: {output_dir}")
    print("Variant summary:")
    for variant, summary in payload["summary"]["variants"].items():
        print(
            f"- {variant}: brier={_fmt(summary['avg_brier_home'])} "
            f"side_acc={_fmt(summary['avg_side_accuracy'])} "
            f"collective_acc={_fmt(summary['collective_accuracy'])} "
            f"memory_hits={_fmt(summary['avg_memory_recall_results'])} "
            f"relevant_hits={_fmt(summary['avg_memory_relevant_results'])} "
            f"irrelevant_hits={_fmt(summary['avg_memory_irrelevant_results'])}"
        )


if __name__ == "__main__":
    main()
