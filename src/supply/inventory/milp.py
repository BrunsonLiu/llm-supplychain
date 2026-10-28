"""Multi-period replenishment MILP with OR-Tools CP-SAT.

The model decides orders per SKU and week under a shared storage and inbound
throughput capacity. It is a small lot-sizing model with lost sales:

    I[i,t] = I[i,t-1] + q[i,t-L] - d[i,t] + u[i,t]
    q[i,t] >= MOQ[i] * y[i,t],  q[i,t] <= M[i] * y[i,t]
    sum_i I[i,t] <= storage,    sum_i q[i,t] <= throughput

Objective: holding + fixed ordering + shortage penalty. An optional terminal
inventory floor can be enabled for studies that need end-of-horizon coverage.

Two modes are provided:

* **perfect foresight** -- one solve on realized demand (an upper bound).
* **rolling horizon** -- re-plan every week with the forecast, execute only the
  first-period decision, then observe real demand. This is the realistic
  comparison against rule-based policies.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
from ortools.sat.python import cp_model

COST_SCALE = 10_000  # objective resolution: 0.0001 currency units


@dataclass(frozen=True)
class MilpConfig:
    horizon_weeks: int = 13
    lead_time_weeks: int = 3
    time_limit_seconds: float = 10.0
    # Wall-clock limits change CP-SAT's restart schedule, so the same limit can
    # return different plans on a loaded machine. A deterministic-time budget
    # makes benchmark runs reproducible.
    deterministic_time: Optional[float] = None
    # One worker keeps CP-SAT deterministic; parallel search can return a
    # different cost-equivalent plan on every run.
    workers: int = 1

    def validate(self) -> None:
        if self.horizon_weeks <= 0:
            raise ValueError("horizon_weeks 必须为正")
        if self.lead_time_weeks < 0:
            raise ValueError("lead_time_weeks 不能为负")
        if self.time_limit_seconds <= 0:
            raise ValueError("time_limit_seconds 必须为正")
        if self.deterministic_time is not None and self.deterministic_time <= 0:
            raise ValueError("deterministic_time 必须为正")


@dataclass
class ReplenishmentPlan:
    status: str
    orders: np.ndarray
    inventory: np.ndarray
    unmet: np.ndarray
    objective: float
    best_bound: float
    solve_seconds: float
    holding_cost: float
    ordering_cost: float
    stockout_cost: float
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_cost(self) -> float:
        return self.holding_cost + self.ordering_cost + self.stockout_cost


def _scaled(value: float, minimum: int = 1) -> int:
    return max(minimum, int(round(float(value) * COST_SCALE)))


def solve_replenishment(
    demand: np.ndarray,
    economics: pd.DataFrame,
    config: MilpConfig,
    initial_inventory: Optional[np.ndarray] = None,
    initial_pipeline: Optional[np.ndarray] = None,
    storage_capacity: Optional[float] = None,
    throughput_capacity: Optional[float] = None,
    terminal_inventory: Optional[np.ndarray] = None,
) -> ReplenishmentPlan:
    """Solve one multi-SKU lot-sizing instance.

    ``demand`` is ``(n_skus, n_weeks)`` in units. ``initial_pipeline[i, k]`` is
    the quantity arriving in week ``k`` (``k < lead_time``). ``terminal_inventory``
    is a per-SKU end-of-horizon floor, typically the safety stock.
    """
    config.validate()
    demand = np.asarray(demand, dtype=float)
    if demand.ndim != 2 or demand.shape[1] == 0:
        raise ValueError("demand 必须是 (n_skus, n_weeks) 的二维非空数组")
    n_skus, n_weeks = demand.shape
    if len(economics) != n_skus:
        raise ValueError(f"economics 有 {len(economics)} 行，与 {n_skus} 个 SKU 不匹配")

    units = np.rint(demand).astype(np.int64)
    units = np.clip(units, 0, None)
    lead = int(config.lead_time_weeks)

    holding = economics["holding_cost_per_unit_week"].to_numpy(dtype=float)
    order_cost = economics["ordering_cost"].to_numpy(dtype=float)
    shortage = economics["stockout_cost_per_unit"].to_numpy(dtype=float)
    moq = np.ceil(economics["moq"].to_numpy(dtype=float)).astype(np.int64)
    moq = np.clip(moq, 1, None)

    init = (
        np.rint(initial_inventory).astype(np.int64)
        if initial_inventory is not None
        else np.rint(economics["initial_inventory"].to_numpy(dtype=float)).astype(np.int64)
    )
    init = np.clip(init, 0, None)
    pipeline = (
        np.asarray(initial_pipeline, dtype=np.int64)
        if initial_pipeline is not None
        else np.zeros((n_skus, lead), dtype=np.int64)
    )
    if pipeline.shape != (n_skus, lead):
        raise ValueError(f"initial_pipeline 形状应为 {(n_skus, lead)}")
    terminal = (
        np.ceil(terminal_inventory).astype(np.int64)
        if terminal_inventory is not None
        else np.zeros(n_skus, dtype=np.int64)
    )
    terminal = np.clip(terminal, 0, None)

    model = cp_model.CpModel()
    q: Dict[tuple[int, int], Any] = {}
    y: Dict[tuple[int, int], Any] = {}
    inv: Dict[tuple[int, int], Any] = {}
    unmet: Dict[tuple[int, int], Any] = {}

    for i in range(n_skus):
        upper = int(units[i].sum() + init[i] + terminal[i] + moq[i] + 1)
        for t in range(n_weeks):
            q[i, t] = model.NewIntVar(0, upper, f"q_{i}_{t}")
            y[i, t] = model.NewBoolVar(f"y_{i}_{t}")
            inv[i, t] = model.NewIntVar(0, upper, f"I_{i}_{t}")
            unmet[i, t] = model.NewIntVar(0, int(units[i, t]) + 1, f"u_{i}_{t}")

            model.Add(q[i, t] >= int(moq[i]) * y[i, t])
            model.Add(q[i, t] <= upper * y[i, t])

            previous = int(init[i]) if t == 0 else inv[i, t - 1]
            if t < lead:
                receipt = int(pipeline[i, t])
                model.Add(inv[i, t] == previous + receipt - int(units[i, t]) + unmet[i, t])
            else:
                model.Add(
                    inv[i, t] == previous + q[i, t - lead] - int(units[i, t]) + unmet[i, t]
                )

        if terminal[i] > 0:
            model.Add(inv[i, n_weeks - 1] >= int(terminal[i]))

    if storage_capacity is not None:
        limit = int(np.floor(storage_capacity))
        for t in range(n_weeks):
            model.Add(sum(inv[i, t] for i in range(n_skus)) <= limit)
    if throughput_capacity is not None:
        limit = int(np.floor(throughput_capacity))
        for t in range(n_weeks):
            model.Add(sum(q[i, t] for i in range(n_skus)) <= limit)

    objective = []
    for i in range(n_skus):
        h_cost = _scaled(holding[i])
        k_cost = _scaled(order_cost[i])
        p_cost = _scaled(shortage[i])
        for t in range(n_weeks):
            objective.append(h_cost * inv[i, t])
            objective.append(k_cost * y[i, t])
            objective.append(p_cost * unmet[i, t])
    model.Minimize(sum(objective))

    solver = cp_model.CpSolver()
    if config.deterministic_time is not None:
        solver.parameters.max_deterministic_time = float(config.deterministic_time)
    else:
        solver.parameters.max_time_in_seconds = float(config.time_limit_seconds)
    solver.parameters.num_search_workers = int(config.workers)
    solver.parameters.random_seed = 0
    solver.parameters.log_search_progress = False
    started = time.perf_counter()
    status_code = solver.Solve(model)
    elapsed = time.perf_counter() - started
    status = solver.StatusName(status_code)

    if status not in {"OPTIMAL", "FEASIBLE"}:
        zeros = np.zeros((n_skus, n_weeks))
        return ReplenishmentPlan(
            status=status,
            orders=zeros,
            inventory=zeros.copy(),
            unmet=zeros.copy(),
            objective=float("nan"),
            best_bound=float("nan"),
            solve_seconds=elapsed,
            holding_cost=float("nan"),
            ordering_cost=float("nan"),
            stockout_cost=float("nan"),
            diagnostics={"sku_rows": n_skus, "weeks": n_weeks, "lead_time": lead},
        )

    orders = np.array(
        [[solver.Value(q[i, t]) for t in range(n_weeks)] for i in range(n_skus)],
        dtype=float,
    )
    inventory = np.array(
        [[solver.Value(inv[i, t]) for t in range(n_weeks)] for i in range(n_skus)],
        dtype=float,
    )
    shortage_units = np.array(
        [[solver.Value(unmet[i, t]) for t in range(n_weeks)] for i in range(n_skus)],
        dtype=float,
    )
    holding_cost = float((inventory * holding[:, None]).sum())
    ordering_cost = float(((orders > 0) * order_cost[:, None]).sum())
    stockout_cost = float((shortage_units * shortage[:, None]).sum())

    return ReplenishmentPlan(
        status=status,
        orders=orders,
        inventory=inventory,
        unmet=shortage_units,
        objective=float(solver.ObjectiveValue()) / COST_SCALE,
        best_bound=float(solver.BestObjectiveBound()) / COST_SCALE,
        solve_seconds=elapsed,
        holding_cost=holding_cost,
        ordering_cost=ordering_cost,
        stockout_cost=stockout_cost,
        diagnostics={
            "sku_rows": n_skus,
            "weeks": n_weeks,
            "lead_time": lead,
            "fixed_orders": int((orders > 0).sum()),
            "storage_capacity": storage_capacity,
            "throughput_capacity": throughput_capacity,
        },
    )


def execute_orders(
    orders: np.ndarray,
    actual_demand: np.ndarray,
    economics: pd.DataFrame,
    initial_inventory: Optional[np.ndarray] = None,
    lead_time_weeks: int = 3,
) -> Dict[str, Any]:
    """Run a given order matrix against realized demand and score it."""
    orders = np.atleast_2d(np.asarray(orders, dtype=float))
    actual = np.atleast_2d(np.asarray(actual_demand, dtype=float))
    if orders.shape != actual.shape:
        raise ValueError("orders 与 actual_demand 形状必须一致")
    n_skus, weeks = actual.shape
    lead = max(int(lead_time_weeks), 0)
    init = (
        np.asarray(initial_inventory, dtype=float)
        if initial_inventory is not None
        else economics["initial_inventory"].to_numpy(dtype=float)
    )

    on_hand = init.astype(float).copy()
    arrivals = np.zeros((n_skus, weeks + lead + 1))
    inventory = np.zeros((n_skus, weeks))
    lost = np.zeros((n_skus, weeks))
    sales = np.zeros((n_skus, weeks))

    for t in range(weeks):
        on_hand += arrivals[:, t]
        if lead == 0:
            on_hand += orders[:, t]
        else:
            arrivals[:, t + lead] += orders[:, t]
        served = np.minimum(np.maximum(on_hand, 0.0), actual[:, t])
        sales[:, t] = served
        lost[:, t] = actual[:, t] - served
        on_hand = np.maximum(on_hand - served, 0.0)
        inventory[:, t] = on_hand

    holding = economics["holding_cost_per_unit_week"].to_numpy(dtype=float)
    order_cost = economics["ordering_cost"].to_numpy(dtype=float)
    shortage = economics["stockout_cost_per_unit"].to_numpy(dtype=float)

    demand_units = float(actual.sum())
    lost_units = float(lost.sum())
    sold_units = float(sales.sum())
    # Portfolio units per week, matching sold_units; inventory.mean() is per SKU.
    avg_on_hand = float(inventory.sum(axis=0).mean())
    holding_cost = float((inventory * holding[:, None]).sum())
    ordering_cost = float(((orders > 0) * order_cost[:, None]).sum())
    stockout_cost = float((lost * shortage[:, None]).sum())

    return {
        "orders": orders,
        "inventory": inventory,
        "lost": lost,
        "sales": sales,
        "demand_units": demand_units,
        "sold_units": sold_units,
        "lost_units": lost_units,
        "fill_rate": 1.0 - lost_units / demand_units if demand_units > 0 else 1.0,
        "avg_on_hand": avg_on_hand,
        "turns": sold_units / avg_on_hand * (52.0 / weeks) if avg_on_hand > 0 else np.nan,
        "fixed_orders": int((orders > 0).sum()),
        "holding_cost": holding_cost,
        "ordering_cost": ordering_cost,
        "stockout_cost": stockout_cost,
        "total_cost": holding_cost + ordering_cost + stockout_cost,
        "cost_per_unit": (holding_cost + ordering_cost + stockout_cost) / sold_units
        if sold_units > 0
        else np.nan,
    }


def perfect_foresight(
    actual_demand: np.ndarray,
    economics: pd.DataFrame,
    config: MilpConfig,
    storage_capacity: Optional[float] = None,
    throughput_capacity: Optional[float] = None,
    terminal_inventory: Optional[np.ndarray] = None,
    initial_inventory: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    plan = solve_replenishment(
        actual_demand,
        economics,
        config,
        initial_inventory=initial_inventory,
        storage_capacity=storage_capacity,
        throughput_capacity=throughput_capacity,
        terminal_inventory=terminal_inventory,
    )
    metrics = execute_orders(
        plan.orders,
        actual_demand,
        economics,
        initial_inventory=initial_inventory,
        lead_time_weeks=config.lead_time_weeks,
    )
    metrics.update({"mode": "perfect_foresight", "plan": plan})
    return metrics


def rolling_horizon(
    actual_demand: np.ndarray,
    forecast: np.ndarray,
    economics: pd.DataFrame,
    config: MilpConfig,
    storage_capacity: Optional[float] = None,
    throughput_capacity: Optional[float] = None,
    terminal_inventory: Optional[np.ndarray] = None,
    initial_inventory: Optional[np.ndarray] = None,
    safety_stock: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Re-plan weekly with the forecast; execute only the current-week order.

    ``safety_stock`` is an optional per-SKU buffer added to every planned week.
    A deterministic lot-sizing model has no reason to hold stock against
    forecast error, so a z * sigma buffer is the practical fix for the point
    forecast. If the buffered plan is infeasible under the shared capacities,
    the solve falls back to the unbuffered forecast instead of failing the week.
    """
    actual = np.atleast_2d(np.asarray(actual_demand, dtype=float))
    forecast = np.atleast_2d(np.asarray(forecast, dtype=float))
    if actual.shape != forecast.shape:
        raise ValueError("actual_demand 与 forecast 形状必须一致")
    n_skus, weeks = actual.shape
    lead = int(config.lead_time_weeks)
    safety = (
        np.zeros(n_skus, dtype=float)
        if safety_stock is None
        else np.clip(np.asarray(safety_stock, dtype=float), 0.0, None)
    )
    if safety.shape != (n_skus,):
        raise ValueError(f"safety_stock 形状应为 {(n_skus,)}")

    on_hand = (
        np.asarray(initial_inventory, dtype=float).copy()
        if initial_inventory is not None
        else economics["initial_inventory"].to_numpy(dtype=float).copy()
    )
    arrivals = np.zeros((n_skus, weeks + lead + 1))
    orders = np.zeros((n_skus, weeks))
    inventory = np.zeros((n_skus, weeks))
    lost = np.zeros((n_skus, weeks))
    sales = np.zeros((n_skus, weeks))
    solve_seconds = 0.0
    statuses: Dict[str, int] = {}
    replans = 0

    for week in range(weeks):
        on_hand += arrivals[:, week]
        horizon = min(int(config.horizon_weeks), weeks - week)
        point_forecast = forecast[:, week : week + horizon]
        plan_demand = point_forecast + safety[:, None]

        pipeline = np.zeros((n_skus, lead))
        for offset in range(1, lead):
            if week + offset < arrivals.shape[1]:
                pipeline[:, offset] = arrivals[:, week + offset]

        plan = solve_replenishment(
            plan_demand,
            economics,
            config,
            initial_inventory=on_hand,
            initial_pipeline=pipeline,
            storage_capacity=storage_capacity,
            throughput_capacity=throughput_capacity,
            terminal_inventory=terminal_inventory,
        )
        attempt_seconds = plan.solve_seconds
        if plan.status not in {"OPTIMAL", "FEASIBLE"} and not np.allclose(safety, 0.0):
            plan = solve_replenishment(
                point_forecast,
                economics,
                config,
                initial_inventory=on_hand,
                initial_pipeline=pipeline,
                storage_capacity=storage_capacity,
                throughput_capacity=throughput_capacity,
                terminal_inventory=terminal_inventory,
            )
            attempt_seconds += plan.solve_seconds
        if plan.status not in {"OPTIMAL", "FEASIBLE"} and terminal_inventory is not None:
            plan = solve_replenishment(
                point_forecast,
                economics,
                config,
                initial_inventory=on_hand,
                initial_pipeline=pipeline,
                storage_capacity=storage_capacity,
                throughput_capacity=throughput_capacity,
                terminal_inventory=None,
            )
            attempt_seconds += plan.solve_seconds
        statuses[plan.status] = statuses.get(plan.status, 0) + 1
        solve_seconds += attempt_seconds
        replans += 1

        decision = plan.orders[:, 0] if plan.status in {"OPTIMAL", "FEASIBLE"} else np.zeros(n_skus)
        orders[:, week] = decision
        if lead == 0:
            on_hand += decision
        else:
            arrivals[:, week + lead] += decision

        served = np.minimum(np.maximum(on_hand, 0.0), actual[:, week])
        sales[:, week] = served
        lost[:, week] = actual[:, week] - served
        on_hand = np.maximum(on_hand - served, 0.0)
        inventory[:, week] = on_hand

    holding = economics["holding_cost_per_unit_week"].to_numpy(dtype=float)
    order_cost = economics["ordering_cost"].to_numpy(dtype=float)
    shortage = economics["stockout_cost_per_unit"].to_numpy(dtype=float)
    demand_units = float(actual.sum())
    lost_units = float(lost.sum())
    sold_units = float(sales.sum())
    # Portfolio units per week, matching sold_units; inventory.mean() is per SKU.
    avg_on_hand = float(inventory.sum(axis=0).mean())
    holding_cost = float((inventory * holding[:, None]).sum())
    ordering_cost = float(((orders > 0) * order_cost[:, None]).sum())
    stockout_cost = float((lost * shortage[:, None]).sum())

    return {
        "orders": orders,
        "inventory": inventory,
        "lost": lost,
        "sales": sales,
        "demand_units": demand_units,
        "sold_units": sold_units,
        "lost_units": lost_units,
        "fill_rate": 1.0 - lost_units / demand_units if demand_units > 0 else 1.0,
        "avg_on_hand": avg_on_hand,
        "turns": sold_units / avg_on_hand * (52.0 / weeks) if avg_on_hand > 0 else np.nan,
        "fixed_orders": int((orders > 0).sum()),
        "holding_cost": holding_cost,
        "ordering_cost": ordering_cost,
        "stockout_cost": stockout_cost,
        "total_cost": holding_cost + ordering_cost + stockout_cost,
        "cost_per_unit": (holding_cost + ordering_cost + stockout_cost) / sold_units
        if sold_units > 0
        else np.nan,
        "mode": "rolling_horizon",
        "replans": replans,
        "solve_seconds": solve_seconds,
        "statuses": statuses,
    }
