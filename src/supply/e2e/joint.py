"""Week-13 joint allocation and stock placement.

Weeks 9-12 keep the DC stock split fixed and vary execution. Week 11 shows the
split changes service but is not optimised with the allocation; Week 12 shows
mid-shift rerouting needs spare pick capacity. This module treats placement and
allocation as one planning problem:

* ``destination`` placement is deployable: each SKU's stock follows its own
  destination-region mix over the prior weeks (UK -> London, EU -> Rotterdam /
  Frankfurt by a declared split). It uses only data available before the week.
* ``joint`` placement is the plan-driven counterfactual: an allocation MILP sees
  only the per-SKU total stock, then materialises the implied placement where
  the plan ships. It is an upper bound on what joint planning can buy for a
  known week, not a deployable forecast.

Both keep the total stock per SKU fixed, so the comparison isolates *where*
inventory sits and *whether* allocation may choose it. The pick layer is still
the Week-8 online release with the Week-9 cutoffs; the pick-capacity proxy in
the MILP is linear minutes, not a wave simulation.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from ortools.sat.python import cp_model

from supply.fulfillment import FulfillmentResult, allocate_greedy, allocate_milp
from supply.fulfillment.solvers import (
    COST_SCALE,
    PICK_MINUTES_PER_LINE,
    PICK_MINUTES_PER_SHIPMENT,
    PICK_MINUTES_PER_UNIT,
    PICK_SCALE,
    evaluate_allocation,
)

from .instances import E2EInstance, PROMISE_TIER, TIER_CUTOFFS

DEFAULT_LOOKBACK_WEEKS = 8
DEFAULT_EU_SPLIT = (0.45, 0.55)  # Rotterdam / Frankfurt inside EU demand
DEFAULT_FALLBACK_SHARES = (0.34, 0.28, 0.38)
DEFAULT_PICK_DEADLINES = {days: TIER_CUTOFFS[tier] for days, tier in PROMISE_TIER.items()}
UK_COUNTRY = "United Kingdom"


@dataclass(frozen=True)
class DestinationMix:
    """Prior-week destination mix per SKU and how much history backed it."""

    shares: np.ndarray  # (skus, dcs)
    history_skus: int
    fallback_skus: int
    weeks_used: int
    start_week: str
    end_week: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "history_skus": int(self.history_skus),
            "fallback_skus": int(self.fallback_skus),
            "weeks_used": int(self.weeks_used),
            "start_week": self.start_week,
            "end_week": self.end_week,
        }


@dataclass(frozen=True)
class PlacementPlan:
    """One materialised stock placement (units per DC and SKU)."""

    key: str
    label: str
    stock: np.ndarray  # (dcs, skus)
    note: str = ""
    source: str = "declared"

    def __post_init__(self) -> None:
        if not self.key or not self.label:
            raise ValueError("库存布点需要 key 与 label")
        stock = np.asarray(self.stock, dtype=np.int64)
        if stock.ndim != 2:
            raise ValueError("库存布点应为 (dcs, skus)")
        if np.any(stock < 0):
            raise ValueError("库存布点不能为负")
        object.__setattr__(self, "stock", stock)

    @property
    def units(self) -> int:
        return int(self.stock.sum())

    @property
    def mix(self) -> List[float]:
        total = self.units
        if total <= 0:
            return [0.0 for _ in range(self.stock.shape[0])]
        return [float(value) for value in self.stock.sum(axis=1) / total]

    def as_dict(self, dcs: Sequence[str]) -> Dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "stock": self.stock.tolist(),
            "stock_mix": self.mix,
            "stock_units": [int(value) for value in self.stock.sum(axis=1)],
            "coverage": None,
            "dcs": list(dcs),
            "source": self.source,
            "note": self.note,
        }


@dataclass
class JointResult:
    """Joint MILP output: the plan, the placement it implies, and its score."""

    allocation: FulfillmentResult
    stock: np.ndarray
    stock_mix: List[float]
    status: str
    objective: float
    solve_seconds: float
    best_bound: float
    gap: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "objective": self.objective,
            "solve_seconds": self.solve_seconds,
            "best_bound": self.best_bound,
            "gap": self.gap,
            "stock_mix": self.stock_mix,
            "stock_units": [int(value) for value in self.stock.sum(axis=1)],
        }


def _largest_remainder(total: int, shares: np.ndarray) -> np.ndarray:
    """Split an integer total by shares, preserving the total exactly."""
    total = int(total)
    shares = np.asarray(shares, dtype=float)
    if total < 0:
        raise ValueError("拆分总量不能为负")
    if shares.ndim != 1 or shares.size == 0:
        raise ValueError("拆分占比应为一维非空数组")
    if np.any(~np.isfinite(shares)) or np.any(shares < 0) or shares.sum() <= 0:
        raise ValueError("拆分占比必须非负且和为正")
    if total == 0:
        return np.zeros(shares.size, dtype=np.int64)
    weights = shares / shares.sum()
    raw = total * weights
    base = np.floor(raw).astype(np.int64)
    remainder = int(total - base.sum())
    if remainder > 0:
        order = np.argsort(-(raw - base))
        base[order[:remainder]] += 1
    return base


def _materialize(totals: np.ndarray, shares: np.ndarray) -> np.ndarray:
    totals = np.asarray(totals, dtype=np.int64)
    shares = np.asarray(shares, dtype=float)
    if shares.ndim != 2 or shares.shape[0] != totals.size:
        raise ValueError("占比矩阵应为 (skus, dcs)")
    stock = np.zeros((shares.shape[1], totals.size), dtype=np.int64)
    for sku, total in enumerate(totals):
        stock[:, sku] = _largest_remainder(int(total), shares[sku])
    return stock


def destination_mix(
    clean: pd.DataFrame,
    skus: Sequence[str],
    week: pd.Timestamp | str,
    lookback_weeks: int = DEFAULT_LOOKBACK_WEEKS,
    eu_split: Tuple[float, float] = DEFAULT_EU_SPLIT,
    fallback: Sequence[float] = DEFAULT_FALLBACK_SHARES,
) -> DestinationMix:
    """Per-SKU prior-week destination mix: UK -> London, EU -> Rotterdam/Frankfurt.

    The split inside the EU is declared, not inferred from the data. SKUs with
    no prior history fall back to the declared baseline shares.
    """
    if lookback_weeks < 1:
        raise ValueError("历史回看周数必须为正")
    if len(eu_split) != 2 or any(value <= 0 for value in eu_split):
        raise ValueError("欧洲内部拆分必须为两个正数")
    if abs(sum(eu_split) - 1.0) > 1e-6:
        raise ValueError("欧洲内部拆分之和应为 1")
    shares_fallback = np.asarray(fallback, dtype=float)
    if shares_fallback.shape != (3,) or np.any(shares_fallback <= 0):
        raise ValueError("回退占比应为 3 个正数")
    shares_fallback = shares_fallback / shares_fallback.sum()

    target = pd.Timestamp(week)
    start = target - pd.Timedelta(weeks=lookback_weeks)
    frame = clean.loc[
        (clean["week"] < target) & (clean["week"] >= start),
        ["sku", "country", "quantity", "week"],
    ].copy()
    frame["sku"] = frame["sku"].astype(str)
    frame["quantity"] = frame["quantity"].astype(float).clip(lower=0.0)
    frame["region"] = np.where(frame["country"] == UK_COUNTRY, "uk", "eu")
    grouped = (
        frame.groupby(["sku", "region"])["quantity"].sum().unstack(fill_value=0.0)
    )
    for column in ("uk", "eu"):
        if column not in grouped:
            grouped[column] = 0.0
    grouped = grouped.reindex([str(sku) for sku in skus], fill_value=0.0)

    shares = np.zeros((len(skus), 3), dtype=float)
    history = 0
    for index, sku in enumerate(skus):
        uk = float(grouped.loc[str(sku), "uk"])
        eu = float(grouped.loc[str(sku), "eu"])
        total = uk + eu
        if total <= 0:
            shares[index] = shares_fallback
            continue
        history += 1
        uk_share = uk / total
        shares[index, 0] = uk_share
        shares[index, 1] = (1.0 - uk_share) * eu_split[0]
        shares[index, 2] = (1.0 - uk_share) * eu_split[1]
    shares = shares / shares.sum(axis=1, keepdims=True)

    weeks = sorted(pd.to_datetime(frame["week"]).unique()) if not frame.empty else []
    return DestinationMix(
        shares=shares,
        history_skus=history,
        fallback_skus=len(skus) - history,
        weeks_used=len(weeks),
        start_week=str(pd.Timestamp(weeks[0]).date()) if weeks else "",
        end_week=str(pd.Timestamp(weeks[-1]).date()) if weeks else "",
    )


def placement_from_shares(
    instance: E2EInstance,
    shares: np.ndarray,
    key: str,
    label: str,
    note: str = "",
    source: str = "declared",
) -> PlacementPlan:
    """Build a placement with the instance's per-SKU stock totals."""
    shares = np.asarray(shares, dtype=float)
    expected = (instance.fulfillment.n_skus, instance.fulfillment.n_dcs)
    if shares.shape != expected:
        raise ValueError(f"占比矩阵形状应为 {expected}")
    totals = np.asarray(instance.fulfillment.stock, dtype=np.int64).sum(axis=0)
    stock = _materialize(totals, shares)
    return PlacementPlan(
        key=key, label=label, stock=stock, note=note, source=source
    )


