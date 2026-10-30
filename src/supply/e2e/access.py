"""Week 41: demand-weighted stock placement with a coverage MILP.

Week 40 varied four hand-picked DC stock splits and found only a directional,
non-robust difference. This module replaces the hand-picked splits with a small
integer program over the *same fixed total stock*:

    max   sum_{d,s} z[d,s]
    s.t.  sum_d y[d,s] = stock_total[s]              for every SKU s
          z[d,s] <= y[d,s]                            covered units
          z[d,s] <= round(demand[d,s])                demand ceiling
          min_share*T <= sum_s y[d,s] <= max_share*T  per-DC stock bounds
          y[d,s], z[d,s] integer >= 0

``demand[d,s]`` is a *partition* of demand: each order line (or historical
country x SKU flow) is assigned to one best on-time DC. Double-counting every
feasible DC was deliberately avoided because with 100% total stock it made the
coverage objective trivially satisfied by the current placement, so the MILP
never moved a unit. Two demand estimates are supported:

* ``oracle``: assign each current-week line to its best on-time DC (uses the
  realised order set; not a policy that could run before the week starts);
* ``history``: assign prior six weeks' country x SKU demand to the DC with the
  best on-time share for that country (a deployable estimate, but still uses
  the current destination/transit matrix).

The objective has a tiny secondary term that penalises moving stock away from
its current DC, so ties do not create arbitrary transfers. The solver is
single-threaded and seeded, because the same instance is replayed across 30
arrival seeds and we do not want solver scheduling noise inside an arm.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd
from ortools.sat.python import cp_model

from supply.fulfillment import FulfillmentInstance

from .instances import E2EInstance

DEFAULT_LOOKBACK_WEEKS = 6
DEFAULT_TIME_LIMIT = 10.0
DEFAULT_MOVE_PENALTY = 1_000_000


@dataclass(frozen=True)
class AccessDemand:
    """Demand reachable from each DC, in units, with an honest source label."""

    units: np.ndarray  # (dcs, skus), float
    source: str
    label: str

    def __post_init__(self) -> None:
        if self.units.ndim != 2:
            raise ValueError("demand 必须是 (dcs, skus)")
        if np.any(~np.isfinite(self.units)) or np.any(self.units < 0):
            raise ValueError("demand 必须是非负有限数")

    @property
    def total(self) -> float:
        return float(self.units.sum())


@dataclass(frozen=True)
class PlacementTarget:
    """Integer target stock and its MILP evidence."""

    stock: np.ndarray  # (dcs, skus), int64
    moved_units: int
    covered_units: float
    demand_units: float
    status: str
    objective: float
    source: str

    @property
    def optimal(self) -> bool:
        return self.status == "OPTIMAL"

    @property
    def coverage(self) -> float:
        return self.covered_units / self.demand_units if self.demand_units else 0.0


def _best_on_time_dc(f: FulfillmentInstance, order: int) -> Optional[int]:
    feasible = [
        dc
        for dc in range(f.n_dcs)
        if int(f.transit_days[dc, order]) <= int(f.promise_days[order])
    ]
    if not feasible:
        return None
    return min(
        feasible,
        key=lambda dc: (
            int(f.transit_days[dc, order]),
            float(f.ship_cost[dc, order]),
            dc,
        ),
    )


def oracle_access(instance: E2EInstance) -> AccessDemand:
    """Assign each realised line to its best on-time DC.

    The assignment partitions demand: every line contributes its quantity once,
    or not at all when no DC can meet the promise. It still uses the realised
    order set, so it is an oracle policy rather than a pre-week plan.
    """
    f = instance.fulfillment
    units = np.zeros((f.n_dcs, f.n_skus), dtype=float)
    for line in range(f.n_lines):
        order = int(f.line_order[line])
        sku = int(f.line_sku[line])
        quantity = float(f.line_qty[line])
        if quantity <= 0:
            continue
        dc = _best_on_time_dc(f, order)
        if dc is not None:
            units[dc, sku] += quantity
    return AccessDemand(units=units, source="oracle", label="本周实际最佳可达 DC 分配")


def history_access(
    clean: pd.DataFrame,
    instance: E2EInstance,
    week: pd.Timestamp,
    lookback_weeks: int = DEFAULT_LOOKBACK_WEEKS,
) -> AccessDemand:
    """Estimate reachable demand from prior weeks' country x SKU mix.

    The current week's *destinations and transit matrix* are used only to decide
    which country can be served on time from which DC; quantities come from the
    prior ``lookback_weeks`` weeks, averaged per week. This is a deployable
    estimate: it does not read the current week's order quantities.
    """
    if lookback_weeks < 1:
        raise ValueError("lookback_weeks 必须 >= 1")
    current = pd.Timestamp(week)
    start = current - pd.Timedelta(weeks=int(lookback_weeks))
    frame = clean.copy()
    frame["invoice_date"] = pd.to_datetime(frame["invoice_date"])
    frame = frame[
        (frame["invoice_date"] >= start) & (frame["invoice_date"] < current)
    ]
    frame = frame[frame["quantity"] > 0]
    if frame.empty:
        return AccessDemand(
            units=np.zeros((instance.fulfillment.n_dcs, instance.fulfillment.n_skus)),
            source="history",
            label=f"前 {lookback_weeks} 周历史需求",
        )

    history = (
        frame.groupby(["country", "sku"], observed=True)["quantity"]
        .sum()
        .div(float(lookback_weeks))
    )
    sku_index = {
        name: index for index, name in enumerate(instance.fulfillment.sku_names)
    }
    f = instance.fulfillment
    countries = np.asarray(f.destinations, dtype=object)
    # country -> mean on-time share over current orders from that country.
    shares: Dict[Tuple[int, str], float] = {}
    for country in pd.unique(countries):
        orders = np.flatnonzero(countries == country)
        if orders.size == 0:
            continue
        for dc in range(f.n_dcs):
            on_time = f.transit_days[dc, orders] <= f.promise_days[orders]
            shares[(dc, str(country))] = float(on_time.mean())

    best_dc: Dict[str, Optional[int]] = {}
    for country in pd.unique(countries):
        candidates = [
            (shares.get((dc, str(country)), 0.0), dc)
            for dc in range(f.n_dcs)
        ]
        # On a tie prefer the lower-index DC so the estimate is deterministic
        # and not biased towards the last warehouse in the list.
        share, dc = max(candidates, key=lambda item: (item[0], -item[1]))
        best_dc[str(country)] = dc if share > 0 else None

    units = np.zeros((f.n_dcs, f.n_skus), dtype=float)
    for (country, sku), quantity in history.items():
        sku_pos = sku_index.get(str(sku))
        if sku_pos is None:
            continue
        dc = best_dc.get(str(country))
        if dc is not None:
            units[dc, sku_pos] += float(quantity)
    return AccessDemand(
        units=units,
        source="history",
        label=f"前 {lookback_weeks} 周历史需求",
    )


def placement_milp(
    instance: E2EInstance,
    demand: AccessDemand,
    time_limit: float = DEFAULT_TIME_LIMIT,
    move_penalty: int = DEFAULT_MOVE_PENALTY,
    min_share: float = 0.0,
    max_share: float = 1.0,
) -> PlacementTarget:
    """Solve the fixed-total coverage model and return integer target stock.

    ``min_share`` / ``max_share`` bound the aggregate stock parked at one DC.
    Without them the coverage objective can put almost all stock into one DC and
    produce an operationally meaningless target; the Week-41 script uses
    10%/60% to keep the target inside the region the pick layer can actually run.
    """
    if time_limit <= 0:
        raise ValueError("time_limit 必须为正")
    if not 0.0 <= min_share <= max_share <= 1.0:
        raise ValueError("需要 0 <= min_share <= max_share <= 1")
    f = instance.fulfillment
    if demand.units.shape != (f.n_dcs, f.n_skus):
        raise ValueError("demand 形状与实例不一致")
    total_by_sku = f.stock.sum(axis=0).astype(np.int64)
    demand_int = np.rint(np.maximum(demand.units, 0.0)).astype(np.int64)

    model = cp_model.CpModel()
    target: Dict[Tuple[int, int], cp_model.IntVar] = {}
    covered: Dict[Tuple[int, int], cp_model.IntVar] = {}
    moves: list[cp_model.IntVar] = []
    total_stock = int(total_by_sku.sum())
    stock_by_dc: Dict[int, list[cp_model.IntVar]] = {
        dc: [] for dc in range(f.n_dcs)
    }
    for sku in range(f.n_skus):
        total = int(total_by_sku[sku])
        row = []
        for dc in range(f.n_dcs):
            current = int(f.stock[dc, sku])
            y = model.NewIntVar(0, total, f"y_{dc}_{sku}")
            z_upper = min(total, int(demand_int[dc, sku]))
            z = model.NewIntVar(0, z_upper, f"z_{dc}_{sku}")
            model.Add(z <= y)
            target[(dc, sku)] = y
            covered[(dc, sku)] = z
            move = model.NewIntVar(0, total, f"m_{dc}_{sku}")
            model.AddAbsEquality(move, y - current)
            moves.append(move)
            row.append(y)
            stock_by_dc[dc].append(y)
        model.Add(sum(row) == total)
    for dc, row in stock_by_dc.items():
        model.Add(sum(row) >= int(np.ceil(min_share * total_stock)))
        model.Add(sum(row) <= int(np.floor(max_share * total_stock)))
    model.Maximize(
        sum(covered.values()) * int(move_penalty) - sum(moves)
    )
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    status = solver.Solve(model)
    name = solver.StatusName(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"布点 MILP 未找到可行解: {name}")
    stock = np.zeros((f.n_dcs, f.n_skus), dtype=np.int64)
    for (dc, sku), var in target.items():
        stock[dc, sku] = int(solver.Value(var))
    # CP-SAT's secondary objective already minimises moves; recompute for audit.
    moved = int(np.maximum(stock - f.stock, 0).sum())
    return PlacementTarget(
        stock=stock,
        moved_units=moved,
        covered_units=float(sum(solver.Value(v) for v in covered.values())),
        demand_units=float(demand_int.sum()),
        status=name,
        objective=float(solver.ObjectiveValue()),
        source=demand.source,
    )


def apply_target(instance: E2EInstance, target: PlacementTarget) -> E2EInstance:
    """Replace only the stock matrix, preserving orders, capacities and transit."""
    f = instance.fulfillment
    stock = np.asarray(target.stock, dtype=np.int64)
    if stock.shape != f.stock.shape:
        raise ValueError("target stock 形状与实例不一致")
    if np.any(stock < 0):
        raise ValueError("target stock 不能为负")
    if not np.array_equal(stock.sum(axis=0), f.stock.sum(axis=0)):
        raise ValueError("target stock 必须保持每个 SKU 的总量")
    return replace(instance, fulfillment=replace(f, stock=stock))


def moved_units(current: np.ndarray, target: np.ndarray) -> int:
    """Units that leave a DC; equals half the L1 distance for conserved stock."""
    left = np.maximum(np.asarray(target) - np.asarray(current), 0)
    if not np.array_equal(np.asarray(current).sum(axis=0), np.asarray(target).sum(axis=0)):
        raise ValueError("stock 总量必须守恒")
    return int(left.sum())


def access_metadata(target: PlacementTarget) -> Dict[str, Any]:
    return {
        "source": target.source,
        "status": target.status,
        "optimal": target.optimal,
        "objective": target.objective,
        "coverage": target.coverage,
        "moved_units": target.moved_units,
    }
