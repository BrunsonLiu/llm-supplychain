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
    build_conformal_scenarios,
    build_e2e_instance,
    calibrate_conformal_unmet_cap,
    evaluate_rolling_policies,
    order_day_map,
    scenario_diagnostics,
    solve_stochastic_joint,
)
from supply.e2e.online import run_online_bandit  # noqa: E402
from supply.forecasting.conformal import (  # noqa: E402
    AdaptiveConformalConfig,
    ConformalConfig,
    evaluate_conformal,
    fit_conformal,
    run_adaptive_conformal,
)
from supply.rl import LinUCB, UCB1  # noqa: E402


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


def _solve_with_cap(instance, scenario_set, cap, args, **kwargs):
    return solve_stochastic_joint(
        instance,
        scenario_set,
        cvar_weight=0.5,
        alpha=0.8,
        time_limit_seconds=args.joint_time,
        workers=2,
        unmet_cap=cap,
        **kwargs,
    )


def _min_feasible_cap(
    instance,
    scenario_set,
    args,
    upper_cap: float,
    iterations: int = 6,
    **kwargs,
) -> Dict[str, Any]:
    """Bisect the smallest CVaR(unmet) cap the model can actually meet.

    ``upper_cap`` must be feasible (usually the unconstrained CVaR). A cap of 0
    is the ideal bound; the returned value is the physical floor implied by
    stock, capacity and serviceability under the chosen levers.
    """
    lo, hi = 0.0, float(np.ceil(upper_cap))
    try:
        _solve_with_cap(instance, scenario_set, hi, args, **kwargs)
    except RuntimeError:
        return {"min_cap": None, "status": "INFEASIBLE_AT_UPPER"}
    best = _solve_with_cap(instance, scenario_set, hi, args, **kwargs)
    for _ in range(iterations):
        if hi - lo <= max(1.0, 0.01 * hi):
            break
        mid = 0.5 * (lo + hi)
        try:
            plan = _solve_with_cap(instance, scenario_set, mid, args, **kwargs)
        except RuntimeError:
            lo = mid
            continue
        hi = mid
        best = plan
    return {
        "min_cap": float(hi),
        "status": best.status,
        "expected_cost": best.expected_cost,
        "cvar_cost": best.cvar_cost,
        "expected_unmet": best.expected_unmet,
        "cvar_unmet": best.cvar_unmet,
        "stock_units": int(np.sum(best.sku_stock)) if best.sku_stock is not None else None,
        "capacity_units": int(np.sum(best.dc_capacity)) if best.dc_capacity is not None else None,
    }