def cap_shares(
    shares: np.ndarray,
    capacity: np.ndarray,
    stock_units: int,
) -> np.ndarray:
    """Cap each DC's per-SKU stock share at its share of weekly throughput.

    A destination mix can send more stock to a DC than that DC can ship in the
    week. This caps every SKU at ``capacity / stock_units`` and redistributes the
    excess to the DCs with remaining headroom in proportion to that headroom.
    """
    shares = np.asarray(shares, dtype=float)
    capacity = np.asarray(capacity, dtype=float)
    if shares.ndim != 2 or capacity.shape != (shares.shape[1],):
        raise ValueError("占比矩阵与产能向量形状不匹配")
    if stock_units <= 0:
        raise ValueError("库存总量必须为正")
    if np.any(~np.isfinite(shares)) or np.any(shares < 0):
        raise ValueError("占比必须非负")
    if np.any(capacity <= 0):
        raise ValueError("DC 产能必须为正")
    caps = capacity / float(stock_units)
    if caps.sum() < 1.0 - 1e-9:
        raise ValueError("DC 产能之和不足以容纳全部库存，无法封顶布点")
    rows = []
    for row in shares:
        if row.sum() <= 0:
            raise ValueError("每个 SKU 的占比和必须为正")
        row = row / row.sum()
        clipped = np.minimum(row, caps)
        deficit = 1.0 - clipped.sum()
        if deficit > 1e-12:
            headroom = caps - clipped
            if headroom.sum() <= 0:
                raise ValueError("没有可承接超额库存的 DC 产能")
            clipped = clipped + deficit * headroom / headroom.sum()
        rows.append(clipped / clipped.sum())
    return np.vstack(rows)


