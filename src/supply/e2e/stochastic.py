"""Week-14 two-stage stochastic stock placement.

Week 13 chooses one placement for the known target week. This module chooses a
placement *before* the week, using the last ``S`` weeks as equally weighted
demand scenarios, then lets the Week-9 allocator react to the actual orders.

* First stage: one integer placement ``z[k, d]`` per SKU and DC with the per-SKU
  total stock fixed.
* Second stage: a fluid allocation ``y[s, k, d]`` per scenario, bounded by the
  placement, by the units that DC can deliver inside the customer promise, and
  by the scenario's per-SKU demand. Each DC also has its weekly throughput cap.
* Objective: ``(1 - w) * E[unmet] + w * CVaR_alpha(unmet)`` plus a small
  tie-break that prefers placing stock where it can serve demand. CVaR uses the
  Uryasev variables ``eta`` and ``e[s]``.

Only prior weeks are used, so the placement is deployable. The target week is
still one draw: the benchmark reports both the scenario-set prediction and the
out-of-sample end-to-end result.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from ortools.sat.python import cp_model

from supply.fulfillment import FULFILLMENT_DCS, PROMISE_TIERS
from supply.fulfillment.instances import HANDLING_DAYS, TRANSIT_KM_PER_DAY
from supply.fulfillment.solvers import PICK_SCALE
from supply.network import (
    COUNTRY_COORDS,
    DEFAULT_CANDIDATES,
    distance_matrix_km,
)
from supply.network.warehouse import route_return
from supply.wave.instances import (
    PICK_MINUTES_PER_LINE as WAVE_MINUTES_PER_LINE,
    PICK_MINUTES_PER_UNIT as WAVE_MINUTES_PER_UNIT,
    SETUP_MINUTES_PER_WAVE,
    TRAVEL_METERS_PER_MINUTE,
)

from .instances import E2EInstance
from .joint import _largest_remainder, _materialize

DEFAULT_SCENARIO_WEEKS = 6
DEFAULT_CVAR_ALPHA = 0.8
DEFAULT_CVAR_WEIGHT = 0.5
SERVICE_SCALE = 600_000
COVER_SCALE = 1
EPS = 1e-9


@dataclass(frozen=True)
class DemandScenario:
    """One prior week rescaled to the target week's total units."""

    week: str
    weight: float
    demand: np.ndarray  # (skus,) units
    serviceable: np.ndarray  # (dcs, skus) units deliverable inside the promise
    raw_units: int
    scale: float
    history_lines: int
    active_skus: int

    def __post_init__(self) -> None:
        demand = np.asarray(self.demand, dtype=np.int64)
        serviceable = np.asarray(self.serviceable, dtype=np.int64)
        if demand.ndim != 1 or demand.size == 0:
            raise ValueError("场景需求应为一维非空数组")
        if serviceable.ndim != 2 or serviceable.shape[1] != demand.size:
            raise ValueError("场景可服务需求形状应为 (dcs, skus)")
        if np.any(demand < 0) or np.any(serviceable < 0):
            raise ValueError("场景需求不能为负")
        if np.any(serviceable > demand[None, :]):
            raise ValueError("单 DC 的可服务需求不能超过该 SKU 总需求")
        if self.weight <= 0:
            raise ValueError("场景权重必须为正")
        object.__setattr__(self, "demand", demand)
        object.__setattr__(self, "serviceable", serviceable)

    def as_dict(self, dc_names: Sequence[str]) -> Dict[str, Any]:
        total = float(self.demand.sum())
        return {
            "week": self.week,
            "weight": float(self.weight),
            "raw_units": int(self.raw_units),
            "scale": float(self.scale),
            "demand_units": int(self.demand.sum()),
            "active_skus": int(self.active_skus),
            "history_lines": int(self.history_lines),
            "serviceable_share": [
                float(value / total) if total > 0 else 0.0
                for value in self.serviceable.sum(axis=1)
            ],
            "dcs": list(dc_names),
        }


