"""Replay the E2E chain under empirical intraday arrival curves.

Week 10 sampled arrivals from a declared uniform window or a declared spike.
This module keeps the same allocation, stock, promises, cutoffs and picker
model, and swaps only the arrival shape:

* ``uniform``: the Week-9/10 declaration (control);
* ``spike``: the declared relative spike (Week-10 control);
* ``mean``: the equal-weight average of the prior-week curves;
* ``empirical``: one prior-week curve per seed, so week-to-week shape noise is
  part of the experiment.

Cells can also change the release policy, add pick-duration noise or add a
picker per DC, which keeps the Week-10 comparison structure intact.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from supply.fulfillment import FulfillmentResult

from .arrival import ArrivalCurve, EmpiricalArrivals
from .instances import E2EInstance, normalize_arrival_profile, rebuild_arrivals
from .pipeline import POLICY_LABELS, run_pick_layer

ARRIVAL_MODES = {"uniform", "spike", "mean", "empirical"}


@dataclass(frozen=True)
class CurveCell:
    """One execution cell: arrival shape, release policy, noise and pickers."""

    key: str
    label: str
    arrival: str = "empirical"
    policy: str = "edf"
    profile: Optional[Dict[str, float]] = None
    duration_noise: float = 0.0
    pickers_per_dc: Optional[int] = None

    def __post_init__(self) -> None:
        if self.arrival not in ARRIVAL_MODES:
            raise ValueError(f"未知到达模式: {self.arrival}")
        if self.policy not in POLICY_LABELS:
            raise ValueError(f"未知在线策略: {self.policy}")
        if self.duration_noise < 0:
            raise ValueError("拣选时长噪声标准差不能为负")
        if self.pickers_per_dc is not None and self.pickers_per_dc < 1:
            raise ValueError("每 DC 拣货员数量必须为正")
        if self.arrival == "spike":
            if self.profile is None:
                raise ValueError("尖峰单元必须提供 profile")
            object.__setattr__(self, "profile", normalize_arrival_profile(self.profile))
        elif self.profile is not None:
            raise ValueError("只有尖峰单元可以设置 profile")

    @property
    def profile_label(self) -> str:
        if self.arrival == "uniform":
            return "均匀到达"
        if self.arrival == "spike":
            profile = self.profile or {}
            return (
                f"尖峰 {profile.get('spike_share', 0.0):.0%} "
                f"@ {profile.get('spike_center', 0.0):.2f}"
                f"±{profile.get('spike_width', 0.0) / 2:.2f}"
            )
        if self.arrival == "mean":
            return "前几周平均经验曲线"
        return "逐周经验曲线"


def curve_for(
    cell: CurveCell,
    seed: int,
    arrivals: EmpiricalArrivals,
) -> Optional[ArrivalCurve]:
    if cell.arrival == "uniform" or cell.arrival == "spike":
        return None
    if cell.arrival == "mean":
        return arrivals.mean
    return arrivals.curve_for(int(seed))


def replay_curves(
    instance: E2EInstance,
    allocation: FulfillmentResult,
    scenario: str,
    cell: CurveCell,
    seeds: Sequence[int],
    arrivals: EmpiricalArrivals,
) -> pd.DataFrame:
    """Replay one allocation under one cell and every seed."""
    if not seeds:
        raise ValueError("随机种子列表不能为空")
    rows: List[Dict[str, object]] = []
    for seed in seeds:
        curve = curve_for(cell, int(seed), arrivals)
        shifted = rebuild_arrivals(
            instance,
            int(seed),
            arrival_profile=cell.profile,
            arrival_curve=curve,
        )
        result = run_pick_layer(
            shifted,
            allocation,
            scenario=scenario,
            policy=cell.policy,
            pickers_per_dc=cell.pickers_per_dc,
            duration_noise=cell.duration_noise or None,
            noise_seed=int(seed),
        )
        rows.append(
            {
                "scenario": scenario,
                "cell": cell.key,
                "cell_label": cell.label,
                "arrival": cell.arrival,
                "profile": cell.profile_label,
                "curve_week": "" if curve is None else curve.week,
                "policy": cell.policy,
                "duration_noise": float(cell.duration_noise),
                "seed": int(seed),
                **result.metrics,
            }
        )
    return pd.DataFrame(rows)


def run_curve_monte_carlo(
    instance: E2EInstance,
    allocations: Mapping[str, FulfillmentResult],
    cells: Sequence[CurveCell],
    seeds: Sequence[int],
    arrivals: EmpiricalArrivals,
) -> pd.DataFrame:
    """Replay every allocation under every cell and seed."""
    if not allocations:
        raise ValueError("至少需要一个分单方案")
    if not cells:
        raise ValueError("至少需要一个执行单元")
    frames = [
        replay_curves(instance, allocation, scenario, cell, seeds, arrivals)
        for scenario, allocation in allocations.items()
        for cell in cells
    ]
    return pd.concat(frames, ignore_index=True)


def arrival_timing(
    instance: E2EInstance,
    cells: Sequence[CurveCell],
    seeds: Sequence[int],
    arrivals: EmpiricalArrivals,
) -> List[Dict[str, Any]]:
    """Summarise where mid-shift orders land inside their tier window."""
    windows = instance.pick.tier_windows
    rows: List[Dict[str, Any]] = []
    for cell in cells:
        fracs: List[float] = []
        minutes: List[float] = []
        for seed in seeds:
            curve = curve_for(cell, int(seed), arrivals)
            shifted = rebuild_arrivals(
                instance,
                int(seed),
                arrival_profile=cell.profile,
                arrival_curve=curve,
            )
            plan = shifted.pick
            for invoice, arrival in plan.arrival_of.items():
                if arrival <= 1e-9:
                    continue
                window = float(windows[plan.tier_of[invoice]])
                if window <= 0:
                    continue
                fracs.append(float(arrival) / window)
                minutes.append(float(arrival))
        if not fracs:
            continue
        values = np.asarray(fracs, dtype=float)
        rows.append(
            {
                "cell": cell.key,
                "label": cell.label,
                "arrival": cell.arrival,
                "policy": cell.policy,
                "orders": int(values.size),
                "mean_fraction": float(values.mean()),
                "median_fraction": float(np.median(values)),
                "share_after_half": float((values > 0.5).mean()),
                "share_after_three_quarters": float((values > 0.75).mean()),
                "mean_minute": float(np.mean(minutes)),
                "curve_source": cell.arrival,
            }
        )
    return rows


def curve_share_table(arrivals: EmpiricalArrivals) -> List[Dict[str, Any]]:
    """Per-week hourly share rows for the report table."""
    hours = list(range(arrivals.start_hour, arrivals.end_hour))
    rows: List[Dict[str, Any]] = []
    for row in arrivals.rows:
        shares = tuple(row.get("shares") or ())
        rows.append(
            {
                "week": row["week"],
                "role": row.get("note") or ("经验曲线" if row.get("used") else "未使用"),
                "lines_total": row["lines_total"],
                "lines_weekday": row["lines_weekday"],
                "lines_used": row["lines_used"],
                "coverage": row["coverage"],
                "weekend_share": row["weekend_share"],
                "peak_hour": row["peak_hour"],
                **{
                    str(hour): float(shares[index]) if index < len(shares) else 0.0
                    for index, hour in enumerate(hours)
                },
            }
        )
    return rows


def cell_dict(cell: CurveCell) -> Dict[str, Any]:
    return {
        "key": cell.key,
        "label": cell.label,
        "arrival": cell.arrival,
        "policy": cell.policy,
        "profile": cell.profile,
        "profile_label": cell.profile_label,
        "duration_noise": float(cell.duration_noise),
        "pickers_per_dc": cell.pickers_per_dc,
    }