def with_stock(
    instance: E2EInstance,
    stock: np.ndarray,
    key: str = "custom",
    label: Optional[str] = None,
) -> E2EInstance:
    """Replace only the DC stock matrix, keeping orders, slots and arrivals."""
    stock = np.asarray(stock, dtype=np.int64)
    original = np.asarray(instance.fulfillment.stock, dtype=np.int64)
    if stock.shape != original.shape:
        raise ValueError("库存矩阵形状应与实例一致")
    if np.any(stock < 0):
        raise ValueError("库存不能为负")
    if not np.array_equal(stock.sum(axis=0), original.sum(axis=0)):
        raise ValueError("库存布点必须保持每个 SKU 的总库存不变")

    total_units = float(instance.fulfillment.line_qty.sum())
    total_stock = float(stock.sum())
    mix = (
        [float(value) for value in stock.sum(axis=1) / total_stock]
        if total_stock > 0
        else [0.0 for _ in range(stock.shape[0])]
    )
    coverage = total_stock / total_units if total_units else 0.0
    placement_label = label or key

    fulfillment_meta = dict(instance.fulfillment.meta)
    fulfillment_meta.update(
        {
            "stock_units": int(total_stock),
            "stock_coverage": coverage,
            "stock_shares": mix,
            "stock_plan": key,
            "stock_placement_label": placement_label,
        }
    )
    fulfillment = replace(
        instance.fulfillment, stock=stock.copy(), meta=fulfillment_meta
    )
    meta = dict(instance.meta)
    meta.update(
        {
            "stock_plan": key,
            "stock_placement_label": placement_label,
            "stock_units": int(total_stock),
            "stock_coverage": coverage,
            "stock_shares": mix,
        }
    )
    return replace(instance, fulfillment=fulfillment, meta=meta)


