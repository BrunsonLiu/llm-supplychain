"""Empirical intraday arrival curves fitted to Online Retail II timestamps.

Every earlier E2E module sampled mid-shift arrivals from a declared uniform
window or a declared relative spike. The public dataset does carry the time of
day of each invoice, so the *shape* of the intraday curve can be estimated
instead of asserted. This module:

* aggregates invoice lines into hourly buckets inside a business window
  (Mon-Fri, 08:00-18:00 by default);
* turns each week into an :class:`ArrivalCurve` with sampling and CDF helpers;
* fits one curve per prior week, an equal-weight mean curve, and a holdout
  curve for the target week that is reported but never used for planning.

The curve fixes only the intraday shape. The promise window per tier, the
on-site share and the pick cutoffs stay declared: an order that arrives inside
its tier window draws its minute from the curve rescaled to that window.

Caveat: ``InvoiceDate`` is the retailer's invoice creation time, not a
warehouse receipt scan. The curve is the best public proxy for when demand
appears during the day, not a measured DC arrival process.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

DEFAULT_START_HOUR = 8
DEFAULT_END_HOUR = 18
DEFAULT_LOOKBACK_WEEKS = 6
MIN_WEEK_LINES = 100
TOL = 1e-6


def _normalized(shares: Sequence[float]) -> Tuple[float, ...]:
    values = tuple(float(value) for value in shares)
    if not values:
        raise ValueError("到达曲线至少需要一个时间桶")
    if any(value < 0 for value in values):
        raise ValueError("到达曲线的小时占比不能为负")
    total = float(sum(values))
    if total <= 0:
        raise ValueError("到达曲线的小时占比之和必须为正")
    return tuple(value / total for value in values)


@dataclass(frozen=True)
class ArrivalCurve:
    """Piecewise-uniform intraday arrival shape over equal-width hour buckets."""

    shares: Tuple[float, ...]
    start_hour: int = DEFAULT_START_HOUR
    end_hour: int = DEFAULT_END_HOUR
    label: str = ""
    week: str = ""

    def __post_init__(self) -> None:
        if self.end_hour <= self.start_hour:
            raise ValueError("到达曲线的结束小时必须晚于开始小时")
        if len(self.shares) != self.end_hour - self.start_hour:
            raise ValueError("到达曲线的小时桶数量必须等于营业小时数")
        if any(float(value) < 0 for value in self.shares):
            raise ValueError("到达曲线的小时占比不能为负")
        total = float(sum(self.shares))
        if total <= 0:
            raise ValueError("到达曲线的小时占比之和必须为正")
        if abs(total - 1.0) > TOL:
            object.__setattr__(self, "shares", _normalized(self.shares))

    @property
    def buckets(self) -> int:
        return len(self.shares)

    @property
    def hours(self) -> List[int]:
        return list(range(self.start_hour, self.end_hour))

    @property
    def cdf(self) -> np.ndarray:
        return np.cumsum(np.asarray(self.shares, dtype=float))

    @property
    def peak_hour(self) -> int:
        return self.start_hour + int(np.argmax(np.asarray(self.shares)))

    @property
    def peak_share(self) -> float:
        return float(max(self.shares))

    @property
    def mean_fraction(self) -> float:
        """Expected position inside the window, in [0, 1]."""
        n = self.buckets
        return float(
            sum(share * (index + 0.5) / n for index, share in enumerate(self.shares))
        )

    def cdf_at(self, fraction: float) -> float:
        """CDF at a relative position inside the window (piecewise linear)."""
        spot = min(max(float(fraction), 0.0), 1.0) * self.buckets
        whole = int(np.floor(spot))
        partial = spot - whole
        cdf = self.cdf
        total = 0.0 if whole == 0 else float(cdf[whole - 1])
        if whole < self.buckets:
            total += float(self.shares[whole]) * partial
        return min(max(total, 0.0), 1.0)

    def sample(self, rng: np.random.Generator, window_minutes: float) -> float:
        """Draw one arrival minute inside ``[0, window_minutes]``."""
        if window_minutes <= 0:
            return 0.0
        index = int(rng.choice(self.buckets, p=np.asarray(self.shares, dtype=float)))
        within = float(rng.random())
        return (index + within) / self.buckets * float(window_minutes)

    def summary(self) -> Dict[str, Any]:
        return {
            "week": self.week,
            "label": self.label,
            "start_hour": self.start_hour,
            "end_hour": self.end_hour,
            "shares": [float(value) for value in self.shares],
            "peak_hour": self.peak_hour,
            "peak_share": self.peak_share,
            "mean_fraction": self.mean_fraction,
            "share_after_half": 1.0 - self.cdf_at(0.5),
            "share_after_three_quarters": 1.0 - self.cdf_at(0.75),
        }

    def as_dict(self) -> Dict[str, Any]:
        return {
            "shares": [float(value) for value in self.shares],
            "start_hour": self.start_hour,
            "end_hour": self.end_hour,
            "label": self.label,
            "week": self.week,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArrivalCurve":
        return cls(
            shares=tuple(float(value) for value in data["shares"]),
            start_hour=int(data.get("start_hour", DEFAULT_START_HOUR)),
            end_hour=int(data.get("end_hour", DEFAULT_END_HOUR)),
            label=str(data.get("label", "")),
            week=str(data.get("week", "")),
        )


def weekly_hourly_counts(
    clean: pd.DataFrame,
    week: pd.Timestamp | str,
    start_hour: int = DEFAULT_START_HOUR,
    end_hour: int = DEFAULT_END_HOUR,
    weekdays_only: bool = True,
) -> Dict[str, Any]:
    """Aggregate one week's invoice lines into hourly buckets."""
    if end_hour <= start_hour:
        raise ValueError("结束小时必须晚于开始小时")
    if "invoice_date" not in clean.columns:
        raise ValueError("清洗数据缺少 invoice_date 列")
    stamp = pd.Timestamp(week)
    block = clean.loc[clean["week"] == stamp]
    total = int(len(block))
    weekday_share = 0.0
    if total and weekdays_only:
        weekday_share = float((block["invoice_date"].dt.day_of_week >= 5).mean())
        block = block.loc[block["invoice_date"].dt.day_of_week < 5]
    hour = block["invoice_date"].dt.hour + block["invoice_date"].dt.minute / 60.0
    in_window = (hour >= start_hour) & (hour < end_hour)
    used = block.loc[in_window]
    counts = np.zeros(end_hour - start_hour, dtype=float)
    if len(used):
        bucket = np.floor(hour.loc[in_window] - start_hour).astype(int)
        counts = np.bincount(bucket, minlength=end_hour - start_hour).astype(float)
    return {
        "week": str(stamp.date()),
        "lines_total": total,
        "lines_weekday": int(len(block)),
        "lines_used": int(len(used)),
        "weekend_share": weekday_share,
        "coverage": float(len(used) / len(block)) if len(block) else 0.0,
        "counts": [int(value) for value in counts],
        "shares": _normalized(counts) if counts.sum() > 0 else tuple(),
        "peak_hour": int(np.argmax(counts)) + start_hour if counts.sum() > 0 else None,
    }


