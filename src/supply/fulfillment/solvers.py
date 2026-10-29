"""Order-to-DC allocation: deadline-first greedy baseline vs CP-SAT MILP.

Each order line must be fulfilled from a DC (or lost). Shipping a line from a
DC that cannot meet the order's promise incurs a per-unit-per-day lateness
penalty; opening a second shipment for the same order costs a fixed handling
fee and counts against the split cap.

The MILP minimises
``transport + fixed shipment + lateness + lost sales`` subject to DC stock,
DC weekly throughput, and at most ``max_splits`` DCs per order. The greedy
baseline tries one fully-stocking on-time DC first, then spills to the next
cheapest DC. Both are evaluated with the same metrics and penalties.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
from ortools.sat.python import cp_model

from .instances import FulfillmentInstance

COST_SCALE = 1_000  # objective resolution: 0.001 currency units
PICK_SCALE = 1_000  # capacity resolution: 0.001 pick-minutes
PICK_MINUTES_PER_LINE = 0.35
PICK_MINUTES_PER_UNIT = 0.02
PICK_MINUTES_PER_SHIPMENT = 0.5  # wave setup amortised over ~6 orders/wave


@dataclass
class FulfillmentResult:
    name: str
    status: str
    shipments: np.ndarray  # (lines, dcs) integer units
    unmet: np.ndarray  # (lines,) integer units
    objective: float
    transport_cost: float
    fixed_cost: float
    late_cost: float
    unmet_cost: float
    demand_units: int
    fulfilled_units: int
    unmet_units: int
    late_units: int
    on_time_units: int
    unit_fill_rate: float
    order_fill_rate: float
    otif_rate: float
    on_time_unit_rate: float
    split_rate: float
    shipments_count: int
    avg_transit_days: float
    dc_units: np.ndarray
    dc_utilization: np.ndarray
    stock_used: np.ndarray  # (dcs, skus)
    solve_seconds: float
    best_bound: float = float("nan")

    @property
    def total_cost(self) -> float:
        return self.transport_cost + self.fixed_cost + self.late_cost + self.unmet_cost

    @property
    def gap(self) -> float:
        if not np.isfinite(self.best_bound) or self.objective == 0:
            return float("nan")
        return max(0.0, (self.objective - self.best_bound) / abs(self.objective))


def _line_matrices(instance: FulfillmentInstance) -> Dict[str, np.ndarray]:
    order = instance.line_order
    return {
        "unit_cost": instance.ship_cost[:, order].T,  # (lines, dcs)
        "transit": instance.transit_days[:, order].T,
        "late_days": np.maximum(
            instance.transit_days - instance.promise_days[None, :], 0
        )[:, order].T,
    }


def evaluate_allocation(
    instance: FulfillmentInstance,
    shipments: np.ndarray,
    name: str,
    status: str = "OPTIMAL",
    objective: Optional[float] = None,
    solve_seconds: float = 0.0,
    max_splits: Optional[int] = None,
    best_bound: Optional[float] = None,
) -> FulfillmentResult:
    """Score a feasible allocation and assert the resource constraints."""
    shipments = np.asarray(shipments, dtype=np.int64)
    if shipments.shape != (instance.n_lines, instance.n_dcs):
        raise ValueError("shipments 形状应为 (lines, dcs)")
    if np.any(shipments < 0):
        raise ValueError("shipments 不能为负")
    if np.any(shipments.sum(axis=1) > instance.line_qty):
        raise ValueError("单行发货量超过订单行数量")

    unmet = instance.line_qty - shipments.sum(axis=1)
    matrices = _line_matrices(instance)

    stock_used = np.zeros((instance.n_dcs, instance.n_skus), dtype=np.int64)
    for line in range(instance.n_lines):
        stock_used[:, instance.line_sku[line]] += shipments[line]
    if np.any(stock_used > instance.stock):
        raise ValueError("分配方案超出 DC 库存")
    dc_units = shipments.sum(axis=0)
    if np.any(dc_units > instance.dc_capacity):
        raise ValueError("分配方案超出 DC 周产能")

    flags = shipments > 0
    order_flags = np.zeros((instance.n_orders, instance.n_dcs), dtype=bool)
    for line in range(instance.n_lines):
        order_flags[instance.line_order[line]] |= flags[line]
    splits = order_flags.sum(axis=1)
    if max_splits is not None and np.any(splits > max_splits):
        raise ValueError("分配方案超出每单拆单上限")

    transport_cost = float((shipments * matrices["unit_cost"]).sum())
    late_days_units = (shipments * matrices["late_days"]).sum(axis=1)
    late_units_line = (shipments * (matrices["late_days"] > 0)).sum(axis=1)
    late_cost = float(late_days_units.sum()) * instance.late_penalty_per_unit_day
    fixed_cost = float(order_flags.sum()) * instance.fixed_ship_cost
    unmet_cost = float(unmet.sum()) * instance.unmet_penalty_per_unit

    demand_units = int(instance.line_qty.sum())
    fulfilled = shipments.sum(axis=1)
    late_units = int(late_units_line.sum())
    on_time_units = int(fulfilled.sum()) - late_units

    order_demand = np.bincount(
        instance.line_order, weights=instance.line_qty, minlength=instance.n_orders
    )
    order_fulfilled = np.bincount(
        instance.line_order, weights=fulfilled, minlength=instance.n_orders
    )
    order_late = np.bincount(
        instance.line_order, weights=late_units_line, minlength=instance.n_orders
    )
    fully_filled = order_fulfilled == order_demand
    on_time_orders = fully_filled & (order_late == 0)

    total_cost = transport_cost + fixed_cost + late_cost + unmet_cost
    return FulfillmentResult(
        name=name,
        status=status,
        shipments=shipments,
        unmet=unmet,
        objective=float(objective) if objective is not None else total_cost,
        transport_cost=transport_cost,
        fixed_cost=fixed_cost,
        late_cost=late_cost,
        unmet_cost=unmet_cost,
        demand_units=demand_units,
        fulfilled_units=int(fulfilled.sum()),
        unmet_units=int(unmet.sum()),
        late_units=late_units,
        on_time_units=on_time_units,
        unit_fill_rate=float(fulfilled.sum()) / demand_units if demand_units else 1.0,
        order_fill_rate=float(fully_filled.mean()) if instance.n_orders else 1.0,
        otif_rate=float(on_time_orders.mean()) if instance.n_orders else 1.0,
        on_time_unit_rate=(
            on_time_units / demand_units if demand_units else 1.0
        ),
        split_rate=(
            float((splits > 1).mean()) if instance.n_orders else 0.0
        ),
        shipments_count=int(order_flags.sum()),
        avg_transit_days=(
            float((shipments * matrices["transit"]).sum()) / float(fulfilled.sum())
            if fulfilled.sum()
            else 0.0
        ),
        dc_units=dc_units.astype(np.int64),
        dc_utilization=np.divide(
            dc_units,
            instance.dc_capacity,
            out=np.zeros(instance.n_dcs, dtype=float),
            where=instance.dc_capacity > 0,
        ),
        stock_used=stock_used,
        solve_seconds=float(solve_seconds),
        best_bound=float(best_bound) if best_bound is not None else float("nan"),
    )


def allocate_greedy(
    instance: FulfillmentInstance, max_splits: int = 2
) -> FulfillmentResult:
    """Deadline-first baseline: one fully-stocking on-time DC, then spill over.

    Orders are processed by tightest promise first. For each order the solver
    looks for a single DC that can fill every line on time; only if none exists
    does it split across the cheapest remaining DCs, up to ``max_splits``.
    """
    if max_splits < 1:
        raise ValueError("max_splits 必须 >= 1")
    started = time.perf_counter()
    stock = instance.stock.copy()
    capacity = instance.dc_capacity.copy()
    shipments = np.zeros((instance.n_lines, instance.n_dcs), dtype=np.int64)
    lines_by_order = instance.lines_by_order()
    order_units = instance.order_units()

    dc_order_cache = [
        sorted(
            range(instance.n_dcs),
            key=lambda d: (
                instance.transit_days[d, order] > instance.promise_days[order],
                instance.ship_cost[d, order],
                d,
            ),
        )
        for order in range(instance.n_orders)
    ]

    for order in sorted(
        range(instance.n_orders), key=lambda o: (instance.promise_days[o], -order_units[o], o)
    ):
        lines = lines_by_order[order]
        remaining = instance.line_qty[lines] - shipments[lines].sum(axis=1)
        needed = float(remaining.sum())
        chosen = None
        for dc in dc_order_cache[order]:
            if capacity[dc] < needed:
                continue
            sku_need: Dict[int, int] = {}
            for line, need in zip(lines, remaining):
                sku_need[int(instance.line_sku[line])] = (
                    sku_need.get(int(instance.line_sku[line]), 0) + int(need)
                )
            if all(stock[dc, sku] >= need for sku, need in sku_need.items()):
                chosen = dc
                break
        if chosen is not None:
            for line, need in zip(lines, remaining):
                if need <= 0:
                    continue
                shipments[line, chosen] += need
                stock[chosen, instance.line_sku[line]] -= need
                capacity[chosen] -= need
            continue

        used = 0
        for dc in dc_order_cache[order]:
            if used >= max_splits:
                break
            allocated = False
            for line in lines:
                need = int(
                    instance.line_qty[line] - shipments[line].sum()
                )
                if need <= 0:
                    continue
                sku = int(instance.line_sku[line])
                take = int(min(need, stock[dc, sku], capacity[dc]))
                if take <= 0:
                    continue
                shipments[line, dc] += take
                stock[dc, sku] -= take
                capacity[dc] -= take
                allocated = True
            if allocated:
                used += 1

    return evaluate_allocation(
        instance,
        shipments,
        name="greedy",
        status="HEURISTIC",
        solve_seconds=time.perf_counter() - started,
        max_splits=max_splits,
    )


def allocate_milp(
    instance: FulfillmentInstance,
    max_splits: int = 2,
    time_limit_seconds: float = 20.0,
    workers: int = 1,
    name: Optional[str] = None,
    late_penalty_per_unit_day: Optional[float] = None,
    otif_bonus: float = 0.0,
    pick_deadlines: Optional[Dict[int, float]] = None,
    pick_minutes_per_line: float = PICK_MINUTES_PER_LINE,
    pick_minutes_per_unit: float = PICK_MINUTES_PER_UNIT,
    pick_minutes_per_shipment: float = PICK_MINUTES_PER_SHIPMENT,
    pick_overload_penalty: float = 0.0,
    order_priority: Optional[np.ndarray] = None,
    hint: Optional["FulfillmentResult"] = None,
) -> FulfillmentResult:
    """CP-SAT allocation with inventory, throughput, and split constraints.

    ``late_penalty_per_unit_day`` overrides the objective weight only; reported
    costs and OTIF always use the instance's base penalty, so service-weighted
    runs stay comparable with the base scenarios. ``otif_bonus`` adds a
    per-order reward for being fully shipped on time.

    ``order_priority`` optionally multiplies each order's unmet and late
    penalties in the objective (not the reported costs). A high-value order
    with priority 3 is three times as expensive to leave unmet or late, so
    scarce stock moves toward it. The weights do not create inventory; they
    only change who gets it.

    ``pick_deadlines`` activates the pick-capacity proxy: for each DC, the
    pick-minutes of all shipments whose promise (in days) is at most ``days``
    must fit before ``pick_deadlines[days]`` minutes after shift start. The
    proxy is cumulative (the 480-min window includes the 240-min one) and uses
    linear pick-time coefficients, so it approximates a wave-picking shift
    without modelling batching. A positive ``pick_overload_penalty`` turns the
    constraint soft and prices each overloaded pick-minute in currency units;
    zero keeps it hard.
    """
    if max_splits < 1:
        raise ValueError("max_splits 必须 >= 1")
    if time_limit_seconds <= 0:
        raise ValueError("time_limit_seconds 必须为正")
    if workers < 1:
        raise ValueError("workers 必须 >= 1")
    if otif_bonus < 0:
        raise ValueError("otif_bonus 不能为负")
    priority = None
    if order_priority is not None:
        priority = np.asarray(order_priority, dtype=float)
        if priority.shape != (instance.n_orders,):
            raise ValueError("order_priority 必须与订单数一致")
        if not np.all(np.isfinite(priority)) or np.any(priority <= 0):
            raise ValueError("order_priority 必须为有限正数")
    late_penalty = (
        instance.late_penalty_per_unit_day
        if late_penalty_per_unit_day is None
        else float(late_penalty_per_unit_day)
    )
    if late_penalty < 0:
        raise ValueError("late_penalty_per_unit_day 不能为负")
    if pick_deadlines is not None:
        if any(float(value) <= 0 for value in pick_deadlines.values()):
            raise ValueError("pick_deadlines 必须为正")
        if not set(pick_deadlines) >= set(int(value) for value in np.unique(instance.promise_days)):
            raise ValueError("pick_deadlines 必须覆盖全部承诺天数")
        if pick_overload_penalty < 0:
            raise ValueError("pick_overload_penalty 不能为负")

    model = cp_model.CpModel()
    lines = range(instance.n_lines)
    dcs = range(instance.n_dcs)
    orders = range(instance.n_orders)
    x: Dict[tuple, Any] = {}
    unmet: Dict[int, Any] = {}
    shipment: Dict[tuple, Any] = {}
    for order in orders:
        for dc in dcs:
            shipment[order, dc] = model.NewBoolVar(f"s_{order}_{dc}")
    for line in lines:
        qty = int(instance.line_qty[line])
        unmet[line] = model.NewIntVar(0, qty, f"u_{line}")
        for dc in dcs:
            x[line, dc] = model.NewIntVar(0, qty, f"x_{line}_{dc}")

    for order in orders:
        model.Add(sum(shipment[order, dc] for dc in dcs) <= max_splits)
    for line in lines:
        order = int(instance.line_order[line])
        qty = int(instance.line_qty[line])
        model.Add(sum(x[line, dc] for dc in dcs) + unmet[line] == qty)
        for dc in dcs:
            model.Add(x[line, dc] <= qty * shipment[order, dc])

    for dc in dcs:
        model.Add(sum(x[line, dc] for line in lines) <= int(instance.dc_capacity[dc]))
        for sku in range(instance.n_skus):
            sku_lines = [
                line
                for line in lines
                if int(instance.line_sku[line]) == sku
            ]
            if sku_lines:
                model.Add(
                    sum(x[line, dc] for line in sku_lines) <= int(instance.stock[dc, sku])
                )

    pick_terms = []
    touch: Dict[tuple, Any] = {}
    slack_vars: Dict[tuple, Any] = {}
    if pick_deadlines is not None:
        line_days = [
            int(instance.promise_days[int(instance.line_order[line])])
            for line in lines
        ]
        order_days = [int(instance.promise_days[order]) for order in orders]
        line_coef = int(round(pick_minutes_per_line * PICK_SCALE))
        unit_coef = int(round(pick_minutes_per_unit * PICK_SCALE))
        ship_coef = int(round(pick_minutes_per_shipment * PICK_SCALE))
        touch: Dict[tuple, Any] = {}
        for line in lines:
            qty = int(instance.line_qty[line])
            for dc in dcs:
                touch[line, dc] = model.NewBoolVar(f"touch_{line}_{dc}")
                model.Add(x[line, dc] <= qty * touch[line, dc])
        pick_bound = sum(
            line_coef + unit_coef * int(instance.line_qty[line]) for line in lines
        ) + ship_coef * len(orders)
        for dc in dcs:
            for days in sorted(int(key) for key in pick_deadlines):
                deadline = int(round(float(pick_deadlines[days]) * PICK_SCALE))
                pieces = []
                for line in lines:
                    if line_days[line] <= days:
                        pieces.append(line_coef * touch[line, dc])
                        pieces.append(unit_coef * x[line, dc])
                for order in orders:
                    if order_days[order] <= days:
                        pieces.append(ship_coef * shipment[order, dc])
                if not pieces:
                    continue
                pick_expr = sum(pieces)
                if pick_overload_penalty > 0:
                    slack = model.NewIntVar(
                        0, pick_bound, f"pick_slack_{dc}_{days}"
                    )
                    slack_vars[dc, days] = slack
                    model.Add(pick_expr <= deadline + slack)
                    pick_terms.append(
                        int(round(pick_overload_penalty * COST_SCALE / PICK_SCALE))
                        * slack
                    )
                else:
                    model.Add(pick_expr <= deadline)

    terms = []
    for line in lines:
        order = int(instance.line_order[line])
        weight = float(priority[order]) if priority is not None else 1.0
        for dc in dcs:
            coefficient = float(instance.ship_cost[dc, order])
            late_days = max(
                0,
                int(instance.transit_days[dc, order])
                - int(instance.promise_days[order]),
            )
            coefficient += late_days * late_penalty * weight
            terms.append(
                max(1, int(round(coefficient * COST_SCALE))) * x[line, dc]
            )
    for order in orders:
        for dc in dcs:
            terms.append(
                max(1, int(round(instance.fixed_ship_cost * COST_SCALE)))
                * shipment[order, dc]
            )
    for line in lines:
        order = int(instance.line_order[line])
        weight = float(priority[order]) if priority is not None else 1.0
        terms.append(
            max(
                1,
                int(
                    round(
                        instance.unmet_penalty_per_unit * weight * COST_SCALE
                    )
                ),
            )
            * unmet[line]
        )
    flags: Dict[int, Any] = {}
    if otif_bonus > 0:
        order_demand = instance.order_units()
        late_mask = instance.transit_days > instance.promise_days[None, :]
        for order in orders:
            demand = int(order_demand[order])
            if demand <= 0:
                continue
            flag = model.NewBoolVar(f"otif_{order}")
            flags[order] = flag
            order_lines = [
                line for line in lines if int(instance.line_order[line]) == order
            ]
            unmet_expression = sum(unmet[line] for line in order_lines)
            late_expression = sum(
                x[line, dc]
                for line in order_lines
                for dc in dcs
                if bool(late_mask[dc, order])
            )
            model.Add(unmet_expression + demand * flag <= demand)
            model.Add(late_expression + demand * flag <= demand)
            weight = float(priority[order]) if priority is not None else 1.0
            terms.append(
                -int(round(otif_bonus * weight * COST_SCALE)) * flag
            )
    model.Minimize(sum(terms) + sum(pick_terms))

    if hint is not None:
        hinted = np.asarray(hint.shipments, dtype=np.int64)
        if hinted.shape != (instance.n_lines, instance.n_dcs):
            raise ValueError("hint.shipments 形状应为 (lines, dcs)")
        order_flags = np.zeros((instance.n_orders, instance.n_dcs), dtype=bool)
        for line in lines:
            order_flags[int(instance.line_order[line])] |= hinted[line] > 0
        for line in lines:
            qty = int(instance.line_qty[line])
            model.AddHint(unmet[line], max(0, qty - int(hinted[line].sum())))
            for dc in dcs:
                value = int(hinted[line, dc])
                model.AddHint(x[line, dc], value)
                if (line, dc) in touch:
                    model.AddHint(touch[line, dc], 1 if value > 0 else 0)
        for order in orders:
            for dc in dcs:
                model.AddHint(shipment[order, dc], 1 if order_flags[order, dc] else 0)
        if flags:
            order_demand = instance.order_units()
            late_mask = instance.transit_days > instance.promise_days[None, :]
            for order, flag in flags.items():
                order_lines = [
                    line for line in lines if int(instance.line_order[line]) == order
                ]
                fully = all(
                    int(hinted[line].sum()) == int(instance.line_qty[line])
                    for line in order_lines
                )
                on_time = all(
                    not bool(late_mask[dc, order]) or int(hinted[line, dc]) == 0
                    for line in order_lines
                    for dc in dcs
                )
                model.AddHint(flag, 0 if fully and on_time else 1)
        if pick_deadlines is not None:
            for dc in dcs:
                for days in sorted(int(key) for key in pick_deadlines):
                    minutes = 0.0
                    for line in lines:
                        if int(instance.promise_days[int(instance.line_order[line])]) <= days:
                            value = int(hinted[line, dc])
                            if value > 0:
                                minutes += pick_minutes_per_line
                                minutes += pick_minutes_per_unit * value
                    for order in orders:
                        if int(instance.promise_days[order]) <= days and order_flags[order, dc]:
                            minutes += pick_minutes_per_shipment
                    if (dc, days) in slack_vars:
                        slack_value = max(
                            0, int(round((minutes - float(pick_deadlines[days])) * PICK_SCALE))
                        )
                        model.AddHint(slack_vars[dc, days], slack_value)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_seconds)
    solver.parameters.num_search_workers = int(workers)
    started = time.perf_counter()
    status_code = solver.Solve(model)
    elapsed = time.perf_counter() - started
    status = solver.StatusName(status_code)
    if status not in {"OPTIMAL", "FEASIBLE"}:
        raise RuntimeError(f"履约 MILP 未找到可行解: {status}")

    shipments = np.zeros((instance.n_lines, instance.n_dcs), dtype=np.int64)
    for line in lines:
        for dc in dcs:
            shipments[line, dc] = int(round(solver.Value(x[line, dc])))

    return evaluate_allocation(
        instance,
        shipments,
        name=name or f"milp_split_{max_splits}",
        status=status,
        objective=solver.ObjectiveValue() / COST_SCALE,
        solve_seconds=elapsed,
        max_splits=max_splits,
        best_bound=solver.BestObjectiveBound() / COST_SCALE,
    )


def fulfillment_summary(results: Dict[str, FulfillmentResult]) -> pd.DataFrame:
    rows = []
    for key, result in results.items():
        rows.append(
            {
                "scenario": result.name,
                "status": result.status,
                "unit fill": result.unit_fill_rate,
                "order fill": result.order_fill_rate,
                "OTIF": result.otif_rate,
                "on-time units": result.on_time_unit_rate,
                "split orders": result.split_rate,
                "shipments": result.shipments_count,
                "transport": result.transport_cost,
                "fixed": result.fixed_cost,
                "late": result.late_cost,
                "unmet": result.unmet_cost,
                "total": result.total_cost,
                "solve (s)": result.solve_seconds,
            }
        )
    return pd.DataFrame(rows)


def dc_table(instance: FulfillmentInstance, result: FulfillmentResult) -> pd.DataFrame:
    stock_remaining = instance.stock - result.stock_used
    return pd.DataFrame(
        {
            "DC": instance.dc_names,
            "units shipped": result.dc_units,
            "weekly capacity": instance.dc_capacity,
            "capacity use": result.dc_utilization,
            "stock left": stock_remaining.sum(axis=1),
        }
    )


def order_table(
    instance: FulfillmentInstance, result: FulfillmentResult
) -> pd.DataFrame:
    """Per-order assignment summary used for examples and diffing scenarios."""
    fulfilled_line = result.shipments.sum(axis=1)
    late_line = (
        result.shipments * (_line_matrices(instance)["late_days"] > 0)
    ).sum(axis=1)
    order_demand = np.bincount(
        instance.line_order, weights=instance.line_qty, minlength=instance.n_orders
    )
    order_fulfilled = np.bincount(
        instance.line_order, weights=fulfilled_line, minlength=instance.n_orders
    )
    order_late = np.bincount(
        instance.line_order, weights=late_line, minlength=instance.n_orders
    )
    order_flags = np.zeros((instance.n_orders, instance.n_dcs), dtype=bool)
    for line in range(instance.n_lines):
        order_flags[instance.line_order[line]] |= result.shipments[line] > 0
    rows = []
    for order in range(instance.n_orders):
        used = [
            instance.dc_names[dc]
            for dc in range(instance.n_dcs)
            if order_flags[order, dc]
        ]
        fully = bool(order_fulfilled[order] == order_demand[order])
        rows.append(
            {
                "order": instance.order_ids[order],
                "destination": instance.destinations[order],
                "promise": int(instance.promise_days[order]),
                "units": int(order_demand[order]),
                "fulfilled": int(order_fulfilled[order]),
                "late_units": int(order_late[order]),
                "unmet_units": int(order_demand[order] - order_fulfilled[order]),
                "dcs": used,
                "splits": len(used),
                "filled": fully,
                "otif": bool(fully and order_late[order] == 0),
            }
        )
    return pd.DataFrame(rows)



def promise_table(
    instance: FulfillmentInstance, result: FulfillmentResult
) -> pd.DataFrame:
    """OTIF and lateness broken down by the declared promise tier."""
    fulfilled = result.shipments.sum(axis=1)
    late_line = (result.shipments * (
        _line_matrices(instance)["late_days"] > 0
    )).sum(axis=1)
    order_demand = np.bincount(
        instance.line_order, weights=instance.line_qty, minlength=instance.n_orders
    )
    order_fulfilled = np.bincount(
        instance.line_order, weights=fulfilled, minlength=instance.n_orders
    )
    order_late = np.bincount(
        instance.line_order, weights=late_line, minlength=instance.n_orders
    )
    order_unmet = order_demand - order_fulfilled
    rows = []
    for days in np.unique(instance.promise_days):
        mask = instance.promise_days == days
        rows.append(
            {
                "promise": f"{int(days)} days",
                "orders": int(mask.sum()),
                "OTIF": float(
                    ((order_fulfilled == order_demand) & (order_late == 0))[mask].mean()
                ),
                "late units": int(order_late[mask].sum()),
                "unmet units": int(order_unmet[mask].sum()),
            }
        )
    return pd.DataFrame(rows)