@dataclass(frozen=True)
class ScenarioSet:
    """Equally weighted prior-week demand scenarios aligned to one instance."""

    scenarios: Tuple[DemandScenario, ...]
    sku_names: Tuple[str, ...]
    dc_names: Tuple[str, ...]
    target_units: int
    promise_shares: Tuple[Tuple[int, float], ...]

    def __post_init__(self) -> None:
        if not self.scenarios:
            raise ValueError("至少需要一个需求场景")
        if not self.sku_names or not self.dc_names:
            raise ValueError("场景集必须包含 SKU 与 DC")
        if self.target_units <= 0:
            raise ValueError("目标周总量必须为正")
        shape = (len(self.sku_names),)
        for scenario in self.scenarios:
            if scenario.demand.shape != shape:
                raise ValueError("场景 SKU 维度与场景集不一致")
            if scenario.serviceable.shape != (len(self.dc_names), len(self.sku_names)):
                raise ValueError("场景 DC/SKU 维度与场景集不一致")
        weights = np.array([scenario.weight for scenario in self.scenarios])
        if abs(weights.sum() - 1.0) > 1e-9:
            raise ValueError("场景权重之和应为 1")
        if not np.allclose(weights, 1.0 / weights.size):
            raise ValueError("当前仅支持等权场景")
        if len(set(scenario.week for scenario in self.scenarios)) != len(
            self.scenarios
        ):
            raise ValueError("场景周不能重复")

    @property
    def demand(self) -> np.ndarray:
        return np.stack([scenario.demand for scenario in self.scenarios])

    @property
    def serviceable(self) -> np.ndarray:
        return np.stack([scenario.serviceable for scenario in self.scenarios])

    @property
    def weights(self) -> np.ndarray:
        return np.array([scenario.weight for scenario in self.scenarios])

    @property
    def weeks(self) -> List[str]:
        return [scenario.week for scenario in self.scenarios]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "target_units": int(self.target_units),
            "promise_shares": [[int(day), float(share)] for day, share in self.promise_shares],
            "weeks": self.weeks,
            "scenarios": [
                scenario.as_dict(self.dc_names) for scenario in self.scenarios
            ],
        }


@dataclass
class StochasticPlacement:
    """One first-stage placement and its scenario-set prediction."""

    stock: np.ndarray  # (dcs, skus)
    status: str
    solve_seconds: float
    expected_unmet: float
    cvar_unmet: float
    scenario_unmet: np.ndarray
    cvar_weight: float
    alpha: float
    objective: float
    solver_objective: float
    best_bound: float
    gap: float
    silent_skus: int
    mix: List[float]
    pick_minutes_per_unit: float
    pick_capacity_per_dc: float
    stock_pick_minutes: List[float]

    @property
    def peak_minutes(self) -> float:
        return max(self.stock_pick_minutes) if self.stock_pick_minutes else 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "solve_seconds": self.solve_seconds,
            "expected_unmet": self.expected_unmet,
            "cvar_unmet": self.cvar_unmet,
            "scenario_unmet": [float(value) for value in self.scenario_unmet],
            "cvar_weight": self.cvar_weight,
            "alpha": self.alpha,
            "objective": self.objective,
            "solver_objective": self.solver_objective,
            "best_bound": self.best_bound,
            "gap": self.gap,
            "silent_skus": int(self.silent_skus),
            "stock_mix": self.mix,
            "stock_units": [int(value) for value in self.stock.sum(axis=1)],
            "pick_minutes_per_unit": self.pick_minutes_per_unit,
            "pick_capacity_per_dc": self.pick_capacity_per_dc,
            "stock_pick_minutes": self.stock_pick_minutes,
            "peak_minutes": self.peak_minutes,
        }


def empirical_cvar(values: Iterable[float], alpha: float) -> float:
    """Empirical upper-tail CVaR with linear interpolation at ``1 - alpha``."""
    data = np.sort(np.asarray(list(values), dtype=float))[::-1]
    if data.size == 0:
        raise ValueError("CVaR 至少需要一个观测")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha 必须在 (0, 1) 内")
    if np.any(~np.isfinite(data)):
        raise ValueError("CVaR 观测必须是有限数")
    mass = (1.0 - alpha) * data.size
    if mass <= EPS:
        return float(data[0])
    whole = int(np.floor(mass))
    fraction = mass - whole
    total = float(data[:whole].sum())
    if whole < data.size:
        total += fraction * float(data[whole])
    return total / mass