def l1_distance(left: ArrivalCurve, right: ArrivalCurve) -> float:
    """Total-variation distance in [0, 1] between two equal-width curves."""
    if left.buckets != right.buckets:
        raise ValueError("两条到达曲线的小时桶数量必须一致")
    return float(
        0.5 * sum(abs(a - b) for a, b in zip(left.shares, right.shares))
    )


def mean_curve(
    curves: Sequence[ArrivalCurve],
    label: str = "前几周平均曲线",
    week: str = "mean",
) -> ArrivalCurve:
    if not curves:
        raise ValueError("至少需要一条到达曲线")
    buckets = curves[0].buckets
    if any(curve.buckets != buckets for curve in curves):
        raise ValueError("到达曲线的桶数量不一致")
    stacks = np.asarray([curve.shares for curve in curves], dtype=float)
    return ArrivalCurve(
        shares=tuple(stacks.mean(axis=0)),
        start_hour=curves[0].start_hour,
        end_hour=curves[0].end_hour,
        label=label,
        week=week,
    )


def uniform_curve(
    start_hour: int = DEFAULT_START_HOUR,
    end_hour: int = DEFAULT_END_HOUR,
    label: str = "均匀到达",
) -> ArrivalCurve:
    return ArrivalCurve(
        shares=tuple(1.0 / (end_hour - start_hour) for _ in range(end_hour - start_hour)),
        start_hour=start_hour,
        end_hour=end_hour,
        label=label,
        week="uniform",
    )


@dataclass(frozen=True)
class EmpiricalArrivals:
    """Curves fitted from prior weeks plus a target-week holdout curve."""

    curves: Tuple[ArrivalCurve, ...]
    mean: ArrivalCurve
    target: ArrivalCurve
    rows: Tuple[Dict[str, Any], ...]
    skipped: Tuple[str, ...]
    diagnostics: Dict[str, Any]
    start_hour: int = DEFAULT_START_HOUR
    end_hour: int = DEFAULT_END_HOUR
    lookback_weeks: int = DEFAULT_LOOKBACK_WEEKS

    def __len__(self) -> int:
        return len(self.curves)

    def curve_for(self, index: int) -> ArrivalCurve:
        if not self.curves:
            raise ValueError("没有可用的经验到达曲线")
        return self.curves[int(index) % len(self.curves)]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "start_hour": self.start_hour,
            "end_hour": self.end_hour,
            "lookback_weeks": self.lookback_weeks,
            "curves": [curve.as_dict() for curve in self.curves],
            "mean_curve": self.mean.as_dict(),
            "target_curve": self.target.as_dict(),
            "rows": [dict(row) for row in self.rows],
            "skipped": list(self.skipped),
            "diagnostics": dict(self.diagnostics),
        }


