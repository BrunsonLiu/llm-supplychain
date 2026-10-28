"""DC -> store allocation as a transportation LP (OR-Tools GLOP).

One period, multiple SKUs, two DCs, and a store-level receiving capacity. The
optimizer decides which DC serves which store and who absorbs a shortage.
Store demand shares and the DC cost matrix are an explicit assumption layer;
the SKU mix and total units come from the real weekly panel.

Three scenarios are compared:

* ``unconstrained`` -- unlimited DC stock and store capacity (cost-only bound).
* ``capacity``      -- real DC stock and store receiving limits, equal penalties.
* ``priority``      -- same constraints, but unmet demand at high-priority stores
  is penalised more, which pushes the shortage to low-priority stores.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
from ortools.linear_solver import pywraplp


@dataclass
class AllocationResult:
    name: str
    status: str
    shipments: np.ndarray  # (dcs, stores, skus)
    unmet: np.ndarray  # (stores, skus)
    objective: float
    transport_cost: float
    shortage_cost: float
    demand_units: float
    shipped_units: float
    unmet_units: float
    fill_rate: float
    store_fill: np.ndarray
    sku_fill: np.ndarray
    dc_utilization: np.ndarray
    solve_seconds: float


def solve_allocation(
    demand: np.ndarray,
    supply: np.ndarray,
    transport_cost: np.ndarray,
    store_capacity: Optional[np.ndarray] = None,
    priority: Optional[np.ndarray] = None,
    shortage_penalty: float = 8.0,
    name: str = "capacity",
    time_limit_seconds: float = 30.0,
) -> AllocationResult:
    """Minimise transport + shortage cost subject to supply and store capacity."""
    demand = np.asarray(demand, dtype=float)
    supply = np.asarray(supply, dtype=float)
    transport_cost = np.asarray(transport_cost, dtype=float)
    if demand.ndim != 2:
        raise ValueError("demand 必须是 (stores, skus)")
    stores, skus = demand.shape
    dcs = supply.shape[0]
    if supply.shape[1] != skus:
        raise ValueError("supply 的 SKU 维与 demand 不一致")
    if transport_cost.shape != (dcs, stores):
        raise ValueError("transport_cost 形状应为 (dcs, stores)")
    priority = (
        np.ones(stores, dtype=float)
        if priority is None
        else np.asarray(priority, dtype=float)
    )
    if priority.shape != (stores,):
        raise ValueError("priority 长度应等于门店数")
    if np.any(demand < 0) or np.any(supply < 0):
        raise ValueError("demand / supply 不能为负")
    if shortage_penalty < 0:
        raise ValueError("shortage_penalty 不能为负")

    solver = pywraplp.Solver.CreateSolver("GLOP")
    if solver is None:
        raise RuntimeError("OR-Tools GLOP 求解器不可用")
    solver.SetTimeLimit(int(time_limit_seconds * 1000))

    x: Dict[tuple[int, int, int], Any] = {}
    unmet: Dict[tuple[int, int], Any] = {}
    for d in range(dcs):
        for s in range(stores):
            for k in range(skus):
                x[d, s, k] = solver.NumVar(0.0, solver.infinity(), f"x_{d}_{s}_{k}")
    for s in range(stores):
        for k in range(skus):
            unmet[s, k] = solver.NumVar(0.0, solver.infinity(), f"u_{s}_{k}")

    for d in range(dcs):
        for k in range(skus):
            solver.Add(
                sum(x[d, s, k] for s in range(stores)) <= float(supply[d, k]),
                f"supply_{d}_{k}",
            )
    for s in range(stores):
        for k in range(skus):
            solver.Add(
                sum(x[d, s, k] for d in range(dcs)) + unmet[s, k] == float(demand[s, k]),
                f"balance_{s}_{k}",
            )
    if store_capacity is not None:
        capacity = np.asarray(store_capacity, dtype=float)
        if capacity.shape != (stores,):
            raise ValueError("store_capacity 长度应等于门店数")
        for s in range(stores):
            solver.Add(
                sum(x[d, s, k] for d in range(dcs) for k in range(skus))
                <= float(capacity[s]),
                f"capacity_{s}",
            )

    objective = solver.Objective()
    for d in range(dcs):
        for s in range(stores):
            unit_cost = float(transport_cost[d, s])
            for k in range(skus):
                objective.SetCoefficient(x[d, s, k], unit_cost)
    for s in range(stores):
        penalty = float(shortage_penalty) * float(priority[s])
        for k in range(skus):
            objective.SetCoefficient(unmet[s, k], penalty)
    objective.SetMinimization()

    started = time.perf_counter()
    status_code = solver.Solve()
    elapsed = time.perf_counter() - started
    status = {
        pywraplp.Solver.OPTIMAL: "OPTIMAL",
        pywraplp.Solver.FEASIBLE: "FEASIBLE",
        pywraplp.Solver.INFEASIBLE: "INFEASIBLE",
        pywraplp.Solver.UNBOUNDED: "UNBOUNDED",
        pywraplp.Solver.ABNORMAL: "ABNORMAL",
        pywraplp.Solver.NOT_SOLVED: "NOT_SOLVED",
    }.get(status_code, str(status_code))

    shipments = np.zeros((dcs, stores, skus))
    unmet_units = np.zeros((stores, skus))
    if status in {"OPTIMAL", "FEASIBLE"}:
        for d in range(dcs):
            for s in range(stores):
                for k in range(skus):
                    shipments[d, s, k] = x[d, s, k].solution_value()
        for s in range(stores):
            for k in range(skus):
                unmet_units[s, k] = unmet[s, k].solution_value()

    total_demand = float(demand.sum())
    total_shipped = float(shipments.sum())
    total_unmet = float(unmet_units.sum())
    transport = float((shipments.sum(axis=2) * transport_cost).sum())
    shortage = float((unmet_units * (shortage_penalty * priority[:, None])).sum())
    store_demand = demand.sum(axis=1)
    store_shipped = shipments.sum(axis=(0, 2))
    sku_demand = demand.sum(axis=0)
    sku_shipped = shipments.sum(axis=(0, 1))
    dc_utilization = np.divide(
        shipments.sum(axis=1),
        supply,
        out=np.zeros_like(supply),
        where=supply > 0,
    )

    return AllocationResult(
        name=name,
        status=status,
        shipments=shipments,
        unmet=unmet_units,
        objective=float(objective.Value()) if status in {"OPTIMAL", "FEASIBLE"} else np.nan,
        transport_cost=transport,
        shortage_cost=shortage,
        demand_units=total_demand,
        shipped_units=total_shipped,
        unmet_units=total_unmet,
        fill_rate=1.0 - total_unmet / total_demand if total_demand > 0 else 1.0,
        store_fill=np.divide(
            store_shipped,
            store_demand,
            out=np.ones_like(store_demand),
            where=store_demand > 0,
        ),
        sku_fill=np.divide(
            sku_shipped,
            sku_demand,
            out=np.ones_like(sku_demand),
            where=sku_demand > 0,
        ),
        dc_utilization=dc_utilization,
        solve_seconds=elapsed,
    )


def build_store_network(
    weekly_demand: np.ndarray,
    n_stores: int = 8,
    supply_factor: float = 0.90,
    store_capacity_factor: float = 0.95,
    seed: int = 7,
) -> Dict[str, Any]:
    """Construct a declared store network around the real SKU mix.

    Store shares follow a long-tail profile with a small random perturbation;
    DC supply covers ``supply_factor`` of each SKU's demand; store receiving
    capacity covers ``store_capacity_factor`` of that store's demand.
    """
    weekly_demand = np.asarray(weekly_demand, dtype=float).clip(min=0.0)
    if weekly_demand.ndim != 1:
        raise ValueError("weekly_demand 必须是 (skus,)")
    rng = np.random.default_rng(seed)
    base_shares = np.array([0.28, 0.19, 0.14, 0.11, 0.09, 0.07, 0.06, 0.06])
    if n_stores != len(base_shares):
        base_shares = np.linspace(0.3, 0.03, n_stores)
        base_shares = base_shares / base_shares.sum()
    jitter = rng.uniform(0.85, 1.15, size=n_stores)
    shares = base_shares * jitter
    shares = shares / shares.sum()

    demand = np.outer(shares, weekly_demand)
    total_by_sku = demand.sum(axis=0)
    first = np.array([0.60, 0.40])
    supply = np.outer(first, total_by_sku * supply_factor)
    transport = np.vstack(
        [
            np.full(n_stores, 0.10) * rng.uniform(0.8, 1.25, size=n_stores),
            np.full(n_stores, 0.17) * rng.uniform(0.8, 1.25, size=n_stores),
        ]
    )
    priority = np.where(
        np.arange(n_stores) < max(1, n_stores // 4),
        1.6,
        np.where(np.arange(n_stores) < (3 * n_stores) // 4, 1.0, 0.6),
    )
    store_capacity = demand.sum(axis=1) * store_capacity_factor

    return {
        "demand": demand,
        "supply": supply,
        "transport_cost": transport,
        "store_capacity": store_capacity,
        "priority": priority,
        "shares": shares,
        "supply_factor": supply_factor,
        "store_capacity_factor": store_capacity_factor,
    }


def allocation_scenarios(
    network: Dict[str, Any],
    shortage_penalty: float = 8.0,
    time_limit_seconds: float = 30.0,
) -> Dict[str, AllocationResult]:
    demand = network["demand"]
    supply = network["supply"]
    transport = network["transport_cost"]
    stores = demand.shape[0]
    skus = demand.shape[1]

    unconstrained_supply = np.repeat(
        demand.sum(axis=0)[np.newaxis, :], supply.shape[0], axis=0
    )
    results = {
        "unconstrained": solve_allocation(
            demand,
            unconstrained_supply,
            transport,
            store_capacity=None,
            priority=np.ones(stores),
            shortage_penalty=shortage_penalty,
            name="unconstrained",
            time_limit_seconds=time_limit_seconds,
        ),
        "capacity": solve_allocation(
            demand,
            supply,
            transport,
            store_capacity=network["store_capacity"],
            priority=np.ones(stores),
            shortage_penalty=shortage_penalty,
            name="capacity",
            time_limit_seconds=time_limit_seconds,
        ),
        "priority": solve_allocation(
            demand,
            supply,
            transport,
            store_capacity=network["store_capacity"],
            priority=network["priority"],
            shortage_penalty=shortage_penalty,
            name="priority",
            time_limit_seconds=time_limit_seconds,
        ),
    }
    return results


def allocation_summary(results: Dict[str, AllocationResult]) -> pd.DataFrame:
    rows = []
    for name, result in results.items():
        rows.append(
            {
                "scenario": name,
                "status": result.status,
                "fill_rate": result.fill_rate,
                "unmet_units": result.unmet_units,
                "transport_cost": result.transport_cost,
                "shortage_cost": result.shortage_cost,
                "total_cost": result.transport_cost + result.shortage_cost,
                "cost_per_unit": (result.transport_cost + result.shortage_cost)
                / result.shipped_units
                if result.shipped_units > 0
                else np.nan,
                "solve_seconds": result.solve_seconds,
            }
        )
    return pd.DataFrame(rows)


def store_table(result: AllocationResult) -> pd.DataFrame:
    demand = result.shipments.sum(axis=(0, 2)) + result.unmet.sum(axis=1)
    shipped = result.shipments.sum(axis=(0, 2))
    return pd.DataFrame(
        {
            "store": [f"S{index + 1}" for index in range(result.store_fill.size)],
            "demand_units": demand,
            "shipped_units": shipped,
            "unmet_units": result.unmet.sum(axis=1),
            "fill_rate": result.store_fill,
            "dc1_share": np.divide(
                result.shipments[0].sum(axis=1),
                shipped,
                out=np.zeros_like(shipped),
                where=shipped > 0,
            ),
        }
    )