def _validate_promises(
    promise_shares: Sequence[Tuple[int, float]],
) -> Tuple[Tuple[int, float], ...]:
    pairs = tuple((int(day), float(share)) for day, share in promise_shares)
    if not pairs:
        raise ValueError("承诺分布不能为空")
    if any(day <= 0 for day, _ in pairs):
        raise ValueError("承诺天数必须为正")
    if any(share < 0 for _, share in pairs):
        raise ValueError("承诺占比不能为负")
    if abs(sum(share for _, share in pairs) - 1.0) > 1e-6:
        raise ValueError("承诺占比之和应为 1")
    return pairs


def _transit_days(
    dcs: Sequence[Mapping[str, Any]],
    countries: Sequence[str],
    transit_km_per_day: float,
    handling_days: int,
) -> np.ndarray:
    if transit_km_per_day <= 0:
        raise ValueError("每日转运公里数必须为正")
    if handling_days < 0:
        raise ValueError("处理天数不能为负")
    coords = []
    for dc in dcs:
        match = [row for row in DEFAULT_CANDIDATES if row["name"] == dc["name"]]
        if not match:
            raise ValueError(f"未知 DC: {dc['name']}")
        coords.append((float(match[0]["lat"]), float(match[0]["lon"])))
    destinations = [COUNTRY_COORDS[country] for country in countries]
    distance = distance_matrix_km(coords, destinations)
    return handling_days + np.ceil(distance / transit_km_per_day).astype(np.int64)


def _serve_shares(
    transit: np.ndarray, promise_shares: Sequence[Tuple[int, float]]
) -> np.ndarray:
    days = np.array([day for day, _ in promise_shares], dtype=np.int64)
    shares = np.array([share for _, share in promise_shares], dtype=float)
    mask = days[None, None, :] >= transit[:, :, None]
    return (mask * shares[None, None, :]).sum(axis=2)


def build_demand_scenarios(
    clean: pd.DataFrame,
    skus: Iterable[str],
    week: pd.Timestamp | str,
    target_units: int,
    lookback_weeks: int = DEFAULT_SCENARIO_WEEKS,
    dcs: Sequence[Mapping[str, Any]] = FULFILLMENT_DCS,
    promise_shares: Sequence[Tuple[int, float]] = PROMISE_TIERS,
    transit_km_per_day: float = TRANSIT_KM_PER_DAY,
    handling_days: int = HANDLING_DAYS,
) -> ScenarioSet:
    """Aggregate the last ``lookback_weeks`` weeks into aligned demand scenarios.

    Each prior week is rescaled so its total units equal ``target_units``; the
    exercise assumes weekly volume is known and the SKU x destination mix is
    not. A unit is serviceable from a DC when that DC's declared transit fits
    the promise; the promise mix is the Week-5 30/50/20 split.
    """
    if lookback_weeks < 1:
        raise ValueError("场景回看周数必须为正")
    if target_units <= 0:
        raise ValueError("目标周总量必须为正")
    sku_names = tuple(str(sku) for sku in skus)
    if not sku_names:
        raise ValueError("SKU 列表不能为空")
    if len(set(sku_names)) != len(sku_names):
        raise ValueError("SKU 列表不能重复")
    dc_names = tuple(str(dc["name"]) for dc in dcs)
    if not dc_names:
        raise ValueError("DC 列表不能为空")
    promises = _validate_promises(promise_shares)

    frame = clean.loc[:, ["sku", "country", "quantity", "week"]].copy()
    frame["sku"] = frame["sku"].astype(str)
    frame["week"] = pd.to_datetime(frame["week"])
    frame["quantity"] = frame["quantity"].astype(float).clip(lower=0.0)
    target = pd.Timestamp(week)
    known = frame.loc[frame["week"] < target]
    weeks = sorted(pd.to_datetime(known["week"].unique()))
    if not weeks:
        raise ValueError("目标周之前没有历史数据")
    weeks = weeks[-int(lookback_weeks):]

    countries = tuple(sorted(COUNTRY_COORDS))
    known = known.loc[
        known["week"].isin(weeks)
        & known["sku"].isin(sku_names)
        & known["country"].isin(countries)
    ]
    if known.empty:
        raise ValueError("历史周没有可映射的 SKU/国家交易记录")
    grouped = known.groupby(["week", "sku", "country"])["quantity"].sum()
    transit = _transit_days(dcs, countries, transit_km_per_day, handling_days)
    serve = _serve_shares(transit, promises)

    scenarios: List[DemandScenario] = []
    present = set(grouped.index.get_level_values(0))
    for stamp in weeks:
        if stamp not in present:
            continue
        block = grouped.loc[stamp]
        pivot = block.unstack(fill_value=0.0).reindex(
            index=sku_names, columns=countries, fill_value=0.0
        )
        units = pivot.to_numpy(dtype=float)
        raw_units = float(units.sum())
        if raw_units <= 0:
            continue
        scale = float(target_units) / raw_units
        demand = np.rint(units.sum(axis=1) * scale).astype(np.int64)
        serviceable = np.rint((units @ serve.T) * scale).astype(np.int64).T
        serviceable = np.clip(serviceable, 0, demand[None, :])
        lines = int((known["week"] == stamp).sum())
        scenarios.append(
            DemandScenario(
                week=str(pd.Timestamp(stamp).date()),
                weight=1.0,
                demand=demand,
                serviceable=serviceable,
                raw_units=int(raw_units),
                scale=scale,
                history_lines=lines,
                active_skus=int((demand > 0).sum()),
            )
        )
    if not scenarios:
        raise ValueError("历史周的需求总量为零，无法构造场景")
    weight = 1.0 / len(scenarios)
    scenarios = [
        DemandScenario(
            week=scenario.week,
            weight=weight,
            demand=scenario.demand,
            serviceable=scenario.serviceable,
            raw_units=scenario.raw_units,
            scale=scenario.scale,
            history_lines=scenario.history_lines,
            active_skus=scenario.active_skus,
        )
        for scenario in scenarios
    ]
    return ScenarioSet(
        scenarios=tuple(scenarios),
        sku_names=sku_names,
        dc_names=dc_names,
        target_units=int(target_units),
        promise_shares=promises,
    )


