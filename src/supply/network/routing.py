"""Vehicle routing: CVRP and VRPTW with OR-Tools, plus baselines.

The routing model is deliberately small (one depot, a handful of stores) so the
reported numbers are readable. OR-Tools uses the standard distance and capacity
dimensions; the time-window variant adds a time dimension with store receiving
blocks. A Clarke-Wright savings heuristic and a one-vehicle-per-store plan show
what optimisation buys over simple dispatch rules. For small instances an exact
dynamic program provides a proven optimum to validate the solver.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

DISTANCE_SCALE = 1000  # kilometres -> metres for integer arc costs


@dataclass
class RoutingInstance:
    coords: np.ndarray  # (n+1, 2) km, depot first
    demand: np.ndarray  # (n,)
    capacity: float
    n_vehicles: int
    speed_kmh: float = 40.0
    service_minutes: float = 20.0
    horizon_minutes: int = 480
    time_windows: Optional[List[tuple[int, int]]] = None
    names: Optional[List[str]] = None

    @property
    def n_customers(self) -> int:
        return len(self.demand)

    @property
    def distance_km(self) -> np.ndarray:
        delta = self.coords[:, None, :] - self.coords[None, :, :]
        return np.sqrt((delta**2).sum(axis=2))


@dataclass
class RoutePlan:
    method: str
    routes: List[List[int]]
    distance_km: float
    vehicles_used: int
    max_load: float
    total_minutes: float
    feasible: bool
    solve_seconds: float
    dropped: List[int]


def _travel_minutes(instance: RoutingInstance, distance_km: float) -> float:
    return distance_km / instance.speed_kmh * 60.0


def _plan_metrics(
    instance: RoutingInstance,
    routes: List[List[int]],
    method: str,
    elapsed: float,
    feasible: bool = True,
    dropped: Optional[List[int]] = None,
) -> RoutePlan:
    matrix = instance.distance_km
    total_distance = 0.0
    total_minutes = 0.0
    max_load = 0.0
    used = 0
    for route in routes:
        if not route:
            continue
        used += 1
        load = float(instance.demand[np.array(route) - 1].sum())
        max_load = max(max_load, load)
        path = [0] + route + [0]
        distance = sum(matrix[path[k], path[k + 1]] for k in range(len(path) - 1))
        total_distance += distance
        total_minutes += _travel_minutes(instance, distance)
        total_minutes += instance.service_minutes * len(route)
    return RoutePlan(
        method=method,
        routes=routes,
        distance_km=float(total_distance),
        vehicles_used=used,
        max_load=max_load,
        total_minutes=float(total_minutes),
        feasible=feasible,
        solve_seconds=float(elapsed),
        dropped=dropped or [],
    )


def naive_dispatch(instance: RoutingInstance) -> RoutePlan:
    """One dedicated vehicle per store."""
    started = time.perf_counter()
    routes = [[i] for i in range(1, instance.n_customers + 1)]
    plan = _plan_metrics(
        instance,
        routes,
        "one route per store",
        time.perf_counter() - started,
        feasible=len(routes) <= instance.n_vehicles,
    )
    return plan


def savings_heuristic(instance: RoutingInstance) -> RoutePlan:
    """Clarke-Wright parallel savings with a hard capacity check."""
    started = time.perf_counter()
    n = instance.n_customers
    matrix = instance.distance_km
    routes: Dict[int, List[int]] = {i: [i] for i in range(1, n + 1)}
    loads = {i: float(instance.demand[i - 1]) for i in range(1, n + 1)}
    savings = []
    for i in range(1, n + 1):
        for j in range(i + 1, n + 1):
            value = matrix[0, i] + matrix[0, j] - matrix[i, j]
            savings.append((value, i, j))
    savings.sort(reverse=True)

    def find_route(customer: int) -> int:
        for route_id, route in routes.items():
            if customer in route:
                return route_id
        raise KeyError(customer)

    for _, i, j in savings:
        ri, rj = find_route(i), find_route(j)
        if ri == rj:
            continue
        if loads[ri] + loads[rj] > instance.capacity + 1e-9:
            continue
        route_i, route_j = routes[ri], routes[rj]
        if i not in (route_i[0], route_i[-1]):
            continue
        if j not in (route_j[0], route_j[-1]):
            continue
        if route_i[0] == i:
            route_i = list(reversed(route_i))
        if route_j[-1] == j:
            route_j = list(reversed(route_j))
        routes[ri] = route_i + route_j
        loads[ri] += loads[rj]
        del routes[rj]

    ordered = [routes[key] for key in sorted(routes)]
    feasible = len(ordered) <= instance.n_vehicles
    return _plan_metrics(
        instance,
        ordered,
        "Clarke-Wright savings",
        time.perf_counter() - started,
        feasible=feasible,
    )


def _exact_subset_cost(
    instance: RoutingInstance, subset: List[int]
) -> Optional[float]:
    """Held-Karp TSP cost for one route; ``None`` if it exceeds capacity."""
    if not subset:
        return 0.0
    if instance.demand[np.array(subset) - 1].sum() > instance.capacity + 1e-9:
        return None
    matrix = instance.distance_km
    k = len(subset)
    if k == 1:
        return float(matrix[0, subset[0]] + matrix[subset[0], 0])
    best: Dict[tuple[int, int], float] = {}
    for idx, node in enumerate(subset):
        best[(1 << idx, idx)] = float(matrix[0, node])
    for mask in range(1, 1 << k):
        for last in range(k):
            current = best.get((mask, last))
            if current is None:
                continue
            for nxt in range(k):
                if mask & (1 << nxt):
                    continue
                key = (mask | (1 << nxt), nxt)
                value = current + matrix[subset[last], subset[nxt]]
                if value < best.get(key, math.inf):
                    best[key] = value
    full = (1 << k) - 1
    return float(
        min(
            best[(full, last)] + matrix[subset[last], 0]
            for last in range(k)
        )
    )


def _tsp_order(instance: RoutingInstance, subset: List[int]) -> List[int]:
    """Optimal depot -> subset -> depot visiting order (Held-Karp)."""
    k = len(subset)
    if k <= 1:
        return list(subset)
    matrix = instance.distance_km
    dp = np.full((1 << k, k), np.inf)
    parent = np.full((1 << k, k), -1, dtype=int)
    for i in range(k):
        dp[1 << i, i] = matrix[0, subset[i]]
    for mask in range(1 << k):
        for last in range(k):
            current = dp[mask, last]
            if not np.isfinite(current):
                continue
            for nxt in range(k):
                if mask & (1 << nxt):
                    continue
                key = mask | (1 << nxt)
                value = current + matrix[subset[last], subset[nxt]]
                if value < dp[key, nxt] - 1e-9:
                    dp[key, nxt] = value
                    parent[key, nxt] = last
    full = (1 << k) - 1
    last = int(
        min(range(k), key=lambda i: dp[full, i] + matrix[subset[i], 0])
    )
    order = []
    mask = full
    while last >= 0:
        order.append(subset[last])
        previous = int(parent[mask, last])
        mask ^= 1 << last
        last = previous
    return list(reversed(order))


def exact_cvrp(instance: RoutingInstance, max_customers: int = 10) -> RoutePlan:
    """Proven optimum by subset enumeration + Held-Karp (small instances only)."""
    started = time.perf_counter()
    n = instance.n_customers
    if n > max_customers:
        raise ValueError(f"exact_cvrp 仅支持 <= {max_customers} 个客户")
    nodes = list(range(1, n + 1))
    subset_cost: Dict[int, Optional[float]] = {}
    for mask in range(1, 1 << n):
        subset = [nodes[i] for i in range(n) if mask & (1 << i)]
        subset_cost[mask] = _exact_subset_cost(instance, subset)

    best_cost = np.full((1 << n, instance.n_vehicles + 1), np.inf)
    best_choice = np.zeros((1 << n, instance.n_vehicles + 1), dtype=int)
    best_cost[0, 0] = 0.0
    for mask in range(1, 1 << n):
        for vehicles in range(1, instance.n_vehicles + 1):
            sub = mask
            while sub:
                route_cost = subset_cost.get(sub)
                if route_cost is not None:
                    previous = best_cost[mask ^ sub, vehicles - 1]
                    candidate = route_cost + previous
                    if candidate < best_cost[mask, vehicles] - 1e-9:
                        best_cost[mask, vehicles] = candidate
                        best_choice[mask, vehicles] = sub
                sub = (sub - 1) & mask
    full = (1 << n) - 1
    feasible_vehicles = [
        vehicles
        for vehicles in range(1, instance.n_vehicles + 1)
        if np.isfinite(best_cost[full, vehicles])
    ]
    if not feasible_vehicles:
        raise ValueError("精确 CVRP 在给定容量/车辆数下不可行")
    vehicles = min(feasible_vehicles, key=lambda v: best_cost[full, v])

    routes = []
    mask = full
    while mask:
        sub = int(best_choice[mask, vehicles])
        subset = [nodes[i] for i in range(n) if sub & (1 << i)]
        routes.append(_tsp_order(instance, subset))
        mask ^= sub
        vehicles -= 1
    elapsed = time.perf_counter() - started
    plan = _plan_metrics(
        instance,
        routes,
        "exact subset DP",
        elapsed,
        feasible=len(routes) <= instance.n_vehicles,
    )
    return plan


def solve_routing(
    instance: RoutingInstance,
    time_windows: bool = False,
    time_limit_seconds: float = 2.0,
    start_time_minutes: int = 0,
) -> RoutePlan:
    """OR-Tools routing with capacity and optional receiving time windows."""
    started = time.perf_counter()
    n = instance.n_customers
    manager = pywrapcp.RoutingIndexManager(n + 1, instance.n_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)
    matrix = instance.distance_km
    matrix_m = (matrix * DISTANCE_SCALE).astype(np.int64)

    def distance_callback(from_index: int, to_index: int) -> int:
        return int(matrix_m[manager.IndexToNode(from_index), manager.IndexToNode(to_index)])

    distance_cb = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(distance_cb)

    def demand_callback(from_index: int) -> int:
        node = manager.IndexToNode(from_index)
        return int(round(float(instance.demand[node - 1]))) if node > 0 else 0

    demand_cb = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_cb,
        0,
        [int(round(instance.capacity))] * instance.n_vehicles,
        True,
        "Capacity",
    )

    if time_windows:
        if instance.time_windows is None:
            raise ValueError("time_windows=True 但实例没有时间窗")

        def time_callback(from_index: int, to_index: int) -> int:
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            travel = _travel_minutes(instance, matrix[from_node, to_node])
            service = instance.service_minutes if from_node != 0 else 0.0
            return int(round(travel + service))

        time_cb = routing.RegisterTransitCallback(time_callback)
        routing.AddDimension(
            time_cb,
            int(instance.service_minutes),
            int(instance.horizon_minutes),
            False,
            "Time",
        )
        time_dim = routing.GetDimensionOrDie("Time")
        time_dim.CumulVar(routing.Start(0)).SetRange(
            int(start_time_minutes), int(instance.horizon_minutes)
        )
        time_dim.CumulVar(routing.End(0)).SetRange(
            int(start_time_minutes), int(instance.horizon_minutes)
        )
        for node in range(1, n + 1):
            index = manager.NodeToIndex(node)
            start, end = instance.time_windows[node - 1]
            time_dim.CumulVar(index).SetRange(int(start), int(end))
            routing.AddVariableMinimizedByFinalizer(time_dim.CumulVar(index))

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    params.time_limit.FromSeconds(int(max(1, round(time_limit_seconds))))
    params.log_search = False

    solution = routing.SolveWithParameters(params)
    elapsed = time.perf_counter() - started
    if solution is None:
        return RoutePlan(
            method="OR-Tools CVRP" + (" + time windows" if time_windows else ""),
            routes=[],
            distance_km=float("nan"),
            vehicles_used=0,
            max_load=0.0,
            total_minutes=float("nan"),
            feasible=False,
            solve_seconds=elapsed,
            dropped=list(range(1, n + 1)),
        )

    routes = []
    for vehicle in range(instance.n_vehicles):
        index = routing.Start(vehicle)
        route = []
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node != 0:
                route.append(node)
            index = solution.Value(routing.NextVar(index))
        if route:
            routes.append(route)
    plan = _plan_metrics(
        instance,
        routes,
        "OR-Tools CVRP" + (" + time windows" if time_windows else ""),
        elapsed,
    )
    return plan


def routing_table(plans: List[RoutePlan]) -> List[Dict[str, Any]]:
    rows = []
    for plan in plans:
        rows.append(
            {
                "method": plan.method,
                "distance_km": plan.distance_km,
                "vehicles": plan.vehicles_used,
                "max_load": plan.max_load,
                "total_minutes": plan.total_minutes,
                "feasible": plan.feasible,
                "solve_seconds": plan.solve_seconds,
            }
        )
    return rows
