"""Warehouse slotting and order-picking routes.

Layout: a single-block warehouse with parallel aisles, bays on both sides,
a front cross-aisle (dispatch) and a back cross-aisle. Distances are metric:
within an aisle you move vertically, between aisles you use the nearer cross
aisle.

Two decisions are separated:

* **slotting** -- which SKU goes to which slot. ``abc`` puts the highest
  velocity SKUs closest to dispatch; ``random`` is the control.
* **routing** -- how a picker visits the slots of one order. ``return`` walks
  each aisle and comes back, ``s_shape`` traverses aisles in a serpentine, and
  ``optimal`` solves the picker TSP (Held-Karp up to 12 picks, else 2-opt).

The order lines and SKU velocities are real; the layout and travel speeds are
declared assumptions.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence

import numpy as np
import pandas as pd

BAY_METERS = 1.2
AISLE_GAP_METERS = 2.5


@dataclass(frozen=True)
class WarehouseLayout:
    n_aisles: int = 8
    n_bays: int = 16
    back_cross_aisle: bool = True

    @property
    def depot_x(self) -> float:
        return (self.n_aisles + 1) / 2.0

    @property
    def slots(self) -> int:
        return self.n_aisles * self.n_bays * 2

    def slot_catalog(self) -> List[tuple[int, int, int]]:
        """Slots sorted by distance to dispatch (control-point distance)."""
        slots = [
            (aisle, bay, side)
            for aisle in range(1, self.n_aisles + 1)
            for bay in range(1, self.n_bays + 1)
            for side in (0, 1)
        ]
        return sorted(slots, key=lambda slot: self.depot_distance(slot))

    def depot_distance(self, slot: tuple[int, int, int]) -> float:
        aisle, bay, _ = slot
        return (
            abs(aisle - self.depot_x) * AISLE_GAP_METERS + bay * BAY_METERS
        )

    def travel(
        self, first: tuple[int, int, int], second: tuple[int, int, int]
    ) -> float:
        aisle1, bay1, _ = first
        aisle2, bay2, _ = second
        horizontal = abs(aisle1 - aisle2) * AISLE_GAP_METERS
        if aisle1 == aisle2:
            return abs(bay1 - bay2) * BAY_METERS
        front = (bay1 + bay2) * BAY_METERS + horizontal
        if not self.back_cross_aisle:
            return front
        back = (
            (self.n_bays + 1 - bay1) + (self.n_bays + 1 - bay2)
        ) * BAY_METERS + horizontal
        return min(front, back)


def assign_slots(
    skus: Iterable[str],
    layout: WarehouseLayout,
    velocity: Mapping[str, float],
    strategy: str = "abc",
    seed: int = 42,
) -> Dict[str, tuple[int, int, int]]:
    """Assign every SKU to a unique slot under a slotting policy."""
    skus = list(skus)
    if len(skus) > layout.slots:
        raise ValueError(
            f"{len(skus)} 个 SKU 超过 {layout.slots} 个槽位"
        )
    catalog = layout.slot_catalog()
    if strategy == "abc":
        ordered = sorted(skus, key=lambda sku: -float(velocity.get(sku, 0.0)))
        slots = catalog
    elif strategy == "random":
        ordered = list(skus)
        rng = np.random.default_rng(seed)
        slots = [catalog[i] for i in rng.permutation(len(catalog))]
    else:
        raise ValueError(f"未知槽位策略: {strategy}")
    return {sku: slots[index] for index, sku in enumerate(ordered)}


def route_return(
    layout: WarehouseLayout, picks: Sequence[tuple[int, int, int]]
) -> float:
    """Visit every non-empty aisle and return to the front cross-aisle."""
    if not picks:
        return 0.0
    farthest: Dict[int, int] = {}
    for aisle, bay, _ in picks:
        farthest[aisle] = max(farthest.get(aisle, 0), bay)
    aisles = sorted(farthest)
    distance = abs(aisles[0] - layout.depot_x) * AISLE_GAP_METERS
    distance += farthest[aisles[0]] * BAY_METERS
    for previous, current in zip(aisles, aisles[1:]):
        distance += (
            farthest[previous] + farthest[current]
        ) * BAY_METERS + abs(current - previous) * AISLE_GAP_METERS
    last = aisles[-1]
    distance += farthest[last] * BAY_METERS
    distance += abs(last - layout.depot_x) * AISLE_GAP_METERS
    return float(distance)


def route_s_shape(
    layout: WarehouseLayout, picks: Sequence[tuple[int, int, int]]
) -> float:
    """Serpentine traversal: enter an aisle at one end, leave at the other."""
    if not picks:
        return 0.0
    farthest: Dict[int, int] = {}
    for aisle, bay, _ in picks:
        farthest[aisle] = max(farthest.get(aisle, 0), bay)
    aisles = sorted(farthest)
    full_length = (layout.n_bays + 1) * BAY_METERS
    distance = 0.0
    at_front = True
    previous_x = layout.depot_x
    for aisle in aisles:
        distance += abs(aisle - previous_x) * AISLE_GAP_METERS
        distance += full_length
        at_front = not at_front
        previous_x = aisle
    if not at_front:
        distance += full_length
    distance += abs(previous_x - layout.depot_x) * AISLE_GAP_METERS
    return float(distance)


def _distance_matrix(
    layout: WarehouseLayout, picks: Sequence[tuple[int, int, int]]
) -> np.ndarray:
    n = len(picks)
    matrix = np.zeros((n + 1, n + 1))
    for i, slot in enumerate(picks):
        matrix[0, i + 1] = matrix[i + 1, 0] = layout.depot_distance(slot)
        for j in range(i + 1, n):
            matrix[i + 1, j + 1] = matrix[j + 1, i + 1] = layout.travel(
                slot, picks[j]
            )
    return matrix


def _held_karp(matrix: np.ndarray) -> float:
    n = matrix.shape[0] - 1
    if n <= 1:
        return float(matrix[0, n] + matrix[n, 0]) if n == 1 else 0.0
    dp = np.full((1 << n, n), np.inf)
    for i in range(n):
        dp[1 << i, i] = matrix[0, i + 1]
    for mask in range(1 << n):
        for last in range(n):
            current = dp[mask, last]
            if not np.isfinite(current):
                continue
            for nxt in range(n):
                if mask & (1 << nxt):
                    continue
                key = mask | (1 << nxt)
                value = current + matrix[last + 1, nxt + 1]
                if value < dp[key, nxt]:
                    dp[key, nxt] = value
    full = (1 << n) - 1
    return float(min(dp[full, i] + matrix[i + 1, 0] for i in range(n)))


def _two_opt(matrix: np.ndarray) -> float:
    n = matrix.shape[0] - 1
    if n <= 2:
        return _held_karp(matrix)
    path = [0] + list(range(1, n + 1))
    improved = True
    while improved:
        improved = False
        for i in range(1, len(path) - 1):
            for j in range(i + 1, len(path)):
                a, b = path[i - 1], path[i]
                c, d = path[j], path[j + 1] if j + 1 < len(path) else 0
                delta = (
                    matrix[a, c]
                    + matrix[b, d]
                    - matrix[a, b]
                    - matrix[c, d]
                )
                if delta < -1e-9:
                    path[i : j + 1] = reversed(path[i : j + 1])
                    improved = True
    full = path + [0]
    return float(sum(matrix[full[k], full[k + 1]] for k in range(len(full) - 1)))


def route_optimal(
    layout: WarehouseLayout,
    picks: Sequence[tuple[int, int, int]],
    exact_limit: int = 12,
) -> float:
    """Picker TSP: exact up to ``exact_limit`` picks, then 2-opt."""
    if not picks:
        return 0.0
    matrix = _distance_matrix(layout, picks)
    if len(picks) <= exact_limit:
        return _held_karp(matrix)
    return _two_opt(matrix)


ROUTING_POLICIES = {
    "return": route_return,
    "s_shape": route_s_shape,
    "optimal": route_optimal,
}


def evaluate_orders(
    orders: pd.DataFrame,
    assignment: Mapping[str, tuple[int, int, int]],
    layout: WarehouseLayout,
) -> pd.DataFrame:
    """Distance per invoice under every routing policy."""
    rows = []
    for invoice, frame in orders.groupby("invoice", sort=True):
        picks = [assignment[sku] for sku in frame["sku"].unique()]
        row: Dict[str, Any] = {
            "invoice": invoice,
            "lines": int(frame["sku"].nunique()),
            "units": float(frame["quantity"].sum()),
        }
        for name, policy in ROUTING_POLICIES.items():
            row[f"{name}_m"] = float(policy(layout, picks))
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_picking(results: Mapping[str, pd.DataFrame]) -> List[Dict[str, Any]]:
    """One summary row per slotting policy, relative to random slotting.

    ``return_saving`` compares each slotting's return-route distance with
    random slotting under the same routing; ``optimal_saving`` does the same
    for the optimised picker route.
    """
    if "random" not in results:
        raise ValueError("缺少 random 槽位基线")
    baseline_return = float(results["random"]["return_m"].mean())
    baseline_optimal = float(results["random"]["optimal_m"].mean())
    rows = []
    for strategy, frame in results.items():
        rows.append(
            {
                "slotting": strategy,
                "orders": int(len(frame)),
                "avg_lines": float(frame["lines"].mean()),
                "avg_units": float(frame["units"].mean()),
                "return_m": float(frame["return_m"].mean()),
                "s_shape_m": float(frame["s_shape_m"].mean()),
                "optimal_m": float(frame["optimal_m"].mean()),
                "return_saving": 1.0
                - float(frame["return_m"].mean()) / baseline_return,
                "optimal_saving": 1.0
                - float(frame["optimal_m"].mean()) / baseline_optimal,
            }
        )
    return rows