def planned_stock_totals(
    scenarios: ScenarioSet, stock_factor: float = 0.85
) -> np.ndarray:
    """Per-SKU stock totals from the scenario mean, not the target week.

    Stock is a first-stage decision. Using the target week's own SKU mix would
    leak the outcome into the plan, so the totals come from the equally
    weighted scenario mean and cover ``stock_factor`` of its units.
    """
    if not 0.0 < stock_factor <= 2.0:
        raise ValueError("stock_factor 必须在 (0, 2] 内")
    mean = scenarios.demand.mean(axis=0)
    totals = np.rint(stock_factor * mean).astype(np.int64)
    if totals.sum() <= 0:
        raise ValueError("场景均值需求为零，无法规划库存")
    return totals


def planned_stock_instance(
    instance: E2EInstance,
    totals: np.ndarray,
    key: str = "scenario_mean",
    label: str = "场景均值库存",
) -> E2EInstance:
    """Replace per-SKU stock totals with scenario-mean levels (equal split)."""
    if not key or not label:
        raise ValueError("库存计划必须有 key 与 label")
    totals = np.asarray(totals, dtype=np.int64)
    n_dcs = instance.fulfillment.n_dcs
    if totals.shape != (instance.fulfillment.n_skus,):
        raise ValueError("库存总量长度应等于 SKU 数")
    if np.any(totals < 0):
        raise ValueError("库存总量不能为负")
    if totals.sum() <= 0:
        raise ValueError("库存总量必须为正")
    shares = np.full((totals.size, n_dcs), 1.0 / n_dcs)
    stock = _materialize(totals, shares)
    fulfillment = replace(instance.fulfillment, stock=stock)
    meta = {
        **instance.meta,
        "stock_plan": key,
        "stock_placement_label": label,
        "stock_units": int(totals.sum()),
        "stock_shares": [1.0 / n_dcs] * n_dcs,
        "stock_source": "scenario_mean",
    }
    return replace(instance, fulfillment=fulfillment, meta=meta)


def _normalize_shares(
    shares: np.ndarray, shape: Tuple[int, int]
) -> np.ndarray:
    shares = np.asarray(shares, dtype=float)
    if shares.shape != shape:
        raise ValueError(f"占比矩阵形状应为 {shape}")
    if np.any(~np.isfinite(shares)) or np.any(shares < 0):
        raise ValueError("占比必须非负")
    if np.any(shares.sum(axis=1) <= 0):
        raise ValueError("每个 SKU 的占比和必须为正")
    return shares / shares.sum(axis=1, keepdims=True)