def _repeated_frontier(
    instance,
    rows: pd.DataFrame,
    base_set,
    target_units: int,
    args,
) -> Dict[str, Any]:
    """Repeat the price-of-robustness sweep over independent scenario seeds.

    A single 6-scenario draw makes CVaR an extreme-value estimate: one lucky or
    unlucky draw decides the premium. Repeating the draw and reporting mean/sd
    separates a real effect from sampling noise.
    """
    holdings = (0.05, 0.25, 1.0, 2.0, 4.0)
    seeds = list(range(args.seed, args.seed + args.lever_seeds))
    records: List[Dict[str, Any]] = []
    for seed in seeds:
        try:
            scenario_set = build_conformal_scenarios(
                rows,
                base_set,
                n_scenarios=args.scenarios,
                seed=seed,
                target_units=target_units,
            )
            holdout = build_conformal_scenarios(
                rows,
                base_set,
                n_scenarios=args.scenarios,
                seed=seed + 10_000,
                target_units=target_units,
            )
        except Exception as exc:  # noqa: BLE001
            records.append({"seed": seed, "status": "ERROR", "error": str(exc)})
            continue
        try:
            calibration = calibrate_conformal_unmet_cap(
                np.asarray(instance.fulfillment.stock, dtype=np.int64),
                holdout,
                instance.fulfillment.dc_capacity,
                target_delta=0.1,
                alpha=0.8,
                time_limit_seconds=max(2.0, args.joint_time / 3.0),
                workers=2,
            )
        except Exception as exc:  # noqa: BLE001
            records.append({"seed": seed, "status": "CALIBRATION_ERROR", "error": str(exc)})
            continue
        cap = float(calibration["cap"])
        for holding in holdings:
            options = {
                "holding_cost": float(holding),
                "shortage_cost": 2.0,
                "adjustable_stock": True,
                "max_stock_factor": 3.0,
            }
            try:
                free = solve_stochastic_joint(
                    instance,
                    scenario_set,
                    cvar_weight=0.5,
                    alpha=0.8,
                    time_limit_seconds=args.joint_time,
                    workers=2,
                    **options,
                )
                capped = solve_stochastic_joint(
                    instance,
                    scenario_set,
                    cvar_weight=0.5,
                    alpha=0.8,
                    time_limit_seconds=args.joint_time,
                    workers=2,
                    unmet_cap=cap,
                    **options,
                )
                records.append(
                    {
                        "seed": seed,
                        "holding_cost": float(holding),
                        "cap": cap,
                        "price_of_robustness": capped.expected_cost - free.expected_cost,
                        "cost_unconstrained": free.expected_cost,
                        "cost_capped": capped.expected_cost,
                        "cvar_unmet_unconstrained": free.cvar_unmet,
                        "cvar_unmet_capped": capped.cvar_unmet,
                        "capped_feasible": True,
                    }
                )
            except RuntimeError:
                records.append(
                    {
                        "seed": seed,
                        "holding_cost": float(holding),
                        "cap": cap,
                        "capped_feasible": False,
                        "price_of_robustness": None,
                    }
                )

    summary: Dict[str, Any] = {}
    for holding in holdings:
        premiums = [
            record["price_of_robustness"]
            for record in records
            if record.get("holding_cost") == holding
            and record.get("price_of_robustness") is not None
        ]
        infeasible = sum(
            1
            for record in records
            if record.get("holding_cost") == holding
            and record.get("capped_feasible") is False
        )
        if premiums:
            summary[str(holding)] = {
                "n": len(premiums),
                "infeasible": infeasible,
                "mean_premium": float(np.mean(premiums)),
                "sd_premium": float(np.std(premiums, ddof=1)) if len(premiums) > 1 else 0.0,
                "min_premium": float(np.min(premiums)),
                "max_premium": float(np.max(premiums)),
                "share_positive": float(np.mean([p > 0 for p in premiums])),
            }
        else:
            summary[str(holding)] = {"n": 0, "infeasible": infeasible}
    return {
        "n_seeds": len(seeds),
        "scenarios_per_seed": int(args.scenarios),
        "shortage_cost": 2.0,
        "note": (
            "每个 seed 独立抽 conformal 场景并在另一批 held-out 场景上校准 cap；"
            "premium 的 mean/sd 用来判断单次实验的跳变是不是噪声。"
        ),
        "summary": summary,
        "records": records,
    }


