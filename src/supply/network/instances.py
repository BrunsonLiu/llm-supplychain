"""Instance builders for facility location, vehicle routing, and order picking.

The public dataset provides transaction lines with a customer country. It does
*not* provide coordinates, candidate DCs, vehicle fleets, or a warehouse
layout. Those are declared in this module as an explicit assumption layer; the
demand volumes, order composition, and SKU popularity are real.

Country coordinates are approximate centroids used only to build a plausible
transport network. They are not derived from the dataset.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

import numpy as np
import pandas as pd


# Approximate country centroids (lat, lon). Kept deliberately small and
# European: Online Retail II is a UK wholesaler and non-European demand is a
# rounding error in units.
COUNTRY_COORDS: Dict[str, tuple[float, float]] = {
    "United Kingdom": (54.0, -2.0),
    "EIRE": (53.4, -8.2),
    "Channel Islands": (49.2, -2.1),
    "Germany": (51.2, 10.4),
    "France": (46.6, 2.2),
    "Netherlands": (52.2, 5.3),
    "Belgium": (50.6, 4.6),
    "Switzerland": (46.8, 8.2),
    "Spain": (40.2, -3.7),
    "Portugal": (39.6, -8.0),
    "Italy": (42.8, 12.5),
    "Austria": (47.6, 14.1),
    "Denmark": (56.0, 10.0),
    "Sweden": (60.1, 15.6),
    "Norway": (61.0, 9.0),
    "Finland": (64.0, 26.0),
    "Poland": (52.1, 19.4),
    "Czech Republic": (49.8, 15.5),
    "Greece": (39.0, 22.0),
    "Iceland": (64.9, -18.6),
}

# Candidate European distribution hubs (lat, lon), annual capacity in units,
# annual fixed cost in currency. Capacity and cost are assumptions; the set of
# hubs is a planning choice.
DEFAULT_CANDIDATES: tuple[Dict[str, Any], ...] = (
    {"name": "London", "lat": 51.5074, "lon": -0.1278, "capacity": 1_000_000, "fixed_cost": 380_000},
    {"name": "Manchester", "lat": 53.4808, "lon": -2.2426, "capacity": 600_000, "fixed_cost": 260_000},
    {"name": "Rotterdam", "lat": 51.9244, "lon": 4.4777, "capacity": 800_000, "fixed_cost": 330_000},
    {"name": "Frankfurt", "lat": 50.1109, "lon": 8.6821, "capacity": 800_000, "fixed_cost": 330_000},
    {"name": "Paris", "lat": 48.8566, "lon": 2.3522, "capacity": 650_000, "fixed_cost": 290_000},
    {"name": "Madrid", "lat": 40.4168, "lon": -3.7038, "capacity": 450_000, "fixed_cost": 220_000},
    {"name": "Milan", "lat": 45.4642, "lon": 9.1900, "capacity": 450_000, "fixed_cost": 220_000},
    {"name": "Warsaw", "lat": 52.2297, "lon": 21.0122, "capacity": 400_000, "fixed_cost": 190_000},
)

EARTH_RADIUS_KM = 6371.0
ROAD_FACTOR = 1.25  # straight-line distance -> road distance
TRANSPORT_COST_PER_UNIT_KM = 0.00018  # currency per unit per road-km


def haversine_km(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2.0) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlambda / 2.0) ** 2
    return float(2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a)))


def distance_matrix_km(
    origins: Iterable[tuple[float, float]],
    destinations: Optional[Iterable[tuple[float, float]]] = None,
) -> np.ndarray:
    """Road distance matrix (km) with shape ``(origins, destinations)``."""
    sources = list(origins)
    targets = sources if destinations is None else list(destinations)
    matrix = np.zeros((len(sources), len(targets)))
    for i, (lat1, lon1) in enumerate(sources):
        for j, (lat2, lon2) in enumerate(targets):
            matrix[i, j] = haversine_km(lat1, lon1, lat2, lon2) * ROAD_FACTOR
    return matrix


@dataclass
class LocationInstance:
    """Capacitated facility location instance."""

    demand_countries: list[str]
    demand_units: np.ndarray
    demand_coords: np.ndarray  # (demand, 2) lat/lon
    candidate_names: list[str]
    candidate_coords: np.ndarray  # (candidates, 2) lat/lon
    capacities: np.ndarray
    fixed_costs: np.ndarray
    transport_cost: np.ndarray  # currency per unit, (demand, candidates)
    distance_km: np.ndarray
    meta: Dict[str, Any]

    @property
    def n_demand(self) -> int:
        return len(self.demand_countries)

    @property
    def n_candidates(self) -> int:
        return len(self.candidate_names)


def build_location_instance(
    clean: pd.DataFrame,
    skus: Optional[Iterable[str]] = None,
    weeks: int = 52,
    top_countries: int = 14,
    candidates: Iterable[Dict[str, Any]] = DEFAULT_CANDIDATES,
    fixed_cost_multiplier: float = 1.0,
    end_week: Optional[pd.Timestamp] = None,
) -> LocationInstance:
    """Aggregate real units by country and attach a declared hub network.

    Countries without a coordinate are excluded; ``meta['coverage']`` reports
    how much of the selected demand the network actually covers. ``end_week``
    pins the window to the panel's last complete week instead of the partial
    final transaction week.
    """
    frame = clean.copy()
    frame["week"] = pd.to_datetime(frame["week"])
    last_week = pd.Timestamp(end_week) if end_week is not None else frame["week"].max()
    start = last_week - pd.Timedelta(weeks=weeks - 1)
    frame = frame[(frame["week"] >= start) & (frame["week"] <= last_week)]
    if skus is not None:
        frame = frame[frame["sku"].isin(list(skus))]
    if frame.empty:
        raise ValueError("选址实例没有可用交易记录")

    by_country = (
        frame.groupby("country", as_index=False)["quantity"].sum()
        .sort_values("quantity", ascending=False)
    )
    mapped = by_country[by_country["country"].isin(COUNTRY_COORDS)]
    selected = mapped.head(top_countries).copy()
    if selected.empty:
        raise ValueError("所选交易没有可映射坐标的国家")
    total_units = float(by_country["quantity"].sum())
    covered_units = float(selected["quantity"].sum())

    candidate_rows = list(candidates)
    candidate_coords = np.array(
        [(row["lat"], row["lon"]) for row in candidate_rows], dtype=float
    )
    demand_coords = np.array(
        [COUNTRY_COORDS[country] for country in selected["country"]], dtype=float
    )
    distance = distance_matrix_km(
        [tuple(coord) for coord in demand_coords],
        [tuple(coord) for coord in candidate_coords],
    )
    return LocationInstance(
        demand_countries=selected["country"].tolist(),
        demand_units=selected["quantity"].to_numpy(dtype=float),
        demand_coords=demand_coords,
        candidate_names=[str(row["name"]) for row in candidate_rows],
        candidate_coords=candidate_coords,
        capacities=np.array([float(row["capacity"]) for row in candidate_rows]),
        fixed_costs=np.array(
            [float(row["fixed_cost"]) * fixed_cost_multiplier for row in candidate_rows]
        ),
        transport_cost=distance * TRANSPORT_COST_PER_UNIT_KM,
        distance_km=distance,
        meta={
            "weeks": int(weeks),
            "period_start": str(start.date()),
            "period_end": str(last_week.date()),
            "total_units_all_countries": total_units,
            "covered_units": covered_units,
            "coverage_share": covered_units / total_units if total_units else 0.0,
            "fixed_cost_multiplier": float(fixed_cost_multiplier),
            "transport_cost_per_unit_km": TRANSPORT_COST_PER_UNIT_KM,
            "road_factor": ROAD_FACTOR,
        },
    )


def build_picking_orders(
    clean: pd.DataFrame,
    skus: Iterable[str],
    sample_orders: int = 200,
    max_lines: int = 20,
    seed: int = 42,
    week: Optional[pd.Timestamp] = None,
) -> tuple[pd.DataFrame, pd.Series, Dict[str, Any]]:
    """Sample real multi-line invoices from one trading week.

    Returns ``(order_lines, velocity, meta)`` where ``order_lines`` has
    ``invoice, sku, quantity`` and ``velocity`` is units over the last 52 weeks.
    Invoices are sampled, not filtered by size until after the line-count cut,
    so the sample keeps a realistic mix of small and large orders.
    """
    frame = clean.copy()
    frame["week"] = pd.to_datetime(frame["week"])
    sku_list = list(skus)
    last_week = pd.Timestamp(week) if week is not None else frame["week"].max()
    velocity = (
        frame[
            (frame["week"] > last_week - pd.Timedelta(weeks=52))
            & (frame["week"] <= last_week)
            & (frame["sku"].isin(sku_list))
        ]
        .groupby("sku")["quantity"]
        .sum()
    )

    window = frame[(frame["week"] == last_week) & (frame["sku"].isin(sku_list))]
    lines = (
        window.groupby(["invoice", "sku"], as_index=False)["quantity"].sum()
    )
    counts = lines.groupby("invoice")["sku"].transform("size")
    lines = lines[(counts >= 2) & (counts <= max_lines)]
    invoices = np.array(sorted(lines["invoice"].unique()))
    if len(invoices) == 0:
        raise ValueError("最后一周没有满足行数要求的订单")
    rng = np.random.default_rng(seed)
    chosen = rng.choice(
        invoices, size=min(sample_orders, len(invoices)), replace=False
    )
    sampled = lines[lines["invoice"].isin(set(chosen.tolist()))].copy()
    sampled = sampled.sort_values(["invoice", "sku"]).reset_index(drop=True)
    meta = {
        "week": str(last_week.date()),
        "eligible_invoices": int(len(invoices)),
        "sampled_invoices": int(sampled["invoice"].nunique()),
        "order_lines": int(len(sampled)),
        "unique_skus": int(sampled["sku"].nunique()),
        "median_lines_per_order": float(
            sampled.groupby("invoice").size().median()
        ),
        "units": float(sampled["quantity"].sum()),
        "seed": int(seed),
    }
    return sampled, velocity, meta


# Deterministic store positions (km) around a depot at (0, 0). The same eight
# stores as the allocation LP, placed on a compact regional grid.
STORE_COORDS: tuple[tuple[float, float], ...] = (
    (18.0, 22.0),
    (35.0, -10.0),
    (12.0, -30.0),
    (-8.0, -35.0),
    (-30.0, -12.0),
    (-22.0, 18.0),
    (-38.0, 5.0),
    (5.0, 40.0),
)


def build_route_network(
    weekly_mean_units: float,
    n_vehicles: int = 4,
    capacity_factor: float = 1.15,
    speed_kmh: float = 40.0,
    service_minutes: float = 20.0,
    horizon_minutes: int = 480,
) -> Dict[str, Any]:
    """Store routing instance around one depot.

    ``weekly_mean_units`` is the real weekly demand of the selected basket;
    store shares are the same long-tail profile as the allocation LP. Vehicle
    capacity is sized so a route can serve several stores without being empty
    on arrival, and time windows split the day into four two-hour blocks.
    """
    shares = np.array([0.28, 0.19, 0.14, 0.11, 0.09, 0.07, 0.06, 0.06])
    shares = shares / shares.sum()
    demand = shares * float(weekly_mean_units)
    capacity = int(np.ceil(demand.max() * capacity_factor / 50.0) * 50)
    coords = np.vstack([np.zeros(2), np.array(STORE_COORDS, dtype=float)])
    # Two-hour receiving blocks, paired by store cluster. Tight enough that the
    # CVRP distance-optimal plan is not automatically time-window feasible.
    blocks = ((0, 120), (120, 240), (240, 360), (360, 480))
    time_windows = [
        blocks[min(index // 2, len(blocks) - 1)] for index in range(len(STORE_COORDS))
    ]
    return {
        "coords": coords,
        "demand": demand,
        "capacity": float(capacity),
        "n_vehicles": int(n_vehicles),
        "speed_kmh": float(speed_kmh),
        "service_minutes": float(service_minutes),
        "horizon_minutes": int(horizon_minutes),
        "time_windows": time_windows,
        "shares": shares,
        "weekly_units": float(weekly_mean_units),
    }
