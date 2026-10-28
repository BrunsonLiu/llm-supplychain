"""Capacitated facility location (CFLP) with OR-Tools CP-SAT.

    min  sum_j f_j y_j + sum_ij c_ij x_ij
    s.t. sum_j x_ij = d_i          (demand served)
         sum_i x_ij <= q_j y_j     (capacity only if open)
         x_ij >= 0, y_j in {0, 1}

Flows are integer units, so CP-SAT solves the model without an extra LP layer.
The baseline opens every hub and assigns each country to the cheapest hub with
remaining capacity; comparing against it isolates the value of joint
opening/assignment decisions.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
from ortools.sat.python import cp_model

from .instances import LocationInstance

COST_SCALE = 1_000  # objective resolution: 0.001 currency units


@dataclass
class CFLPResult:
    status: str
    open_indices: List[int]
    flows: np.ndarray
    fixed_cost: float
    transport_cost: float
    total_cost: float
    avg_distance_km: float
    opened_names: List[str]
    solve_seconds: float
    capacity_utilization: np.ndarray


def _metrics(
    instance: LocationInstance,
    flows: np.ndarray,
    open_flags: np.ndarray,
    status: str,
    elapsed: float,
) -> CFLPResult:
    transport = float((flows * instance.transport_cost).sum())
    fixed = float((open_flags * instance.fixed_costs).sum())
    units = float(flows.sum())
    avg_distance = (
        float((flows * instance.distance_km).sum() / units) if units > 0 else 0.0
    )
    used = flows.sum(axis=0)
    utilization = np.divide(
        used,
        instance.capacities,
        out=np.zeros_like(used),
        where=instance.capacities > 0,
    )
    open_indices = np.flatnonzero(open_flags > 0.5).tolist()
    return CFLPResult(
        status=status,
        open_indices=open_indices,
        flows=flows,
        fixed_cost=fixed,
        transport_cost=transport,
        total_cost=fixed + transport,
        avg_distance_km=avg_distance,
        opened_names=[instance.candidate_names[j] for j in open_indices],
        solve_seconds=elapsed,
        capacity_utilization=utilization,
    )


def solve_cflp(
    instance: LocationInstance,
    deterministic_time: float = 5.0,
    workers: int = 1,
    max_open: Optional[int] = None,
) -> CFLPResult:
    """Solve the CFLP to the best incumbent within a deterministic budget."""
    n_demand = instance.n_demand
    n_candidates = instance.n_candidates
    demand = np.rint(instance.demand_units).astype(np.int64)
    capacity = np.floor(instance.capacities).astype(np.int64)
    if demand.sum() > capacity.sum():
        raise ValueError("候选仓总容量不足以覆盖需求")

    model = cp_model.CpModel()
    open_vars = [
        model.NewBoolVar(f"open_{j}") for j in range(n_candidates)
    ]
    flow: List[List[Any]] = []
    for i in range(n_demand):
        row = [
            model.NewIntVar(0, int(demand[i]), f"flow_{i}_{j}")
            for j in range(n_candidates)
        ]
        flow.append(row)
        model.Add(sum(row) == int(demand[i]))

    for j in range(n_candidates):
        model.Add(
            sum(flow[i][j] for i in range(n_demand))
            <= int(capacity[j]) * open_vars[j]
        )
    if max_open is not None:
        model.Add(sum(open_vars) <= int(max_open))

    objective = []
    for j in range(n_candidates):
        objective.append(
            int(round(float(instance.fixed_costs[j]) * COST_SCALE)) * open_vars[j]
        )
    for i in range(n_demand):
        for j in range(n_candidates):
            coefficient = int(
                round(float(instance.transport_cost[i, j]) * COST_SCALE)
            )
            objective.append(coefficient * flow[i][j])
    model.Minimize(sum(objective))

    solver = cp_model.CpSolver()
    solver.parameters.max_deterministic_time = float(deterministic_time)
    solver.parameters.num_search_workers = int(workers)
    solver.parameters.random_seed = 0
    solver.parameters.log_search_progress = False
    started = time.perf_counter()
    code = solver.Solve(model)
    elapsed = time.perf_counter() - started
    status = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.UNKNOWN: "UNKNOWN",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
    }.get(code, str(code))
    flows = np.zeros((n_demand, n_candidates))
    open_flags = np.zeros(n_candidates)
    if status in {"OPTIMAL", "FEASIBLE"}:
        for i in range(n_demand):
            for j in range(n_candidates):
                flows[i, j] = solver.Value(flow[i][j])
        for j in range(n_candidates):
            open_flags[j] = solver.Value(open_vars[j])
    return _metrics(instance, flows, open_flags, status, elapsed)


def all_open_nearest(instance: LocationInstance) -> CFLPResult:
    """Baseline: every hub open, each country to its cheapest hub with capacity."""
    started = time.perf_counter()
    remaining = instance.capacities.astype(float).copy()
    flows = np.zeros((instance.n_demand, instance.n_candidates))
    order = np.argsort(instance.transport_cost, axis=1)
    for i in range(instance.n_demand):
        need = float(instance.demand_units[i])
        for j in order[i]:
            if remaining[j] <= 0:
                continue
            take = min(need, remaining[j])
            flows[i, j] = take
            remaining[j] -= take
            need -= take
            if need <= 1e-9:
                break
        if need > 1e-6:
            raise ValueError(
                f"{instance.demand_countries[i]} 需求无法被剩余容量满足"
            )
    elapsed = time.perf_counter() - started
    return _metrics(
        instance,
        flows,
        np.ones(instance.n_candidates),
        "HEURISTIC",
        elapsed,
    )


def fixed_cost_sensitivity(
    instance_factory,
    multipliers: Iterable[float] = (0.5, 1.0, 2.0, 4.0),
    deterministic_time: float = 5.0,
) -> List[Dict[str, Any]]:
    """Re-solve with scaled fixed costs to trace the open/close trade-off."""
    rows = []
    for multiplier in multipliers:
        instance = instance_factory(multiplier)
        result = solve_cflp(instance, deterministic_time=deterministic_time)
        rows.append(
            {
                "fixed_cost_multiplier": float(multiplier),
                "status": result.status,
                "opened": len(result.open_indices),
                "fixed_cost": result.fixed_cost,
                "transport_cost": result.transport_cost,
                "total_cost": result.total_cost,
                "avg_distance_km": result.avg_distance_km,
                "facilities": ", ".join(result.opened_names),
            }
        )
    return rows


def facility_table(result: CFLPResult, instance: LocationInstance) -> List[Dict[str, Any]]:
    """Per-facility throughput, utilisation, and fixed cost for the report."""
    rows = []
    for j, name in enumerate(result.opened_names):
        index = result.open_indices[j]
        served = result.flows[:, index]
        rows.append(
            {
                "facility": name,
                "units": float(served.sum()),
                "utilization": float(result.capacity_utilization[index]),
                "fixed_cost": float(instance.fixed_costs[index]),
            }
        )
    return rows