def _lever_stage(
    instance,
    clean: pd.DataFrame,
    last_week,
    conformal_set,
    rows: pd.DataFrame,
    calibration: Dict[str, Any],
    args,
    unconstrained_cvar: float,
) -> Dict[str, Any]:
    """Compare inventory vs capacity vs transit on the same risk target.

    For every arm we bisect the smallest cap the model can meet. The conformal
    target is fixed, so ``cap_gap = min_cap - target_cap`` says how far the
    physical network is from the statistical target; the arm with the smallest
    gap is the lever that actually relaxes the floor.
    """
    target_cap = float(calibration["cap"])
    target_units = int(instance.fulfillment.line_qty.sum())
    upper = max(float(unconstrained_cvar) + 1.0, target_cap + 1.0)
    arms: Dict[str, Any] = {}

    # Realistic unit economics: holding must be comparable to shortage for the
    # levers to trade off at all. With 0.01 vs 4.0 the trivially optimal policy
    # is "stock everything" and the price of robustness is meaningless.
    economics = {"holding_cost": 0.3, "shortage_cost": 2.0}

    def _run(name: str, scenario_set=None, **kwargs) -> None:
        chosen = conformal_set if scenario_set is None else scenario_set
        options = {**economics, **kwargs}
        try:
            arm = _min_feasible_cap(
                instance,
                chosen,
                args,
                upper_cap=upper,
                **options,
            )
            if arm.get("min_cap") is not None:
                free = _solve_with_cap(instance, chosen, upper, args, **options)
                arm["cost_unconstrained"] = free.expected_cost
                arm["cvar_unmet_unconstrained"] = free.cvar_unmet
                # Cost of meeting the statistical target: if the network cannot
                # reach it, report the cost at the achievable floor instead.
                achieved = max(target_cap, float(arm["min_cap"]))
                constrained = _solve_with_cap(instance, chosen, achieved, args, **options)
                arm["cost_at_target"] = constrained.expected_cost
                arm["cap_achieved"] = achieved
                arm["price_of_robustness"] = (
                    constrained.expected_cost - free.expected_cost
                )
            arms[name] = arm
        except Exception as exc:  # noqa: BLE001
            arms[name] = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}

    _run("baseline")
    _run("inventory", adjustable_stock=True, max_stock_factor=3.0)
    _run("capacity", capacity_expansion_cost=0.5, max_capacity_factor=2.0)
    _run(
        "inventory_plus_capacity",
        adjustable_stock=True,
        max_stock_factor=3.0,
        capacity_expansion_cost=0.5,
        max_capacity_factor=2.0,
    )
    try:
        faster_base = build_calibrated_scenarios(
            clean,
            instance.fulfillment.sku_names,
            last_week,
            target_units,
            config=ScenarioConfig(
                method="gaussian_copula",
                n_scenarios=args.scenarios,
                lookback_weeks=6,
                seed=args.seed,
                transit_km_per_day=1400.0,
                handling_days=0,
            ),
        )
        faster_set = build_conformal_scenarios(
            rows,
            faster_base,
            n_scenarios=args.scenarios,
            seed=args.seed,
            target_units=target_units,
        )
        _run("transit", scenario_set=faster_set)
    except Exception as exc:  # noqa: BLE001
        arms["transit"] = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}

    for name, arm in arms.items():
        if arm.get("min_cap") is not None:
            arm["cap_gap"] = float(arm["min_cap"]) - target_cap

    # Price-of-robustness frontier: the cap only costs money when holding is
    # expensive relative to shortage. Sweep that ratio for the inventory lever.
    frontier: List[Dict[str, Any]] = []
    for holding in (0.05, 0.25, 1.0, 2.0, 4.0):
        options = {
            "holding_cost": holding,
            "shortage_cost": 2.0,
            "adjustable_stock": True,
            "max_stock_factor": 3.0,
        }
        try:
            free = _solve_with_cap(instance, conformal_set, upper, args, **options)
            constrained = _solve_with_cap(
                instance, conformal_set, target_cap, args, **options
            )
            frontier.append(
                {
                    "holding_cost": holding,
                    "shortage_cost": 2.0,
                    "cost_unconstrained": free.expected_cost,
                    "cost_at_target_cap": constrained.expected_cost,
                    "price_of_robustness": constrained.expected_cost - free.expected_cost,
                    "cvar_unmet_unconstrained": free.cvar_unmet,
                    "cvar_unmet_at_target": constrained.cvar_unmet,
                    "stock_units": int(np.sum(constrained.sku_stock)),
                }
            )
        except RuntimeError as exc:
            frontier.append(
                {
                    "holding_cost": holding,
                    "status": "INFEASIBLE",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    return {
        "frontier": frontier,
        "target_cap": target_cap,
        "economics": economics,
        "target_coverage": float(calibration["target_coverage"]),
        "note": (
            "min_cap 是模型实际能达到的最小 CVaR(unmet)；cap_gap>0 表示物理网络"
            "无法满足 conformal 目标，需要更多场景/更大杠杆。"
            "price_of_robustness = 满足 cap 的成本 - 无 cap 成本，单位与成本模型一致。"
        ),
        "arms": arms,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the four-layer frontier smoke benchmark")
    parser.add_argument("--out-dir", default=str(ROOT / "benchmarks/frontier"))
    parser.add_argument(
        "--predictions",
        default=str(ROOT / "benchmarks/backtest_predictions.csv"),
        help="out-of-sample backtest predictions for the conformal stage",
    )
    parser.add_argument("--orders", type=int, default=60)
    parser.add_argument("--max-lines", type=int, default=6)
    parser.add_argument("--top-skus", type=int, default=12)
    parser.add_argument("--scenarios", type=int, default=8)
    parser.add_argument("--conformal-horizon", type=int, default=13)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--milp-time", type=float, default=1.0)
    parser.add_argument("--joint-time", type=float, default=15.0)
    parser.add_argument("--causal-replicates", type=int, default=3)
    parser.add_argument("--online-repeats", type=int, default=2)
    parser.add_argument("--skip-online", action="store_true")
    parser.add_argument("--lever-seeds", type=int, default=30)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()

    if args.quick:
        args.orders = min(args.orders, 30)
        args.max_lines = min(args.max_lines, 4)
        args.scenarios = min(args.scenarios, 6)
        args.causal_replicates = min(args.causal_replicates, 2)
        # A 0.5s CP-SAT budget can return UNKNOWN under load; keep the smoke
        # benchmark noisy only in the metric, not in an unhandled exception.
        args.milp_time = max(1.0, args.milp_time)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for stale_name in ("online.json", "conformal.json"):
        stale = out / stale_name
        if stale.exists():
            stale.unlink()
    manifest: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "git_dirty": _git_dirty(),
        "script": "scripts/run_frontier_bench.py",
        "stages": [],
        "limitations": [
            "因果阶段是 SCM 合成结果，不是 UCI 观测数据的真实因果效应。",
            "Conformal 阶段只报经验覆盖率和宽度；时间序列可交换性并不严格成立。",
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

    # 2) Conformal calibration on real out-of-sample backtest rows.
    prediction_path = Path(args.predictions)
    predictions = None
    calibrator = None
    adaptive_result = None
    if prediction_path.exists():
        try:
            predictions = pd.read_csv(prediction_path)
            calibrator = fit_conformal(
                predictions,
                last_week,
                ConformalConfig(
                    alpha=0.1,
                    method="mondrian",
                    model="lightgbm",
                    horizon=args.conformal_horizon,
                    min_samples=80,
                ),
            )
            report = evaluate_conformal(predictions, calibrator, last_week)
            conformal_payload = {
                "calibrator": calibrator.as_dict(),
                "evaluation": {
                    "overall": report["overall"],
                    "by_week": report["overall"]["by_week"],
                },
                "caveat": "时间序列可交换性不严格；只报经验覆盖，不宣称无条件保证。",
            }
            try:
                adaptive_result = run_adaptive_conformal(
                    predictions,
                    AdaptiveConformalConfig(
                        alpha=0.1,
                        gamma=0.02,
                        window=52,
                        min_samples=80,
                        model="lightgbm",
                        horizon=args.conformal_horizon,
                    ),
                )
                conformal_payload["adaptive"] = adaptive_result.as_dict()
            except Exception as adaptive_exc:  # noqa: BLE001
                conformal_payload["adaptive_error"] = (
                    f"{type(adaptive_exc).__name__}: {adaptive_exc}"
                )
                manifest["conformal_adaptive_error"] = conformal_payload[
                    "adaptive_error"
                ]
            (out / "conformal.json").write_text(
                json.dumps(conformal_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            manifest["stages"].append("conformal")
            manifest["conformal"] = {
                "target_coverage": calibrator.target_coverage,
                "empirical_coverage": report["overall"]["empirical_coverage"],
                "mean_width": report["overall"]["mean_width"],
                "n_calibration": calibrator.n_calibration,
            }
            if adaptive_result is not None:
                manifest["conformal"]["adaptive_long_run_coverage"] = (
                    adaptive_result.long_run_coverage
                )
                manifest["conformal"]["adaptive_mean_width"] = (
                    adaptive_result.mean_width
                )
            print(
                "[conformal] target "
                f"{calibrator.target_coverage:.2f}; empirical "
                f"{report['overall']['empirical_coverage']:.3f}; "
                f"mean width {report['overall']['mean_width']:.1f}"
            )
            if adaptive_result is not None:
                print(
                    "[conformal-adaptive] long-run "
                    f"{adaptive_result.long_run_coverage:.3f}; "
                    f"final alpha {adaptive_result.final_alpha:.3f}; "
                    f"mean width {adaptive_result.mean_width:.1f}"
                )
        except Exception as exc:  # noqa: BLE001 - keep the rest of the smoke run
            manifest["conformal_error"] = f"{type(exc).__name__}: {exc}"
            print(f"[conformal] skipped: {exc}")
    else:
        print(f"[conformal] skipped: missing {prediction_path}")

    # 3) Real small instance.
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

    # 4) Joint optimization on conformal scenarios, when calibration exists.
    if predictions is not None and calibrator is not None:
        try:
            pred_frame = predictions.copy()
            pred_frame["week"] = pd.to_datetime(pred_frame["week"])
            selected = pred_frame.loc[
                (pred_frame["week"] == last_week)
                & (pred_frame["model"].astype(str) == "lightgbm")
                & (pred_frame["horizon"].astype(int) == args.conformal_horizon)
                & (pred_frame["sku"].astype(str).isin(instance.fulfillment.sku_names))
            ]
            by_sku = selected.drop_duplicates("sku").set_index("sku")
            adaptive_by_sku = pd.DataFrame()
            if adaptive_result is not None and not adaptive_result.final_intervals.empty:
                adaptive_by_sku = (
                    adaptive_result.final_intervals.drop_duplicates("sku")
                    .set_index("sku")
                )
            base_mean = scenario_set.demand.mean(axis=0)
            rows = []
            for sku_index, sku in enumerate(instance.fulfillment.sku_names):
                if sku in adaptive_by_sku.index:
                    raw = adaptive_by_sku.loc[sku]
                    rows.append(
                        {
                            "sku": sku,
                            "pred": float(raw["pred"]),
                            "lower": float(raw["lower"]),
                            "upper": float(raw["upper"]),
                        }
                    )
                elif sku in by_sku.index:
                    raw = by_sku.loc[sku]
                    pred = float(raw["pred"])
                    interval = calibrator.interval(
                        pred, sku=sku, scale=float(raw.get("scale", 1.0))
                    )
                    rows.append(
                        {
                            "sku": sku,
                            "pred": pred,
                            "lower": interval.lower,
                            "upper": interval.upper,
                        }
                    )
                else:
                    pred = float(base_mean[sku_index])
                    interval = calibrator.interval(pred, sku=sku, scale=1.0)
                    rows.append(
                        {
                            "sku": sku,
                            "pred": pred,
                            "lower": interval.lower,
                            "upper": interval.upper,
                        }
                    )
            conformal_set = build_conformal_scenarios(
                pd.DataFrame(rows),
                scenario_set,
                n_scenarios=args.scenarios,
                seed=args.seed,
                target_units=int(instance.fulfillment.line_qty.sum()),
            )
            conformal_plan = solve_stochastic_joint(
                instance,
                conformal_set,
                cvar_weight=0.5,
                alpha=0.8,
                time_limit_seconds=args.joint_time,
                workers=2,
            )
            # Held-out conformal scenarios for the risk cap; same forecast
            # intervals, different sampling seed.
            validation_set = build_conformal_scenarios(
                pd.DataFrame(rows),
                scenario_set,
                n_scenarios=args.scenarios,
                seed=args.seed + 100,
                target_units=int(instance.fulfillment.line_qty.sum()),
            )
            calibration = calibrate_conformal_unmet_cap(
                conformal_plan.stock,
                validation_set,
                instance.fulfillment.dc_capacity,
                target_delta=0.1,
                alpha=0.8,
                time_limit_seconds=max(5.0, args.joint_time / 2.0),
                workers=2,
            )
            risk_payload: Dict[str, Any]
            risk_plan = None
            try:
                risk_plan = solve_stochastic_joint(
                    instance,
                    conformal_set,
                    cvar_weight=0.5,
                    alpha=0.8,
                    time_limit_seconds=args.joint_time,
                    workers=2,
                    unmet_cap=calibration["cap"],
                    adjustable_stock=True,
                    max_stock_factor=3.0,
                )
                risk_payload = risk_plan.as_dict()
            except RuntimeError as exc:
                # Even with adjustable stock, a tight cap can be below the
                # minimum unmet implied by DC capacity/transit/serviceability.
                # Report infeasibility instead of silently relaxing the cap.
                risk_payload = {
                    "status": "INFEASIBLE",
                    "error": f"{type(exc).__name__}: {exc}",
                    "unmet_cap": calibration["cap"],
                }
            (out / "joint_conformal.json").write_text(
                json.dumps(
                    {
                        "unconstrained": conformal_plan.as_dict(),
                        "risk_control": risk_payload,
                        "calibration": calibration,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            manifest["stages"].append("joint_conformal")
            manifest["joint_conformal"] = {
                "unconstrained": {
                    "expected_cost": conformal_plan.expected_cost,
                    "cvar_cost": conformal_plan.cvar_cost,
                    "expected_unmet": conformal_plan.expected_unmet,
                    "status": conformal_plan.status,
                },
                "risk_control": (
                    {
                        "expected_cost": risk_plan.expected_cost,
                        "cvar_cost": risk_plan.cvar_cost,
                        "expected_unmet": risk_plan.expected_unmet,
                        "status": risk_plan.status,
                        "unmet_cap": risk_plan.unmet_cap,
                        "cap_cvar": risk_plan.cap_cvar,
                    }
                    if risk_plan is not None
                    else risk_payload
                ),
                "calibration": {
                    "cap": calibration["cap"],
                    "target_coverage": calibration["target_coverage"],
                    "empirical_coverage": calibration["empirical_coverage"],
                    "n_scenarios": calibration["n_scenarios"],
                },
            }
            if risk_plan is not None:
                print(
                    f"[joint-conformal] unconstrained cost "
                    f"{conformal_plan.expected_cost:.2f}; risk cap "
                    f"{calibration['cap']:.2f}; cost "
                    f"{risk_plan.expected_cost:.2f}, "
                    f"CVaR {risk_plan.cvar_cost:.2f}"
                )
            else:
                print(
                    f"[joint-conformal] conformal cap "
                    f"{calibration['cap']:.2f} INFEASIBLE under current "
                    f"stock/capacity/serviceability; "
                    f"unconstrained CVaR unmet {conformal_plan.cvar_unmet:.2f}"
                )
        except Exception as exc:  # noqa: BLE001 - keep the rest of the smoke run
            manifest["joint_conformal_error"] = f"{type(exc).__name__}: {exc}"
            print(f"[joint-conformal] skipped: {exc}")

        # 5) Lever comparison: which spend actually meets the same cap?
        try:
            levers = _lever_stage(
                instance,
                clean,
                last_week,
                conformal_set,
                pd.DataFrame(rows),
                calibration,
                args,
                unconstrained_cvar=conformal_plan.cvar_unmet,
            )
            (out / "levers.json").write_text(
                json.dumps(levers, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            manifest["stages"].append("levers")
            manifest["levers"] = {
                "target_cap": levers["target_cap"],
                "arms": {
                    name: {
                        "min_cap": arm.get("min_cap"),
                        "cap_gap": arm.get("cap_gap"),
                        "cap_achieved": arm.get("cap_achieved"),
                        "cost_unconstrained": arm.get("cost_unconstrained"),
                        "cost_at_target": arm.get("cost_at_target"),
                        "price_of_robustness": arm.get("price_of_robustness"),
                        "status": arm.get("status"),
                    }
                    for name, arm in levers["arms"].items()
                },
            }
            summary = ", ".join(
                (
                    f"{name}: floor={arm['min_cap']:.1f} "
                    f"+{arm['price_of_robustness']:.1f}"
                )
                if arm.get("min_cap") is not None
                else f"{name}: {arm.get('status')}"
                for name, arm in levers["arms"].items()
            )
            print(f"[levers] conformal cap {levers['target_cap']:.1f} -> {summary}")
            if args.lever_seeds > 0:
                repeated = _repeated_frontier(
                    instance,
                    pd.DataFrame(rows),
                    scenario_set,
                    int(instance.fulfillment.line_qty.sum()),
                    args,
                )
                (out / "levers_seeds.json").write_text(
                    json.dumps(repeated, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                manifest["stages"].append("levers_seeds")
                manifest["levers_seeds"] = repeated["summary"]
                parts = []
                for holding, stats in repeated["summary"].items():
                    if stats.get("n"):
                        parts.append(
                            f"h={holding}: {stats['mean_premium']:.1f}"
                            f"±{stats['sd_premium']:.1f}"
                        )
                    else:
                        parts.append(f"h={holding}: n=0")
                print(f"[levers-seeds] {repeated['n_seeds']} seeds -> " + ", ".join(parts))
        except Exception as exc:  # noqa: BLE001
            manifest["levers_error"] = f"{type(exc).__name__}: {exc}"
            print(f"[levers] skipped: {exc}")

    if not args.skip_online:
        policies = list(ROLLING_POLICIES)
        matrices = []
        rolling_payload: Dict[str, Any] = {}
        online_failed = False
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
                raise_errors=False,
            )
            errors = {
                policy: result["error"]
                for policy, result in rolling.items()
                if "error" in result
            }
            if errors:
                online_failed = True
                manifest["online_errors"] = errors
                print(f"[online] skipped: {errors}")
                break
            matrices.append(_daily_matrix(rolling, policies).T)
            rolling_payload[str(args.seed + offset)] = {
                policy: {
                    "otif_rate": float(rolling[policy]["otif_rate"]),
                    "backlog_units": int(rolling[policy]["backlog_units"]),
                }
                for policy in policies
            }
        if not online_failed:
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
                json.dumps(
                    {"online": online, "rl": rl},
                    ensure_ascii=False,
                    indent=2,
                ),
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
