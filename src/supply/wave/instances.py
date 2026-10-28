"""Wave-picking instance: real invoices, ABC slots, declared labor assumptions.

Online Retail II provides invoice lines and SKU popularity, not warehouse
layouts, pick times, or wave capacities. Slots come from the Week-3 ABC
slotting model; wave capacity, walking speed, pick time, setup time and labor
cost are an explicit assumption layer declared here and echoed in the report.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Sequence

import pandas as pd

from supply.network.warehouse import WarehouseLayout

DEFAULT_MAX_ORDERS = 8
DEFAULT_MAX_LINES = 40
TRAVEL_METERS_PER_MINUTE = 72.0  # 1.2 m/s walking with a cart
PICK_MINUTES_PER_LINE = 0.35
PICK_MINUTES_PER_UNIT = 0.02
SETUP_MINUTES_PER_WAVE = 3.0
LABOR_COST_PER_MINUTE = 0.45

Slot = tuple[int, int, int]


@dataclass(frozen=True)
class WaveOrder:
    invoice: str
    lines: int
    units: float
    slots: tuple[Slot, ...]


@dataclass
class WaveInstance:
    orders: list[WaveOrder]
    layout: WarehouseLayout
    max_orders: int = DEFAULT_MAX_ORDERS
    max_lines: int = DEFAULT_MAX_LINES
    pick_minutes_per_line: float = PICK_MINUTES_PER_LINE
    pick_minutes_per_unit: float = PICK_MINUTES_PER_UNIT
    setup_minutes_per_wave: float = SETUP_MINUTES_PER_WAVE
    travel_meters_per_minute: float = TRAVEL_METERS_PER_MINUTE
    labor_cost_per_minute: float = LABOR_COST_PER_MINUTE
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def order_ids(self) -> list[str]:
        return [order.invoice for order in self.orders]

    def by_id(self) -> Dict[str, WaveOrder]:
        return {order.invoice: order for order in self.orders}

    def capacity_of(self, invoices: Iterable[str]) -> tuple[int, int, float]:
        lookup = self.by_id()
        selected = [lookup[invoice] for invoice in invoices]
        return (
            len(selected),
            sum(order.lines for order in selected),
            sum(order.units for order in selected),
        )

    def fits(self, invoices: Iterable[str]) -> bool:
        count, lines, _ = self.capacity_of(invoices)
        return count <= self.max_orders and lines <= self.max_lines


def build_wave_instance(
    order_lines: pd.DataFrame,
    assignment: Mapping[str, Slot],
    layout: WarehouseLayout,
    max_orders: int = DEFAULT_MAX_ORDERS,
    max_lines: int = DEFAULT_MAX_LINES,
    pick_minutes_per_line: float = PICK_MINUTES_PER_LINE,
    pick_minutes_per_unit: float = PICK_MINUTES_PER_UNIT,
    setup_minutes_per_wave: float = SETUP_MINUTES_PER_WAVE,
    travel_meters_per_minute: float = TRAVEL_METERS_PER_MINUTE,
    labor_cost_per_minute: float = LABOR_COST_PER_MINUTE,
    meta: Dict[str, Any] | None = None,
) -> WaveInstance:
    """Aggregate invoice lines into orders and map every SKU to its slot."""
    required = {"invoice", "sku", "quantity"}
    missing = required - set(order_lines.columns)
    if missing:
        raise ValueError(f"订单行缺少列: {sorted(missing)}")
    if max_orders < 1 or max_lines < 1:
        raise ValueError("波次容量必须为正整数")

    frame = order_lines.copy()
    unmapped = sorted(set(frame["sku"].astype(str)) - set(assignment))
    if unmapped:
        raise ValueError(f"{len(unmapped)} 个 SKU 未分配槽位，例如 {unmapped[:3]}")

    orders: list[WaveOrder] = []
    for invoice, group in frame.groupby("invoice", sort=True):
        skus = sorted(group["sku"].astype(str).unique())
        slots = tuple(assignment[sku] for sku in skus)
        lines = int(len(skus))
        if lines > max_lines:
            raise ValueError(
                f"订单 {invoice} 有 {lines} 行，超过波次行数上限 {max_lines}"
            )
        orders.append(
            WaveOrder(
                invoice=str(invoice),
                lines=lines,
                units=float(group["quantity"].sum()),
                slots=slots,
            )
        )
    if not orders:
        raise ValueError("波次实例没有订单")

    details = dict(meta or {})
    details.update(
        {
            "orders": len(orders),
            "lines": sum(order.lines for order in orders),
            "units": sum(order.units for order in orders),
            "skus": int(frame["sku"].nunique()),
            "max_orders": int(max_orders),
            "max_lines": int(max_lines),
            "pick_minutes_per_line": float(pick_minutes_per_line),
            "pick_minutes_per_unit": float(pick_minutes_per_unit),
            "setup_minutes_per_wave": float(setup_minutes_per_wave),
            "travel_meters_per_minute": float(travel_meters_per_minute),
            "labor_cost_per_minute": float(labor_cost_per_minute),
            "layout_aisles": int(layout.n_aisles),
            "layout_bays": int(layout.n_bays),
            "layout_slots": int(layout.slots),
        }
    )
    return WaveInstance(
        orders=orders,
        layout=layout,
        max_orders=int(max_orders),
        max_lines=int(max_lines),
        pick_minutes_per_line=float(pick_minutes_per_line),
        pick_minutes_per_unit=float(pick_minutes_per_unit),
        setup_minutes_per_wave=float(setup_minutes_per_wave),
        travel_meters_per_minute=float(travel_meters_per_minute),
        labor_cost_per_minute=float(labor_cost_per_minute),
        meta=details,
    )


def unique_slots(orders: Sequence[WaveOrder]) -> tuple[Slot, ...]:
    return tuple({slot for order in orders for slot in order.slots})