def _check_alignment(instance: E2EInstance, scenarios: ScenarioSet) -> None:
    if tuple(instance.fulfillment.sku_names) != scenarios.sku_names:
        raise ValueError("场景 SKU 顺序与履约实例不一致")
    if tuple(instance.fulfillment.dc_names) != scenarios.dc_names:
        raise ValueError("场景 DC 顺序与履约实例不一致")


def pick_proxy(
    instance: E2EInstance,
    pick_minutes_per_unit: Optional[float] = None,
    pickers_per_dc: Optional[int] = None,
    shift_minutes: Optional[float] = None,
    congestion_margin: float = 0.20,
) -> Tuple[float, float]:
    """Linear pick-minute coefficient per unit and per-DC shift capacity.

    The coefficient comes from the order set and the ABC slot map: one
    return route per order, line and unit handling from the Week-7 labor
    model, and one setup per wave at the wave-cardinality lower bound.
    ``congestion_margin`` covers wave formation, blocking and release idle
    time; at 20% the proxy matches the Week-9 pick layer's measured minutes
    per unit on the declared placement (0.079 vs 0.079).
    """
    fulfillment = instance.fulfillment
    total_units = float(fulfillment.line_qty.sum())
    if total_units <= 0:
        raise ValueError("订单总量必须为正")
    if congestion_margin < 0:
        raise ValueError("拥堵余量不能为负")
    if pick_minutes_per_unit is None:
        if not instance.slots:
            raise ValueError("缺少 SKU 槽位，无法估计拣选路程")
        travel_m = 0.0
        for order in range(fulfillment.n_orders):
            lines = np.flatnonzero(fulfillment.line_order == order)
            names = sorted(
                {fulfillment.sku_names[index] for index in fulfillment.line_sku[lines]}
            )
            travel_m += route_return(
                instance.layout, [instance.slots[name] for name in names]
            )
        waves = max(
            int(np.ceil(fulfillment.n_orders / instance.max_orders)),
            int(np.ceil(fulfillment.n_lines / instance.max_lines)),
        )
        minutes = (
            travel_m / TRAVEL_METERS_PER_MINUTE
            + fulfillment.n_lines * WAVE_MINUTES_PER_LINE
            + total_units * WAVE_MINUTES_PER_UNIT
            + waves * SETUP_MINUTES_PER_WAVE
        )
        pick_minutes_per_unit = minutes / total_units * (1.0 + congestion_margin)
    if pick_minutes_per_unit <= 0:
        raise ValueError("单件拣选分钟必须为正")
    pickers = instance.pickers_per_dc if pickers_per_dc is None else int(pickers_per_dc)
    shift = instance.shift_minutes if shift_minutes is None else float(shift_minutes)
    if pickers < 1:
        raise ValueError("每 DC 拣货员数量必须为正")
    if shift <= 0:
        raise ValueError("班次时长必须为正")
    return float(pick_minutes_per_unit), float(pickers * shift)


def _hint_second_stage(
    model: cp_model.CpModel,
    z: Dict[tuple, Any],
    y: Dict[tuple, Any],
    u: Dict[tuple, Any],
    hint: np.ndarray,
    demand: np.ndarray,
    serviceable: np.ndarray,
    capacity: np.ndarray,
) -> None:
    n_scenarios, n_dcs, n_skus = serviceable.shape
    for sku in range(n_skus):
        for dc in range(n_dcs):
            model.AddHint(z[sku, dc], int(hint[dc, sku]))
    for scenario in range(n_scenarios):
        remaining = demand[scenario].astype(np.int64).copy()
        headroom = capacity.astype(np.int64).copy()
        served = np.zeros(n_skus, dtype=np.int64)
        for dc in range(n_dcs):
            if headroom[dc] <= 0:
                for sku in range(n_skus):
                    model.AddHint(y[scenario, sku, dc], 0)
                continue
            order = np.argsort(-serviceable[scenario, dc])
            for sku in order:
                take = int(
                    min(
                        hint[dc, sku],
                        serviceable[scenario, dc, sku],
                        remaining[sku],
                        headroom[dc],
                    )
                )
                take = max(0, take)
                model.AddHint(y[scenario, sku, dc], take)
                remaining[sku] -= take
                headroom[dc] -= take
                served[sku] += take
        for sku in range(n_skus):
            model.AddHint(
                u[scenario, sku], int(max(0, demand[scenario, sku] - served[sku]))
            )