def placement_row(
    plan: PlacementPlan, instance: E2EInstance
) -> Dict[str, Any]:
    row = plan.as_dict(instance.fulfillment.dc_names)
    total_units = float(instance.fulfillment.line_qty.sum())
    row["coverage"] = float(plan.units / total_units) if total_units else 0.0
    return row


def paired_placements(
    frame: pd.DataFrame,
    left: str,
    right: str,
    labels: Optional[Mapping[str, str]] = None,
    metric: str = "e2e_otif_rate",
) -> pd.DataFrame:
    """Per-cell paired difference ``right - left`` on shared seeds."""
    if metric not in frame.columns:
        raise ValueError(f"缺少指标列: {metric}")
    labels = dict(labels or {})
    rows: List[Dict[str, object]] = []
    for cell, block in frame.groupby("cell", sort=False):
        first = block[block["scenario"] == left].set_index("seed")[metric]
        second = block[block["scenario"] == right].set_index("seed")[metric]
        common = first.index.intersection(second.index)
        if len(common) == 0:
            continue
        delta = (second.loc[common] - first.loc[common]).astype(float).to_numpy()
        sd = float(delta.std(ddof=1)) if delta.size > 1 else 0.0
        ci95 = 1.96 * sd / np.sqrt(delta.size) if delta.size > 1 else 0.0
        name = lambda key: labels.get(key, key)
        rows.append(
            {
                "scenario": right,
                "cell": cell,
                "cell_label": str(block["cell_label"].iloc[0]),
                "left": left,
                "right": right,
                "comparison": f"{name(right)} − {name(left)}",
                "metric": metric,
                "n": int(delta.size),
                "mean_delta": float(delta.mean()),
                "ci95": ci95,
                "win_rate": float((delta > 0).mean()),
                "loss_rate": float((delta < 0).mean()),
                "tie_rate": float((delta == 0).mean()),
                "min_delta": float(delta.min()),
                "max_delta": float(delta.max()),
            }
        )
    return pd.DataFrame(rows)


def capacity_aware_allocation(
    instance: E2EInstance,
    service_time: float = 30.0,
    milp_time: float = 60.0,
    workers: int = 4,
    service_late_weight: float = 5.0,
    service_otif_bonus: float = 200.0,
    pick_overload_penalty: float = 5.0,
    pick_deadlines: Optional[Mapping[int, float]] = None,
    name: Optional[str] = None,
) -> FulfillmentResult:
    """Week-9 two-stage allocation on a fixed placement (service warm start)."""
    fulfillment = instance.fulfillment
    label = name or str(fulfillment.meta.get("stock_plan", "placement"))
    deadlines = dict(pick_deadlines or DEFAULT_PICK_DEADLINES)
    service = allocate_milp(
        fulfillment,
        max_splits=2,
        time_limit_seconds=service_time,
        workers=workers,
        late_penalty_per_unit_day=fulfillment.late_penalty_per_unit_day
        * service_late_weight,
        otif_bonus=service_otif_bonus,
        name=f"{label} · 服务优先",
    )
    return allocate_milp(
        fulfillment,
        max_splits=2,
        time_limit_seconds=milp_time,
        workers=workers,
        late_penalty_per_unit_day=fulfillment.late_penalty_per_unit_day
        * service_late_weight,
        otif_bonus=service_otif_bonus,
        pick_deadlines=deadlines,
        pick_overload_penalty=pick_overload_penalty,
        hint=service,
        name=f"{label} · 拣选容量感知",
    )


