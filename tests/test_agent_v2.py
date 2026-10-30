# -*- coding: utf-8 -*-
"""Agent v2 tests: DAG, contracts, real diagnosis, OR MILP, verifier, repair.

Run: PYTHONPATH=src;. python tests/test_agent_v2.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from supply.agent_v2 import (  # noqa: E402
    AgentRuntime,
    ContractError,
    Plan,
    PlanStep,
    ToolResult,
    Verifier,
    build_registry,
)


def test_plan_topo_and_cycle_rejected():
    plan = Plan(
        (
            PlanStep("b", "list_experiments", depends_on=("a",)),
            PlanStep("a", "list_experiments"),
        )
    )
    assert [step.id for step in plan.topo()] == ["a", "b"]
    try:
        Plan(
            (
                PlanStep("a", "list_experiments", depends_on=("b",)),
                PlanStep("b", "list_experiments", depends_on=("a",)),
            )
        )
    except ContractError as exc:
        assert "环" in str(exc)
    else:
        raise AssertionError("环没有被拒绝")
    print("[OK] plan DAG 拓扑排序与环检测")


def test_registry_allowlist_and_schema():
    registry = build_registry()
    blocked = registry.execute(PlanStep("x", "drop_database", {}))
    assert blocked.status == "blocked"
    invalid = registry.execute(
        PlanStep("x", "solve_allocation_milp", {"scenario": "huge"})
    )
    assert invalid.status == "blocked"
    assert "参数校验失败" in invalid.message
    assert registry.execute(PlanStep("x", "solve_allocation_milp", {"scenario": "base"})).ok
    print("[OK] allowlist 与 JSON schema 在 handler 前拦截")


def test_diagnosis_reads_real_benchmark():
    registry = build_registry()
    for constraint, delta in [
        ("stock", 10.0),
        ("dc_capacity", 2.5),
        ("transit", 5.0),
        ("local_stock", 2.5),
        ("placement", 2.5),
    ]:
        result = registry.execute(
            PlanStep("d", "diagnose_service_gap", {"constraint": constraint})
        )
        assert result.ok, result.message
        assert abs(result.facts["target_delta_pp"] - delta) < 0.05, result.facts
        assert result.facts["top_constraint"] == constraint
    print("[OK] 诊断工具读取真实 benchmark JSON")


def test_allocation_milp_beats_greedy():
    registry = build_registry()
    result = registry.execute(
        PlanStep("m", "solve_allocation_milp", {"scenario": "base"})
    )
    assert result.ok, result.message
    assert result.facts["optimal_cost"] == 880.0
    assert result.facts["greedy_cost"] == 930.0
    assert result.facts["optimality_gap_pct"] > 5.0
    print("[OK] SCIP 分配 MILP 优于 greedy 基线")


def test_verifier_rejects_wrong_fact():
    registry = build_registry()
    plan = Plan((PlanStep("d", "diagnose_service_gap", {"constraint": "stock"}),))
    checker = Verifier(
        required_steps=("d",),
        expected_facts={"target_delta_pp": 10.0},
        tolerance=0.05,
    )
    run = AgentRuntime(registry, checker).run(plan)
    assert run.status == "success", run.summary()

    bad = Verifier(
        required_steps=("d",),
        expected_facts={"target_delta_pp": 0.0},
        tolerance=0.05,
    )
    failed = AgentRuntime(registry, bad).run(plan)
    assert failed.status == "failed"
    assert "target_delta_pp" in failed.verification.reason
    print("[OK] verifier 拒绝与事实不符的答案")


def test_adaptive_fallback_repairs_failed_step():
    registry = build_registry()
    plan = Plan((PlanStep("m", "solve_allocation_milp", {"scenario": "tight"}),))
    fallback = Plan((PlanStep("m", "solve_allocation_milp", {"scenario": "base"}),))
    checker = Verifier(
        required_steps=("m",),
        expected_facts={"optimal_cost": 880.0},
        tolerance=0.05,
    )
    run = AgentRuntime(registry, checker).run(plan, fallback_plan=fallback)
    assert run.replanned, run.summary()
    assert run.status == "success", run.summary()
    assert run.facts["optimal_cost"] == 880.0
    assert any(event.status == "error" for event in run.trace)
    print("[OK] 失败步骤触发 fallback 并恢复")


def test_budget_and_dependency_guardrails():
    registry = build_registry()
    checker = Verifier(required_steps=("d0",), min_facts=0)
    plan = Plan(
        tuple(
            PlanStep(f"d{i}", "diagnose_service_gap", {"constraint": "stock"})
            for i in range(10)
        )
    )
    run = AgentRuntime(registry, checker, max_steps=4).run(plan)
    assert run.status == "blocked"
    assert "预算" in run.verification.reason

    broken = Plan(
        (
            PlanStep("a", "drop_database", {}),
            PlanStep("b", "diagnose_service_gap", {"constraint": "stock"}, depends_on=("a",)),
        )
    )
    dep = AgentRuntime(registry, Verifier(required_steps=("b",))).run(broken)
    assert dep.status == "blocked"
    assert any(event.error.startswith("依赖失败") for event in dep.trace)
    print("[OK] 步数预算与坏依赖均在运行时拦截")


if __name__ == "__main__":
    test_plan_topo_and_cycle_rejected()
    test_registry_allowlist_and_schema()
    test_diagnosis_reads_real_benchmark()
    test_allocation_milp_beats_greedy()
    test_verifier_rejects_wrong_fact()
    test_adaptive_fallback_repairs_failed_step()
    test_budget_and_dependency_guardrails()
    print("\nAgent v2 tests passed")