def fit_empirical_arrivals(
    clean: pd.DataFrame,
    target_week: pd.Timestamp | str,
    lookback_weeks: int = DEFAULT_LOOKBACK_WEEKS,
    start_hour: int = DEFAULT_START_HOUR,
    end_hour: int = DEFAULT_END_HOUR,
    weekdays_only: bool = True,
    min_lines: int = MIN_WEEK_LINES,
) -> EmpiricalArrivals:
    """Fit one curve per prior week, plus a mean and a holdout curve."""
    if lookback_weeks < 1:
        raise ValueError("回看周数必须 >= 1")
    target = pd.Timestamp(target_week)
    weeks = [target - pd.Timedelta(weeks=offset) for offset in range(lookback_weeks, 0, -1)]

    rows: List[Dict[str, Any]] = []
    curves: List[ArrivalCurve] = []
    skipped: List[str] = []
    for week in weeks:
        stats = weekly_hourly_counts(
            clean, week, start_hour, end_hour, weekdays_only=weekdays_only
        )
        if stats["lines_used"] < min_lines:
            skipped.append(str(week.date()))
            rows.append({**stats, "used": False, "note": "样本不足"})
            continue
        curve = ArrivalCurve(
            shares=tuple(stats["shares"]),
            start_hour=start_hour,
            end_hour=end_hour,
            label=f"{week.date()} 经验曲线",
            week=str(week.date()),
        )
        curves.append(curve)
        rows.append(
            {
                **stats,
                "used": True,
                "peak_share": curve.peak_share,
                "mean_fraction": curve.mean_fraction,
                "share_after_half": 1.0 - curve.cdf_at(0.5),
                "share_after_three_quarters": 1.0 - curve.cdf_at(0.75),
                "note": "",
            }
        )
    if not curves:
        raise ValueError(f"前 {lookback_weeks} 周没有足够样本拟合到达曲线")

    target_stats = weekly_hourly_counts(
        clean, target, start_hour, end_hour, weekdays_only=weekdays_only
    )
    if target_stats["lines_used"] < min_lines:
        raise ValueError("目标周样本不足，无法生成留出曲线")
    target_curve = ArrivalCurve(
        shares=tuple(target_stats["shares"]),
        start_hour=start_hour,
        end_hour=end_hour,
        label=f"{target.date()} 目标周（留出，不参与选点）",
        week=str(target.date()),
    )
    mean = mean_curve(
        curves,
        label=f"前 {len(curves)} 周平均曲线",
        week="mean",
    )

    pairwise = [
        l1_distance(left, right)
        for index, left in enumerate(curves)
        for right in curves[index + 1 :]
    ]
    uniform = uniform_curve(start_hour, end_hour)
    to_uniform = [l1_distance(curve, uniform) for curve in curves]
    holdout = l1_distance(target_curve, mean)
    diagnostics = {
        "pairwise_l1_mean": float(np.mean(pairwise)) if pairwise else 0.0,
        "pairwise_l1_max": float(np.max(pairwise)) if pairwise else 0.0,
        "uniform_l1_mean": float(np.mean(to_uniform)),
        "holdout_l1": holdout,
        "holdout_percentile": (
            float(np.mean([holdout > value for value in pairwise])) if pairwise else 0.0
        ),
        "target_peak_hour": target_curve.peak_hour,
        "target_peak_share": target_curve.peak_share,
        "target_mean_fraction": target_curve.mean_fraction,
        "target_share_after_half": 1.0 - target_curve.cdf_at(0.5),
        "target_share_after_three_quarters": 1.0 - target_curve.cdf_at(0.75),
        "target_coverage": target_stats["coverage"],
        "target_weekend_share": target_stats["weekend_share"],
    }
    rows.append({**target_stats, "used": False, "note": "目标周留出诊断"})
    return EmpiricalArrivals(
        curves=tuple(curves),
        mean=mean,
        target=target_curve,
        rows=tuple(rows),
        skipped=tuple(skipped),
        diagnostics=diagnostics,
        start_hour=start_hour,
        end_hour=end_hour,
        lookback_weeks=lookback_weeks,
    )


def cutoff_coverage(
    curve: ArrivalCurve,
    cutoffs: Iterable[int],
    shift_minutes: float,
) -> Dict[str, float]:
    """Share of the curve's mass that shows up before each pick cutoff."""
    if shift_minutes <= 0:
        raise ValueError("班次时长必须为正")
    return {
        str(int(cutoff)): curve.cdf_at(float(cutoff) / float(shift_minutes))
        for cutoff in cutoffs
    }
