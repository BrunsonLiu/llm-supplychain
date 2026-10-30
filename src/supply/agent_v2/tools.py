"""Decision tools exposed to the agent: experiment diagnosis, comparison, OR.

The tools read the real benchmark JSON artifacts checked into ``benchmarks/``
and solve a small DC→order MILP with OR-Tools. They do not mutate the database.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .contracts import ToolContract, ToolResult

ROOT = Path(__file__).resolve().parents[3]
BENCHMARKS = ROOT / "benchmarks"

EXPERIMENTS: Dict[str, Dict[str, Any]] = {
    "stock": {
        "file": "stock_summary.json",
        "arm": "stock_factor",
        "baseline": 0.85,
        "label": "库存 85%→100%",
    },
    "dc_capacity": {
        "file": "dc_capacity_summary.json",
        "arm": "dc_capacity_factor",
        "baseline": 1.0,
        "label": "DC 产能 1×→2×/10×",
    },
    "transit": {
        "file": "transit_summary.json",
        "arm": "transit_cut_days",
        "baseline": 0,
        "label": "transit 0→−1/−2 天",
    },
    "local_stock": {
        "file": "local_stock_summary.json",
        "arm": "stock_factor",
        "baseline": 1.0,
        "label": "局部库存 100%→120%/150%",
    },
    "placement": {
        "file": "placement_summary.json",
        "arm": "shares",
        "baseline": None,
        "label": "固定总量 100%：DC 布点重摆",
    },
}

METRICS = {
    "target": "target_accepted_otif_mean",
    "rest": "rest_accepted_otif_mean",
    "all": "all_otif_mean",
    "backlog": "accepted_backlog_units",
}

_CACHE: Dict[str, Dict[str, Any]] = {}


def _load(name: str) -> Dict[str, Any]:
    if name not in _CACHE:
        path = BENCHMARKS / EXPERIMENTS[name]["file"]
        if not path.exists():
            raise FileNotFoundError(f"缺少 benchmark: {path}")
        _CACHE[name] = json.loads(path.read_text(encoding="utf-8"))
    return _CACHE[name]


def _rows(name: str) -> List[Dict[str, Any]]:
    return list(_load(name).get("summary", []))


def _arm(row: Mapping[str, Any], name: str) -> Any:
    return row.get(EXPERIMENTS[name]["arm"])


def _pct(value: Any) -> float:
    return round(float(value) * 100.0, 3)


def _summarize(name: str, metric: str) -> Dict[str, Any]:
    rows = _rows(name)
    spec = EXPERIMENTS[name]
    metric_key = METRICS[metric]
    if name == "placement":
        baseline_row = next(
            (row for row in rows if row.get("placement") == "baseline"), rows[0]
        )
        best_row = max(rows, key=lambda row: float(row["target_accepted_otif_mean"]))
        best_value = float(best_row["target_accepted_otif_mean"])
        close = [
            row
            for row in rows
            if abs(float(row["target_accepted_otif_mean"]) - best_value) < 0.0005
        ]
        baseline_target = _pct(baseline_row["target_accepted_otif_mean"])
        best_target = _pct(best_value)
        return {
            "experiment": name,
            "label": spec["label"],
            "rows": [
                {
                    "arm": row.get("shares", row.get("placement")),
                    "label": row.get("label", ""),
                    "target_pct": _pct(row["target_accepted_otif_mean"]),
                    "rest_pct": _pct(row.get("rest_accepted_otif_mean", 0.0)),
                    "all_pct": _pct(row.get("all_otif_mean", 0.0)),
                    "backlog": float(row.get("accepted_backlog_units", 0.0)),
                    "metric": _pct(row.get(metric_key, 0.0)),
                }
                for row in rows
            ],
            "baseline_arm": baseline_row.get("shares", baseline_row.get("placement")),
            "baseline_target_pct": baseline_target,
            "best_arm": best_row.get("shares", best_row.get("placement")),
            "best_target_pct": best_target,
            "target_delta_pp": round(best_target - baseline_target, 3),
            "saturates": len(close) > 1,
            "facts": {
                "baseline_target_pct": baseline_target,
                "best_target_pct": best_target,
                "target_delta_pp": round(best_target - baseline_target, 3),
                "saturates": len(close) > 1,
            },
        }
    target = [
        {
            "arm": _arm(row, name),
            "target_pct": _pct(row["target_accepted_otif_mean"]),
            "rest_pct": _pct(row.get("rest_accepted_otif_mean", 0.0)),
            "all_pct": _pct(row.get("all_otif_mean", 0.0)),
            "backlog": float(row.get("accepted_backlog_units", 0.0)),
            "metric": _pct(row.get(metric_key, 0.0)),
        }
        for row in rows
    ]
    baseline_row = next(
        (row for row in rows if abs(float(_arm(row, name)) - float(spec["baseline"])) < 1e-9),
        rows[0],
    )
    best_row = max(rows, key=lambda row: float(row["target_accepted_otif_mean"]))
    best_value = float(best_row["target_accepted_otif_mean"])
    close = [
        row
        for row in rows
        if abs(float(row["target_accepted_otif_mean"]) - best_value) < 0.0005
    ]
    baseline_target = _pct(baseline_row["target_accepted_otif_mean"])
    best_target = _pct(best_value)
    return {
        "experiment": name,
        "label": spec["label"],
        "rows": target,
        "baseline_arm": _arm(baseline_row, name),
        "baseline_target_pct": baseline_target,
        "best_arm": _arm(best_row, name),
        "best_target_pct": best_target,
        "target_delta_pp": round(best_target - baseline_target, 3),
        "saturates": len(close) > 1,
        "facts": {
            "baseline_target_pct": baseline_target,
            "best_target_pct": best_target,
            "target_delta_pp": round(best_target - baseline_target, 3),
            "saturates": len(close) > 1,
        },
    }


def _contract(name: str, description: str, properties: Dict[str, Any], required: Sequence[str] = ()) -> ToolContract:
    return ToolContract(
        name=name,
        description=description,
        parameters={
            "type": "object",
            "properties": properties,
            "required": list(required),
            "additionalProperties": False,
        },
        tags=("read",),
    )


def _list_experiments(args: Mapping[str, Any]) -> ToolResult:
    items = [
        {"name": key, "label": value["label"], "arm": value["arm"]}
        for key, value in EXPERIMENTS.items()
    ]
    return ToolResult(
        status="success",
        data={"experiments": items, "facts": {"experiment_count": len(items)}},
        message="可用实验目录",
    )


def _experiment_summary(args: Mapping[str, Any]) -> ToolResult:
    name = str(args["experiment"])
    metric = str(args.get("metric", "target"))
    if name not in EXPERIMENTS:
        return ToolResult(status="error", message=f"未知实验 {name}")
    result = _summarize(name, metric)
    return ToolResult(status="success", data=result, message=result["label"])


def _compare_arms(args: Mapping[str, Any]) -> ToolResult:
    name = str(args["experiment"])
    metric = str(args.get("metric", "target"))
    arm_a = float(args["arm_a"])
    arm_b = float(args["arm_b"])
    if name not in EXPERIMENTS:
        return ToolResult(status="error", message=f"未知实验 {name}")
    rows = _rows(name)
    metric_key = METRICS[metric]
    by_arm = {round(float(_arm(row, name)), 8): row for row in rows}
    key_a, key_b = round(arm_a, 8), round(arm_b, 8)
    if key_a not in by_arm or key_b not in by_arm:
        return ToolResult(status="error", message=f"找不到 arm {arm_a}/{arm_b}")
    a, b = by_arm[key_a], by_arm[key_b]
    raw_delta = float(b.get(metric_key, 0.0)) - float(a.get(metric_key, 0.0))
    if metric == "backlog":
        facts = {
            "delta_units": round(raw_delta, 3),
            "arm_a": arm_a,
            "arm_b": arm_b,
            "metric": metric,
        }
        return ToolResult(
            status="success",
            data={
                "experiment": name,
                "metric": metric,
                "arm_a": arm_a,
                "arm_b": arm_b,
                "value_a": float(a.get(metric_key, 0.0)),
                "value_b": float(b.get(metric_key, 0.0)),
                "delta_units": round(raw_delta, 3),
                "facts": facts,
            },
            message=f"backlog: {arm_a}→{arm_b} {raw_delta:+.3f} units",
        )
    delta = raw_delta * 100.0
    facts = {
        "delta_pp": round(delta, 3),
        "arm_a": arm_a,
        "arm_b": arm_b,
        "metric": metric,
    }
    return ToolResult(
        status="success",
        data={
            "experiment": name,
            "metric": metric,
            "arm_a": arm_a,
            "arm_b": arm_b,
            "value_a": _pct(a.get(metric_key, 0.0)),
            "value_b": _pct(b.get(metric_key, 0.0)),
            "delta_pp": round(delta, 3),
            "facts": facts,
        },
        message=f"{metric}: {arm_a}→{arm_b} {delta:+.3f}pp",
    )


def _diagnose(args: Mapping[str, Any]) -> ToolResult:
    name = str(args["constraint"])
    if name not in EXPERIMENTS:
        return ToolResult(status="error", message=f"未知约束 {name}")
    summary = _summarize(name, "target")
    delta = summary["target_delta_pp"]
    if name == "stock":
        finding = (
            f"库存 85%→100% 让目标 OTIF {summary['baseline_target_pct']}%→"
            f"{summary['best_target_pct']}%（{delta:+.1f}pp），库存是主约束。"
        )
        recommendation = "先补库存，再谈排序/拣选/加人。"
    elif name == "dc_capacity":
        finding = (
            f"DC 产能 1×→2×/10× 让目标 OTIF 最多 {delta:+.1f}pp，"
            f"{'并在 2× 饱和' if summary['saturates'] else '未见饱和'}；"
            "吞吐是次约束。"
        )
        recommendation = "只扩到 2×；继续扩产没有服务收益。"
    elif name == "transit":
        finding = (
            f"transit −1 天让目标 OTIF {delta:+.1f}pp，"
            f"{'−1 天即饱和' if summary['saturates'] else '未饱和'}；"
            "承运商时效是第三约束。"
        )
        recommendation = "先买一天时效，不要再买第二天。"
    elif name == "local_stock":
        finding = (
            f"局部库存 100%→150% 才让目标 OTIF {delta:+.1f}pp；"
            "120% 反而更差，路径不单调，不能证明固定总量重摆位有效。"
        )
        recommendation = "150% 是上量上界；下一步做固定总量重摆位实验。"
    else:
        finding = (
            f"固定 100% 总量、只改 DC 布点：最好 {summary['best_arm']} "
            f"让目标 OTIF {delta:+.1f}pp（{summary['baseline_target_pct']}%→"
            f"{summary['best_target_pct']}%）；"
            + (
                "布点本身能改善服务。"
                if delta >= 5.0
                else "方向性但不稳健：baseline 重复运行跨度 5pp，臂间 2–3pp 差异在噪声内，不能当因果效应。"
            )
        )
        recommendation = (
            "先做布点优化。"
            if delta >= 5.0
            else "不要用固定总量重摆位替代补货；优先保留库存总量。"
        )
    facts = {
        **summary["facts"],
        "top_constraint": name,
        "finding": finding,
        "recommendation": recommendation,
    }
    return ToolResult(
        status="success",
        data={
            "constraint": name,
            "finding": finding,
            "recommendation": recommendation,
            "evidence": summary["rows"],
            "facts": facts,
        },
        message=finding,
    )


def _solve_allocation_milp(args: Mapping[str, Any]) -> ToolResult:
    """Small DC→order MILP with OR-Tools; greedy is the baseline."""
    from ortools.linear_solver import pywraplp

    scenario = str(args.get("scenario", "base"))
    if scenario == "tight":
        supply = [60, 55, 55]
    else:
        supply = [80, 70, 60]
    demand = [50, 45, 55, 60]
    costs = [
        [4.0, 6.0, 9.0, 7.0],
        [8.0, 3.0, 5.0, 6.0],
        [6.0, 7.0, 4.0, 3.0],
    ]
    if sum(supply) < sum(demand):
        return ToolResult(status="error", message="供给不足，模型不可行")

    solver = pywraplp.Solver.CreateSolver("SCIP")
    if solver is None:
        return ToolResult(status="error", message="SCIP 不可用")
    x = {
        (dc, order): solver.IntVar(0, demand[order], f"x_{dc}_{order}")
        for dc in range(3)
        for order in range(4)
    }
    for dc in range(3):
        solver.Add(sum(x[dc, order] for order in range(4)) <= supply[dc])
    for order in range(4):
        solver.Add(sum(x[dc, order] for dc in range(3)) == demand[order])
    solver.Minimize(
        sum(costs[dc][order] * x[dc, order] for dc in range(3) for order in range(4))
    )
    status = solver.Solve()
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        return ToolResult(status="error", message=f"求解失败 status={status}")

    flows = [
        {
            "dc": dc,
            "order": order,
            "units": int(round(x[dc, order].solution_value())),
        }
        for dc in range(3)
        for order in range(4)
        if x[dc, order].solution_value() > 0.5
    ]
    optimal = float(round(solver.Objective().Value(), 4))

    # Greedy baseline: each order takes the cheapest DC with remaining supply.
    remaining = list(supply)
    greedy = 0.0
    for order in range(4):
        left = demand[order]
        for dc in sorted(range(3), key=lambda item: costs[item][order]):
            take = min(left, remaining[dc])
            greedy += take * costs[dc][order]
            remaining[dc] -= take
            left -= take
            if left == 0:
                break
    gap = (greedy - optimal) / optimal * 100.0 if optimal else 0.0
    facts = {
        "optimal_cost": optimal,
        "greedy_cost": float(round(greedy, 4)),
        "optimality_gap_pct": round(gap, 4),
        "flow_count": len(flows),
    }
    return ToolResult(
        status="success",
        data={
            "scenario": scenario,
            "solver": "SCIP",
            "optimal_cost": optimal,
            "greedy_cost": round(greedy, 4),
            "optimality_gap_pct": round(gap, 4),
            "flows": flows,
            "facts": facts,
        },
        message=f"MILP 最优 {optimal}，greedy {greedy:.2f}，gap {gap:.2f}%",
    )


def build_registry():
    from .registry import ToolRegistry

    registry = ToolRegistry()
    registry.register(
        _contract(
            "list_experiments",
            "列出可查询的 benchmark 实验及其 arm 字段。",
            {},
        ),
        _list_experiments,
    )
    registry.register(
        _contract(
            "experiment_summary",
            "汇总一个实验的各 arm 目标/非目标/全量 OTIF 与积压。",
            {
                "experiment": {"type": "string", "enum": sorted(EXPERIMENTS)},
                "metric": {"type": "string", "enum": sorted(METRICS)},
            },
            required=("experiment",),
        ),
        _experiment_summary,
    )
    registry.register(
        _contract(
            "compare_arms",
            "比较同一实验两个 arm 的指标差（百分点）。",
            {
                "experiment": {"type": "string", "enum": sorted(EXPERIMENTS)},
                "arm_a": {"type": "number"},
                "arm_b": {"type": "number"},
                "metric": {"type": "string", "enum": sorted(METRICS)},
            },
            required=("experiment", "arm_a", "arm_b"),
        ),
        _compare_arms,
    )
    registry.register(
        _contract(
            "diagnose_service_gap",
            "从真实 benchmark 诊断目标 OTIF 的 binding constraint。",
            {
                "constraint": {"type": "string", "enum": sorted(EXPERIMENTS)},
            },
            required=("constraint",),
        ),
        _diagnose,
    )
    registry.register(
        _contract(
            "solve_allocation_milp",
            "用 OR-Tools SCIP 求解小规模 DC→订单分配 MILP，并与 greedy 基线比较。",
            {
                "scenario": {"type": "string", "enum": ["base", "tight"]},
            },
        ),
        _solve_allocation_milp,
    )
    return registry
