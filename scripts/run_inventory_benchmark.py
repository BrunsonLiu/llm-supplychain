"""Week 2 benchmark: demand -> forecast -> inventory policy -> MILP -> allocation.

Runs on the real Online Retail II weekly panel. The last 52 weeks are held out
for evaluation; per-SKU demand and cost parameters come from the preceding 52
weeks only. Forecasts come from the Week-1 rolling-origin backtest when that
CSV exists, otherwise from seasonal naive.

Usage:
    PYTHONPATH=src;. python scripts/run_inventory_benchmark.py
    PYTHONPATH=src;. python scripts/run_inventory_benchmark.py --sims 100 --milp-skus 10
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.data.online_retail import load_panel  # noqa: E402
from supply.inventory import (  # noqa: E402
    InventoryAssumptions,
    MilpConfig,
    PolicySpec,
    aggregate_runs,
    allocation_scenarios,
    allocation_summary,
    assumption_summary,
    build_evaluation,
    build_sku_economics,
    build_store_network,
    default_policies,
    lead_time_sensitivity,
    perfect_foresight,
    rolling_horizon,
    run_all_policies,
    run_policy,
    service_level_z,
    simulate_demand_scenarios,
    store_table,
    summarize_portfolio,
    write_inventory_report,
)


def _initial_stock(
    forecast_frame: pd.DataFrame, weeks_of_cover: float
) -> Dict[str, float]:
    """Initial stock = cover weeks x the first forecast in the window.

    Using the first forecast instead of the annual mean avoids handicapping a
    policy that starts at the Q4 peak.
    """
    return {
        str(sku): weeks_of_cover * max(float(forecast_frame[sku].iloc[0]), 0.0)
        for sku in forecast_frame.columns
    }


def _runs_for_forecast(
    evaluation,
    economics: pd.DataFrame,
    policies,
    forecast_name: str,
    lead_time: int,
    initial_by_sku: Dict[str, float],
) -> Dict[str, Dict[str, Any]]:
    runs: Dict[str, Dict[str, Any]] = {}
    forecast_frame = evaluation.forecast[forecast_name]
    for sku in evaluation.skus:
        demand = evaluation.demand[sku].to_numpy(dtype=float)[None, :]
        forecast = forecast_frame[sku].to_numpy(dtype=float)
        runs[sku] = run_all_policies(
            demand,
            forecast,
            economics.loc[sku],
            policies,
            lead_time,
            initial_inventory=initial_by_sku[sku],
        )
    return runs


def _mc_runs(
    evaluation,
    economics: pd.DataFrame,
    policies,
    forecast_name: str,
    lead_time: int,
    simulations: int,
    seed: int,
    initial_by_sku: Dict[str, float],
) -> tuple[Dict[str, Dict[str, Any]], Dict[str, np.ndarray]]:
    runs: Dict[str, Dict[str, Any]] = {}
    scenarios_by_sku: Dict[str, np.ndarray] = {}
    forecast_frame = evaluation.forecast[forecast_name]
    for index, sku in enumerate(evaluation.skus):
        forecast = forecast_frame[sku].to_numpy(dtype=float)
        econ = economics.loc[sku]
        scenarios = simulate_demand_scenarios(
            forecast, econ, simulations, seed + index
        )
        scenarios_by_sku[sku] = scenarios
        runs[sku] = run_all_policies(
            scenarios,
            forecast,
            econ,
            policies,
            lead_time,
            initial_inventory=initial_by_sku[sku],
        )
    return runs, scenarios_by_sku


def _portfolio_row(
    scenarios: pd.DataFrame, policy: PolicySpec, forecast_name: str
) -> Dict[str, Any]:
    summary = summarize_portfolio(scenarios, policy)
    summary["forecast"] = forecast_name
    return summary


def _detail_frame(runs_by_sku: Dict[str, Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for sku, runs in runs_by_sku.items():
        for kind, run in runs.items():
            row = {"sku": sku, "policy": kind, "label": run.policy.label}
            row.update(run.summary)
            rows.append(row)
    return pd.DataFrame(rows)


def _milp_comparison(
    evaluation,
    economics: pd.DataFrame,
    policies,
    forecast_name: str,
    lead_time: int,
    weeks: int,
    n_skus: int,
    time_limit: float,
    workers: int,
    initial_cover_weeks: float,
    deterministic_time: float | None = None,
) -> Dict[str, Any]:
    demand_window = evaluation.demand.iloc[-weeks:]
    forecast_window = evaluation.forecast[forecast_name].iloc[-weeks:]
    initial_by_sku = _initial_stock(forecast_window, initial_cover_weeks)
    chosen = (
        economics.sort_values("mean_weekly", ascending=False)
        .head(n_skus)
        .index.tolist()
    )
    actual = demand_window[chosen].to_numpy(dtype=float).T
    forecast = forecast_window[chosen].to_numpy(dtype=float).T
    econ = economics.loc[chosen].copy()
    initial = np.array([initial_by_sku[sku] for sku in chosen], dtype=float)

    window_mean_total = float(actual.sum() / weeks)
    storage = max(5.0 * window_mean_total, 1.2 * float(initial.sum()))
    throughput = 3.0 * window_mean_total
    config = MilpConfig(
        horizon_weeks=weeks,
        lead_time_weeks=lead_time,
        time_limit_seconds=time_limit,
        deterministic_time=deterministic_time,
        workers=workers,
    )

    perfect = perfect_foresight(
        actual,
        econ,
        config,
        storage_capacity=storage,
        throughput_capacity=throughput,
        initial_inventory=initial,
    )
    rolling = rolling_horizon(
        actual,
        forecast,
        econ,
        config,
        storage_capacity=storage,
        throughput_capacity=throughput,
        initial_inventory=initial,
    )

    rows: List[Dict[str, Any]] = []
    for policy in policies:
        runs = {}
        for index, sku in enumerate(chosen):
            runs[sku] = {
                policy.kind: run_policy(
                    actual[index][None, :],
                    forecast[index],
                    econ.loc[sku],
                    policy,
                    lead_time,
                    initial_inventory=initial_by_sku[sku],
                )
            }
        portfolio = aggregate_runs(runs, economics, policy.kind, weeks)
        rows.append(
            {
                "method": f"policy: {policy.label}",
                "fill_rate": float(portfolio["fill_rate"].iloc[0]),
                "total_cost": float(portfolio["total_cost"].iloc[0]),
                "cost_per_unit": float(portfolio["cost_per_unit"].iloc[0]),
                "turns": float(portfolio["turns"].iloc[0]),
                "fixed_orders": float(portfolio["orders"].iloc[0]),
                "solve_seconds": 0.0,
            }
        )

    rows.append(
        {
            "method": "MILP: rolling horizon",
            "fill_rate": float(rolling["fill_rate"]),
            "total_cost": float(rolling["total_cost"]),
            "cost_per_unit": float(rolling["cost_per_unit"]),
            "turns": float(rolling["turns"]),
            "fixed_orders": float(rolling["fixed_orders"]),
            "solve_seconds": float(rolling["solve_seconds"]),
        }
    )
    rows.append(
        {
            "method": "MILP: perfect foresight",
            "fill_rate": float(perfect["fill_rate"]),
            "total_cost": float(perfect["total_cost"]),
            "cost_per_unit": float(perfect["cost_per_unit"]),
            "turns": float(perfect["turns"]),
            "fixed_orders": float(perfect["fixed_orders"]),
            "solve_seconds": float(perfect["plan"].solve_seconds),
        }
    )

    return {
        "config": {
            "horizon_weeks": weeks,
            "lead_time_weeks": lead_time,
            "time_limit_seconds": time_limit,
            "deterministic_time": deterministic_time,
        },
        "skus": len(chosen),
        "weeks": weeks,
        "window_start": str(demand_window.index[0].date()),
        "window_end": str(demand_window.index[-1].date()),
        "lead_time_weeks": lead_time,
        "storage_capacity": storage,
        "throughput_capacity": throughput,
        "utilization": {
            "rolling_storage_peak": float(rolling["inventory"].sum(axis=0).max()) / storage,
            "rolling_throughput_peak": float(rolling["orders"].sum(axis=0).max()) / throughput,
            "perfect_storage_peak": float(perfect["inventory"].sum(axis=0).max()) / storage,
            "perfect_throughput_peak": float(perfect["orders"].sum(axis=0).max()) / throughput,
        },
        "comparison": pd.DataFrame(rows),
        "statuses": rolling["statuses"],
        "rolling_seconds": rolling["solve_seconds"],
        "rolling_fill": rolling["fill_rate"],
        "perfect_fill": perfect["fill_rate"],
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Week 2 inventory benchmark")
    parser.add_argument(
        "--panel", default=str(ROOT / "data/processed/online_retail_ii_weekly.parquet")
    )
    parser.add_argument(
        "--meta", default=str(ROOT / "data/processed/online_retail_ii_weekly.meta.json")
    )
    parser.add_argument(
        "--backtest", default=str(ROOT / "benchmarks/backtest_predictions.csv")
    )
    parser.add_argument("--out-dir", default=str(ROOT / "benchmarks"))
    parser.add_argument("--eval-weeks", type=int, default=52)
    parser.add_argument("--history-weeks", type=int, default=52)
    parser.add_argument("--forecast", choices=["auto", "lightgbm", "seasonal_naive"], default="auto")
    parser.add_argument("--service-level", type=float, default=0.95)
    parser.add_argument("--lead-time", type=int, default=3)
    parser.add_argument("--review-period", type=int, default=2)
    parser.add_argument("--min-history-nonzero", type=int, default=13)
    parser.add_argument("--sims", type=int, default=300)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--milp-skus", type=int, default=20)
    parser.add_argument("--milp-weeks", type=int, default=13)
    parser.add_argument("--milp-time-limit", type=float, default=10.0)
    parser.add_argument(
        "--milp-deterministic-time",
        type=float,
        default=10.0,
        help="CP-SAT deterministic-time budget per solve; makes results reproducible",
    )
    parser.add_argument("--milp-workers", type=int, default=1)
    parser.add_argument("--skip-milp", action="store_true")
    parser.add_argument("--skip-allocation", action="store_true")
    parser.add_argument("--title", default="Inventory policy benchmark (Week 2)")
    args = parser.parse_args()

    panel, meta = load_panel(args.panel, args.meta)
    panel["sku"] = panel["sku"].astype(str)
    assumptions = InventoryAssumptions(
        service_level=args.service_level,
        lead_time_weeks=args.lead_time,
        review_period_weeks=args.review_period,
        n_simulations=args.sims,
        random_seed=args.seed,
    )
    assumptions.validate()

    evaluation = build_evaluation(
        panel,
        eval_weeks=args.eval_weeks,
        history_weeks=args.history_weeks,
        backtest_path=args.backtest,
    )
    forecast_name = args.forecast
    if forecast_name == "auto":
        forecast_name = "lightgbm" if "lightgbm" in evaluation.forecast else "seasonal_naive"
    if forecast_name not in evaluation.forecast:
        forecast_name = "seasonal_naive"

    economics = build_sku_economics(evaluation.history, assumptions)
    economics["sku"] = economics["sku"].astype(str)
    economics = economics.set_index("sku")
    eligible = economics[
        (economics["nonzero_weeks"] >= args.min_history_nonzero)
        & (economics["mean_weekly"] >= 1.0)
    ].index.tolist()
    excluded = len(set(evaluation.skus) - set(eligible))
    evaluation = evaluation.restrict(eligible)
    economics = economics.loc[eligible]
    if not evaluation.skus:
        raise RuntimeError("没有 SKU 同时满足历史非零周数与最小需求，请放宽筛选")
    initial_by_sku = _initial_stock(
        evaluation.forecast[forecast_name], assumptions.initial_inventory_weeks
    )
    policies = default_policies(
        assumptions.service_level, assumptions.review_period_weeks
    )

    print("=" * 72)
    print(args.title)
    print("=" * 72)
    print(
        f"SKUs {len(evaluation.skus)} | excluded {excluded} without enough history | "
        f"eval {evaluation.weeks[0].date()} -> {evaluation.weeks[-1].date()} | "
        f"forecast {forecast_name} | lead time {args.lead_time}w | "
        f"SL {args.service_level:.0%}"
    )

    accuracy = evaluation.forecast_accuracy()
    print("\nForecast accuracy in the evaluation window:")
    print(accuracy.to_string(index=False))

    replay_runs = _runs_for_forecast(
        evaluation,
        economics,
        policies,
        forecast_name,
        args.lead_time,
        initial_by_sku,
    )
    replay_rows = []
    for policy in policies:
        portfolio = aggregate_runs(
            replay_runs, economics, policy.kind, len(evaluation.weeks)
        )
        row = _portfolio_row(portfolio, policy, forecast_name)
        row["policy"] = policy.kind
        replay_rows.append(row)
    replay_table = pd.DataFrame(replay_rows)
    print(f"\nPolicy replay ({len(evaluation.weeks)} weeks of realized demand):")
    print(
        replay_table[
            [
                "label",
                "fill_rate",
                "sku_week_instock_rate",
                "stockout_week_rate",
                "avg_on_hand",
                "turns",
                "total_cost",
                "cost_per_unit",
            ]
        ].to_string(index=False)
    )

    mc_runs, scenarios_by_sku = _mc_runs(
        evaluation,
        economics,
        policies,
        forecast_name,
        args.lead_time,
        args.sims,
        args.seed,
        initial_by_sku,
    )
    mc_rows = []
    for policy in policies:
        portfolio = aggregate_runs(
            mc_runs, economics, policy.kind, len(evaluation.weeks)
        )
        row = _portfolio_row(portfolio, policy, forecast_name)
        row["policy"] = policy.kind
        mc_rows.append(row)
    mc_table = pd.DataFrame(mc_rows)
    print(f"\nMonte Carlo ({args.sims} scenarios per SKU):")
    print(
        mc_table[
            [
                "label",
                "fill_rate",
                "fill_rate_p5",
                "fill_rate_p95",
                "total_cost_p50",
                "total_cost_p95",
            ]
        ].to_string(index=False)
    )

    forecast_rows = []
    for name in evaluation.forecast:
        initial_for_forecast = _initial_stock(
            evaluation.forecast[name], assumptions.initial_inventory_weeks
        )
        runs = _runs_for_forecast(
            evaluation,
            economics,
            [PolicySpec("min_max", assumptions.service_level)],
            name,
            args.lead_time,
            initial_for_forecast,
        )
        portfolio = aggregate_runs(
            runs, economics, "min_max", len(evaluation.weeks)
        )
        summary = summarize_portfolio(
            portfolio, PolicySpec("min_max", assumptions.service_level)
        )
        summary["forecast"] = name
        forecast_rows.append(summary)
    forecast_comparison = pd.DataFrame(forecast_rows)

    service_levels = [0.80, 0.85, 0.90, 0.95, 0.975, 0.99]
    sweep_rows = []
    for level in service_levels:
        policy = PolicySpec("eoq_rop", level)
        runs = {
            sku: {
                "eoq_rop": run_policy(
                    scenarios_by_sku[sku],
                    evaluation.forecast[forecast_name][sku].to_numpy(dtype=float),
                    economics.loc[sku],
                    policy,
                    args.lead_time,
                    initial_inventory=initial_by_sku[sku],
                )
            }
            for sku in evaluation.skus
        }
        portfolio = aggregate_runs(runs, economics, "eoq_rop", len(evaluation.weeks))
        row = summarize_portfolio(portfolio, policy)
        row["policy"] = "eoq_rop"
        row["z"] = service_level_z(level)
        sweep_rows.append(row)
    sweep_table = pd.DataFrame(sweep_rows)

    lead_rows = []
    for lead in (2, 3, 4, 6):
        runs = _runs_for_forecast(
            evaluation, economics, policies, forecast_name, lead, initial_by_sku
        )
        for policy in policies:
            portfolio = aggregate_runs(
                runs, economics, policy.kind, len(evaluation.weeks)
            )
            row = summarize_portfolio(portfolio, policy)
            row["policy"] = policy.kind
            row["lead_time_weeks"] = lead
            lead_rows.append(row)
    lead_table = pd.DataFrame(lead_rows)

    milp_results: Dict[str, Any] = {}
    if not args.skip_milp:
        print("\nSolving MILP...")
        milp_results = _milp_comparison(
            evaluation,
            economics,
            policies,
            forecast_name,
            args.lead_time,
            args.milp_weeks,
            args.milp_skus,
            args.milp_time_limit,
            args.milp_workers,
            assumptions.initial_inventory_weeks,
            deterministic_time=args.milp_deterministic_time,
        )
        print(milp_results["comparison"].to_string(index=False))
        print(
            f"rolling statuses {milp_results['statuses']} | "
            f"MILP time {milp_results['rolling_seconds']:.2f}s"
        )

    allocation_results: Dict[str, Any] = {}
    if not args.skip_allocation:
        weekly = evaluation.demand.mean(axis=0)
        network = build_store_network(weekly.to_numpy(dtype=float))
        results = allocation_scenarios(network, shortage_penalty=8.0)
        allocation_results = {
            "summary": allocation_summary(results),
            "stores": store_table(results["priority"]),
            "config": {
                "stores": network["demand"].shape[0],
                "skus": network["demand"].shape[1],
                "supply_factor": network["supply_factor"],
                "store_capacity_factor": network["store_capacity_factor"],
            },
        }
        print("\nDC -> store allocation (representative week):")
        print(allocation_results["summary"].to_string(index=False))

    history = evaluation.history
    dataset = {
        "skus": len(evaluation.skus),
        "skus_excluded_insufficient_history": excluded,
        "min_history_nonzero_weeks": args.min_history_nonzero,
        "eval_start": str(evaluation.weeks[0].date()),
        "eval_end": str(evaluation.weeks[-1].date()),
        "eval_weeks": int(len(evaluation.weeks)),
        "history_start": str(pd.to_datetime(history["week"]).min().date()),
        "history_end": str(pd.to_datetime(history["week"]).max().date()),
        "history_weeks": int(evaluation.history_weeks),
        "primary_forecast": forecast_name,
        "forecast_wmape": float(
            accuracy.loc[accuracy["forecast"] == forecast_name, "wmape"].iloc[0]
        ),
        "total_demand_units": float(evaluation.demand.to_numpy().sum()),
    }

    assumption_rows = [
        {"parameter": "evaluation weeks", "value": str(len(evaluation.weeks)), "source": "observed"},
        {"parameter": "SKUs (ABC top-N by revenue)", "value": str(len(evaluation.skus)), "source": "observed"},
        {"parameter": "weekly demand / price", "value": "panel", "source": "observed"},
        {
            "parameter": "lead time",
            "value": f"{assumptions.lead_time_weeks} weeks",
            "source": "assumed",
            "note": "not in Online Retail II; sensitivity 2/4/6 weeks reported",
        },
        {
            "parameter": "target cycle service level",
            "value": f"{assumptions.service_level:.0%}",
            "source": "assumed",
            "note": "business input; cost-service frontier reported",
        },
        {
            "parameter": "holding cost",
            "value": f"{assumptions.holding_rate_annual:.0%}/yr of unit cost",
            "source": "assumed",
        },
        {
            "parameter": "order cost",
            "value": f"{assumptions.ordering_cost:.0f} per order",
            "source": "assumed",
        },
        {
            "parameter": "unit cost",
            "value": f"{assumptions.cost_ratio:.0%} of price",
            "source": "assumed",
            "note": "implies a 40% gross margin",
        },
        {
            "parameter": "shortage cost",
            "value": "lost margin × multiplier",
            "source": "assumed",
            "note": f"multiplier {assumptions.lost_margin_multiplier:.1f}",
        },
        {
            "parameter": "initial inventory",
            "value": f"{assumptions.initial_inventory_weeks:.0f} weeks of demand",
            "source": "assumed",
        },
        {
            "parameter": "MOQ",
            "value": f"{assumptions.min_order_weeks:.1f} week of demand, min 1 unit",
            "source": "assumed",
        },
        {
            "parameter": "review period",
            "value": f"{assumptions.review_period_weeks} weeks",
            "source": "assumed",
        },
        {
            "parameter": "Monte Carlo",
            "value": f"{assumptions.n_simulations} scenarios, seed {assumptions.random_seed}",
            "source": "method",
        },
    ]

    results = {
        "dataset": dataset,
        "assumptions": assumptions.to_dict(),
        "assumption_summary": assumption_summary(economics.reset_index(), assumptions),
        "assumption_rows": assumption_rows,
        "forecast_accuracy": accuracy,
        "policy_replay": replay_table,
        "policy_mc": mc_table,
        "forecast_comparison": forecast_comparison,
        "service_sweep": sweep_table,
        "lead_time": lead_table,
        "milp": milp_results,
        "allocation": allocation_results,
    }

    paths = write_inventory_report(
        results,
        args.out_dir,
        title=args.title,
        detail=_detail_frame(replay_runs),
    )
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
