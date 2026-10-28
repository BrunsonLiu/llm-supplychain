"""Deadline-aware wave release scheduling on parallel pickers.

Week 6 decides *which* orders share a wave. This module decides *when* each
wave is picked and by whom. Promise tiers, cutoffs, the picker count and the
shift length are declared assumptions, not data: Online Retail II has invoices,
not customer promises or picker rosters.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence

import numpy as np

from .instances import WaveInstance
from .solvers import WaveResult, wave_load

TIER_ORDER = ("express", "standard", "economy")
TIER_LABELS = {"express": "特快", "standard": "标准", "economy": "经济"}
DEFAULT_MIX = {"express": 0.20, "standard": 0.50, "economy": 0.30}
DEFAULT_CUTOFFS = {"express": 240, "standard": 480, "economy": 600}
DEFAULT_PICKERS = 2
DEFAULT_SHIFT_MINUTES = 600.0
SHIFT_START_HOUR = 8
SCHEDULE_SCALE = 1000  # integer thousandths of a minute for CP-SAT
TARDINESS_WEIGHT = 100  # one late order-minute outweighs one minute of makespan
MAKESPAN_WEIGHT = 1


@dataclass(frozen=True)
class PromisePlan:
    """Per-invoice promise tier and cutoff, in minutes after shift start."""

    tier_of: Dict[str, str]
    cutoff_of: Dict[str, int]
    tier_counts: Dict[str, int]
    cutoffs: Dict[str, int]
    mix: Dict[str, float]
    seed: int

    def cutoff(self, invoice: str) -> int:
        return self.cutoff_of[invoice]


@dataclass(frozen=True)
class WaveJob:
    index: int
    invoices: tuple[str, ...]
    minutes: float
    cutoff_of: Mapping[str, int]
    tier_of: Mapping[str, str]
    tier_counts: Mapping[str, int]
    tier_cutoffs: Mapping[str, int]

    @property
    def deadline(self) -> float:
        return float(min(self.cutoff_of.values()))

    @property
    def orders(self) -> int:
        return len(self.invoices)


@dataclass
class Schedule:
    name: str
    status: str
    jobs: List[WaveJob]
    starts: List[float]
    ends: List[float]
    pickers: List[int]
    picker_count: int
    shift_minutes: float
    labor_cost_per_minute: float
    solve_seconds: float = 0.0
    objective: Optional[float] = None
    best_bound: Optional[float] = None
    meta: Dict[str, object] = field(default_factory=dict)

    @property
    def gap(self) -> Optional[float]:
        if self.objective is None or self.best_bound is None:
            return None
        if self.objective <= 0:
            return 0.0
        return max(0.0, (self.objective - self.best_bound) / self.objective)


def assign_promises(
    instance: WaveInstance,
    mix: Optional[Mapping[str, float]] = None,
    cutoffs: Optional[Mapping[str, int]] = None,
    seed: int = 42,
) -> PromisePlan:
    """Assign exact tier counts by seeded shuffle, then apply tier cutoffs."""
    mix_values = dict(DEFAULT_MIX if mix is None else mix)
    cutoff_values = dict(DEFAULT_CUTOFFS if cutoffs is None else cutoffs)
    if set(mix_values) != set(cutoff_values):
        raise ValueError("承诺占比与截单时间必须使用同一组层级")
    if any(value < 0 for value in mix_values.values()):
        raise ValueError("承诺占比不能为负")
    if not math.isclose(sum(mix_values.values()), 1.0, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError("承诺占比之和必须为 1")
    if any(cutoff_values[tier] <= 0 for tier in TIER_ORDER):
        raise ValueError("截单时间必须为正数")
    if not (
        cutoff_values["express"]
        < cutoff_values["standard"]
        < cutoff_values["economy"]
    ):
        raise ValueError("截单时间必须按 特快 < 标准 < 经济 递增")

    total = len(instance.orders)
    rng = np.random.default_rng(seed)
    shuffled = [instance.orders[index].invoice for index in rng.permutation(total)]

    counts: Dict[str, int] = {}
    cumulative = 0.0
    previous = 0
    for tier in TIER_ORDER:
        cumulative += mix_values[tier]
        boundary = int(round(cumulative * total))
        boundary = max(previous, min(total, boundary))
        counts[tier] = boundary - previous
        previous = boundary

    tier_of: Dict[str, str] = {}
    cutoff_of: Dict[str, int] = {}
    cursor = 0
    for tier in TIER_ORDER:
        for invoice in shuffled[cursor : cursor + counts[tier]]:
            tier_of[invoice] = tier
            cutoff_of[invoice] = int(cutoff_values[tier])
        cursor += counts[tier]
    if cursor != total:
        raise ValueError("承诺分层未覆盖全部订单")

    return PromisePlan(
        tier_of=tier_of,
        cutoff_of=cutoff_of,
        tier_counts=counts,
        cutoffs={tier: int(cutoff_values[tier]) for tier in TIER_ORDER},
        mix={tier: float(mix_values[tier]) for tier in TIER_ORDER},
        seed=int(seed),
    )


def jobs_from_result(
    instance: WaveInstance, result: WaveResult, plan: PromisePlan
) -> List[WaveJob]:
    """Turn a Week-6 partition into scheduling jobs with per-invoice cutoffs."""
    lookup = instance.by_id()
    jobs: List[WaveJob] = []
    seen: List[str] = []
    for batch in result.batches:
        invoices = tuple(sorted(batch))
        selected = [lookup[invoice] for invoice in invoices]
        _, minutes = wave_load(instance, invoices)
        tier_counts: Dict[str, int] = {tier: 0 for tier in TIER_ORDER}
        for invoice in invoices:
            tier_counts[plan.tier_of[invoice]] += 1
            seen.append(invoice)
        jobs.append(
            WaveJob(
                index=len(jobs),
                invoices=invoices,
                minutes=float(minutes),
                cutoff_of={invoice: plan.cutoff_of[invoice] for invoice in invoices},
                tier_of={invoice: plan.tier_of[invoice] for invoice in invoices},
                tier_counts=tier_counts,
                tier_cutoffs=dict(plan.cutoffs),
            )
        )
    expected = set(instance.order_ids)
    if set(seen) != expected or len(seen) != len(expected):
        raise ValueError("波次划分未恰好覆盖全部订单")
    jobs.sort(key=lambda job: (job.deadline, job.invoices))
    return [
        WaveJob(
            index=index,
            invoices=job.invoices,
            minutes=job.minutes,
            cutoff_of=job.cutoff_of,
            tier_of=job.tier_of,
            tier_counts=job.tier_counts,
            tier_cutoffs=job.tier_cutoffs,
        )
        for index, job in enumerate(jobs)
    ]


def _validate(schedule: Schedule) -> None:
    count = len(schedule.jobs)
    if count == 0:
        raise ValueError("排程没有波次")
    for name, values in (("start", schedule.starts), ("end", schedule.ends), ("picker", schedule.pickers)):
        if len(values) != count:
            raise ValueError(f"{name} 数量与波次数不一致")
    if schedule.picker_count < 1:
        raise ValueError("拣货员数量必须为正")
    for index in range(count):
        if not 0 <= schedule.pickers[index] < schedule.picker_count:
            raise ValueError(f"波次 {index} 分配了不存在的拣货员")
        if schedule.starts[index] < -1e-9:
            raise ValueError(f"波次 {index} 开始时间为负")
        if schedule.ends[index] < schedule.starts[index] - 1e-9:
            raise ValueError(f"波次 {index} 结束早于开始")
    for picker in range(schedule.picker_count):
        intervals = sorted(
            (
                schedule.starts[index],
                schedule.ends[index],
                index,
            )
            for index in range(count)
            if schedule.pickers[index] == picker
        )
        for previous, current in zip(intervals, intervals[1:]):
            if current[0] < previous[1] - 1e-6:
                raise ValueError(
                    f"拣货员 {picker + 1} 的波次 {previous[2]} 与 {current[2]} 重叠"
                )


def schedule_edf(
    jobs: Sequence[WaveJob],
    picker_count: int = DEFAULT_PICKERS,
    shift_minutes: float = DEFAULT_SHIFT_MINUTES,
    labor_cost_per_minute: float = 0.45,
    name: str = "EDF 排程",
) -> Schedule:
    """Earliest-deadline-first list scheduling on identical pickers."""
    if picker_count < 1:
        raise ValueError("拣货员数量必须为正")
    if not jobs:
        raise ValueError("排程没有波次")
    order = sorted(
        range(len(jobs)),
        key=lambda index: (jobs[index].deadline, -jobs[index].minutes, jobs[index].invoices),
    )
    starts = [0.0] * len(jobs)
    ends = [0.0] * len(jobs)
    pickers = [0] * len(jobs)
    availability = [0.0] * picker_count
    for index in order:
        picker = min(range(picker_count), key=lambda value: (availability[value], value))
        starts[index] = availability[picker]
        ends[index] = starts[index] + jobs[index].minutes
        pickers[index] = picker
        availability[picker] = ends[index]
    schedule = Schedule(
        name=name,
        status="HEURISTIC",
        jobs=list(jobs),
        starts=starts,
        ends=ends,
        pickers=pickers,
        picker_count=int(picker_count),
        shift_minutes=float(shift_minutes),
        labor_cost_per_minute=float(labor_cost_per_minute),
        meta={"rule": "earliest deadline first"},
    )
    _validate(schedule)
    return schedule


def schedule_cpsat(
    jobs: Sequence[WaveJob],
    picker_count: int = DEFAULT_PICKERS,
    shift_minutes: float = DEFAULT_SHIFT_MINUTES,
    labor_cost_per_minute: float = 0.45,
    time_limit_seconds: float = 10.0,
    workers: int = 1,
    seed: int = 42,
    name: str = "CP-SAT 排程",
) -> Schedule:
    """Parallel-machine scheduling minimising weighted tardiness + makespan.

    The model is seeded with the EDF schedule, so the returned plan is never
    worse than EDF on the same objective.
    """
    from ortools.sat.python import cp_model

    if picker_count < 1:
        raise ValueError("拣货员数量必须为正")
    if not jobs:
        raise ValueError("排程没有波次")
    if time_limit_seconds <= 0:
        raise ValueError("求解预算必须为正")

    started = time.perf_counter()
    scale = SCHEDULE_SCALE
    sizes = [max(1, int(round(job.minutes * scale))) for job in jobs]
    horizon = sum(sizes) + 1
    model = cp_model.CpModel()

    starts = [model.NewIntVar(0, horizon, f"start_{index}") for index in range(len(jobs))]
    ends = [model.NewIntVar(0, horizon, f"end_{index}") for index in range(len(jobs))]
    literals: List[List] = [[] for _ in jobs]
    per_picker = [[] for _ in range(picker_count)]

    for index, job in enumerate(jobs):
        for picker in range(picker_count):
            literal = model.NewBoolVar(f"job_{index}_picker_{picker}")
            interval = model.NewOptionalIntervalVar(
                starts[index],
                sizes[index],
                ends[index],
                literal,
                f"interval_{index}_{picker}",
            )
            literals[index].append(literal)
            per_picker[picker].append(interval)
        model.Add(sum(literals[index]) == 1)

    for picker in range(picker_count):
        model.AddNoOverlap(per_picker[picker])

    tardiness_terms = []
    for index, job in enumerate(jobs):
        for tier, count in job.tier_counts.items():
            if count <= 0:
                continue
            cutoff = int(job.tier_cutoffs[tier])
            tardy = model.NewIntVar(0, horizon, f"tardy_{index}_{tier}")
            model.Add(tardy >= ends[index] - cutoff * scale)
            tardiness_terms.append(int(count) * tardy)

    makespan = model.NewIntVar(0, horizon, "makespan")
    for index in range(len(jobs)):
        model.Add(makespan >= ends[index])

    model.Minimize(
        TARDINESS_WEIGHT * sum(tardiness_terms) + MAKESPAN_WEIGHT * makespan
    )

    order = sorted(
        range(len(jobs)),
        key=lambda index: (jobs[index].deadline, -jobs[index].minutes, jobs[index].invoices),
    )
    availability = [0] * picker_count
    for index in order:
        picker = min(range(picker_count), key=lambda value: (availability[value], value))
        start_hint = availability[picker]
        availability[picker] += sizes[index]
        model.AddHint(starts[index], start_hint)
        # Build the hint from rounded sizes so hinted intervals never overlap.
        model.AddHint(ends[index], availability[picker])
        for other in range(picker_count):
            model.AddHint(literals[index][other], 1 if picker == other else 0)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_seconds)
    solver.parameters.num_search_workers = int(workers)
    solver.parameters.random_seed = int(seed)
    status_code = solver.Solve(model)
    elapsed = time.perf_counter() - started
    status = solver.StatusName(status_code)
    if status not in {"OPTIMAL", "FEASIBLE"}:
        raise RuntimeError(f"波次排程未找到可行解: {status}")

    pickers = []
    for index in range(len(jobs)):
        chosen = [picker for picker in range(picker_count) if solver.Value(literals[index][picker]) == 1]
        if len(chosen) != 1:
            raise RuntimeError(f"波次 {index} 的拣货员选择无效")
        pickers.append(chosen[0])

    schedule = Schedule(
        name=name,
        status=status,
        jobs=list(jobs),
        starts=[solver.Value(starts[index]) / scale for index in range(len(jobs))],
        ends=[solver.Value(ends[index]) / scale for index in range(len(jobs))],
        pickers=pickers,
        picker_count=int(picker_count),
        shift_minutes=float(shift_minutes),
        labor_cost_per_minute=float(labor_cost_per_minute),
        solve_seconds=elapsed,
        objective=solver.ObjectiveValue() / scale,
        best_bound=solver.BestObjectiveBound() / scale,
        meta={
            "time_limit_seconds": float(time_limit_seconds),
            "workers": int(workers),
            "seed": int(seed),
            "tardiness_weight": TARDINESS_WEIGHT,
            "makespan_weight": MAKESPAN_WEIGHT,
            "hinted": "EDF",
        },
    )
    _validate(schedule)
    return schedule


def schedule_metrics(schedule: Schedule) -> Dict[str, float]:
    """Order-level on-time metrics; tardiness is counted per order-minute."""
    orders = sum(job.orders for job in schedule.jobs)
    on_time = 0
    tardy = 0
    total_tardiness = 0.0
    max_tardiness = 0.0
    for job, end in zip(schedule.jobs, schedule.ends):
        for invoice in job.invoices:
            late = max(0.0, end - job.cutoff_of[invoice])
            if late <= 1e-9:
                on_time += 1
            else:
                tardy += 1
                total_tardiness += late
                max_tardiness = max(max_tardiness, late)
    labor_minutes = sum(job.minutes for job in schedule.jobs)
    makespan = max(schedule.ends)
    busy_capacity = schedule.picker_count * makespan
    return {
        "waves": len(schedule.jobs),
        "orders": orders,
        "pickers": schedule.picker_count,
        "labor_minutes": labor_minutes,
        "labor_per_order": labor_minutes / orders if orders else 0.0,
        "labor_cost": labor_minutes * schedule.labor_cost_per_minute,
        "on_time_orders": on_time,
        "on_time_rate": on_time / orders if orders else 0.0,
        "tardy_orders": tardy,
        "total_tardiness": total_tardiness,
        "avg_tardiness_late": total_tardiness / tardy if tardy else 0.0,
        "max_tardiness": max_tardiness,
        "makespan": makespan,
        "overtime": max(0.0, makespan - schedule.shift_minutes),
        "picker_utilization": labor_minutes / busy_capacity if busy_capacity else 0.0,
        "orders_per_labor_hour": orders / (labor_minutes / 60.0) if labor_minutes else 0.0,
    }


def promise_summary(schedule: Schedule) -> List[Dict[str, object]]:
    rows = []
    for tier in TIER_ORDER:
        orders = on_time = tardy = 0
        total_tardiness = 0.0
        max_tardiness = 0.0
        for job, end in zip(schedule.jobs, schedule.ends):
            for invoice in job.invoices:
                if job.tier_of[invoice] != tier:
                    continue
                orders += 1
                late = max(0.0, end - job.cutoff_of[invoice])
                if late <= 1e-9:
                    on_time += 1
                else:
                    tardy += 1
                    total_tardiness += late
                    max_tardiness = max(max_tardiness, late)
        rows.append(
            {
                "tier": TIER_LABELS[tier],
                "cutoff": _clock(schedule.jobs[0].tier_cutoffs[tier]) if schedule.jobs else "—",
                "orders": orders,
                "on_time": on_time,
                "on_time_rate": on_time / orders if orders else 0.0,
                "tardy": tardy,
                "total_tardiness": total_tardiness,
                "max_tardiness": max_tardiness,
            }
        )
    return rows


def schedule_summary(schedules: Mapping[str, Schedule]) -> List[Dict[str, object]]:
    rows = []
    for key, schedule in schedules.items():
        metrics = schedule_metrics(schedule)
        rows.append(
            {
                "key": key,
                "scenario": schedule.name,
                "status": schedule.status,
                **metrics,
                "solve_seconds": schedule.solve_seconds,
                "objective": schedule.objective,
                "gap": schedule.gap,
            }
        )
    return rows


def _clock(minutes: float) -> str:
    total = int(round(minutes))
    return f"{SHIFT_START_HOUR + total // 60:02d}:{total % 60:02d}"


def schedule_detail(schedule: Schedule, limit: int = 10) -> List[Dict[str, object]]:
    order = sorted(range(len(schedule.jobs)), key=lambda index: (schedule.starts[index], schedule.pickers[index]))
    rows = []
    for position, index in enumerate(order[:limit], start=1):
        job = schedule.jobs[index]
        late = [
            (invoice, max(0.0, schedule.ends[index] - job.cutoff_of[invoice]))
            for invoice in job.invoices
        ]
        late = [(invoice, value) for invoice, value in late if value > 0]
        rows.append(
            {
                "wave": f"W{position}",
                "picker": f"P{schedule.pickers[index] + 1}",
                "start": _clock(schedule.starts[index]),
                "end": _clock(schedule.ends[index]),
                "minutes": job.minutes,
                "orders": job.orders,
                "deadline": _clock(job.deadline),
                "late_orders": len(late),
                "max_late": max((value for _, value in late), default=0.0),
            }
        )
    return rows
