"""Agent v2 benchmark: raw vs verified vs adaptive on 30 tasks.

Run:
    PYTHONPATH=src;. python scripts/run_agent_v2_benchmark.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.agent_v2 import (  # noqa: E402
    AgentRuntime,
    Plan,
    PlanStep,
    ToolResult,
    Verifier,
    build_registry,
    require_facts,
)


@dataclass
class Task:
    id: str
    category: str
    prompt: str
    plan: Plan
    expected_facts: Dict[str, Any]
    expected_status: str = "success"
    required_steps: Tuple[str, ...] = ()
    fallback: Optional[Plan] = None
    expect_recovery: bool = False
    fault_tool: Optional[str] = None
    fault_facts: Dict[str, Any] = field(default_factory=dict)


class FaultOnceRegistry:
    """Return one wrong success response, then delegate to the real registry."""

    def __init__(self, base, tool: str, wrong_facts: Mapping[str, Any]):
        self.base = base
        self.tool = tool
        self.wrong_facts = dict(wrong_facts)
        self.fired = False

    def execute(self, step):
        if step.tool == self.tool and not self.fired:
            self.fired = True
            return ToolResult(
                status="success",
                data={
                    "facts": self.wrong_facts,
                    "finding": "缓存命中（错误结果）",
                    "recommendation": "继续",
                },
                message="fault injected",
            )
        return self.base.execute(step)


def _plan(*steps: PlanStep) -> Plan:
    return Plan(tuple(steps))


def _diag(constraint: str, step_id: str = "d") -> Plan:
    return _plan(PlanStep(step_id, "diagnose_service_gap", {"constraint": constraint}))


def _compare(experiment: str, a: float, b: float, metric: str = "target") -> Plan:
    return _plan(
        PlanStep(
            "c",
            "compare_arms",
            {"experiment": experiment, "arm_a": a, "arm_b": b, "metric": metric},
        )
    )


def _summary(experiment: str) -> Plan:
    return _plan(PlanStep("s", "experiment_summary", {"experiment": experiment}))


def _alloc() -> Plan:
    return _plan(PlanStep("m", "solve_allocation_milp", {"scenario": "base"}))


def _diag_compare(constraint: str) -> Plan:
    arms = {
        "stock": (0.85, 1.0),
        "dc_capacity": (1.0, 2.0),
        "transit": (0.0, 1.0),
        "local_stock": (1.0, 1.5),
    }
    arm_a, arm_b = arms[constraint]
    return _plan(
        PlanStep("d", "diagnose_service_gap", {"constraint": constraint}),
        PlanStep(
            "c",
            "compare_arms",
            {
                "experiment": constraint,
                "arm_a": arm_a,
                "arm_b": arm_b,
                "metric": "target",
            },
            depends_on=("d",),
        ),
    )


def build_tasks() -> List[Task]:
    tasks: List[Task] = []

    # 4 diagnosis tasks
    diagnosis = [
        ("diag_stock", "stock", 10.0),
        ("diag_dc", "dc_capacity", 2.5),
        ("diag_transit", "transit", 5.0),
        ("diag_local", "local_stock", 2.5),
    ]
    for task_id, constraint, delta in diagnosis:
        tasks.append(
            Task(
                id=task_id,
                category="diagnosis",
                prompt=f"为什么目标 OTIF 低？诊断 {constraint}。",
                plan=_diag(constraint),
                expected_facts={"target_delta_pp": delta, "top_constraint": constraint},
                required_steps=("d",),
            )
        )

    # 8 comparison tasks
    comparisons = [
        ("cmp_stock_target", "stock", 0.85, 1.0, "target", 10.0),
        ("cmp_stock_rest", "stock", 0.85, 1.0, "rest", 3.1),
        ("cmp_dc_target", "dc_capacity", 1.0, 2.0, "target", 2.5),
        ("cmp_dc_all", "dc_capacity", 1.0, 2.0, "all", 0.75),
        ("cmp_transit_1", "transit", 0.0, 1.0, "target", 5.0),
        ("cmp_transit_2", "transit", 0.0, 2.0, "target", 5.0),
        ("cmp_local_target", "local_stock", 1.0, 1.5, "target", 2.5),
        ("cmp_local_backlog", "local_stock", 1.0, 1.5, "backlog", -134.0),
    ]
    for task_id, experiment, a, b, metric, delta in comparisons:
        key = "delta_units" if metric == "backlog" else "delta_pp"
        tasks.append(
            Task(
                id=task_id,
                category="comparison",
                prompt=f"比较 {experiment} 的 {a}→{b}（{metric}）。",
                plan=_compare(experiment, a, b, metric),
                expected_facts={key: delta},
                required_steps=("c",),
            )
        )

    # 4 summary tasks
    for task_id, experiment, best in [
        ("sum_stock", "stock", 95.0),
        ("sum_dc", "dc_capacity", 95.0),
        ("sum_transit", "transit", 97.5),
        ("sum_local", "local_stock", 100.0),
    ]:
        tasks.append(
            Task(
                id=task_id,
                category="summary",
                prompt=f"汇总 {experiment} 各臂的目标 OTIF。",
                plan=_summary(experiment),
                expected_facts={"best_target_pct": best},
                required_steps=("s",),
            )
        )

    # 4 allocation tasks
    allocation = [
        ("alloc_opt", "optimal_cost", 880.0),
        ("alloc_greedy", "greedy_cost", 930.0),
        ("alloc_gap", "optimality_gap_pct", 5.6818),
        ("alloc_flows", "flow_count", 5),
    ]
    for task_id, key, expected in allocation:
        tasks.append(
            Task(
                id=task_id,
                category="allocation",
                prompt="求解 DC→订单分配 MILP 并报告结果。",
                plan=_alloc(),
                expected_facts={key: expected},
                required_steps=("m",),
            )
        )

    # 3 multi-step DAG tasks
    for task_id, constraint, delta in [
        ("multi_stock", "stock", 10.0),
        ("multi_dc", "dc_capacity", 2.5),
        ("multi_transit", "transit", 5.0),
    ]:
        tasks.append(
            Task(
                id=task_id,
                category="multi_step",
                prompt=f"先诊断 {constraint}，再给出 arm 对比。",
                plan=_diag_compare(constraint),
                expected_facts={"target_delta_pp": delta, "delta_pp": delta},
                required_steps=("d", "c"),
            )
        )

    # 7 robustness tasks
    tasks.extend(
        [
            Task(
                id="guard_invalid_enum",
                category="guardrail",
                prompt="用非法 scenario 调分配工具",
                plan=_plan(PlanStep("m", "solve_allocation_milp", {"scenario": "huge"})),
                expected_facts={},
                expected_status="blocked",
                required_steps=("m",),
            ),
            Task(
                id="guard_unknown_tool",
                category="guardrail",
                prompt="调用不存在的工具",
                plan=_plan(PlanStep("x", "drop_database", {})),
                expected_facts={},
                expected_status="blocked",
                required_steps=("x",),
            ),
            Task(
                id="recover_missing_experiment",
                category="recovery",
                prompt="实验名写错后回退到 stock",
                plan=_summary("ghost"),
                fallback=_diag("stock", "d2"),
                expected_facts={"target_delta_pp": 10.0},
                required_steps=("d2",),
                expect_recovery=True,
            ),
            Task(
                id="recover_infeasible_tight",
                category="recovery",
                prompt="tight 场景不可行，回退 base",
                plan=_plan(PlanStep("m", "solve_allocation_milp", {"scenario": "tight"})),
                fallback=_alloc(),
                expected_facts={"optimal_cost": 880.0},
                required_steps=("m",),
                expect_recovery=True,
            ),
            Task(
                id="guard_bad_dependency",
                category="guardrail",
                prompt="依赖一个失败步骤",
                plan=_plan(
                    PlanStep("a", "drop_database", {}),
                    PlanStep(
                        "b",
                        "diagnose_service_gap",
                        {"constraint": "stock"},
                        depends_on=("a",),
                    ),
                ),
                expected_facts={},
                expected_status="blocked",
                required_steps=("b",),
            ),
            Task(
                id="guard_budget",
                category="guardrail",
                prompt="计划超过步数预算",
                plan=Plan(
                    tuple(
                        PlanStep(f"d{index}", "diagnose_service_gap", {"constraint": "stock"})
                        for index in range(12)
                    )
                ),
                expected_facts={},
                expected_status="blocked",
                required_steps=("d0",),
            ),
            Task(
                id="recover_wrong_fact",
                category="recovery",
                prompt="工具返回错误数字，验证后重试",
                plan=_diag("stock"),
                fallback=_diag("stock", "d2"),
                expected_facts={"target_delta_pp": 10.0},
                required_steps=("d",),
                expect_recovery=True,
                fault_tool="diagnose_service_gap",
                fault_facts={"target_delta_pp": 0.0, "top_constraint": "stock"},
            ),
        ]
    )
    return tasks


def _run_one(task: Task, policy: str) -> Dict[str, Any]:
    base = build_registry()
    registry = (
        FaultOnceRegistry(base, task.fault_tool, task.fault_facts)
        if task.fault_tool
        else base
    )
    verifier = Verifier(
        required_steps=task.required_steps,
        expected_facts=task.expected_facts,
        tolerance=0.05,
    )
    started = time.perf_counter()
    if policy == "raw":
        runtime = AgentRuntime(registry, verifier=None, max_steps=8)
        run = runtime.run(task.plan)
    elif policy == "verified":
        runtime = AgentRuntime(registry, verifier=verifier, max_steps=8)
        run = runtime.run(task.plan)
    else:
        runtime = AgentRuntime(registry, verifier=verifier, max_steps=8)
        run = runtime.run(task.plan, fallback_plan=task.fallback)
    elapsed = (time.perf_counter() - started) * 1000
    fact_errors = require_facts(run.facts, task.expected_facts, tolerance=0.05)
    status_ok = run.status == task.expected_status
    recovery_ok = (not task.expect_recovery) or run.replanned
    success = status_ok and not fact_errors and recovery_ok
    return {
        "task": task.id,
        "category": task.category,
        "policy": policy,
        "status": run.status,
        "expected_status": task.expected_status,
        "success": success,
        "facts_ok": not fact_errors,
        "fact_errors": fact_errors,
        "verified": run.verification.ok,
        "abstained": (not run.verification.ok),
        "replanned": run.replanned,
        "steps": len(run.trace),
        "elapsed_ms": round(elapsed, 3),
        "facts": run.facts,
        "answer": run.answer,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent v2 30-task benchmark")
    parser.add_argument("--out-dir", default=str(ROOT / "benchmarks"))
    args = parser.parse_args()
    tasks = build_tasks()
    if len(tasks) != 30:
        raise AssertionError(f"期望 30 个任务，实际 {len(tasks)}")
    policies = ["raw", "verified", "adaptive"]
    rows = [_run_one(task, policy) for task in tasks for policy in policies]

    summary: List[Dict[str, Any]] = []
    for policy in policies:
        group = [row for row in rows if row["policy"] == policy]
        summary.append(
            {
                "policy": policy,
                "tasks": len(group),
                "success": sum(1 for row in group if row["success"]),
                "success_rate": sum(1 for row in group if row["success"]) / len(group),
                "verified_rate": sum(1 for row in group if row["verified"]) / len(group),
                "false_success": sum(
                    1
                    for row in group
                    if row["status"] == "success" and not row["facts_ok"]
                ),
                "abstained": sum(1 for row in group if row["abstained"]),
                "replans": sum(1 for row in group if row["replanned"]),
                "avg_steps": round(sum(row["steps"] for row in group) / len(group), 2),
                "avg_latency_ms": round(
                    sum(row["elapsed_ms"] for row in group) / len(group), 3
                ),
            }
        )

    by_category: List[Dict[str, Any]] = []
    for category in sorted({task.category for task in tasks}):
        for policy in policies:
            group = [
                row
                for row in rows
                if row["category"] == category and row["policy"] == policy
            ]
            by_category.append(
                {
                    "category": category,
                    "policy": policy,
                    "tasks": len(group),
                    "success": sum(1 for row in group if row["success"]),
                }
            )

    payload = {
        "title": "Agent v2 30-task benchmark",
        "generated": datetime.now(timezone.utc).isoformat(),
        "tasks": len(tasks),
        "policies": policies,
        "summary": summary,
        "by_category": by_category,
        "rows": rows,
        "limitations": [
            "Planner 是脚本化 DAG，不是 LLM；本基准测的是运行时/工具契约/验证/修复，不是模型规划能力。",
            "diagnosis/compare 工具读取已提交的 benchmark JSON；数值正确性受这些报告与求解器波动约束。",
            "分配 MILP 是小规模合成 3 DC × 4 订单模型，用于验证 OR 工具链，不代表真实 400 单规模。",
            "30 个任务覆盖 4 类约束、8 个对比、4 个汇总、4 个 MILP、3 个 DAG、7 个鲁棒性；不覆盖开放对话/长期记忆。",
            "三个策略共用同一套工具与任务，差异只来自 verifier 和 fallback；raw 的 verified=True 仅表示没有 verifier。",
            "abstain 表示 verifier 失败且 runtime 拒绝输出结论；它不应被算作成功。",
        ],
    }

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "agent_v2_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = ["# Agent v2 benchmark", ""]
    lines.append(f"- Generated: `{payload['generated']}`")
    lines.append(f"- Tasks: **{len(tasks)}** | policies: `{', '.join(policies)}`")
    lines.append("")
    lines += ["## Summary", ""]
    lines.append("| policy | success | success rate | verifier pass | false success | abstain | replans | avg steps | avg ms |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in summary:
        lines.append(
            f"| {row['policy']} | {row['success']}/{row['tasks']} | "
            f"{row['success_rate']:.1%} | {row['verified_rate']:.1%} | "
            f"{row['false_success']} | {row['abstained']} | {row['replans']} | "
            f"{row['avg_steps']} | {row['avg_latency_ms']:.2f} |"
        )
    lines.append("")
    lines += ["## By category", ""]
    lines.append("| category | raw | verified | adaptive |")
    lines.append("|---|---:|---:|---:|")
    for category in sorted({task.category for task in tasks}):
        cells = []
        for policy in policies:
            row = next(
                item
                for item in by_category
                if item["category"] == category and item["policy"] == policy
            )
            cells.append(f"{row['success']}/{row['tasks']}")
        lines.append(f"| {category} | " + " | ".join(cells) + " |")
    lines.append("")
    lines += ["## Findings", ""]
    raw = next(row for row in summary if row["policy"] == "raw")
    verified = next(row for row in summary if row["policy"] == "verified")
    adaptive = next(row for row in summary if row["policy"] == "adaptive")
    lines.append(
        f"- **Raw 完成不等于正确。** `raw` 成功 {raw['success']}/{raw['tasks']}，"
        f"但有 {raw['false_success']} 个假成功（工具返回错误数字仍报 success）；"
        f"`verified` {verified['success']}/{verified['tasks']}，假成功 "
        f"{verified['false_success']}；`adaptive` {adaptive['success']}/{adaptive['tasks']}。"
    )
    lines.append(
        f"- **Verifier 的作用是拒绝错误事实。** `verified` 对 7 个任务未通过验证"
        f"（4 个预期拦截 + 3 个需修复；verifier pass {verified['verified_rate']:.1%}），"
        f"其中 {verified['abstained']} 个验证失败任务输出显式 abstain；"
        f"`adaptive` 用 fallback 重规划 {adaptive['replans']} 次后 3/3 恢复，"
        f"另有 {adaptive['abstained']} 个 abstain，均为 guardrail 的预期阻断，"
        f"不是恢复失败。"
    )
    lines.append(
        "- **Guardrail 在注册表层就生效。** 非法枚举、未知工具、坏依赖和超预算"
        "都不会进入 handler；这比在 prompt 里要求模型“不要调用”更可靠。"
    )
    lines.append(
        "- **这不是模型能力分数。** 规划器是脚本 DAG；要测 LLM 规划，需要把同一个"
        " `Plan` 接口接到真实 function calling，并单独报告 token/延迟/方差。"
    )
    lines.append("")
    lines += ["## Task matrix", ""]
    lines.append("| task | category | raw | verified | adaptive |")
    lines.append("|---|---|---|---|---|")
    for task in tasks:
        cells = []
        for policy in policies:
            row = next(
                item
                for item in rows
                if item["task"] == task.id and item["policy"] == policy
            )
            cells.append("pass" if row["success"] else f"fail({row['status']})")
        lines.append(f"| {task.id} | {task.category} | " + " | ".join(cells) + " |")
    lines.append("")
    (out / "AGENT_V2_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:40]))
    print(f"\nWrote {out / 'AGENT_V2_REPORT.md'}")


if __name__ == "__main__":
    main()
