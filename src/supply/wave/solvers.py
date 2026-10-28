"""Order batching for wave picking: baselines and a restricted set-partition MILP.

The routing distance of a wave depends only on the set of slots it visits, so
candidate waves are evaluated with the Week-3 ``return`` picker route. The
CP-SAT model is a set-partitioning model over a generated candidate pool:
singletons, high-saving pairs, and waves produced by randomized savings merges.
``OPTIMAL`` therefore means optimal *for that pool*, not for all subsets.
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

import numpy as np

from supply.network.warehouse import route_return

from .instances import WaveInstance, WaveOrder, unique_slots

OBJECTIVE_SCALE = 1000


@dataclass
class WaveResult:
    name: str
    status: str
    batches: List[List[str]]
    waves: int
    orders: int
    travel_m: float
    travel_minutes: float
    pick_minutes: float
    setup_minutes: float
    labor_minutes: float
    labor_cost: float
    orders_per_hour: float
    avg_orders: float
    avg_lines: float
    max_lines: int
    max_units: float
    solve_seconds: float = 0.0
    objective: Optional[float] = None
    best_bound: Optional[float] = None
    pool_size: int = 0
    meta: Dict[str, float] = field(default_factory=dict)

    @property
    def travel_per_order(self) -> float:
        return self.travel_m / self.orders if self.orders else 0.0

    @property
    def labor_per_order(self) -> float:
        return self.labor_minutes / self.orders if self.orders else 0.0

    @property
    def gap(self) -> Optional[float]:
        if self.objective is None or self.best_bound is None:
            return None
        if self.objective <= 0:
            return 0.0
        return max(0.0, (self.objective - self.best_bound) / self.objective)


@dataclass(frozen=True)
class WaveCandidate:
    invoices: tuple[str, ...]
    lines: int
    units: float
    travel_m: float
    travel_minutes: float
    setup_minutes: float

    @property
    def objective_minutes(self) -> float:
        return self.travel_minutes + self.setup_minutes


def _travel(instance: WaveInstance, orders: Sequence[WaveOrder]) -> float:
    return float(route_return(instance.layout, unique_slots(orders)))


def wave_load(instance: WaveInstance, invoices: Iterable[str]) -> tuple[float, float]:
    """Travel metres and total labor minutes of one wave."""
    lookup = instance.by_id()
    selected = [lookup[invoice] for invoice in invoices]
    travel_m = _travel(instance, selected)
    lines = sum(order.lines for order in selected)
    units = sum(order.units for order in selected)
    minutes = (
        travel_m / instance.travel_meters_per_minute
        + lines * instance.pick_minutes_per_line
        + units * instance.pick_minutes_per_unit
        + instance.setup_minutes_per_wave
    )
    return travel_m, minutes


def evaluate_waves(
    instance: WaveInstance,
    batches: Iterable[Iterable[str]],
    name: str,
    status: str = "HEURISTIC",
    solve_seconds: float = 0.0,
    objective: Optional[float] = None,
    best_bound: Optional[float] = None,
    pool_size: int = 0,
) -> WaveResult:
    """Validate coverage/capacity and aggregate travel and labor metrics."""
    lookup = instance.by_id()
    normalized: List[List[str]] = []
    flat: List[str] = []
    for batch in batches:
        invoices = [str(invoice) for invoice in batch]
        if not invoices:
            raise ValueError("波次不能为空")
        unknown = [invoice for invoice in invoices if invoice not in lookup]
        if unknown:
            raise ValueError(f"未知订单: {unknown[:3]}")
        if not instance.fits(invoices):
            count, lines, _ = instance.capacity_of(invoices)
            raise ValueError(
                f"波次超出容量: {count}/{instance.max_orders} 单, "
                f"{lines}/{instance.max_lines} 行"
            )
        normalized.append(sorted(invoices))
        flat.extend(invoices)

    if len(flat) != len(set(flat)):
        raise ValueError("订单在波次中重复出现")
    expected = set(instance.order_ids)
    if set(flat) != expected:
        missing = sorted(expected - set(flat))
        extra = sorted(set(flat) - expected)
        raise ValueError(f"订单覆盖不完整: 缺少 {missing[:3]}, 多出 {extra[:3]}")

    waves = len(normalized)
    lines = sum(order.lines for order in instance.orders)
    units = sum(order.units for order in instance.orders)
    travel_m = 0.0
    max_lines = 0
    max_units = 0.0
    for invoice_batch in normalized:
        selected = [lookup[invoice] for invoice in invoice_batch]
        travel_m += _travel(instance, selected)
        max_lines = max(max_lines, sum(order.lines for order in selected))
        max_units = max(max_units, sum(order.units for order in selected))

    travel_minutes = travel_m / instance.travel_meters_per_minute
    pick_minutes = (
        lines * instance.pick_minutes_per_line
        + units * instance.pick_minutes_per_unit
    )
    setup_minutes = waves * instance.setup_minutes_per_wave
    labor_minutes = travel_minutes + pick_minutes + setup_minutes
    orders = len(instance.orders)
    return WaveResult(
        name=name,
        status=status,
        batches=normalized,
        waves=waves,
        orders=orders,
        travel_m=travel_m,
        travel_minutes=travel_minutes,
        pick_minutes=pick_minutes,
        setup_minutes=setup_minutes,
        labor_minutes=labor_minutes,
        labor_cost=labor_minutes * instance.labor_cost_per_minute,
        orders_per_hour=orders / (labor_minutes / 60.0) if labor_minutes else 0.0,
        avg_orders=orders / waves if waves else 0.0,
        avg_lines=lines / waves if waves else 0.0,
        max_lines=max_lines,
        max_units=max_units,
        solve_seconds=float(solve_seconds),
        objective=objective,
        best_bound=best_bound,
        pool_size=pool_size,
    )


def single_order_waves(instance: WaveInstance) -> WaveResult:
    """Pick-by-order control: one wave and one setup per invoice."""
    batches = [[order.invoice] for order in instance.orders]
    return evaluate_waves(instance, batches, name="按单拣选", status="BASELINE")


def fcfs_waves(instance: WaveInstance, seed: int = 42) -> WaveResult:
    """First-come-first-served wave filling over a synthetic arrival order."""
    rng = np.random.default_rng(seed)
    arrival = [instance.orders[index] for index in rng.permutation(len(instance.orders))]
    batches: List[List[str]] = []
    current: List[str] = []
    for order in arrival:
        trial = current + [order.invoice]
        if current and not instance.fits(trial):
            batches.append(current)
            current = [order.invoice]
        else:
            current = trial
    if current:
        batches.append(current)
    return evaluate_waves(instance, batches, name="FCFS 波次", status="HEURISTIC")


def _pair_rows(
    instance: WaveInstance, indices: Optional[Sequence[int]] = None
) -> List[tuple[float, int, int]]:
    orders = instance.orders
    indices = list(range(len(orders))) if indices is None else list(indices)
    distances = {index: _travel(instance, [orders[index]]) for index in indices}
    rows: List[tuple[float, int, int]] = []
    for position, first in enumerate(indices):
        for second in indices[position + 1 :]:
            combined = _travel(instance, [orders[first], orders[second]])
            saving = distances[first] + distances[second] - combined
            rows.append((saving, first, second))
    return rows


def _merge_pairs(
    instance: WaveInstance, scored_pairs: Sequence[tuple[float, int, int]]
) -> List[List[str]]:
    """Parallel savings merge: keep clusters while orders and lines fit."""
    orders = instance.orders
    parent = list(range(len(orders)))
    members = [[index] for index in range(len(orders))]
    line_totals = [order.lines for order in orders]

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for score, first, second in sorted(scored_pairs, reverse=True):
        if score <= 0:
            break
        root_first, root_second = find(first), find(second)
        if root_first == root_second:
            continue
        if len(members[root_first]) + len(members[root_second]) > instance.max_orders:
            continue
        if line_totals[root_first] + line_totals[root_second] > instance.max_lines:
            continue
        parent[root_second] = root_first
        members[root_first].extend(members[root_second])
        line_totals[root_first] += line_totals[root_second]
        members[root_second] = []

    return [
        sorted(orders[index].invoice for index in cluster)
        for cluster in members
        if cluster
    ]


def savings_batches(
    instance: WaveInstance,
    jitter: float = 0.0,
    seed: int = 42,
    groups: Optional[Mapping[str, str]] = None,
    name: str = "节省算法波次",
) -> WaveResult:
    """Clarke-Wright-style order savings under wave capacity limits.

    ``groups`` maps every invoice to a group; pairs are only scored inside a
    group, so orders from different groups are never merged. This is how the
    Week-7 benchmark keeps promise tiers apart while reusing the same solver.
    """
    if groups is None:
        rows = _pair_rows(instance)
    else:
        missing = set(instance.order_ids) - set(groups)
        if missing:
            raise ValueError(f"分组缺少订单: {sorted(missing)[:3]}")
        buckets: Dict[str, List[int]] = defaultdict(list)
        for index, order in enumerate(instance.orders):
            buckets[groups[order.invoice]].append(index)
        rows = []
        for indices in buckets.values():
            rows.extend(_pair_rows(instance, indices))
    if jitter > 0:
        rng = np.random.default_rng(seed)
        rows = [
            (score * (1.0 + jitter * rng.uniform(-1.0, 1.0)), first, second)
            for score, first, second in rows
        ]
    batches = _merge_pairs(instance, rows)
    return evaluate_waves(instance, batches, name=name, status="HEURISTIC")


def _candidate(instance: WaveInstance, invoices: Sequence[str]) -> WaveCandidate:
    lookup = instance.by_id()
    selected = [lookup[invoice] for invoice in invoices]
    travel_m = _travel(instance, selected)
    return WaveCandidate(
        invoices=tuple(sorted(invoices)),
        lines=sum(order.lines for order in selected),
        units=sum(order.units for order in selected),
        travel_m=travel_m,
        travel_minutes=travel_m / instance.travel_meters_per_minute,
        setup_minutes=instance.setup_minutes_per_wave,
    )


def candidate_pool(
    instance: WaveInstance,
    max_pairs: int = 2000,
    random_runs: int = 8,
    jitter: float = 0.30,
    seed: int = 42,
) -> List[WaveCandidate]:
    """Build the restricted pool the set-partitioning model can choose from."""
    pool: Dict[frozenset[str], WaveCandidate] = {}

    def add(invoices: Iterable[str]) -> None:
        key = frozenset(str(invoice) for invoice in invoices)
        if not key or key in pool or not instance.fits(key):
            return
        pool[key] = _candidate(instance, sorted(key))

    for order in instance.orders:
        add([order.invoice])

    rows = _pair_rows(instance)
    for _, first, second in sorted(rows, reverse=True)[:max_pairs]:
        add([instance.orders[first].invoice, instance.orders[second].invoice])

    for batch in _merge_pairs(instance, rows):
        add(batch)

    rng = np.random.default_rng(seed)
    for _ in range(max(0, random_runs)):
        jittered = [
            (score * (1.0 + jitter * rng.uniform(-1.0, 1.0)), first, second)
            for score, first, second in rows
        ]
        for batch in _merge_pairs(instance, jittered):
            add(batch)

    return sorted(pool.values(), key=lambda wave: (len(wave.invoices), wave.invoices))


def optimize_waves(
    instance: WaveInstance,
    max_pairs: int = 2000,
    random_runs: int = 8,
    jitter: float = 0.30,
    seed: int = 42,
    time_limit_seconds: float = 15.0,
    workers: int = 1,
) -> WaveResult:
    """Set partitioning over the candidate pool via CP-SAT."""
    from ortools.sat.python import cp_model

    started = time.perf_counter()
    pool = candidate_pool(
        instance,
        max_pairs=max_pairs,
        random_runs=random_runs,
        jitter=jitter,
        seed=seed,
    )
    if not pool:
        raise ValueError("候选波次为空")

    model = cp_model.CpModel()
    chosen = [model.NewBoolVar(f"wave_{index}") for index in range(len(pool))]
    covering: Dict[str, List[int]] = {invoice: [] for invoice in instance.order_ids}
    for index, wave in enumerate(pool):
        for invoice in wave.invoices:
            covering[invoice].append(index)

    for invoice, indexes in covering.items():
        if not indexes:
            raise ValueError(f"候选池未覆盖订单 {invoice}")
        model.Add(sum(chosen[index] for index in indexes) == 1)

    model.Minimize(
        sum(
            int(round(wave.objective_minutes * OBJECTIVE_SCALE)) * chosen[index]
            for index, wave in enumerate(pool)
        )
    )

    # Seed the incumbent with the savings partition. Without it CP-SAT can
    # return a feasible partition that is worse than the heuristic it is meant
    # to improve, because the set-partitioning search is not exhaustive.
    heuristic = savings_batches(instance, seed=seed)
    heuristic_keys = {frozenset(batch) for batch in heuristic.batches}
    hinted = 0
    for index, wave in enumerate(pool):
        if frozenset(wave.invoices) in heuristic_keys:
            model.AddHint(chosen[index], 1)
            hinted += 1

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_seconds)
    solver.parameters.num_search_workers = int(workers)
    status_code = solver.Solve(model)
    elapsed = time.perf_counter() - started
    status = solver.StatusName(status_code)
    if status not in {"OPTIMAL", "FEASIBLE"}:
        raise RuntimeError(f"波次集合划分未找到可行解: {status}")

    batches = [
        list(wave.invoices)
        for index, wave in enumerate(pool)
        if solver.Value(chosen[index]) == 1
    ]
    objective = solver.ObjectiveValue() / OBJECTIVE_SCALE
    bound = solver.BestObjectiveBound() / OBJECTIVE_SCALE
    result = evaluate_waves(
        instance,
        batches,
        name="集合划分 CP-SAT",
        status=status,
        solve_seconds=elapsed,
        objective=objective,
        best_bound=bound,
        pool_size=len(pool),
    )
    result.meta = {
        "max_pairs": int(max_pairs),
        "random_runs": int(random_runs),
        "jitter": float(jitter),
        "seed": int(seed),
        "workers": int(workers),
        "time_limit_seconds": float(time_limit_seconds),
        "hinted_waves": hinted,
    }
    return result


def wave_summary(results: Dict[str, WaveResult]) -> List[Dict[str, object]]:
    """One row per policy with savings relative to pick-by-order."""
    baseline = results.get("single_order")
    base_travel = baseline.travel_m if baseline else 0.0
    base_labor = baseline.labor_minutes if baseline else 0.0
    rows = []
    for key, result in results.items():
        rows.append(
            {
                "key": key,
                "scenario": result.name,
                "status": result.status,
                "waves": result.waves,
                "avg_orders": result.avg_orders,
                "avg_lines": result.avg_lines,
                "travel_m": result.travel_m,
                "travel_per_order": result.travel_per_order,
                "travel_saving": 1.0 - result.travel_m / base_travel if base_travel else 0.0,
                "labor_minutes": result.labor_minutes,
                "labor_per_order": result.labor_per_order,
                "labor_saving": 1.0 - result.labor_minutes / base_labor if base_labor else 0.0,
                "orders_per_hour": result.orders_per_hour,
                "labor_cost": result.labor_cost,
                "max_lines": result.max_lines,
                "max_units": result.max_units,
                "solve_seconds": result.solve_seconds,
                "pool_size": result.pool_size,
            }
        )
    return rows


def wave_detail(
    instance: WaveInstance, result: WaveResult, limit: int = 8
) -> List[Dict[str, object]]:
    """Largest waves of one scenario, for report inspection."""
    lookup = instance.by_id()
    rows = []
    ranked = sorted(result.batches, key=lambda batch: (-len(batch), batch))
    for index, batch in enumerate(ranked[:limit], start=1):
        selected = [lookup[invoice] for invoice in batch]
        rows.append(
            {
                "wave": f"W{index}",
                "orders": len(batch),
                "lines": sum(order.lines for order in selected),
                "units": sum(order.units for order in selected),
                "travel_m": _travel(instance, selected),
                "invoices": ", ".join(batch),
            }
        )
    return rows
