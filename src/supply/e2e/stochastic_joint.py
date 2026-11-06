"""Cost-aware two-stage stochastic joint placement and allocation.

The existing Week-14 model (``stochastic.py``) optimises unmet demand and a CVaR
penalty for a fixed per-SKU stock total. The existing Week-13 model
(``joint.py``) optimises placement and allocation for a *known* week. This module
combines the deployable first stage with a cost-aware recourse:

* first stage: ``z[k, d]`` placement before demand is observed;
* second stage: ``y[s, k, d]`` allocation per scenario, bounded by placement,
  serviceability and DC throughput;
* objective: expected handling + shortage + holding cost, plus CVaR of the
  scenario cost.

It is intentionally a small, auditable MILP/CP-SAT model. It is not a claim of
state-of-the-art scale; scenario reduction and a time limit are part of the
contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
from ortools.sat.python import cp_model

from .stochastic import ScenarioSet, empirical_cvar

COST_SCALE = 100
WEIGHT_SCALE = 1000
EPS = 1e-9
DEFAULT_HANDLING = (0.02, 0.04, 0.05)
DEFAULT_SHORTAGE = 4.0
DEFAULT_HOLDING = 0.01


@dataclass(frozen=True)
class JointPlan:
    """One first-stage placement, scenario allocations, and cost metrics."""

    stock: np.ndarray  # (D, K)
    allocation: np.ndarray  # (S, D, K)
    status: str
    solve_seconds: float
    expected_unmet: float
    cvar_unmet: float
    expected_cost: float
    cvar_cost: float
    objective: float
    solver_objective: float
    best_bound: float
    gap: float
    cvar_weight: float
    alpha: float
    scenario_cost: np.ndarray
    scenario_unmet: np.ndarray
    handling_cost: List[float]
    shortage_cost: float
    holding_cost: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "solve_seconds": float(self.solve_seconds),
            "expected_unmet": float(self.expected_unmet),
            "cvar_unmet": float(self.cvar_unmet),
            "expected_cost": float(self.expected_cost),
            "cvar_cost": float(self.cvar_cost),
            "objective": float(self.objective),
            "solver_objective": float(self.solver_objective),
            "best_bound": float(self.best_bound),
            "gap": float(self.gap),
            "cvar_weight": float(self.cvar_weight),
            "alpha": float(self.alpha),
            "scenario_cost": [float(value) for value in self.scenario_cost],
            "scenario_unmet": [float(value) for value in self.scenario_unmet],
            "stock_units": [int(value) for value in self.stock.sum(axis=1)],
            "allocation_units": [
                [int(value) for value in self.allocation[s].sum(axis=1)]
                for s in range(self.allocation.shape[0])
            ],
            "handling_cost": list(self.handling_cost),
            "shortage_cost": float(self.shortage_cost),
            "holding_cost": float(self.holding_cost),
        }


def _weight_ints(weights: np.ndarray, scale: int) -> np.ndarray:
    """Round scenario weights to integers that sum exactly to ``scale``."""
    values = np.asarray(weights, dtype=float)
    if values.size == 0 or np.any(values < 0):
        raise ValueError("场景权重必须为非空非负数")
    if abs(float(values.sum()) - 1.0) > 1e-6:
        raise ValueError("场景权重之和应为 1")
    integers = np.rint(values * scale).astype(np.int64)
    delta = int(scale - integers.sum())
    if delta:
        # Adjust the largest weight; the perturbation is at most a few units.
        integers[int(np.argmax(integers))] += delta
    if integers.sum() != scale or np.any(integers < 0):
        raise ValueError("无法将场景权重离散化")
    return integers


def _validate(instance: Any, scenarios: ScenarioSet) -> None:
    if not hasattr(instance, "fulfillment"):
        raise ValueError("instance 必须提供 fulfillment")
    fulfillment = instance.fulfillment
    if fulfillment.n_dcs != len(scenarios.dc_names):
        raise ValueError("DC 数与场景不一致")
    if fulfillment.n_skus != len(scenarios.sku_names):
        raise ValueError("SKU 数与场景不一致")
    stock = np.asarray(fulfillment.stock, dtype=np.int64)
    if stock.shape != (fulfillment.n_dcs, fulfillment.n_skus):
        raise ValueError("库存形状应为 (dcs, skus)")
    if np.any(stock < 0):
        raise ValueError("库存不能为负")
    capacity = np.asarray(fulfillment.dc_capacity, dtype=np.int64)
    if capacity.shape != (fulfillment.n_dcs,):
        raise ValueError("DC 产能长度不正确")
    if np.any(capacity <= 0):
        raise ValueError("DC 产能必须为正")
    demand = scenarios.demand
    serviceable = scenarios.serviceable
    if demand.ndim != 2 or demand.shape[1] != fulfillment.n_skus:
        raise ValueError("场景需求形状不正确")
    if serviceable.shape != (demand.shape[0], fulfillment.n_dcs, fulfillment.n_skus):
        raise ValueError("场景可服务需求形状不正确")
    if np.any(demand < 0) or np.any(serviceable < 0):
        raise ValueError("场景需求不能为负")
    if np.any(serviceable > demand[:, None, :]):
        raise ValueError("单 DC 可服务需求不能超过总需求")


def solve_stochastic_joint(
    instance: Any,
    scenarios: ScenarioSet,
    cvar_weight: float = 0.5,
    alpha: float = 0.8,
    handling_cost: Optional[Sequence[float]] = None,
    shortage_cost: float = DEFAULT_SHORTAGE,
    holding_cost: float = DEFAULT_HOLDING,
    time_limit_seconds: float = 60.0,
    workers: int = 4,
) -> JointPlan:
    """Solve the cost-aware two-stage model.

    ``handling_cost`` is per DC per unit shipped. The default is the declared
    three-DC handling cost; longer DC lists fall back to the last value.
    """
    if not 0.0 <= cvar_weight <= 1.0:
        raise ValueError("cvar_weight 必须在 [0, 1]")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha 必须在 (0, 1)")
    if shortage_cost < 0 or holding_cost < 0:
        raise ValueError("成本参数不能为负")
    if time_limit_seconds <= 0:
        raise ValueError("time_limit_seconds 必须为正")
    if workers < 1:
        raise ValueError("workers 必须 >= 1")
    _validate(instance, scenarios)

    fulfillment = instance.fulfillment
    n_dcs = int(fulfillment.n_dcs)
    n_skus = int(fulfillment.n_skus)
    stock_total = np.asarray(fulfillment.stock, dtype=np.int64).sum(axis=0)
    capacity = np.asarray(fulfillment.dc_capacity, dtype=np.int64)
    demand = np.asarray(scenarios.demand, dtype=np.int64)
    serviceable = np.asarray(scenarios.serviceable, dtype=np.int64)
    weights = np.asarray(scenarios.weights, dtype=float)
    n_scenarios = demand.shape[0]

    if handling_cost is None:
        handling = np.array(
            [DEFAULT_HANDLING[min(index, len(DEFAULT_HANDLING) - 1)] for index in range(n_dcs)],
            dtype=float,
        )
    else:
        handling = np.asarray(handling_cost, dtype=float)
        if handling.shape != (n_dcs,):
            raise ValueError("handling_cost 长度应等于 DC 数")
        if np.any(handling < 0):
            raise ValueError("handling_cost 不能为负")

    handling_int = np.rint(handling * COST_SCALE).astype(np.int64)
    shortage_int = int(round(shortage_cost * COST_SCALE))
    holding_int = int(round(holding_cost * COST_SCALE))

    model = cp_model.CpModel()
    z: Dict[tuple, Any] = {}
    y: Dict[tuple, Any] = {}
    unmet: Dict[tuple, Any] = {}
    for sku in range(n_skus):
        upper = int(stock_total[sku])
        for dc in range(n_dcs):
            z[sku, dc] = model.NewIntVar(0, upper, f"z_{sku}_{dc}")
        model.Add(sum(z[sku, dc] for dc in range(n_dcs)) == upper)

    for scenario in range(n_scenarios):
        for sku in range(n_skus):
            quantity = int(demand[scenario, sku])
            unmet[scenario, sku] = model.NewIntVar(
                0, quantity, f"u_{scenario}_{sku}"
            )
            for dc in range(n_dcs):
                upper = int(min(stock_total[sku], serviceable[scenario, dc, sku]))
                y[scenario, sku, dc] = model.NewIntVar(
                    0, upper, f"y_{scenario}_{sku}_{dc}"
                )
                model.Add(y[scenario, sku, dc] <= z[sku, dc])
            model.Add(
                sum(y[scenario, sku, dc] for dc in range(n_dcs))
                + unmet[scenario, sku]
                == quantity
            )
        for dc in range(n_dcs):
            model.Add(
                sum(y[scenario, sku, dc] for sku in range(n_skus))
                <= int(capacity[dc])
            )

    # Scenario cost: handling of shipped units + shortage + holding of the
    # first-stage placement. All terms are integer cents.
    scenario_cost: Dict[int, Any] = {}
    max_cost = 0
    for scenario in range(n_scenarios):
        shipped_cost = sum(
            int(handling_int[dc]) * y[scenario, sku, dc]
            for sku in range(n_skus)
            for dc in range(n_dcs)
        )
        unmet_cost = sum(
            shortage_int * unmet[scenario, sku] for sku in range(n_skus)
        )
        holding = holding_int * int(stock_total.sum())
        upper = int(
            handling_int.max() * int(demand[scenario].sum())
            + shortage_int * int(demand[scenario].sum())
            + holding
            + 1
        )
        max_cost = max(max_cost, upper)
        scenario_cost[scenario] = model.NewIntVar(0, upper, f"cost_{scenario}")
        model.Add(scenario_cost[scenario] == shipped_cost + unmet_cost + holding)

    # Keep the objective in integer units of WEIGHT_SCALE * cents. The final
    # solver objective is divided by WEIGHT_SCALE * COST_SCALE to get dollars.
    weight_ints = _weight_ints(weights, WEIGHT_SCALE)
    objective_terms: List[Any] = [
        int(round((1.0 - cvar_weight) * weight_ints[scenario]))
        * scenario_cost[scenario]
        for scenario in range(n_scenarios)
    ]
    if cvar_weight > 0:
        eta = model.NewIntVar(0, max_cost, "eta")
        excess: Dict[int, Any] = {}
        for scenario in range(n_scenarios):
            excess[scenario] = model.NewIntVar(0, max_cost, f"e_{scenario}")
            model.Add(scenario_cost[scenario] <= eta + excess[scenario])
        objective_terms.append(int(round(cvar_weight * WEIGHT_SCALE)) * eta)
        for scenario in range(n_scenarios):
            coefficient = int(
                round(
                    cvar_weight
                    * WEIGHT_SCALE
                    * weights[scenario]
                    / (1.0 - alpha)
                )
            )
            if coefficient:
                objective_terms.append(coefficient * excess[scenario])
    model.Minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_seconds)
    solver.parameters.num_search_workers = int(workers)
    status_code = solver.Solve(model)
    status = solver.StatusName(status_code)
    if status not in {"OPTIMAL", "FEASIBLE"}:
        raise RuntimeError(f"随机联合 MILP 未找到可行解: {status}")

    stock = np.zeros((n_dcs, n_skus), dtype=np.int64)
    allocation = np.zeros((n_scenarios, n_dcs, n_skus), dtype=np.int64)
    unmet_values = np.zeros((n_scenarios, n_skus), dtype=np.int64)
    costs = np.zeros(n_scenarios, dtype=float)
    for scenario in range(n_scenarios):
        for sku in range(n_skus):
            unmet_values[scenario, sku] = int(round(solver.Value(unmet[scenario, sku])))
            for dc in range(n_dcs):
                allocation[scenario, dc, sku] = int(
                    round(solver.Value(y[scenario, sku, dc]))
                )
        costs[scenario] = solver.Value(scenario_cost[scenario]) / COST_SCALE
    for sku in range(n_skus):
        for dc in range(n_dcs):
            stock[dc, sku] = int(round(solver.Value(z[sku, dc])))
    if not np.array_equal(stock.sum(axis=0), stock_total):
        raise RuntimeError("联合模型未保持每 SKU 总库存")

    scenario_unmet = unmet_values.sum(axis=1).astype(float)
    expected_unmet = float((weights * scenario_unmet).sum())
    cvar_unmet = float(empirical_cvar(scenario_unmet, alpha))
    expected_cost = float((weights * costs).sum())
    cvar_cost = float(empirical_cvar(costs, alpha))
    objective = (1.0 - cvar_weight) * expected_cost + cvar_weight * cvar_cost
    denominator = float(WEIGHT_SCALE * COST_SCALE)
    solver_objective = float(solver.ObjectiveValue()) / denominator
    best_bound = float(solver.BestObjectiveBound()) / denominator
    gap = (
        max(0.0, (solver_objective - best_bound) / abs(solver_objective))
        if abs(solver_objective) > EPS
        else float("nan")
    )
    return JointPlan(
        stock=stock,
        allocation=allocation,
        status=status,
        solve_seconds=float(solver.WallTime()),
        expected_unmet=expected_unmet,
        cvar_unmet=cvar_unmet,
        expected_cost=expected_cost,
        cvar_cost=cvar_cost,
        objective=objective,
        solver_objective=solver_objective,
        best_bound=best_bound,
        gap=gap,
        cvar_weight=float(cvar_weight),
        alpha=float(alpha),
        scenario_cost=costs,
        scenario_unmet=scenario_unmet,
        handling_cost=[float(value) for value in handling],
        shortage_cost=float(shortage_cost),
        holding_cost=float(holding_cost),
    )