def stochastic_placement(
    instance: E2EInstance,
    scenarios: ScenarioSet,
    cvar_weight: float = DEFAULT_CVAR_WEIGHT,
    alpha: float = DEFAULT_CVAR_ALPHA,
    time_limit_seconds: float = 60.0,
    workers: int = 4,
    hint_stock: Optional[np.ndarray] = None,
    fallback_shares: Optional[np.ndarray] = None,
    pick_minutes_per_unit: Optional[float] = None,
    pickers_per_dc: Optional[int] = None,
    shift_minutes: Optional[float] = None,
) -> StochasticPlacement:
    """Solve the two-stage scenario placement with per-SKU totals fixed."""
    _check_alignment(instance, scenarios)
    if not 0.0 <= cvar_weight <= 1.0:
        raise ValueError("CVaR 权重必须在 [0, 1]")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha 必须在 (0, 1)")
    if time_limit_seconds <= 0:
        raise ValueError("求解时限必须为正")
    if workers < 1:
        raise ValueError("workers 必须 >= 1")
    minute_per_unit, pick_capacity = pick_proxy(
        instance, pick_minutes_per_unit, pickers_per_dc, shift_minutes
    )

    fulfillment = instance.fulfillment
    n_dcs = fulfillment.n_dcs
    n_skus = fulfillment.n_skus
    stock_total = np.asarray(fulfillment.stock, dtype=np.int64).sum(axis=0)
    if np.any(stock_total < 0):
        raise ValueError("每个 SKU 的总库存不能为负")
    if stock_total.sum() <= 0:
        raise ValueError("库存总量必须为正")
    capacity = np.asarray(fulfillment.dc_capacity, dtype=np.int64)
    if np.any(capacity <= 0):
        raise ValueError("DC 周产能必须为正")

    demand = scenarios.demand  # (S, K)
    serviceable = scenarios.serviceable  # (S, D, K)
    weights = scenarios.weights
    n_scenarios = demand.shape[0]
    max_scenario_unmet = int(demand.sum(axis=1).max())

    if hint_stock is not None:
        hint = np.asarray(hint_stock, dtype=np.int64)
        if hint.shape != (n_dcs, n_skus):
            raise ValueError("hint_stock 形状应为 (dcs, skus)")
        if np.any(hint < 0):
            raise ValueError("hint_stock 不能为负")
        if not np.array_equal(hint.sum(axis=0), stock_total):
            raise ValueError("hint_stock 必须保持每 SKU 总库存")
    else:
        hint = None

    shape = (n_skus, n_dcs)
    if fallback_shares is None:
        fallback = np.full(shape, 1.0 / n_dcs)
    else:
        fallback = _normalize_shares(fallback_shares, shape)

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
    pick_coefficient = int(round(minute_per_unit * PICK_SCALE))
    pick_bound = int(round(pick_capacity * PICK_SCALE))
    # Holding stock does not consume pick minutes; only shipping does. ``peak``
    # is a balance tie-break, so its bound is the stock's own pick minutes, not
    # the shift capacity. Capping stock at the shift would make the model
    # infeasible whenever total stock exceeds what one shift can pick.
    peak_upper = int(round(minute_per_unit * float(stock_total.sum()))) + 1
    peak = model.NewIntVar(0, max(1, peak_upper), "peak_minutes")
    for dc in range(n_dcs):
        model.Add(
            sum(pick_coefficient * z[sku, dc] for sku in range(n_skus))
            <= PICK_SCALE * peak
        )
    for scenario in range(n_scenarios):
        for dc in range(n_dcs):
            model.Add(
                sum(y[scenario, sku, dc] for sku in range(n_skus))
                <= int(capacity[dc])
            )
            model.Add(
                sum(
                    pick_coefficient * y[scenario, sku, dc]
                    for sku in range(n_skus)
                )
                <= pick_bound
            )

    terms: List[Any] = []
    for scenario in range(n_scenarios):
        weight = float(weights[scenario])
        coefficient = int(round(SERVICE_SCALE * (1.0 - cvar_weight) * weight))
        if coefficient:
            for sku in range(n_skus):
                terms.append(coefficient * unmet[scenario, sku])
    if cvar_weight > 0:
        eta = model.NewIntVar(0, max_scenario_unmet, "eta")
        excess: Dict[int, Any] = {}
        for scenario in range(n_scenarios):
            excess[scenario] = model.NewIntVar(
                0, max_scenario_unmet, f"e_{scenario}"
            )
            model.Add(
                sum(unmet[scenario, sku] for sku in range(n_skus))
                <= eta + excess[scenario]
            )
        eta_coefficient = int(round(SERVICE_SCALE * cvar_weight))
        if eta_coefficient:
            terms.append(eta_coefficient * eta)
        for scenario in range(n_scenarios):
            coefficient = int(
                round(
                    SERVICE_SCALE
                    * cvar_weight
                    * float(weights[scenario])
                    / (1.0 - alpha)
                )
            )
            if coefficient:
                terms.append(coefficient * excess[scenario])

    cover = np.zeros((n_skus, n_dcs))
    denom = demand.sum(axis=0)
    for sku in range(n_skus):
        if denom[sku] <= 0:
            continue
        for dc in range(n_dcs):
            cover[sku, dc] = float(
                (weights * serviceable[:, dc, sku]).sum() / denom[sku]
            )
    cover_coefficient = int(round(COVER_SCALE))
    if cover_coefficient:
        for sku in range(n_skus):
            for dc in range(n_dcs):
                value = int(round(cover[sku, dc] * cover_coefficient))
                if value:
                    terms.append(-value * z[sku, dc])
    terms.append(-peak)
    model.Minimize(sum(terms))

    if hint is not None:
        _hint_second_stage(
            model,
            z,
            y,
            unmet,
            hint,
            demand,
            serviceable,
            capacity,
        )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_seconds)
    solver.parameters.num_search_workers = int(workers)
    started = time.perf_counter()
    status_code = solver.Solve(model)
    elapsed = time.perf_counter() - started
    status = solver.StatusName(status_code)
    if status not in {"OPTIMAL", "FEASIBLE"}:
        raise RuntimeError(f"随机布点 MILP 未找到可行解: {status}")

    stock = np.zeros((n_dcs, n_skus), dtype=np.int64)
    for sku in range(n_skus):
        for dc in range(n_dcs):
            stock[dc, sku] = int(round(solver.Value(z[sku, dc])))
    if not np.array_equal(stock.sum(axis=0), stock_total):
        raise RuntimeError("随机布点未保持每 SKU 总库存")

    unmet_values = np.zeros((n_scenarios, n_skus), dtype=np.int64)
    for scenario in range(n_scenarios):
        for sku in range(n_skus):
            unmet_values[scenario, sku] = int(round(solver.Value(unmet[scenario, sku])))
    scenario_unmet = unmet_values.sum(axis=1).astype(float)

    silent = (denom == 0) | (serviceable.sum(axis=(0, 1)) == 0)
    served_silent = demand[:, silent] - unmet_values[:, silent]
    if np.any(served_silent > 0):
        raise RuntimeError("无场景信号的 SKU 不应有场景发货量")
    for sku in np.flatnonzero(silent):
        stock[:, sku] = _largest_remainder(int(stock_total[sku]), fallback[sku])
    if not np.array_equal(stock.sum(axis=0), stock_total):
        raise RuntimeError("回退布点未保持每 SKU 总库存")

    expected = float((weights * scenario_unmet).sum())
    cvar = empirical_cvar(scenario_unmet, alpha)
    objective = (1.0 - cvar_weight) * expected + cvar_weight * cvar
    solver_objective = float(solver.ObjectiveValue()) / SERVICE_SCALE
    best_bound = float(solver.BestObjectiveBound()) / SERVICE_SCALE
    gap = (
        max(0.0, (solver_objective - best_bound) / abs(solver_objective))
        if abs(solver_objective) > EPS
        else float("nan")
    )
    total = float(stock.sum())
    mix = (
        [float(value) for value in stock.sum(axis=1) / total]
        if total > 0
        else [0.0 for _ in range(n_dcs)]
    )
    stock_pick_minutes = [
        float(minute_per_unit * float(stock[dc].sum())) for dc in range(n_dcs)
    ]
    return StochasticPlacement(
        stock=stock,
        status=status,
        solve_seconds=elapsed,
        expected_unmet=expected,
        cvar_unmet=cvar,
        scenario_unmet=scenario_unmet,
        cvar_weight=float(cvar_weight),
        alpha=float(alpha),
        objective=objective,
        solver_objective=solver_objective,
        best_bound=best_bound,
        gap=gap,
        silent_skus=int(silent.sum()),
        mix=mix,
        pick_minutes_per_unit=minute_per_unit,
        pick_capacity_per_dc=pick_capacity,
        stock_pick_minutes=stock_pick_minutes,
    )


