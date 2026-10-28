"""Monte Carlo robustness for the allocation -> picking -> release chain.

Week 9 scores one arrival draw with deterministic pick minutes. That is a
single point estimate. This module replays the same allocation under many
arrival seeds and optional stress axes:

* an intraday arrival spike (a share of mid-shift orders lands inside a
  relative window), and
* lognormal pick-duration noise as a congestion proxy.

The output is a tidy frame of per-seed metrics plus distribution and paired
statistics. All assumptions are declared, not fitted: seeds share the order
set, stock, promises and allocation, so differences isolate execution risk.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from supply.fulfillment import FulfillmentResult
from supply.wave.dynamic import DEFAULT_MIN_FILL, DEFAULT_WAIT_MINUTES

from .instances import E2EInstance, normalize_arrival_profile, rebuild_arrivals
from .pipeline import POLICY_LABELS, run_pick_layer

DEFAULT_SEEDS: Tuple[int, ...] = tuple(range(1, 31))

SUMMARY_METRICS: Dict[str, str] = {
    "e2e_otif_rate": "端到端 OTIF",
    "pick_on_time_rate": "拣选准时率",
    "pick_makespan": "最长完工 (min)",
    "pick_tardiness": "迟到票据分钟",
    "labor_per_ticket": "单票工时 (min)",
    "total_cost": "总成本 (€)",
}

# Service rates are read from the lower tail; time and cost from the upper tail.
DOWN_SIDE = {"e2e_otif_rate", "pick_on_time_rate", "dock_otif_rate"}


@dataclass(frozen=True)
class StressCell:
    """One execution environment: release policy, arrival profile and noise."""

    key: str
    label: str
    policy: str = "edf"
    profile: Optional[Dict[str, float]] = None
    duration_noise: float = 0.0
    pickers_per_dc: Optional[int] = None
    wait_minutes: float = DEFAULT_WAIT_MINUTES
    min_fill: int = DEFAULT_MIN_FILL

    def __post_init__(self) -> None:
        if self.policy not in POLICY_LABELS:
            raise ValueError(f"未知在线策略: {self.policy}")
        if self.duration_noise < 0:
            raise ValueError("拣选时长噪声标准差不能为负")
        if self.pickers_per_dc is not None and self.pickers_per_dc < 1:
            raise ValueError("每 DC 拣货员数量必须为正")
        object.__setattr__(
            self, "profile", normalize_arrival_profile(self.profile)
        )

    @property
    def profile_label(self) -> str:
        if self.profile is None:
            return "均匀到达"
        return (
            f"尖峰 {self.profile['spike_share']:.0%} "
            f"@ {self.profile['spike_center']:.2f}±{self.profile['spike_width'] / 2:.2f}"
        )


def replay_allocation(
    instance: E2EInstance,
    allocation: FulfillmentResult,
    scenario: str,
    cell: StressCell,
    seeds: Sequence[int],
) -> pd.DataFrame:
    """Replay one allocation under every seed of one stress cell."""
    if not seeds:
        raise ValueError("随机种子列表不能为空")
    rows: List[Dict[str, object]] = []
    for seed in seeds:
        shifted = rebuild_arrivals(instance, int(seed), cell.profile)
        result = run_pick_layer(
            shifted,
            allocation,
            scenario=scenario,
            policy=cell.policy,
            wait_minutes=cell.wait_minutes,
            min_fill=cell.min_fill,
            pickers_per_dc=cell.pickers_per_dc,
            duration_noise=cell.duration_noise or None,
            noise_seed=int(seed),
        )
        rows.append(
            {
                "scenario": scenario,
                "cell": cell.key,
                "cell_label": cell.label,
                "policy": cell.policy,
                "profile": cell.profile_label,
                "duration_noise": float(cell.duration_noise),
                "seed": int(seed),
                **result.metrics,
            }
        )
    return pd.DataFrame(rows)


def run_monte_carlo(
    instance: E2EInstance,
    allocations: Mapping[str, FulfillmentResult],
    cells: Sequence[StressCell],
    seeds: Sequence[int] = DEFAULT_SEEDS,
) -> pd.DataFrame:
    """Replay every allocation under every stress cell and seed."""
    if not allocations:
        raise ValueError("至少需要一个分单方案")
    if not cells:
        raise ValueError("至少需要一个压力格")
    frames = [
        replay_allocation(instance, allocation, scenario, cell, seeds)
        for scenario, allocation in allocations.items()
        for cell in cells
    ]
    return pd.concat(frames, ignore_index=True)


def summarize_runs(
    frame: pd.DataFrame,
    metrics: Optional[Iterable[str]] = None,
) -> pd.DataFrame:
    """Distribution summary per scenario x cell x metric."""
    wanted = list(metrics or SUMMARY_METRICS)
    missing = sorted(set(wanted) - set(frame.columns))
    if missing:
        raise ValueError(f"缺少指标列: {missing}")
    rows: List[Dict[str, object]] = []
    for (scenario, cell), block in frame.groupby(["scenario", "cell"], sort=False):
        for metric in wanted:
            values = block[metric].astype(float).to_numpy()
            values = values[~np.isnan(values)]
            if values.size == 0:
                continue
            mean = float(values.mean())
            sd = float(values.std(ddof=1)) if values.size > 1 else 0.0
            ci95 = 1.96 * sd / math.sqrt(values.size) if values.size > 1 else 0.0
            direction = "down" if metric in DOWN_SIDE else "up"
            tail_count = max(1, int(math.ceil(0.10 * values.size)))
            ordered = np.sort(values)
            tail = ordered[:tail_count] if direction == "down" else ordered[-tail_count:]
            rows.append(
                {
                    "scenario": scenario,
                    "cell": cell,
                    "cell_label": str(block["cell_label"].iloc[0]),
                    "policy": str(block["policy"].iloc[0]),
                    "profile": str(block["profile"].iloc[0]),
                    "duration_noise": float(block["duration_noise"].iloc[0]),
                    "metric": metric,
                    "metric_label": SUMMARY_METRICS.get(metric, metric),
                    "n": int(values.size),
                    "mean": mean,
                    "sd": sd,
                    "ci95": ci95,
                    "p10": float(np.percentile(values, 10)),
                    "p50": float(np.percentile(values, 50)),
                    "p90": float(np.percentile(values, 90)),
                    "min": float(values.min()),
                    "max": float(values.max()),
                    "tail10": float(tail.mean()),
                    "tail_direction": direction,
                }
            )
    return pd.DataFrame(rows)


def paired_delta(
    frame: pd.DataFrame,
    left: str,
    right: str,
    metric: str = "e2e_otif_rate",
) -> pd.DataFrame:
    """Per-scenario paired difference ``right - left`` on shared seeds."""
    if metric not in frame.columns:
        raise ValueError(f"缺少指标列: {metric}")
    rows: List[Dict[str, object]] = []
    for scenario, block in frame.groupby("scenario", sort=False):
        first = block[block["cell"] == left].set_index("seed")[metric]
        second = block[block["cell"] == right].set_index("seed")[metric]
        common = first.index.intersection(second.index)
        if len(common) == 0:
            continue
        delta = (second.loc[common] - first.loc[common]).astype(float).to_numpy()
        sd = float(delta.std(ddof=1)) if delta.size > 1 else 0.0
        ci95 = 1.96 * sd / math.sqrt(delta.size) if delta.size > 1 else 0.0
        rows.append(
            {
                "scenario": scenario,
                "left": left,
                "right": right,
                "comparison": f"{right} − {left}",
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


def over_shift_rate(frame: pd.DataFrame, shift_minutes: float) -> pd.DataFrame:
    """Share of seeds whose picking makespan exceeds the shift."""
    if shift_minutes <= 0:
        raise ValueError("班次时长必须为正")
    rows = []
    for (scenario, cell), block in frame.groupby(["scenario", "cell"], sort=False):
        rows.append(
            {
                "scenario": scenario,
                "cell": cell,
                "n": int(len(block)),
                "over_shift_rate": float((block["pick_makespan"] > shift_minutes).mean()),
                "mean_makespan": float(block["pick_makespan"].mean()),
                "p90_makespan": float(np.percentile(block["pick_makespan"], 90)),
            }
        )
    return pd.DataFrame(rows)
