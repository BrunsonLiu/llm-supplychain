"""Run the four frontier layers on a small, reproducible slice.

Stages:

* ``causal``: SCM benchmark (synthetic outcomes; model-relative effects);
* ``scenarios``: calibrated scenarios from real UCI demand;
* ``joint``: cost-aware CVaR stochastic joint model on a real instance;
* ``online`` / ``rl``: policy-selection replay over the five order days.

The script is deliberately small. It is a reproducible smoke benchmark, not a
replacement for the full 30-seed research harness.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.causal import CausalBenchmarkConfig, run_estimator_benchmark  # noqa: E402
from supply.data.online_retail import (  # noqa: E402
    clean_transactions,
    load_online_retail_raw,
    load_panel,
)
from supply.e2e import (  # noqa: E402
    ROLLING_POLICIES,
    ScenarioConfig,
    build_calibrated_scenarios,
    build_e2e_instance,
    evaluate_rolling_policies,
    order_day_map,
    scenario_diagnostics,
    solve_stochastic_joint,
)
from supply.e2e.online import run_online_bandit  # noqa: E402
from supply.rl import LinUCB, ThompsonSampling, UCB1  # noqa: E402


def _git_sha() -> str:
    try:
        value = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        return value
    except Exception:  # noqa: BLE001
        return "unknown"


def _git_dirty() -> bool:
    try:
        value = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        )
        # The benchmark writes its own manifest; don't call that code dirty.
        ignored = ("benchmarks/frontier/", "__pycache__/", ".pytest_cache/")
        changed = [
            line
            for line in value.splitlines()
            if line.strip() and not any(token in line for token in ignored)
        ]
        return bool(changed)
    except Exception:  # noqa: BLE001
        return True


def _top_skus(clean: pd.DataFrame, limit: int) -> List[str]:
    ranked = (
        clean.groupby("sku")["quantity"]
        .sum()
        .sort_values(ascending=False)
        .head(limit)
        .index.astype(str)
        .tolist()
    )
    return ranked


def _daily_matrix(results: Dict[str, Dict[str, Any]], policies: List[str]) -> np.ndarray:
    matrix = np.zeros((len(policies), 5), dtype=float)
    for policy_index, policy in enumerate(policies):
        rows = results[policy].get("by_order_day", [])
        for row in rows:
            day = int(row["day"])
            if 0 <= day < 5:
                matrix[policy_index, day] = float(row["otif_rate"])
    return matrix


def _online_stage(
    matrix: np.ndarray,
    policies: List[str],
    selector,
    label: str,
) -> Dict[str, Any]:
    """``matrix`` is rounds x policies; context[0] is the round row."""
    contexts = [
        np.array([float(row), float(row % 5)], dtype=float)
        for row in range(matrix.shape[0])
    ]

    def evaluate(action: int, context) -> float:
        row = int(round(float(context[0])))
        return float(matrix[row, action])

    result = run_online_bandit(
        selector,
        contexts,
        evaluate,
        policy_names=policies,
    )
    return {
        "label": label,
        **result.as_dict(),
        "matrix": matrix.tolist(),
        "reward_metric": "otif_rate",
        "caveat": "按订单日/实例离线回放，不是实时上线；策略在一周内固定。",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the four-layer frontier smoke benchmark")
    parser.add_argument("--out-dir", default=str(ROOT / "benchmarks/frontier"))
    parser.add_argument("--orders", type=int, default=60)
    parser.add_argument("--max-lines", type=int, default=6)
    parser.add_argument("--top-skus", type=int, default=12)
    parser.add_argument("--scenarios", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--milp-time", type=float, default=1.0)
    parser.add_argument("--joint-time", type=float, default=15.0)
    parser.add_argument("--causal-replicates", type=int, default=3)
    parser.add_argument("--online-repeats", type=int, default=2)
    parser.add_argument("--skip-online", action="store_true")
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()

    if args.quick:
        args.orders = min(args.orders, 30)
        args.max_lines = min(args.max_lines, 4)
        args.scenarios = min(args.scenarios, 6)
        args.causal_replicates = min(args.causal_replicates, 2)
        args.milp_time = min(args.milp_time, 0.5)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "git_dirty": _git_dirty(),
        "script": "scripts/run_frontier_bench.py",
        "stages": [],
        "limitations": [
            "因果阶段是 SCM 合成结果，不是 UCI 观测数据的真实因果效应。",
            "在线/RL 阶段是按订单日离线回放，不是实时上线。",
            "联合优化只跑一个小规模真实实例；不是 30-seed 全量结论。",
        ],
    }

    panel, _ = load_panel(ROOT / "data/processed/online_retail_ii_weekly.parquet")
    raw = load_online_retail_raw(
        ROOT / "data/raw/online_retail_II.xlsx",
        cache_path=ROOT / "data/raw/online_retail_II.raw.parquet",
    )
    clean, clean_stats = clean_transactions(raw)
    clean["sku"] = clean["sku"].astype(str)
    last_week = pd.to_datetime(panel["week"]).max()
    weekly = panel.groupby("week")["demand"].sum()
    manifest["dataset"] = {
        "clean_rows": int(clean_stats["clean_rows"]),
        "skus": int(clean["sku"].nunique()),
        "weeks": int(panel["week"].nunique()),
        "target_week": str(last_week.date()),
        "weekly_demand_mean": float(weekly.mean()),
        "weekly_demand_sd": float(weekly.std(ddof=1)),
    }

    # 1) Causal SCM benchmark.
    causal = run_estimator_benchmark(
        CausalBenchmarkConfig(
            n_units=1200 if args.quick else 2500,
            n_replicates=args.causal_replicates,
            seed=args.seed,
        )
    )
    (out / "causal.json").write_text(
        json.dumps(causal.as_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest["stages"].append("causal")
    print(
        "[causal] truth "
        f"{causal.truth:.4f}; best "
        f"{causal.summary.iloc[0]['method']} "
        f"abs_bias {causal.summary.iloc[0]['mean_abs_bias']:.4f}"
    )

    # 2) Real small instance.
    skus = _top_skus(clean, args.top_skus)
    instance = build_e2e_instance(
        clean,
        skus,
        sample_orders=args.orders,
        max_lines=args.max_lines,
        stock_factor=0.85,
        seed=args.seed,
        week=last_week,
        pickers_per_dc=1,
        shift_minutes=600.0,
        arrival_seed=1,
    )
    order_day = order_day_map(instance, clean)
    manifest["instance"] = {
        "orders": int(instance.n_orders),
        "skus": int(instance.fulfillment.n_skus),
        "units": int(instance.fulfillment.line_qty.sum()),
        "stock": int(instance.fulfillment.stock.sum()),
        "order_days": {
            str(day): int((order_day == day).sum())
            for day in range(int(order_day.max()) + 1)
        },
    }

    scenario_set = build_calibrated_scenarios(
        clean,
        instance.fulfillment.sku_names,
        last_week,
        int(instance.fulfillment.line_qty.sum()),
        config=ScenarioConfig(
            method="gaussian_copula",
            n_scenarios=args.scenarios,
            lookback_weeks=6,
            seed=args.seed,
        ),
    )
    diagnostics = scenario_diagnostics(scenario_set)
    (out / "scenarios.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest["stages"].append("scenarios")
    print(
        f"[scenarios] {diagnostics['n_scenarios']} scenarios x "
        f"{diagnostics['n_skus']} SKUs; target {diagnostics['target_units']}"
    )

    # 3) Stochastic joint.
    plan = solve_stochastic_joint(
        instance,
        scenario_set,
        cvar_weight=0.5,
        alpha=0.8,
        time_limit_seconds=args.joint_time,
        workers=2,
    )
    (out / "joint.json").write_text(
        json.dumps(plan.as_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest["stages"].append("joint")
    print(
        f"[joint] {plan.status} expected_cost {plan.expected_cost:.2f} "
        f"CVaR {plan.cvar_cost:.2f} gap {plan.gap:.4f}"
    )

    if not args.skip_online:
        policies = list(ROLLING_POLICIES)
        matrices = []
        rolling_payload: Dict[str, Any] = {}
        for offset in range(max(1, args.online_repeats)):
            if offset == 0:
                replay_instance, replay_days = instance, order_day
            else:
                replay_instance = build_e2e_instance(
                    clean,
                    skus,
                    sample_orders=args.orders,
                    max_lines=args.max_lines,
                    stock_factor=0.85,
                    seed=args.seed + offset,
                    week=last_week,
                    pickers_per_dc=1,
                    shift_minutes=600.0,
                    arrival_seed=1 + offset,
                )
                replay_days = order_day_map(replay_instance, clean)
            rolling = evaluate_rolling_policies(
                replay_instance,
                replay_days,
                policies=policies,
                metric="otif_rate",
                milp_time=args.milp_time,
                workers=1,
            )
            matrices.append(_daily_matrix(rolling, policies).T)
            rolling_payload[str(args.seed + offset)] = {
                policy: {
                    "otif_rate": float(rolling[policy]["otif_rate"]),
                    "backlog_units": int(rolling[policy]["backlog_units"]),
                }
                for policy in policies
            }
        matrix = np.vstack(matrices)
        online = _online_stage(
            matrix,
            policies,
            UCB1(len(policies), exploration=1.0),
            "UCB1 replay over order days",
        )
        rl = _online_stage(
            matrix,
            policies,
            LinUCB(len(policies), n_features=2, alpha=0.2),
            "LinUCB RL-0 replay over order days",
        )
        (out / "online.json").write_text(
            json.dumps({"online": online, "rl": rl}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        manifest["stages"].extend(["online", "rl"])
        manifest["rolling"] = rolling_payload
        manifest["online_repeats"] = max(1, args.online_repeats)
        print(
            f"[online] UCB1 reward {online['cumulative_reward']:.3f} "
            f"regret {online['regret']:.3f}"
        )
        print(
            f"[rl] LinUCB reward {rl['cumulative_reward']:.3f} "
            f"regret {rl['regret']:.3f}"
        )

    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
