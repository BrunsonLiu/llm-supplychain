"""End-to-end instance: allocation -> per-DC pick tickets -> online release.

Week 5 allocates orders to DCs, Week 6/7 batch and schedule the picks, and
Week 8 releases waves as orders arrive. This module keeps one instance and one
promise field so the three layers can be chained without re-declaring data:

* the customer promise (2/3/5 days) drives the allocation lateness penalty;
* the same promise maps to an intra-day pick cutoff (12:00/16:00/18:00), so an
  express order must also leave the DC before noon;
* arrivals are sampled per tier (70/50/40% onsite, 120/360/480-min windows).

Online Retail II supplies invoices, quantities and destination countries. DC
stock, throughput, transit days, warehouse layout, pick times, picker count
and the promise-to-cutoff mapping are an explicit assumption layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, Mapping, Optional

import numpy as np
import pandas as pd

from supply.fulfillment import (
    DEFAULT_STOCK_SHARES,
    FulfillmentInstance,
    build_fulfillment_instance,
)
from supply.network import (
    WarehouseLayout,
    assign_slots,
    build_picking_orders,
)

from .arrival import ArrivalCurve

PROMISE_TIER = {2: "express", 3: "standard", 5: "economy"}
TIER_CUTOFFS = {"express": 240, "standard": 480, "economy": 600}
DEFAULT_TIER_ONSITE = {"express": 0.70, "standard": 0.50, "economy": 0.40}
DEFAULT_TIER_WINDOWS = {"express": 120.0, "standard": 360.0, "economy": 480.0}
DEFAULT_MAX_ORDERS = 8
DEFAULT_MAX_LINES = 40
DEFAULT_PICKERS_PER_DC = 2
DEFAULT_SHIFT_MINUTES = 600.0
DEFAULT_LAYOUT = (8, 16)
EPS = 1e-9


@dataclass(frozen=True)
class PickPlan:
    """One promise tier, pick cutoff and arrival minute per order."""

    tier_of: Dict[str, str]
    cutoff_of: Dict[str, int]
    arrival_of: Dict[str, float]
    tier_onsite: Dict[str, float]
    tier_windows: Dict[str, float]
    seed: int
    arrival_profile: Optional[Dict[str, float]] = None
    arrival_curve: Optional[Dict[str, Any]] = None

    @property
    def orders(self) -> int:
        return len(self.arrival_of)

    @property
    def onsite_orders(self) -> int:
        return sum(1 for value in self.arrival_of.values() if value <= EPS)

    @property
    def mid_shift_orders(self) -> int:
        return self.orders - self.onsite_orders

    def tier_counts(self) -> Dict[str, int]:
        counts = {tier: 0 for tier in TIER_CUTOFFS}
        for tier in self.tier_of.values():
            counts[tier] += 1
        return counts


@dataclass
class E2EInstance:
    fulfillment: FulfillmentInstance
    layout: WarehouseLayout
    slots: Dict[str, tuple]
    pick: PickPlan
    max_orders: int = DEFAULT_MAX_ORDERS
    max_lines: int = DEFAULT_MAX_LINES
    pickers_per_dc: int = DEFAULT_PICKERS_PER_DC
    shift_minutes: float = DEFAULT_SHIFT_MINUTES
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def order_ids(self):
        return self.fulfillment.order_ids

    @property
    def n_orders(self) -> int:
        return self.fulfillment.n_orders

    def pickup_for(self, invoices: Iterable[str]) -> Dict[str, str]:
        return {invoice: self.pick.tier_of[invoice] for invoice in invoices}


def _velocity(
    clean: pd.DataFrame,
    skus: Iterable[str],
    sample_orders: int,
    max_lines: int,
    seed: int,
    week: Optional[pd.Timestamp],
) -> pd.Series:
    _, velocity, _ = build_picking_orders(
        clean,
        skus,
        sample_orders=sample_orders,
        max_lines=max_lines,
        seed=seed,
        week=week,
    )
    return velocity


ARRIVAL_PROFILE_KEYS = {"spike_share", "spike_center", "spike_width"}
DEFAULT_ARRIVAL_PROFILE = {
    "spike_share": 0.60,
    "spike_center": 0.50,
    "spike_width": 0.25,
}


def normalize_arrival_profile(
    profile: Optional[Mapping[str, float]],
) -> Optional[Dict[str, float]]:
    """Validate an intraday arrival spike; ``None`` keeps the uniform window."""
    if profile is None:
        return None
    if set(profile) != ARRIVAL_PROFILE_KEYS:
        raise ValueError(
            "到达尖峰参数必须且只能包含 spike_share / spike_center / spike_width"
        )
    values = {key: float(profile[key]) for key in ARRIVAL_PROFILE_KEYS}
    if not 0.0 <= values["spike_share"] <= 1.0:
        raise ValueError("尖峰订单占比必须在 [0, 1]")
    if not 0.0 <= values["spike_center"] <= 1.0:
        raise ValueError("尖峰中心必须在 [0, 1]")
    if not 0.0 < values["spike_width"] <= 1.0:
        raise ValueError("尖峰宽度必须在 (0, 1]")
    start = values["spike_center"] - values["spike_width"] / 2.0
    end = values["spike_center"] + values["spike_width"] / 2.0
    if end - max(0.0, start) <= EPS:
        raise ValueError("尖峰窗口必须覆盖正长度")
    return values


def rebuild_pick_plan(
    instance: E2EInstance,
    promise_days: np.ndarray,
    keep_arrivals: bool = True,
    keep_cutoffs: bool = False,
) -> E2EInstance:
    """Replace promise days and rebuild tiers/cutoffs, optionally keeping both."""
    promises = np.asarray(promise_days, dtype=np.int64)
    if promises.shape != (instance.n_orders,):
        raise ValueError("承诺天数长度应等于订单数")
    fulfillment = replace(instance.fulfillment, promise_days=promises)
    plan = _pick_plan(
        fulfillment,
        None,
        None,
        instance.pick.seed,
        arrival_profile=instance.pick.arrival_profile,
        arrival_curve=instance.pick.arrival_curve,
    )
    if keep_arrivals:
        plan = replace(plan, arrival_of=dict(instance.pick.arrival_of))
    if keep_cutoffs:
        plan = replace(
            plan,
            tier_of=dict(instance.pick.tier_of),
            cutoff_of=dict(instance.pick.cutoff_of),
        )
    return replace(instance, fulfillment=fulfillment, pick=plan)


def _pick_plan(
    instance: FulfillmentInstance,
    tier_onsite: Optional[Mapping[str, float]],
    tier_windows: Optional[Mapping[str, float]],
    seed: int,
    arrival_profile: Optional[Mapping[str, float]] = None,
    arrival_curve: Optional[ArrivalCurve | Mapping[str, Any]] = None,
) -> PickPlan:
    onsite_share = dict(DEFAULT_TIER_ONSITE if tier_onsite is None else tier_onsite)
    windows = dict(DEFAULT_TIER_WINDOWS if tier_windows is None else tier_windows)
    profile = normalize_arrival_profile(arrival_profile)
    if arrival_curve is not None:
        if profile is not None:
            raise ValueError("到达尖峰与经验到达曲线只能二选一")
        curve = (
            arrival_curve
            if isinstance(arrival_curve, ArrivalCurve)
            else ArrivalCurve.from_dict(arrival_curve)
        )
    else:
        curve = None
    if set(onsite_share) != set(TIER_CUTOFFS) or set(windows) != set(TIER_CUTOFFS):
        raise ValueError("到达参数必须覆盖 express/standard/economy 三层")
    if any(not 0.0 <= share <= 1.0 for share in onsite_share.values()):
        raise ValueError("开班前到达占比必须在 [0, 1]")
    if any(window < 0 for window in windows.values()):
        raise ValueError("到达窗口不能为负")

    unknown = sorted(set(int(days) for days in instance.promise_days) - set(PROMISE_TIER))
    if unknown:
        raise ValueError(f"承诺天数没有对应的截单层: {unknown}")

    tier_of = {
        invoice: PROMISE_TIER[int(instance.promise_days[order])]
        for order, invoice in enumerate(instance.order_ids)
    }
    cutoff_of = {invoice: TIER_CUTOFFS[tier] for invoice, tier in tier_of.items()}

    rng = np.random.default_rng(seed)
    arrival_of: Dict[str, float] = {}
    for tier in TIER_CUTOFFS:
        invoices = sorted(
            invoice for invoice, value in tier_of.items() if value == tier
        )
        if not invoices:
            continue
        shuffled = [invoices[index] for index in rng.permutation(len(invoices))]
        share = float(onsite_share[tier])
        count = max(0, min(len(shuffled), int(round(share * len(shuffled)))))
        for invoice in shuffled[:count]:
            arrival_of[invoice] = 0.0
        mid_shift = shuffled[count:]
        window = float(windows[tier])
        if curve is not None:
            for invoice in mid_shift:
                arrival_of[invoice] = float(curve.sample(rng, window))
            continue
        if profile is None:
            for invoice in mid_shift:
                arrival_of[invoice] = float(rng.uniform(0.0, window))
            continue
        spike_count = min(
            len(mid_shift), int(round(profile["spike_share"] * len(mid_shift)))
        )
        if window <= EPS:
            for invoice in mid_shift:
                arrival_of[invoice] = 0.0
            continue
        start = max(0.0, (profile["spike_center"] - profile["spike_width"] / 2.0) * window)
        end = min(window, (profile["spike_center"] + profile["spike_width"] / 2.0) * window)
        if end - start <= EPS:
            raise ValueError(f"{tier} 层的尖峰窗口为空")
        for invoice in mid_shift[:spike_count]:
            arrival_of[invoice] = float(rng.uniform(start, end))
        for invoice in mid_shift[spike_count:]:
            arrival_of[invoice] = float(rng.uniform(0.0, window))
    if set(arrival_of) != set(instance.order_ids):
        raise ValueError("到达时间未覆盖全部订单")
    return PickPlan(
        tier_of=tier_of,
        cutoff_of=cutoff_of,
        arrival_of=arrival_of,
        tier_onsite={tier: float(onsite_share[tier]) for tier in TIER_CUTOFFS},
        tier_windows={tier: float(windows[tier]) for tier in TIER_CUTOFFS},
        seed=int(seed),
        arrival_profile=None if profile is None else dict(profile),
        arrival_curve=None if curve is None else curve.as_dict(),
    )


def build_e2e_instance(
    clean: pd.DataFrame,
    skus: Iterable[str],
    sample_orders: int = 400,
    max_lines: int = 20,
    stock_factor: float = 0.85,
    stock_shares: Optional[Iterable[float]] = None,
    seed: int = 42,
    week: Optional[pd.Timestamp] = None,
    pickers_per_dc: int = DEFAULT_PICKERS_PER_DC,
    shift_minutes: float = DEFAULT_SHIFT_MINUTES,
    arrival_seed: int = 42,
    tier_onsite: Optional[Mapping[str, float]] = None,
    tier_windows: Optional[Mapping[str, float]] = None,
    arrival_profile: Optional[Mapping[str, float]] = None,
    arrival_curve: Optional[ArrivalCurve | Mapping[str, Any]] = None,
    layout: Optional[WarehouseLayout] = None,
) -> E2EInstance:
    """Build one week where allocation, picking and arrivals share a promise."""
    if pickers_per_dc < 1:
        raise ValueError("每 DC 拣货员数量必须为正")
    if shift_minutes <= 0:
        raise ValueError("班次时长必须为正")

    fulfillment = build_fulfillment_instance(
        clean,
        skus,
        sample_orders=sample_orders,
        max_lines=max_lines,
        stock_factor=stock_factor,
        stock_shares=tuple(stock_shares) if stock_shares is not None else DEFAULT_STOCK_SHARES,
        seed=seed,
        week=week,
    )
    velocity = _velocity(clean, skus, sample_orders, max_lines, seed, week)
    layout = layout or WarehouseLayout(n_aisles=8, n_bays=16)
    slots = assign_slots(skus, layout, velocity, strategy="abc", seed=seed)
    missing = sorted(set(fulfillment.sku_names) - set(slots))
    if missing:
        raise ValueError(f"{len(missing)} 个 SKU 没有槽位，例如 {missing[:3]}")

    pick = _pick_plan(
        fulfillment, tier_onsite, tier_windows, arrival_seed, arrival_profile, arrival_curve
    )
    details = dict(fulfillment.meta)
    details.update(
        {
            "promise_cutoffs": dict(TIER_CUTOFFS),
            "promise_tier_map": {str(days): tier for days, tier in PROMISE_TIER.items()},
            "pick_tier_counts": pick.tier_counts(),
            "arrival_seed": int(arrival_seed),
            "tier_onsite": dict(pick.tier_onsite),
            "tier_windows": dict(pick.tier_windows),
            "arrival_profile": pick.arrival_profile,
            "arrival_curve": pick.arrival_curve,
            "onsite_orders": pick.onsite_orders,
            "mid_shift_orders": pick.mid_shift_orders,
            "pickers_per_dc": int(pickers_per_dc),
            "shift_minutes": float(shift_minutes),
            "max_orders_per_wave": int(DEFAULT_MAX_ORDERS),
            "max_lines_per_wave": int(DEFAULT_MAX_LINES),
            "layout_aisles": int(layout.n_aisles),
            "layout_bays": int(layout.n_bays),
            "slotting": "abc",
            "assumptions": list(fulfillment.meta.get("assumptions", []))
            + [
                "承诺天数 2/3/5 映射到拣选截单 12:00/16:00/18:00",
                "班中到达占比与到达窗口是显式假设",
            ]
            + (
                ["尖峰画像按层内相对窗口抽样，不是观测到的日内曲线"]
                if pick.arrival_profile is not None
                else []
            )
            + (
                [
                    "日内到达形状取自 Online Retail II 发票时间戳（逐周经验曲线），"
                    "承诺窗口与班前占比仍是声明值"
                ]
                if pick.arrival_curve is not None
                else []
            )
            + [
                "三个 DC 共用同一 ABC 布局与拣选工时模型，每 DC 独立拣货员",
            ],
        }
    )
    return E2EInstance(
        fulfillment=fulfillment,
        layout=layout,
        slots=slots,
        pick=pick,
        pickers_per_dc=int(pickers_per_dc),
        shift_minutes=float(shift_minutes),
        meta=details,
    )


def rebuild_arrivals(
    instance: E2EInstance,
    arrival_seed: int,
    arrival_profile: Optional[Mapping[str, float]] = None,
    arrival_curve: Optional[ArrivalCurve | Mapping[str, Any]] = None,
    keep_cutoffs: bool = False,
) -> E2EInstance:
    """Replace only the arrival draw, keeping stock, slots, cutoffs and layout."""
    plan = _pick_plan(
        instance.fulfillment,
        instance.pick.tier_onsite,
        instance.pick.tier_windows,
        arrival_seed,
        arrival_profile,
        arrival_curve,
    )
    if keep_cutoffs:
        plan = replace(
            plan,
            tier_of=dict(instance.pick.tier_of),
            cutoff_of=dict(instance.pick.cutoff_of),
        )
    meta = dict(instance.meta)
    meta.update(
        {
            "arrival_seed": int(arrival_seed),
            "arrival_profile": plan.arrival_profile,
            "arrival_curve": plan.arrival_curve,
            "onsite_orders": plan.onsite_orders,
            "mid_shift_orders": plan.mid_shift_orders,
        }
    )
    return replace(instance, pick=plan, meta=meta)
