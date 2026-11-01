"""Multi-DC order fulfillment instances built on real invoices.

Online Retail II supplies the order composition, quantities, SKU mix, and
destination country. It does *not* supply warehouse stock, transit times,
shipping rates, or customer promises. Those are declared here as an explicit
assumption layer and reported alongside every benchmark result.

The instance is one trading week: sampled invoices become orders, invoice
lines become order lines, and each order gets a promise tier. Three DCs hold
integer stock per SKU and have a weekly throughput cap.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from supply.network.instances import (
    COUNTRY_COORDS,
    DEFAULT_CANDIDATES,
    build_picking_orders,
    distance_matrix_km,
)

# Fulfillment DCs and their per-unit handling surcharge. Coordinates are
# borrowed from the network assumption layer so both modules share one map.
FULFILLMENT_DCS: Tuple[Dict[str, Any], ...] = (
    {"name": "London", "handling_cost": 0.02},
    {"name": "Rotterdam", "handling_cost": 0.04},
    {"name": "Frankfurt", "handling_cost": 0.05},
)

DEFAULT_STOCK_SHARES = (0.34, 0.28, 0.38)
DEFAULT_CAPACITY_SHARES = (0.55, 0.40, 0.35)
PROMISE_TIERS = ((2, 0.30), (3, 0.50), (5, 0.20))  # (days, share)

TRANSIT_KM_PER_DAY = 700.0
HANDLING_DAYS = 1
FREIGHT_COST_PER_UNIT_KM = 0.0006


@dataclass
class FulfillmentInstance:
    """One-week, multi-DC, multi-line order fulfillment instance."""

    order_ids: List[str]
    destinations: List[str]
    line_order: np.ndarray  # (lines,) order index
    line_sku: np.ndarray  # (lines,) sku index
    line_qty: np.ndarray  # (lines,) units
    sku_names: List[str]
    dc_names: List[str]
    stock: np.ndarray  # (dcs, skus) integer units
    dc_capacity: np.ndarray  # (dcs,) integer units per week
    ship_cost: np.ndarray  # (dcs, orders) currency per unit
    fixed_ship_cost: float
    transit_days: np.ndarray  # (dcs, orders) integer days
    promise_days: np.ndarray  # (orders,) integer days
    late_penalty_per_unit_day: float
    unmet_penalty_per_unit: float
    meta: Dict[str, Any]

    @property
    def n_orders(self) -> int:
        return len(self.order_ids)

    @property
    def n_lines(self) -> int:
        return int(self.line_order.size)

    @property
    def n_skus(self) -> int:
        return len(self.sku_names)

    @property
    def n_dcs(self) -> int:
        return len(self.dc_names)

    def demand_by_sku(self) -> np.ndarray:
        return np.bincount(
            self.line_sku, weights=self.line_qty, minlength=self.n_skus
        ).astype(np.int64)

    def order_units(self) -> np.ndarray:
        return np.bincount(
            self.line_order, weights=self.line_qty, minlength=self.n_orders
        ).astype(np.int64)

    def lines_by_order(self) -> List[np.ndarray]:
        return [
            np.flatnonzero(self.line_order == order)
            for order in range(self.n_orders)
        ]

    def validate(self) -> None:
        if self.n_orders == 0 or self.n_lines == 0:
            raise ValueError("履约实例必须至少包含一个订单行")
        if len(self.destinations) != self.n_orders:
            raise ValueError("destinations 长度应等于订单数")
        if self.stock.shape != (self.n_dcs, self.n_skus):
            raise ValueError("stock 形状应为 (dcs, skus)")
        if self.ship_cost.shape != (self.n_dcs, self.n_orders):
            raise ValueError("ship_cost 形状应为 (dcs, orders)")
        if self.transit_days.shape != (self.n_dcs, self.n_orders):
            raise ValueError("transit_days 形状应为 (dcs, orders)")
        if self.promise_days.shape != (self.n_orders,):
            raise ValueError("promise_days 长度应等于订单数")
        if np.any(self.line_qty <= 0):
            raise ValueError("订单行数量必须为正")
        if np.any(self.stock < 0) or np.any(self.dc_capacity < 0):
            raise ValueError("库存与产能不能为负")


def _split_integer(total: np.ndarray, shares: np.ndarray) -> np.ndarray:
    """Split integer totals across columns by shares using largest remainder."""
    raw = total[:, None] * shares
    base = np.floor(raw).astype(np.int64)
    remainder = total - base.sum(axis=1)
    for row in range(base.shape[0]):
        extra = int(remainder[row])
        if extra <= 0:
            continue
        order = np.argsort(-(raw[row] - base[row]))
        base[row, order[:extra]] += 1
    return base


def _promise_days(n_orders: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed + 17)
    promises = np.empty(n_orders, dtype=np.int64)
    order = rng.permutation(n_orders)
    cursor = 0
    for days, share in PROMISE_TIERS:
        size = int(round(share * n_orders))
        stop = min(n_orders, cursor + size)
        promises[order[cursor:stop]] = days
        cursor = stop
    promises[order[cursor:]] = PROMISE_TIERS[-1][0]
    return promises


def build_fulfillment_instance(
    clean: pd.DataFrame,
    skus: Iterable[str],
    sample_orders: int = 120,
    max_lines: int = 8,
    stock_factor: float = 0.85,
    stock_shares: Sequence[float] = DEFAULT_STOCK_SHARES,
    capacity_shares: Sequence[float] = DEFAULT_CAPACITY_SHARES,
    seed: int = 42,
    week: Optional[pd.Timestamp] = None,
    dcs: Sequence[Dict[str, Any]] = FULFILLMENT_DCS,
    stock_basis: str = "actual",
    lookback_weeks: int = 6,
    safety_z: float = 1.645,
    forecast_path: str = "benchmarks/backtest_predictions.csv",
    forecast_model: str = "lightgbm",
    forecast_calibrate: bool = True,
    forecast_fill: str = "none",
) -> FulfillmentInstance:
    """Sample one week of real invoices and attach a declared fulfillment network.

    Stock covers ``stock_factor`` of sampled demand when ``stock_basis`` is
    ``"actual"`` (the benchmark convention), ``stock_factor`` times the mean
    demand of the previous ``lookback_weeks`` when it is ``"history"``,
    ``stock_factor`` times ``mean + safety_z × std`` when it is ``"safety"``
    (order-up-to safety stock), ``stock_factor`` times the rolling-origin
    forecast in ``forecast_path`` when it is ``"forecast"``, or the forecast's
    per-SKU shares applied to the historical total when it is
    ``"forecast_share"``. Stock is split across DCs by ``stock_shares`` plus a
    deterministic per-SKU jitter, so some SKUs sit in a DC far from where they
    are ordered. ``capacity_shares`` sets each DC's weekly unit throughput.
    Both are assumptions, not observations.
    """
    if sample_orders <= 0:
        raise ValueError("sample_orders 必须为正")
    if not 0.0 < stock_factor <= 2.0:
        raise ValueError("stock_factor 必须在 (0, 2] 内")
    if stock_basis not in {
        "actual",
        "history",
        "safety",
        "forecast",
        "forecast_share",
        "last_week_share",
    }:
        raise ValueError(
            "stock_basis 必须是 actual / history / safety / forecast / "
            "forecast_share / last_week_share"
        )
    if lookback_weeks <= 0:
        raise ValueError("lookback_weeks 必须为正")
    if safety_z < 0:
        raise ValueError("safety_z 不能为负")
    if forecast_fill not in {"none", "history"}:
        raise ValueError("forecast_fill 必须是 none 或 history")
    shares = np.asarray(stock_shares, dtype=float)
    capacities = np.asarray(capacity_shares, dtype=float)
    if shares.shape != (len(dcs),) or capacities.shape != (len(dcs),):
        raise ValueError("stock_shares / capacity_shares 长度应等于 DC 数")
    if np.any(shares <= 0) or np.any(capacities <= 0):
        raise ValueError("库存与产能占比必须为正")

    frame = clean[clean["country"].isin(COUNTRY_COORDS)].copy()
    if frame.empty:
        raise ValueError("没有可映射国家坐标的交易记录")
    orders, _, picking_meta = build_picking_orders(
        frame,
        skus,
        sample_orders=sample_orders,
        max_lines=max_lines,
        seed=seed,
        week=week,
    )
    country = (
        frame[["invoice", "country"]]
        .drop_duplicates("invoice")
        .set_index("invoice")["country"]
    )
    orders["country"] = orders["invoice"].map(country)
    orders = orders[orders["country"].notna()].copy()
    if orders.empty:
        raise ValueError("采样订单没有可用的目的国")

    order_ids = sorted(orders["invoice"].astype(str).unique())
    order_index = {order: index for index, order in enumerate(order_ids)}
    sku_names = sorted(orders["sku"].astype(str).unique())
    sku_index = {sku: index for index, sku in enumerate(sku_names)}
    orders["order_index"] = orders["invoice"].astype(str).map(order_index)
    orders["sku_index"] = orders["sku"].astype(str).map(sku_index)
    orders = orders.sort_values(["order_index", "sku_index"]).reset_index(drop=True)

    line_order = orders["order_index"].to_numpy(dtype=np.int64)
    line_sku = orders["sku_index"].to_numpy(dtype=np.int64)
    line_qty = np.rint(orders["quantity"].to_numpy(dtype=float)).astype(np.int64)
    line_qty = np.clip(line_qty, 1, None)

    destinations = (
        orders.drop_duplicates("order_index")
        .sort_values("order_index")["country"]
        .tolist()
    )
    n_orders = len(order_ids)
    n_skus = len(sku_names)

    rng = np.random.default_rng(seed)
    demand = np.bincount(line_sku, weights=line_qty, minlength=n_skus)
    order_scale = 1.0
    forecast_scale = 1.0
    if stock_basis in {
        "history",
        "safety",
        "forecast",
        "forecast_share",
        "last_week_share",
    }:
        target_week = pd.Timestamp(week) if week is not None else pd.to_datetime(
            clean["week"]
        ).max()
        history = clean[clean["country"].isin(COUNTRY_COORDS)].copy()
        history["week"] = pd.to_datetime(history["week"])
        past_weeks = sorted(
            history.loc[history["week"] < target_week, "week"].unique()
        )[-lookback_weeks:]
        if not past_weeks:
            raise ValueError("history 库存基准没有目标周之前的历史")
        past = history[history["week"].isin(past_weeks)]
        weekly = past.pivot_table(
            index="week",
            columns="sku",
            values="quantity",
            aggfunc="sum",
            fill_value=0.0,
        )
        mean_demand = weekly.mean().reindex(sku_names, fill_value=0.0)
        if stock_basis == "safety":
            std_demand = weekly.std(ddof=1).reindex(sku_names, fill_value=0.0)
            target_demand = mean_demand + safety_z * std_demand
        elif stock_basis == "forecast":
            predictions = pd.read_csv(forecast_path, parse_dates=["week"])
            selected = predictions[
                (predictions["model"] == forecast_model)
                & (predictions["week"] == target_week)
            ]
            if selected.empty:
                raise ValueError(
                    f"forecast 没有 {forecast_model} 在 {target_week.date()} 的预测"
                )
            model_rows = predictions[predictions["model"] == forecast_model]
            if forecast_calibrate:
                completed = model_rows[model_rows["week"] < target_week].dropna(
                    subset=["actual", "pred"]
                )
                completed_weeks = sorted(completed["week"].unique())[-lookback_weeks:]
                calibration = completed[completed["week"].isin(completed_weeks)]
                predicted_total = float(calibration["pred"].sum())
                actual_total = float(calibration["actual"].sum())
                if predicted_total > 0:
                    forecast_scale = actual_total / predicted_total
                    forecast_scale = float(np.clip(forecast_scale, 0.5, 2.0))
            predicted = (
                selected.drop_duplicates("sku", keep="last")
                .set_index("sku")["pred"]
                .reindex(sku_names)
            )
            target_demand = predicted.clip(lower=0.0) * forecast_scale
            if forecast_fill == "history":
                target_demand = target_demand.fillna(mean_demand)
            else:
                target_demand = target_demand.fillna(0.0)
        elif stock_basis == "forecast_share":
            predictions = pd.read_csv(forecast_path, parse_dates=["week"])
            selected = predictions[
                (predictions["model"] == forecast_model)
                & (predictions["week"] == target_week)
            ]
            if selected.empty:
                raise ValueError(
                    f"forecast_share 没有 {forecast_model} 在 "
                    f"{target_week.date()} 的预测"
                )
            predicted = (
                selected.drop_duplicates("sku", keep="last")
                .set_index("sku")["pred"]
                .reindex(sku_names)
                .clip(lower=0.0)
            )
            base = predicted.fillna(mean_demand)
            total = float(mean_demand.sum())
            if base.sum() > 0 and total > 0:
                target_demand = base / base.sum() * total
            else:
                target_demand = mean_demand
        elif stock_basis == "last_week_share":
            prior_week = target_week - pd.Timedelta(weeks=1)
            if prior_week not in weekly.index:
                raise ValueError(
                    f"last_week_share 缺少 {prior_week.date()} 的前一周需求"
                )
            prior = weekly.loc[prior_week].reindex(sku_names).fillna(0.0)
            total = float(mean_demand.sum())
            if prior.sum() > 0 and total > 0:
                target_demand = prior / prior.sum() * total
            else:
                target_demand = mean_demand
        else:
            target_demand = mean_demand
        # The benchmark instance holds stock for a sampled number of orders,
        # not the whole week. Scale the historical weekly demand by the ratio
        # of sampled orders to the historical average weekly invoice count.
        weekly_invoices = past.groupby("week")["invoice"].nunique()
        mean_weekly_invoices = float(weekly_invoices.mean())
        order_scale = float(n_orders) / mean_weekly_invoices if mean_weekly_invoices else 1.0
        stock_total = np.rint(
            target_demand.to_numpy(dtype=float) * stock_factor * order_scale
        ).astype(np.int64)
    else:
        stock_total = np.rint(demand * stock_factor).astype(np.int64)
    weights = shares[None, :] * rng.uniform(0.75, 1.25, size=(n_skus, len(dcs)))
    stock = _split_integer(
        stock_total, weights / weights.sum(axis=1, keepdims=True)
    ).T

    total_units = int(line_qty.sum())
    dc_capacity = np.ceil(capacities * total_units).astype(np.int64)

    dc_rows = []
    for dc in dcs:
        match = [row for row in DEFAULT_CANDIDATES if row["name"] == dc["name"]]
        if not match:
            raise ValueError(f"未知 DC: {dc['name']}")
        dc_rows.append(match[0])
    dc_coords = np.array([(row["lat"], row["lon"]) for row in dc_rows], dtype=float)
    dest_coords = np.array(
        [COUNTRY_COORDS[name] for name in destinations], dtype=float
    )
    distance = distance_matrix_km(
        [tuple(coord) for coord in dc_coords],
        [tuple(coord) for coord in dest_coords],
    )
    handling = np.array([float(dc["handling_cost"]) for dc in dcs])
    ship_cost = distance * FREIGHT_COST_PER_UNIT_KM + handling[:, None]
    transit_days = (
        HANDLING_DAYS + np.ceil(distance / TRANSIT_KM_PER_DAY).astype(np.int64)
    )
    promise_days = _promise_days(n_orders, seed)

    promise_counts = {
        str(days): int((promise_days == days).sum())
        for days, _ in PROMISE_TIERS
    }
    instance = FulfillmentInstance(
        order_ids=order_ids,
        destinations=destinations,
        line_order=line_order,
        line_sku=line_sku,
        line_qty=line_qty,
        sku_names=sku_names,
        dc_names=[str(dc["name"]) for dc in dcs],
        stock=stock,
        dc_capacity=dc_capacity,
        ship_cost=ship_cost,
        fixed_ship_cost=25.0,
        transit_days=transit_days,
        promise_days=promise_days,
        late_penalty_per_unit_day=0.35,
        unmet_penalty_per_unit=6.0,
        meta={
            "week": picking_meta["week"],
            "orders": n_orders,
            "order_lines": int(line_qty.size),
            "skus": n_skus,
            "units": total_units,
            "dcs": [str(dc["name"]) for dc in dcs],
            "promise_mix": ", ".join(
                f"{days}d={count}" for days, count in promise_counts.items()
            ),
            "handling_days": HANDLING_DAYS,
            "transit_km_per_day": TRANSIT_KM_PER_DAY,
            "freight_cost_per_unit_km": FREIGHT_COST_PER_UNIT_KM,
            "eligible_invoices": picking_meta["eligible_invoices"],
            "sampled_invoices": picking_meta["sampled_invoices"],
            "median_lines_per_order": picking_meta["median_lines_per_order"],
            "stock_factor": float(stock_factor),
            "stock_basis": stock_basis,
            "stock_lookback_weeks": int(lookback_weeks),
            "stock_safety_z": float(safety_z) if stock_basis == "safety" else None,
            "stock_forecast_path": forecast_path
            if stock_basis in {"forecast", "forecast_share"}
            else None,
            "stock_forecast_model": forecast_model
            if stock_basis in {"forecast", "forecast_share"}
            else None,
            "stock_forecast_scale": float(forecast_scale)
            if stock_basis == "forecast"
            else None,
            "stock_forecast_fill": forecast_fill
            if stock_basis == "forecast"
            else None,
            "stock_history_order_scale": float(order_scale),
            "stock_units": int(stock.sum()),
            "stock_coverage": float(stock.sum() / total_units) if total_units else 0.0,
            "stock_shares": [float(x) for x in shares],
            "capacity_shares": [float(x) for x in capacities],
            "dc_capacity": [int(x) for x in dc_capacity],
            "promise_days": promise_counts,
            "promise_tiers": [[int(day), float(share)] for day, share in PROMISE_TIERS],
            "transit_days_range": [
                int(transit_days.min()),
                int(transit_days.max()),
            ],
            "fixed_ship_cost": 25.0,
            "late_penalty_per_unit_day": 0.35,
            "unmet_penalty_per_unit": 6.0,
            "handling_cost_per_unit": [float(x) for x in handling],
            "seed": int(seed),
            "assumptions": [
                "订单/行/数量/目的国来自 Online Retail II 真实发票",
                "DC 库存、产能、转运天数、SLA 承诺与费率是显式假设",
                "库存按 stock_basis（actual=目标周需求，history=前 N 周均值，safety=均值+z×标准差，forecast=滚动预测，forecast_share=预测结构+历史总量）× stock_factor 分配并加入确定性偏斜",
            ],
        },
    )
    instance.validate()
    return instance
