"""Transportation LP and fixed-charge MIP with dual/shadow-price output.

This is the solver-engineering layer requested by domestic OR JDs:

* LP: DC -> order flow, shortage penalty, dual values for demand and DC capacity;
* MIP: fixed-charge DC activation, solved with SCIP or Gurobi;
* optional Gurobi adapter; OR-Tools remains the default so CI has no license
  dependency.

The model is a *transportation relaxation* of fulfillment, not a replacement for
the full allocation MILP. It is deliberately small enough to inspect duals.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np

try:  # optional; CI does not install Gurobi
    import gurobipy as gp
    from gurobipy import GRB
except Exception:  # pragma: no cover - depends on environment
    gp = None
    GRB = None

from ortools.linear_solver import pywraplp


class TransportSolverError(RuntimeError):
    """Raised when a transportation model cannot be solved."""


@dataclass(frozen=True)
class TransportInstance:
    """A small DC -> order transportation model."""

    supply: np.ndarray  # (D,)
    demand: np.ndarray  # (O,)
    cost: np.ndarray  # (D, O)
    shortage_penalty: float = 1_000.0
    capacity: Optional[np.ndarray] = None  # (D,), defaults to supply
    fixed_cost: Optional[np.ndarray] = None  # (D,), for the MIP

    def __post_init__(self) -> None:
        supply = np.asarray(self.supply, dtype=float)
        demand = np.asarray(self.demand, dtype=float)
        cost = np.asarray(self.cost, dtype=float)
        if supply.ndim != 1 or demand.ndim != 1:
            raise ValueError("supply/demand 必须是一维")
        if cost.shape != (supply.size, demand.size):
            raise ValueError("cost 形状应为 (dcs, orders)")
        if np.any(supply < 0) or np.any(demand < 0) or np.any(cost < 0):
            raise ValueError("supply/demand/cost 不能为负")
        if self.shortage_penalty <= 0:
            raise ValueError("shortage_penalty 必须为正")
        capacity = supply if self.capacity is None else np.asarray(self.capacity, dtype=float)
        if capacity.shape != supply.shape or np.any(capacity < 0):
            raise ValueError("capacity 形状/数值不正确")
        fixed = (
            np.zeros(supply.size, dtype=float)
            if self.fixed_cost is None
            else np.asarray(self.fixed_cost, dtype=float)
        )
        if fixed.shape != supply.shape or np.any(fixed < 0):
            raise ValueError("fixed_cost 形状/数值不正确")
        object.__setattr__(self, "supply", supply)
        object.__setattr__(self, "demand", demand)
        object.__setattr__(self, "cost", cost)
        object.__setattr__(self, "capacity", capacity)
        object.__setattr__(self, "fixed_cost", fixed)


@dataclass
class TransportLPResult:
    solver: str
    status: str
    objective: float
    flows: np.ndarray  # (D, O)
    unmet: np.ndarray  # (O,)
    demand_duals: np.ndarray  # (O,)
    supply_duals: np.ndarray  # (D,)
    solve_seconds: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "solver": self.solver,
            "status": self.status,
            "objective": float(self.objective),
            "flows": [[float(v) for v in row] for row in self.flows],
            "unmet": [float(v) for v in self.unmet],
            "demand_duals": [float(v) for v in self.demand_duals],
            "supply_duals": [float(v) for v in self.supply_duals],
            "solve_seconds": float(self.solve_seconds),
        }


@dataclass
class TransportMIPResult:
    solver: str
    status: str
    objective: float
    flows: np.ndarray
    unmet: np.ndarray
    open_dcs: List[int]
    variable_cost: float
    fixed_cost: float
    gap: float
    solve_seconds: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "solver": self.solver,
            "status": self.status,
            "objective": float(self.objective),
            "flows": [[float(v) for v in row] for row in self.flows],
            "unmet": [float(v) for v in self.unmet],
            "open_dcs": list(self.open_dcs),
            "variable_cost": float(self.variable_cost),
            "fixed_cost": float(self.fixed_cost),
            "gap": float(self.gap),
            "solve_seconds": float(self.solve_seconds),
        }


def _gurobi_available() -> bool:
    return gp is not None and GRB is not None


def solve_transport_lp(
    instance: TransportInstance,
    solver: str = "glop",
) -> TransportLPResult:
    """Solve the transportation LP and return demand/supply duals."""
    if solver not in {"glop", "gurobi"}:
        raise ValueError("solver 必须是 glop 或 gurobi")
    if solver == "gurobi":
        return _solve_lp_gurobi(instance)
    return _solve_lp_glop(instance)


def _solve_lp_glop(instance: TransportInstance) -> TransportLPResult:
    import time

    started = time.perf_counter()
    model = pywraplp.Solver.CreateSolver("GLOP")
    if model is None:
        raise TransportSolverError("GLOP 不可用")
    n_dcs, n_orders = instance.cost.shape
    x = {}
    unmet = {}
    for d in range(n_dcs):
        for o in range(n_orders):
            x[d, o] = model.NumVar(0.0, model.infinity(), f"x_{d}_{o}")
    for o in range(n_orders):
        unmet[o] = model.NumVar(0.0, model.infinity(), f"u_{o}")
    demand_constraints = {}
    for o in range(n_orders):
        demand_constraints[o] = model.Add(
            sum(x[d, o] for d in range(n_dcs)) + unmet[o] == float(instance.demand[o])
        )
    supply_constraints = {}
    for d in range(n_dcs):
        supply_constraints[d] = model.Add(
            sum(x[d, o] for o in range(n_orders)) <= float(instance.capacity[d])
        )
    model.Minimize(
        sum(float(instance.cost[d, o]) * x[d, o] for d in range(n_dcs) for o in range(n_orders))
        + float(instance.shortage_penalty) * sum(unmet[o] for o in range(n_orders))
    )
    status = model.Solve()
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        raise TransportSolverError(f"GLOP 未求解: {status}")
    flows = np.array(
        [[x[d, o].solution_value() for o in range(n_orders)] for d in range(n_dcs)]
    )
    unmet_values = np.array([unmet[o].solution_value() for o in range(n_orders)])
    demand_duals = np.array(
        [demand_constraints[o].dual_value() for o in range(n_orders)]
    )
    supply_duals = np.array(
        [supply_constraints[d].dual_value() for d in range(n_dcs)]
    )
    return TransportLPResult(
        solver="glop",
        status="OPTIMAL",
        objective=float(model.Objective().Value()),
        flows=flows,
        unmet=unmet_values,
        demand_duals=demand_duals,
        supply_duals=supply_duals,
        solve_seconds=time.perf_counter() - started,
    )


def _solve_lp_gurobi(instance: TransportInstance) -> TransportLPResult:
    if not _gurobi_available():
        raise TransportSolverError("gurobipy 不可用")
    import time

    started = time.perf_counter()
    try:
        model = gp.Model("transport_lp")
        model.Params.OutputFlag = 0
        n_dcs, n_orders = instance.cost.shape
        x = model.addVars(n_dcs, n_orders, lb=0.0, name="x")
        unmet = model.addVars(n_orders, lb=0.0, name="u")
        demand_constr = model.addConstrs(
            (
                gp.quicksum(x[d, o] for d in range(n_dcs)) + unmet[o]
                == float(instance.demand[o])
                for o in range(n_orders)
            ),
            name="demand",
        )
        supply_constr = model.addConstrs(
            (
                gp.quicksum(x[d, o] for o in range(n_orders))
                <= float(instance.capacity[d])
                for d in range(n_dcs)
            ),
            name="capacity",
        )
        model.setObjective(
            gp.quicksum(float(instance.cost[d, o]) * x[d, o] for d in range(n_dcs) for o in range(n_orders))
            + float(instance.shortage_penalty) * gp.quicksum(unmet[o] for o in range(n_orders)),
            GRB.MINIMIZE,
        )
        model.optimize()
        if model.Status not in (GRB.OPTIMAL, GRB.SUBOPTIMAL):
            raise TransportSolverError(f"Gurobi 未求解: {model.Status}")
        flows = np.array(
            [[x[d, o].X for o in range(n_orders)] for d in range(n_dcs)]
        )
        return TransportLPResult(
            solver="gurobi",
            status="OPTIMAL" if model.Status == GRB.OPTIMAL else "SUBOPTIMAL",
            objective=float(model.ObjVal),
            flows=flows,
            unmet=np.array([unmet[o].X for o in range(n_orders)]),
            demand_duals=np.array([demand_constr[o].Pi for o in range(n_orders)]),
            supply_duals=np.array([supply_constr[d].Pi for d in range(n_dcs)]),
            solve_seconds=time.perf_counter() - started,
        )
    except TransportSolverError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise TransportSolverError(f"Gurobi 求解失败: {exc}") from exc


def solve_transport_mip(
    instance: TransportInstance,
    solver: str = "scip",
    time_limit_seconds: float = 30.0,
) -> TransportMIPResult:
    """Fixed-charge DC activation MIP; no duals (MIP)."""
    if solver not in {"scip", "gurobi"}:
        raise ValueError("solver 必须是 scip 或 gurobi")
    if time_limit_seconds <= 0:
        raise ValueError("time_limit_seconds 必须为正")
    if solver == "gurobi":
        return _solve_mip_gurobi(instance, time_limit_seconds)
    return _solve_mip_scip(instance, time_limit_seconds)


def _solve_mip_scip(instance: TransportInstance, limit: float) -> TransportMIPResult:
    import time

    started = time.perf_counter()
    model = pywraplp.Solver.CreateSolver("SCIP")
    if model is None:
        raise TransportSolverError("SCIP 不可用")
    model.SetTimeLimit(int(limit * 1000))
    n_dcs, n_orders = instance.cost.shape
    x = {}
    y = {}
    unmet = {}
    for d in range(n_dcs):
        y[d] = model.BoolVar(f"y_{d}")
        for o in range(n_orders):
            x[d, o] = model.NumVar(0.0, model.infinity(), f"x_{d}_{o}")
    for o in range(n_orders):
        unmet[o] = model.NumVar(0.0, model.infinity(), f"u_{o}")
    for o in range(n_orders):
        model.Add(
            sum(x[d, o] for d in range(n_dcs)) + unmet[o] == float(instance.demand[o])
        )
    for d in range(n_dcs):
        model.Add(sum(x[d, o] for o in range(n_orders)) <= float(instance.capacity[d]) * y[d])
    model.Minimize(
        sum(float(instance.cost[d, o]) * x[d, o] for d in range(n_dcs) for o in range(n_orders))
        + float(instance.shortage_penalty) * sum(unmet[o] for o in range(n_orders))
        + sum(float(instance.fixed_cost[d]) * y[d] for d in range(n_dcs))
    )
    status = model.Solve()
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        raise TransportSolverError(f"SCIP 未求解: {status}")
    flows = np.array(
        [[x[d, o].solution_value() for o in range(n_orders)] for d in range(n_dcs)]
    )
    variable = float(
        sum(float(instance.cost[d, o]) * flows[d, o] for d in range(n_dcs) for o in range(n_orders))
        + float(instance.shortage_penalty) * sum(unmet[o].solution_value() for o in range(n_orders))
    )
    fixed = float(
        sum(float(instance.fixed_cost[d]) * y[d].solution_value() for d in range(n_dcs))
    )
    objective = float(model.Objective().Value())
    gap = (
        max(0.0, (objective - model.Objective().BestBound()) / abs(objective))
        if abs(objective) > 1e-9
        else 0.0
    )
    return TransportMIPResult(
        solver="scip",
        status="OPTIMAL" if status == pywraplp.Solver.OPTIMAL else "FEASIBLE",
        objective=objective,
        flows=flows,
        unmet=np.array([unmet[o].solution_value() for o in range(n_orders)]),
        open_dcs=[d for d in range(n_dcs) if y[d].solution_value() > 0.5],
        variable_cost=variable,
        fixed_cost=fixed,
        gap=gap,
        solve_seconds=time.perf_counter() - started,
    )


def _solve_mip_gurobi(instance: TransportInstance, limit: float) -> TransportMIPResult:
    if not _gurobi_available():
        raise TransportSolverError("gurobipy 不可用")
    import time

    started = time.perf_counter()
    try:
        model = gp.Model("transport_mip")
        model.Params.OutputFlag = 0
        model.Params.TimeLimit = float(limit)
        n_dcs, n_orders = instance.cost.shape
        x = model.addVars(n_dcs, n_orders, lb=0.0, name="x")
        y = model.addVars(n_dcs, vtype=GRB.BINARY, name="y")
        unmet = model.addVars(n_orders, lb=0.0, name="u")
        model.addConstrs(
            (
                gp.quicksum(x[d, o] for d in range(n_dcs)) + unmet[o]
                == float(instance.demand[o])
                for o in range(n_orders)
            ),
            name="demand",
        )
        model.addConstrs(
            (
                gp.quicksum(x[d, o] for o in range(n_orders))
                <= float(instance.capacity[d]) * y[d]
                for d in range(n_dcs)
            ),
            name="capacity",
        )
        model.setObjective(
            gp.quicksum(float(instance.cost[d, o]) * x[d, o] for d in range(n_dcs) for o in range(n_orders))
            + float(instance.shortage_penalty) * gp.quicksum(unmet[o] for o in range(n_orders))
            + gp.quicksum(float(instance.fixed_cost[d]) * y[d] for d in range(n_dcs)),
            GRB.MINIMIZE,
        )
        model.optimize()
        if model.Status not in (GRB.OPTIMAL, GRB.SUBOPTIMAL, GRB.TIME_LIMIT):
            raise TransportSolverError(f"Gurobi 未求解: {model.Status}")
        flows = np.array(
            [[x[d, o].X for o in range(n_orders)] for d in range(n_dcs)]
        )
        variable = float(
            sum(float(instance.cost[d, o]) * flows[d, o] for d in range(n_dcs) for o in range(n_orders))
            + float(instance.shortage_penalty) * sum(unmet[o].X for o in range(n_orders))
        )
        fixed = float(
            sum(float(instance.fixed_cost[d]) * y[d].X for d in range(n_dcs))
        )
        objective = float(model.ObjVal)
        best = float(model.ObjBound)
        return TransportMIPResult(
            solver="gurobi",
            status="OPTIMAL" if model.Status == GRB.OPTIMAL else "FEASIBLE",
            objective=objective,
            flows=flows,
            unmet=np.array([unmet[o].X for o in range(n_orders)]),
            open_dcs=[d for d in range(n_dcs) if y[d].X > 0.5],
            variable_cost=variable,
            fixed_cost=fixed,
            gap=max(0.0, (objective - best) / abs(objective)) if abs(objective) > 1e-9 else 0.0,
            solve_seconds=time.perf_counter() - started,
        )
    except TransportSolverError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise TransportSolverError(f"Gurobi 求解失败: {exc}") from exc


def instance_from_e2e(
    instance: Any,
    fixed_cost: float = 1000.0,
    shortage_penalty: Optional[float] = None,
) -> TransportInstance:
    """Build a transportation relaxation from an E2E instance."""
    fulfillment = instance.fulfillment
    demand = np.asarray(fulfillment.order_units(), dtype=float)
    supply = np.asarray(fulfillment.stock.sum(axis=1), dtype=float)
    cost = np.asarray(fulfillment.ship_cost, dtype=float)
    if cost.shape != (supply.size, demand.size):
        raise ValueError("ship_cost 形状与 DC/订单数不一致")
    penalty = (
        float(shortage_penalty)
        if shortage_penalty is not None
        else float(max(1.0, cost.max()) * 10.0)
    )
    return TransportInstance(
        supply=supply,
        demand=demand,
        cost=cost,
        shortage_penalty=penalty,
        capacity=supply.copy(),
        fixed_cost=np.full(supply.size, float(fixed_cost)),
    )
