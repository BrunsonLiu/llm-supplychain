"""Compare transportation LP/MIP solvers and extract dual/shadow prices.

This is the JD-oriented solver benchmark:

* LP: OR-Tools GLOP vs Gurobi (when a license is available);
* MIP: OR-Tools SCIP vs Gurobi fixed-charge activation;
* SQL: panel summary via DuckDB, then a real E2E instance.

The model is a transportation relaxation, not the full fulfillment MILP.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.data import (  # noqa: E402
    DemandWarehouse,
    clean_transactions,
    load_online_retail_raw,
)
from supply.e2e import build_e2e_instance  # noqa: E402
from supply.network.transport import (  # noqa: E402
    TransportSolverError,
    instance_from_e2e,
    solve_transport_lp,
    solve_transport_mip,
)


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="Transport LP/MIP solver benchmark")
    parser.add_argument("--panel", default=str(ROOT / "data/processed/online_retail_ii_weekly.parquet"))
    parser.add_argument("--raw", default=str(ROOT / "data/raw/online_retail_II.xlsx"))
    parser.add_argument("--cache", default=str(ROOT / "data/raw/online_retail_II.raw.parquet"))
    parser.add_argument("--orders", type=int, default=80)
    parser.add_argument("--max-lines", type=int, default=8)
    parser.add_argument("--top-skus", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--milp-time", type=float, default=20.0)
    parser.add_argument("--out-dir", default=str(ROOT / "benchmarks/solver"))
    args = parser.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "model": "transportation relaxation",
        "limitations": [
            "运输松弛，不是完整履约 MILP。",
            "dual 只在 LP 有；MIP 不报 dual。",
            "Gurobi 不可用/无许可证时自动跳过，不伪造结果。",
        ],
    }

    with DemandWarehouse(args.panel) as warehouse:
        top = warehouse.top_skus(args.top_skus)
        weekly = warehouse.weekly_demand()
        payload["sql"] = {
            "panel": str(args.panel),
            "weeks": int(len(weekly)),
            "top_skus": top["sku"].astype(str).tolist(),
            "weekly_demand_mean": float(weekly["demand"].mean()),
        }
        skus = top["sku"].astype(str).tolist()

    raw = load_online_retail_raw(args.raw, cache_path=args.cache)
    clean, stats = clean_transactions(raw)
    clean["sku"] = clean["sku"].astype(str)
    last_week = pd.to_datetime(weekly["week"]).max()
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
    transport = instance_from_e2e(instance, fixed_cost=1000.0)
    payload["instance"] = {
        "orders": int(instance.n_orders),
        "dcs": int(transport.supply.size),
        "demand_units": float(transport.demand.sum()),
        "supply_units": float(transport.supply.sum()),
        "shortage_penalty": float(transport.shortage_penalty),
        "clean_rows": int(stats["clean_rows"]),
    }

    solvers: Dict[str, Any] = {}
    for solver in ("glop", "gurobi"):
        try:
            result = solve_transport_lp(transport, solver=solver)
            solvers[solver] = result.as_dict()
            print(
                f"[LP/{solver}] obj {result.objective:.2f} "
                f"time {result.solve_seconds:.3f}s "
                f"demand dual range [{result.demand_duals.min():.2f}, "
                f"{result.demand_duals.max():.2f}]"
            )
        except TransportSolverError as exc:
            solvers[solver] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"[LP/{solver}] skipped: {exc}")

    for solver in ("scip", "gurobi"):
        try:
            result = solve_transport_mip(
                transport,
                solver=solver,
                time_limit_seconds=args.milp_time,
            )
            solvers[f"mip_{solver}"] = result.as_dict()
            print(
                f"[MIP/{solver}] obj {result.objective:.2f} "
                f"open {result.open_dcs} time {result.solve_seconds:.3f}s"
            )
        except TransportSolverError as exc:
            solvers[f"mip_{solver}"] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"[MIP/{solver}] skipped: {exc}")

    payload["solvers"] = solvers
    (out / "solver_benchmark.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {out / 'solver_benchmark.json'}")


if __name__ == "__main__":
    main()