def score_placement(
    stock: np.ndarray,
    scenarios: ScenarioSet,
    dc_capacity: np.ndarray,
    alpha: float = DEFAULT_CVAR_ALPHA,
    time_limit_seconds: float = 5.0,
    workers: int = 4,
    pick_minutes_per_unit: Optional[float] = None,
    pick_capacity_per_dc: Optional[float] = None,
) -> Dict[str, Any]:
    """Best achievable per-scenario service for a fixed placement (fluid)."""
    stock = np.asarray(stock, dtype=np.int64)
    capacity = np.asarray(dc_capacity, dtype=np.int64)
    n_dcs = len(scenarios.dc_names)
    n_skus = len(scenarios.sku_names)
    if stock.shape != (n_dcs, n_skus):
        raise ValueError("库存布点形状应为 (dcs, skus)")
    if np.any(stock < 0):
        raise ValueError("库存布点不能为负")
    if capacity.shape != (n_dcs,):
        raise ValueError("DC 产能长度应与 DC 数一致")
    if np.any(capacity <= 0):
        raise ValueError("DC 产能必须为正")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha 必须在 (0, 1)")
    if time_limit_seconds <= 0:
        raise ValueError("求解时限必须为正")
    if (pick_minutes_per_unit is None) != (pick_capacity_per_dc is None):
        raise ValueError("拣选分钟系数与班次产能必须同时给出")
    if pick_minutes_per_unit is not None:
        if pick_minutes_per_unit <= 0 or pick_capacity_per_dc <= 0:
            raise ValueError("拣选分钟系数与班次产能必须为正")
        pick_coefficient = int(round(pick_minutes_per_unit * PICK_SCALE))
        pick_bound = int(round(pick_capacity_per_dc * PICK_SCALE))
    else:
        pick_coefficient = 0
        pick_bound = 0

    demand = scenarios.demand
    serviceable = scenarios.serviceable
    n_scenarios = demand.shape[0]
    unmet = np.zeros(n_scenarios, dtype=float)
    states: List[str] = []
    started = time.perf_counter()
    for scenario in range(n_scenarios):
        model = cp_model.CpModel()
        y: Dict[tuple, Any] = {}
        for sku in range(n_skus):
            for dc in range(n_dcs):
                upper = int(min(stock[dc, sku], serviceable[scenario, dc, sku]))
                y[sku, dc] = model.NewIntVar(0, upper, f"y_{sku}_{dc}")
            model.Add(
                sum(y[sku, dc] for dc in range(n_dcs))
                <= int(demand[scenario, sku])
            )
        for dc in range(n_dcs):
            model.Add(
                sum(y[sku, dc] for sku in range(n_skus)) <= int(capacity[dc])
            )
        if pick_coefficient:
            for dc in range(n_dcs):
                model.Add(
                    sum(pick_coefficient * y[sku, dc] for sku in range(n_skus))
                    <= pick_bound
                )
        model.Maximize(sum(y.values()))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(time_limit_seconds)
        solver.parameters.num_search_workers = int(workers)
        code = solver.Solve(model)
        state = solver.StatusName(code)
        states.append(state)
        if state not in {"OPTIMAL", "FEASIBLE"}:
            raise RuntimeError(f"固定布点评估未找到可行解: {state}")
        served = float(solver.ObjectiveValue())
        unmet[scenario] = max(0.0, float(demand[scenario].sum()) - served)
    elapsed = time.perf_counter() - started
    expected = float(unmet.mean())
    cvar = empirical_cvar(unmet, alpha)
    total = float(scenarios.target_units)
    return {
        "status": "OPTIMAL" if all(state == "OPTIMAL" for state in states) else "FEASIBLE",
        "expected_unmet": expected,
        "cvar_unmet": cvar,
        "expected_unmet_rate": expected / total if total > 0 else float("nan"),
        "cvar_unmet_rate": cvar / total if total > 0 else float("nan"),
        "scenario_unmet": [float(value) for value in unmet],
        "solve_seconds": elapsed,
    }