def allocate_joint(
    instance: E2EInstance,
    max_splits: int = 2,
    time_limit_seconds: float = 60.0,
    workers: int = 4,
    late_penalty_per_unit_day: Optional[float] = None,
    otif_bonus: float = 0.0,
    pick_deadlines: Optional[Mapping[int, float]] = None,
    pick_minutes_per_line: float = PICK_MINUTES_PER_LINE,
    pick_minutes_per_unit: float = PICK_MINUTES_PER_UNIT,
    pick_minutes_per_shipment: float = PICK_MINUTES_PER_SHIPMENT,
    pick_overload_penalty: float = 0.0,
    reserve_shares: Optional[np.ndarray] = None,
    hint: Optional[FulfillmentResult] = None,
    name: str = "joint",
) -> JointResult:
    """Allocate orders while placement is free, then materialise the placement.

    The only stock constraint is the per-SKU total, so the model may put stock
    where it ships. The implied placement puts used units at their shipping DC
    and splits the unallocated reserve by ``reserve_shares`` (uniform by
    default). The returned allocation is re-scored on that placement.
    """
    fulfillment = instance.fulfillment
    if max_splits < 1:
        raise ValueError("max_splits 必须 >= 1")
    if time_limit_seconds <= 0:
        raise ValueError("time_limit_seconds 必须为正")
    if workers < 1:
        raise ValueError("workers 必须 >= 1")
    if otif_bonus < 0:
        raise ValueError("otif_bonus 不能为负")
    late_penalty = (
        fulfillment.late_penalty_per_unit_day
        if late_penalty_per_unit_day is None
        else float(late_penalty_per_unit_day)
    )
    if late_penalty < 0:
        raise ValueError("late_penalty_per_unit_day 不能为负")
    if pick_deadlines is not None:
        if any(float(value) <= 0 for value in pick_deadlines.values()):
            raise ValueError("pick_deadlines 必须为正")
        if not set(pick_deadlines) >= set(
            int(value) for value in np.unique(fulfillment.promise_days)
        ):
            raise ValueError("pick_deadlines 必须覆盖全部承诺天数")
        if pick_overload_penalty < 0:
            raise ValueError("pick_overload_penalty 不能为负")

    n_lines = fulfillment.n_lines
    n_dcs = fulfillment.n_dcs
    n_skus = fulfillment.n_skus
    n_orders = fulfillment.n_orders
    lines = range(n_lines)
    dcs = range(n_dcs)
    orders = range(n_orders)
    stock_total = np.asarray(fulfillment.stock, dtype=np.int64).sum(axis=0)
    if np.any(stock_total <= 0):
        raise ValueError("每个 SKU 的总库存必须为正")

    if reserve_shares is None:
        reserve = np.full((n_skus, n_dcs), 1.0 / n_dcs)
    else:
        reserve = np.asarray(reserve_shares, dtype=float)
        if reserve.shape != (n_skus, n_dcs):
            raise ValueError("reserve_shares 形状应为 (skus, dcs)")
        if np.any(~np.isfinite(reserve)) or np.any(reserve < 0):
            raise ValueError("reserve_shares 必须非负")
        if np.any(reserve.sum(axis=1) <= 0):
            raise ValueError("每个 SKU 的 reserve_shares 和必须为正")
        reserve = reserve / reserve.sum(axis=1, keepdims=True)

    model = cp_model.CpModel()
    x: Dict[tuple, Any] = {}
    unmet: Dict[int, Any] = {}
    shipment: Dict[tuple, Any] = {}
    for order in orders:
        for dc in dcs:
            shipment[order, dc] = model.NewBoolVar(f"s_{order}_{dc}")
    for line in lines:
        qty = int(fulfillment.line_qty[line])
        unmet[line] = model.NewIntVar(0, qty, f"u_{line}")
        for dc in dcs:
            x[line, dc] = model.NewIntVar(0, qty, f"x_{line}_{dc}")

    for order in orders:
        model.Add(sum(shipment[order, dc] for dc in dcs) <= max_splits)
    for line in lines:
        order = int(fulfillment.line_order[line])
        qty = int(fulfillment.line_qty[line])
        model.Add(sum(x[line, dc] for dc in dcs) + unmet[line] == qty)
        for dc in dcs:
            model.Add(x[line, dc] <= qty * shipment[order, dc])
    for dc in dcs:
        model.Add(
            sum(x[line, dc] for line in lines) <= int(fulfillment.dc_capacity[dc])
        )
    for sku in range(n_skus):
        sku_lines = [line for line in lines if int(fulfillment.line_sku[line]) == sku]
        if sku_lines:
            model.Add(
                sum(x[line, dc] for line in sku_lines for dc in dcs)
                <= int(stock_total[sku])
            )

    pick_terms: List[Any] = []
    slack_vars: Dict[tuple, Any] = {}
    touch: Dict[tuple, Any] = {}
    if pick_deadlines is not None:
        line_days = [
            int(fulfillment.promise_days[int(fulfillment.line_order[line])])
            for line in lines
        ]
        order_days = [int(fulfillment.promise_days[order]) for order in orders]
        line_coef = int(round(pick_minutes_per_line * PICK_SCALE))
        unit_coef = int(round(pick_minutes_per_unit * PICK_SCALE))
        ship_coef = int(round(pick_minutes_per_shipment * PICK_SCALE))
        for line in lines:
            qty = int(fulfillment.line_qty[line])
            for dc in dcs:
                touch[line, dc] = model.NewBoolVar(f"touch_{line}_{dc}")
                model.Add(x[line, dc] <= qty * touch[line, dc])
        pick_bound = sum(
            line_coef + unit_coef * int(fulfillment.line_qty[line])
            for line in lines
        ) + ship_coef * n_orders
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
                expression = sum(pieces)
                if pick_overload_penalty > 0:
                    slack = model.NewIntVar(
                        0, pick_bound, f"pick_slack_{dc}_{days}"
                    )
                    slack_vars[dc, days] = slack
                    model.Add(expression <= deadline + slack)
                    pick_terms.append(
                        int(round(pick_overload_penalty * COST_SCALE / PICK_SCALE))
                        * slack
                    )
                else:
                    model.Add(expression <= deadline)

    terms: List[Any] = []
    for line in lines:
        order = int(fulfillment.line_order[line])
        for dc in dcs:
            coefficient = float(fulfillment.ship_cost[dc, order])
            late_days = max(
                0,
                int(fulfillment.transit_days[dc, order])
                - int(fulfillment.promise_days[order]),
            )
            coefficient += late_days * late_penalty
            terms.append(max(1, int(round(coefficient * COST_SCALE))) * x[line, dc])
    for order in orders:
        for dc in dcs:
            terms.append(
                max(1, int(round(fulfillment.fixed_ship_cost * COST_SCALE)))
                * shipment[order, dc]
            )
    for line in lines:
        terms.append(
            max(1, int(round(fulfillment.unmet_penalty_per_unit * COST_SCALE)))
            * unmet[line]
        )
    flags: Dict[int, Any] = {}
    if otif_bonus > 0:
        order_demand = fulfillment.order_units()
        late_mask = fulfillment.transit_days > fulfillment.promise_days[None, :]
        for order in orders:
            demand = int(order_demand[order])
            if demand <= 0:
                continue
            flag = model.NewBoolVar(f"otif_{order}")
            flags[order] = flag
            order_lines = [
                line for line in lines if int(fulfillment.line_order[line]) == order
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
            terms.append(-int(round(otif_bonus * COST_SCALE)) * flag)
    model.Minimize(sum(terms) + sum(pick_terms))

    if hint is not None:
        hinted = np.asarray(hint.shipments, dtype=np.int64)
        if hinted.shape != (n_lines, n_dcs):
            raise ValueError("hint.shipments 形状应为 (lines, dcs)")
        order_flags = np.zeros((n_orders, n_dcs), dtype=bool)
        for line in lines:
            order_flags[int(fulfillment.line_order[line])] |= hinted[line] > 0
        for line in lines:
            qty = int(fulfillment.line_qty[line])
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
            order_demand = fulfillment.order_units()
            late_mask = fulfillment.transit_days > fulfillment.promise_days[None, :]
            for order, flag in flags.items():
                order_lines = [
                    line
                    for line in lines
                    if int(fulfillment.line_order[line]) == order
                ]
                fully = all(
                    int(hinted[line].sum()) == int(fulfillment.line_qty[line])
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
                        if (
                            int(
                                fulfillment.promise_days[
                                    int(fulfillment.line_order[line])
                                ]
                            )
                            <= days
                        ):
                            value = int(hinted[line, dc])
                            if value > 0:
                                minutes += pick_minutes_per_line
                                minutes += pick_minutes_per_unit * value
                    for order in orders:
                        if (
                            int(fulfillment.promise_days[order]) <= days
                            and order_flags[order, dc]
                        ):
                            minutes += pick_minutes_per_shipment
                    if (dc, days) in slack_vars:
                        slack_value = max(
                            0,
                            int(
                                round(
                                    (minutes - float(pick_deadlines[days]))
                                    * PICK_SCALE
                                )
                            ),
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
        raise RuntimeError(f"联合分单-布点 MILP 未找到可行解: {status}")

    shipments = np.zeros((n_lines, n_dcs), dtype=np.int64)
    for line in lines:
        for dc in dcs:
            shipments[line, dc] = int(round(solver.Value(x[line, dc])))

    used = np.zeros((n_dcs, n_skus), dtype=np.int64)
    for line in lines:
        used[:, int(fulfillment.line_sku[line])] += shipments[line]
    leftover = stock_total - used.sum(axis=0)
    if np.any(leftover < 0):
        raise RuntimeError("联合方案的已分配库存超过每 SKU 总库存")
    stock = used.copy()
    for sku in range(n_skus):
        if leftover[sku] > 0:
            stock[:, sku] += _largest_remainder(int(leftover[sku]), reserve[sku])
    if not np.array_equal(stock.sum(axis=0), stock_total):
        raise RuntimeError("库存布点未保持每 SKU 总库存")

    placed = replace(fulfillment, stock=stock.copy())
    allocation = evaluate_allocation(
        placed,
        shipments,
        name=name,
        status=status,
        objective=solver.ObjectiveValue() / COST_SCALE,
        solve_seconds=elapsed,
        max_splits=max_splits,
        best_bound=solver.BestObjectiveBound() / COST_SCALE,
    )
    objective = float(solver.ObjectiveValue()) / COST_SCALE
    best_bound = float(solver.BestObjectiveBound()) / COST_SCALE
    gap = (
        max(0.0, (objective - best_bound) / abs(objective))
        if objective
        else float("nan")
    )
    total = float(stock.sum())
    mix = (
        [float(value) for value in stock.sum(axis=1) / total]
        if total > 0
        else [0.0 for _ in range(n_dcs)]
    )
    return JointResult(
        allocation=allocation,
        stock=stock,
        stock_mix=mix,
        status=status,
        objective=objective,
        solve_seconds=elapsed,
        best_bound=best_bound,
        gap=gap,
    )


def joint_plan(
    instance: E2EInstance,
    mix: DestinationMix,
    milp_time: float = 60.0,
    workers: int = 4,
    service_late_weight: float = 5.0,
    service_otif_bonus: float = 200.0,
    pick_overload_penalty: float = 5.0,
) -> JointResult:
    """Solve the joint MILP with a greedy warm start and destination reserve."""
    hint = allocate_greedy(instance.fulfillment, max_splits=2)
    return allocate_joint(
        instance,
        max_splits=2,
        time_limit_seconds=milp_time,
        workers=workers,
        late_penalty_per_unit_day=instance.fulfillment.late_penalty_per_unit_day
        * service_late_weight,
        otif_bonus=service_otif_bonus,
        pick_deadlines=DEFAULT_PICK_DEADLINES,
        pick_overload_penalty=pick_overload_penalty,
        reserve_shares=mix.shares,
        hint=hint,
        name="joint",
    )
