"""Week-11 stock deployment: where inventory sits changes end-to-end service.

Week 5 places stock by a declared DC share plus a per-SKU jitter; Weeks 9-10
keep that placement fixed and vary execution. This module treats the placement
itself as the decision. The order set, promises, layout, picker count and
release policy stay fixed and only the stock split across DCs changes, because
stock is what lets the allocator route around a congested DC.

The trade-off is explicit: a share-heavy DC can serve nearby promises with
short transit, but it also carries a larger pick load. Moving stock toward a
spare DC buys pick slack and may cost fill or transport, so the benchmark
reports mean and worst-decile service, not a single ranking.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

from .instances import E2EInstance

SHARE_TOLERANCE = 1e-6


@dataclass(frozen=True)
class StockPlan:
    """One declared stock split across DCs (shares sum to one)."""

    key: str
    label: str
    shares: Tuple[float, ...]
    note: str = ""

    def __post_init__(self) -> None:
        if not self.key or not self.label:
            raise ValueError("库存布点需要 key 与 label")
        shares = tuple(float(value) for value in self.shares)
        if len(shares) < 2:
            raise ValueError("库存布点至少需要两个 DC")
        if any(not np.isfinite(value) or value <= 0 for value in shares):
            raise ValueError("库存占比必须为正")
        total = sum(shares)
        if abs(total - 1.0) > SHARE_TOLERANCE:
            raise ValueError(f"库存占比之和应为 1，当前 {total:.6f}")
        object.__setattr__(self, "shares", shares)

    @property
    def share_text(self) -> str:
        return " / ".join(f"{value:.0%}" for value in self.shares)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "shares": list(self.shares),
            "share_text": self.share_text,
            "note": self.note,
        }


DEFAULT_STOCK_PLANS: Tuple[StockPlan, ...] = (
    StockPlan(
        "baseline",
        "基线 34/28/38",
        (0.34, 0.28, 0.38),
        "Week-5 默认布点（London / Rotterdam / Frankfurt）",
    ),
    StockPlan(
        "balanced",
        "均衡 33/33/34",
        (0.33, 0.33, 0.34),
        "从 Frankfurt 挪 4pp、从 London 挪 1pp 到 Rotterdam",
    ),
    StockPlan(
        "rotterdam",
        "Rotterdam 偏重 30/40/30",
        (0.30, 0.40, 0.30),
        "再向 Rotterdam 集中 10pp，测试是否过度",
    ),
    StockPlan(
        "london",
        "London 偏重 40/24/36",
        (0.40, 0.24, 0.36),
        "反向：把库存拉回 UK 近端，削弱 Rotterdam 缓冲",
    ),
)


def dc_stock_units(instance: E2EInstance) -> List[int]:
    """Units held per DC in the built instance."""
    stock = np.asarray(instance.fulfillment.stock)
    if stock.size == 0 or stock.sum() <= 0:
        raise ValueError("实例库存必须为正")
    return [int(value) for value in stock.sum(axis=1)]


def stock_mix(instance: E2EInstance) -> List[float]:
    """Realised stock share per DC after the per-SKU jitter and rounding."""
    units = np.asarray(dc_stock_units(instance), dtype=float)
    return [float(value) for value in units / units.sum()]


def plan_row(plan: StockPlan, instance: E2EInstance) -> Dict[str, Any]:
    """Declared and realised stock placement for the report."""
    names = list(instance.fulfillment.dc_names)
    if len(names) != len(plan.shares):
        raise ValueError("库存布点与实例的 DC 数不匹配")
    units = dc_stock_units(instance)
    mix = stock_mix(instance)
    return {
        **plan.as_dict(),
        "dcs": names,
        "stock_units": units,
        "stock_mix": mix,
        "coverage": float(instance.meta.get("stock_coverage", float("nan"))),
    }


def plans_for(keys: Sequence[str]) -> List[StockPlan]:
    """Select declared plans by key, preserving the requested order."""
    lookup = {plan.key: plan for plan in DEFAULT_STOCK_PLANS}
    unknown = [key for key in keys if key not in lookup]
    if unknown:
        raise ValueError(f"未知库存布点: {unknown}")
    return [lookup[key] for key in keys]
