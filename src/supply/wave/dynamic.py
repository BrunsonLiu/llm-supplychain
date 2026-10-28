"""Week-8 online wave release: mid-shift order arrivals and re-batching.

Week 6/7 assume every order is known before the shift. This module simulates
orders arriving during the shift and compares four online policies against an
offline oracle that sees all orders at t=0:

* ``single``: release one order per wave as soon as a picker is free.
* ``edf``: dispatch the earliest-deadline available order and fill the wave
  with available orders from the same promise tier.
* ``savings``: re-run the tier-aware Clarke-Wright merge over everything that
  has arrived, then dispatch the wave containing the earliest order.
* ``savings_wait``: same, but idle pickers wait up to a window for enough
  orders to form a fuller wave.

Arrival windows, tier shares, picker count and the wait window are declared
assumptions, not data.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from supply.network.warehouse import route_return

from .instances import WaveInstance, unique_slots
from .scheduling import (
    TIER_ORDER,
    PromisePlan,
    Schedule,
    WaveJob,
    jobs_from_result,
    schedule_edf,
)
from .solvers import savings_batches, wave_load

DEFAULT_TIER_ONSITE = {"express": 0.70, "standard": 0.50, "economy": 0.40}
DEFAULT_TIER_WINDOWS = {"express": 120.0, "standard": 360.0, "economy": 480.0}
DEFAULT_WAIT_MINUTES = 15.0
DEFAULT_MIN_FILL = 4
EPS = 1e-9


@dataclass(frozen=True)
class ArrivalPlan:
    arrival_of: Dict[str, float]
    tier_onsite: Dict[str, float]
    tier_windows: Dict[str, float]
    onsite: Dict[str, int]
    seed: int

    @property
    def orders(self) -> int:
        return len(self.arrival_of)

    @property
    def onsite_orders(self) -> int:
        return sum(1 for value in self.arrival_of.values() if value <= EPS)

    @property
    def mid_shift_orders(self) -> int:
        return self.orders - self.onsite_orders


def assign_arrivals(
    instance: WaveInstance,
    plan: PromisePlan,
    tier_onsite: Optional[Mapping[str, float]] = None,
    tier_windows: Optional[Mapping[str, float]] = None,
    seed: int = 42,
) -> ArrivalPlan:
    """Give each order an arrival minute; earlier tiers arrive earlier."""
    onsite_share = dict(DEFAULT_TIER_ONSITE if tier_onsite is None else tier_onsite)
    windows = dict(DEFAULT_TIER_WINDOWS if tier_windows is None else tier_windows)
    if set(onsite_share) != set(TIER_ORDER) or set(windows) != set(TIER_ORDER):
        raise ValueError("到达参数必须覆盖 express/standard/economy 三层")
    if any(not 0.0 <= share <= 1.0 for share in onsite_share.values()):
        raise ValueError("开班前到达占比必须在 [0, 1]")
    if any(window < 0 for window in windows.values()):
        raise ValueError("到达窗口不能为负")

    rng = np.random.default_rng(seed)
    arrival_of: Dict[str, float] = {}
    onsite: Dict[str, int] = {}
    for tier in TIER_ORDER:
        invoices = sorted(
            order.invoice for order in instance.orders if plan.tier_of[order.invoice] == tier
        )
        if not invoices:
            onsite[tier] = 0
            continue
        shuffled = [invoices[index] for index in rng.permutation(len(invoices))]
        share = float(onsite_share[tier])
        count = int(round(share * len(shuffled)))
        count = max(0, min(len(shuffled), count))
        onsite[tier] = count
        for invoice in shuffled[:count]:
            arrival_of[invoice] = 0.0
        for invoice in shuffled[count:]:
            arrival_of[invoice] = float(rng.uniform(0.0, windows[tier]))
    if set(arrival_of) != set(instance.order_ids):
        raise ValueError("到达时间未覆盖全部订单")
    return ArrivalPlan(
        arrival_of=arrival_of,
        tier_onsite={tier: float(onsite_share[tier]) for tier in TIER_ORDER},
        tier_windows={tier: float(windows[tier]) for tier in TIER_ORDER},
        onsite=onsite,
        seed=int(seed),
    )


def _travel(instance: WaveInstance, invoices: Sequence[str]) -> float:
    lookup = instance.by_id()
    return float(route_return(instance.layout, unique_slots([lookup[invoice] for invoice in invoices])))


def _pair_savings(instance: WaveInstance) -> Dict[Tuple[int, int], float]:
    orders = instance.orders
    singles = [_travel(instance, [order.invoice]) for order in orders]
    savings: Dict[Tuple[int, int], float] = {}
    for first in range(len(orders)):
        for second in range(first + 1, len(orders)):
            combined = _travel(instance, [orders[first].invoice, orders[second].invoice])
            savings[(first, second)] = singles[first] + singles[second] - combined
    return savings


def _available_clusters(
    instance: WaveInstance,
    indices: Sequence[int],
    pair_savings: Mapping[Tuple[int, int], float],
    plan: PromisePlan,
) -> List[List[int]]:
    """Tier-restricted savings merge over the currently available orders."""
    orders = instance.orders
    indices = list(indices)
    parent = {index: index for index in indices}
    members = {index: [index] for index in indices}
    counts = {index: 1 for index in indices}
    lines = {index: orders[index].lines for index in indices}

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    rows = []
    for position, first in enumerate(indices):
        for second in indices[position + 1 :]:
            if plan.tier_of[orders[first].invoice] != plan.tier_of[orders[second].invoice]:
                continue
            key = (first, second) if first < second else (second, first)
            rows.append((pair_savings[key], first, second))
    for score, first, second in sorted(rows, reverse=True):
        if score <= 0:
            break
        root_first, root_second = find(first), find(second)
        if root_first == root_second:
            continue
        if counts[root_first] + counts[root_second] > instance.max_orders:
            continue
        if lines[root_first] + lines[root_second] > instance.max_lines:
            continue
        parent[root_second] = root_first
        members[root_first].extend(members[root_second])
        counts[root_first] += counts[root_second]
        lines[root_first] += lines[root_second]
        members[root_second] = []
    return [cluster for cluster in members.values() if cluster]


def _earliest(
    instance: WaveInstance,
    plan: PromisePlan,
    arrivals: ArrivalPlan,
    available: Sequence[str],
) -> str:
    return min(
        available,
        key=lambda invoice: (
            plan.cutoff_of[invoice],
            arrivals.arrival_of[invoice],
            invoice,
        ),
    )


def _form_wave(
    instance: WaveInstance,
    plan: PromisePlan,
    arrivals: ArrivalPlan,
    available: Sequence[str],
    policy: str,
    pair_savings: Optional[Mapping[Tuple[int, int], float]] = None,
) -> List[str]:
    if not available:
        raise ValueError("没有可派工的订单")
    first = _earliest(instance, plan, arrivals, available)
    tier = plan.tier_of[first]
    if policy == "single":
        return [first]
    if policy == "edf":
        wave = [first]
        candidates = sorted(
            (invoice for invoice in available if invoice != first and plan.tier_of[invoice] == tier),
            key=lambda invoice: (
                plan.cutoff_of[invoice],
                arrivals.arrival_of[invoice],
                invoice,
            ),
        )
        for invoice in candidates:
            if instance.fits(wave + [invoice]):
                wave.append(invoice)
        return sorted(wave)

    if policy not in {"savings", "savings_wait"}:
        raise ValueError(f"未知在线策略: {policy}")
    if pair_savings is None:
        raise ValueError("节省策略需要预计算订单对节省")
    lookup_index = {order.invoice: index for index, order in enumerate(instance.orders)}
    available_indices = [lookup_index[invoice] for invoice in available]
    clusters = _available_clusters(instance, available_indices, pair_savings, plan)
    first_index = lookup_index[first]
    for cluster in clusters:
        if first_index in cluster:
            return sorted(instance.orders[index].invoice for index in cluster)
    raise RuntimeError("最早订单不在任何可合并簇中")


def simulate_online(
    instance: WaveInstance,
    plan: PromisePlan,
    arrivals: ArrivalPlan,
    policy: str = "savings",
    picker_count: int = 2,
    shift_minutes: float = 600.0,
    wait_minutes: float = DEFAULT_WAIT_MINUTES,
    min_fill: int = DEFAULT_MIN_FILL,
    duration_noise: Optional[float] = None,
    noise_seed: int = 0,
    name: Optional[str] = None,
    start_time: float = 0.0,
    picker_free: Optional[Sequence[float]] = None,
) -> Schedule:
    """Event-driven shift simulation; waves dispatch whenever a picker is free.

    ``duration_noise`` multiplies each wave's modeled minutes by a right-skewed
    lognormal factor ``exp(sigma * Z)``. The median stays on plan while the
    expected factor is ``exp(sigma**2 / 2) > 1``, so noise models congestion
    and overruns rather than symmetric jitter. It is a declared proxy, not a
    fitted distribution: zero (or ``None``) reproduces the deterministic
    schedule.

    ``start_time`` and ``picker_free`` resume a shift mid-way: all orders in
    ``instance`` are treated as still to pick, arrivals before ``start_time``
    are available immediately, and each picker becomes free no earlier than
    ``picker_free[picker]``. Defaults reproduce a shift from time zero.
    """
    if picker_count < 1:
        raise ValueError("拣货员数量必须为正")
    if start_time < 0:
        raise ValueError("恢复时点不能为负")
    if picker_free is not None and len(picker_free) != picker_count:
        raise ValueError("picker_free 长度必须等于拣货员数量")
    if policy not in {"single", "edf", "savings", "savings_wait"}:
        raise ValueError(f"未知在线策略: {policy}")
    if policy == "savings_wait" and (wait_minutes < 0 or min_fill < 1):
        raise ValueError("等待窗口与最小成波单数必须为正")
    if policy == "savings_wait" and min_fill > instance.max_orders:
        raise ValueError("最小成波单数不能超过波次容量")
    sigma = 0.0 if duration_noise is None else float(duration_noise)
    if sigma < 0:
        raise ValueError("拣选时长噪声标准差不能为负")
    noise_rng = np.random.default_rng(noise_seed) if sigma > EPS else None

    remaining = set(instance.order_ids)
    pending: List[Tuple[float, str]] = sorted(
        (arrivals.arrival_of[invoice], invoice) for invoice in remaining
    )
    available: List[str] = []
    now = float(start_time)
    pickers_free = (
        [now] * picker_count
        if picker_free is None
        else [max(now, float(value)) for value in picker_free]
    )
    waves: List[Tuple[List[str], float, float, int]] = []
    pair_savings = (
        _pair_savings(instance) if policy in {"savings", "savings_wait"} else None
    )

    while remaining:
        while pending and pending[0][0] <= now + EPS:
            available.append(pending.pop(0)[1])

        idle = [picker for picker in range(picker_count) if pickers_free[picker] <= now + EPS]
        if idle and available:
            invoice_wave = _form_wave(
                instance,
                plan,
                arrivals,
                available,
                policy,
                pair_savings=pair_savings,
            )
            if policy == "savings_wait" and len(invoice_wave) < min_fill and pending:
                next_arrival = pending[0][0]
                waited = now - min(pickers_free[picker] for picker in idle)
                if next_arrival - now <= wait_minutes + EPS and waited < wait_minutes - EPS:
                    now = next_arrival
                    continue
            minutes = wave_load(instance, invoice_wave)[1]
            if noise_rng is not None:
                factor = float(np.exp(sigma * noise_rng.standard_normal()))
                minutes *= min(2.0, max(0.5, factor))
            picker = idle[0]
            end = now + minutes
            waves.append((invoice_wave, now, end, picker))
            chosen = set(invoice_wave)
            available = [invoice for invoice in available if invoice not in chosen]
            remaining -= chosen
            pickers_free[picker] = end
            continue

        if not remaining:
            break
        if available:
            # every picker is busy: wake on the next arrival or the first free picker
            next_time = min(pending[0][0] if pending else math.inf, min(pickers_free))
        elif pending:
            next_time = pending[0][0]
        else:
            raise RuntimeError("仍有订单未排程但没有可用事件")
        if next_time <= now + EPS:
            raise RuntimeError("仿真时间未能推进")
        now = next_time

    waves.sort(key=lambda row: (row[1], row[3], row[0]))
    jobs: List[WaveJob] = []
    starts: List[float] = []
    ends: List[float] = []
    pickers: List[int] = []
    for index, (invoices, start, end, picker) in enumerate(waves):
        tier_counts = {tier: 0 for tier in TIER_ORDER}
        for invoice in invoices:
            tier_counts[plan.tier_of[invoice]] += 1
        jobs.append(
            WaveJob(
                index=index,
                invoices=tuple(sorted(invoices)),
                minutes=float(end - start),
                cutoff_of={invoice: plan.cutoff_of[invoice] for invoice in invoices},
                tier_of={invoice: plan.tier_of[invoice] for invoice in invoices},
                tier_counts=tier_counts,
                tier_cutoffs=dict(plan.cutoffs),
            )
        )
        starts.append(float(start))
        ends.append(float(end))
        pickers.append(int(picker))

    if len(jobs) != len(waves):
        raise RuntimeError("波次任务构造失败")
    covered = {invoice for job in jobs for invoice in job.invoices}
    if covered != set(instance.order_ids):
        raise RuntimeError("在线仿真未覆盖全部订单")

    return Schedule(
        name=name or f"在线 {policy}",
        status="ONLINE",
        jobs=jobs,
        starts=starts,
        ends=ends,
        pickers=pickers,
        picker_count=picker_count,
        shift_minutes=float(shift_minutes),
        labor_cost_per_minute=instance.labor_cost_per_minute,
        meta={
            "policy": policy,
            "wait_minutes": float(wait_minutes),
            "min_fill": int(min_fill),
            "arrivals_seed": arrivals.seed,
            "duration_noise": sigma,
            "noise_seed": int(noise_seed),
            "start_time": float(start_time),
            "picker_free": [float(value) for value in pickers_free],
        },
    )


def oracle_schedule(
    instance: WaveInstance,
    plan: PromisePlan,
    picker_count: int = 2,
    shift_minutes: float = 600.0,
) -> Schedule:
    """Offline upper bound: all orders known at t=0, tier-aware savings + EDF."""
    batches = savings_batches(instance, groups=plan.tier_of, name="离线 Oracle 波次")
    jobs = jobs_from_result(instance, batches, plan)
    return schedule_edf(
        jobs,
        picker_count=picker_count,
        shift_minutes=shift_minutes,
        labor_cost_per_minute=instance.labor_cost_per_minute,
        name="离线参考（全量已知）",
    )


def dynamic_metrics(schedule: Schedule, arrivals: Optional[ArrivalPlan] = None) -> Dict[str, float]:
    """Shift metrics plus order waiting and picker idle time."""
    from .scheduling import schedule_metrics

    metrics = schedule_metrics(schedule)
    makespan = metrics["makespan"]
    metrics["idle_minutes"] = max(0.0, schedule.picker_count * makespan - metrics["labor_minutes"])
    metrics["avg_fill"] = metrics["orders"] / metrics["waves"] if metrics["waves"] else 0.0
    if arrivals is not None:
        waits = []
        for job, start in zip(schedule.jobs, schedule.starts):
            for invoice in job.invoices:
                waits.append(max(0.0, start - arrivals.arrival_of[invoice]))
        metrics["avg_wait"] = float(np.mean(waits)) if waits else 0.0
        metrics["max_wait"] = float(np.max(waits)) if waits else 0.0
        metrics["p90_wait"] = float(np.percentile(waits, 90)) if waits else 0.0
        metrics["onsite_orders"] = arrivals.onsite_orders
        metrics["mid_shift_orders"] = arrivals.mid_shift_orders
    return metrics


def dynamic_summary(
    schedules: Mapping[str, Schedule],
    arrivals: Optional[ArrivalPlan] = None,
    offline_keys: Sequence[str] = ("oracle",),
) -> List[Dict[str, object]]:
    rows = []
    for key, schedule in schedules.items():
        metrics = dynamic_metrics(
            schedule, None if key in offline_keys else arrivals
        )
        rows.append(
            {
                "key": key,
                "scenario": schedule.name,
                "status": schedule.status,
                "policy": schedule.meta.get("policy", "offline"),
                "wait_minutes": schedule.meta.get("wait_minutes"),
                "min_fill": schedule.meta.get("min_fill"),
                **metrics,
                "solve_seconds": schedule.solve_seconds,
            }
        )
    return rows


def dynamic_detail(schedule: Schedule, limit: int = 10) -> List[Dict[str, object]]:
    from .scheduling import _clock

    order = sorted(range(len(schedule.jobs)), key=lambda index: (schedule.starts[index], schedule.pickers[index]))
    rows = []
    for position, index in enumerate(order[:limit], start=1):
        job = schedule.jobs[index]
        late = [
            max(0.0, schedule.ends[index] - job.cutoff_of[invoice])
            for invoice in job.invoices
        ]
        rows.append(
            {
                "wave": f"W{position}",
                "picker": f"P{schedule.pickers[index] + 1}",
                "start": _clock(schedule.starts[index]),
                "end": _clock(schedule.ends[index]),
                "minutes": job.minutes,
                "orders": job.orders,
                "deadline": _clock(job.deadline),
                "late_orders": sum(1 for value in late if value > EPS),
                "max_late": max(late, default=0.0),
            }
        )
    return rows
