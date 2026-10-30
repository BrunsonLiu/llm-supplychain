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
    LLMPlanner,
    OpenAIPlannerClient,
    Plan,
    PlannerError,
    PlannerResponse,
    PlanStep,
    ToolCall,
    ToolResult,
    Verifier,
    build_registry,
    plan_tool_schema,
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
    assert run.replanned_by == "fallback", run.summary()
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


class _ScriptedClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages, tools):
        self.calls.append((list(messages), list(tools)))
        return self.responses.pop(0)


def _plan_response(steps, goal="诊断库存约束"):
    return PlannerResponse(
        tool_calls=(
            ToolCall(
                name="submit_plan",
                arguments={"goal": goal, "steps": steps},
            ),
        ),
        content="submit_plan",
    )


def test_llm_planner_emits_runtime_executable_dag():
    registry = build_registry()
    client = _ScriptedClient(
        [
            _plan_response(
                [
                    {"id": "list", "tool": "list_experiments", "args": {}},
                    {
                        "id": "diag",
                        "tool": "diagnose_service_gap",
                        "args": {"constraint": "stock"},
                        "depends_on": ["list"],
                    },
                ]
            )
        ]
    )
    planner = LLMPlanner(registry, client)
    plan = planner.plan("库存是不是瓶颈？")
    assert [step.id for step in plan.topo()] == ["list", "diag"]
    assert plan.goal == "诊断库存约束"
    assert client.calls[0][1][-1]["function"]["name"] == "submit_plan"

    run = AgentRuntime(
        registry,
        Verifier(required_steps=("diag",), expected_facts={"target_delta_pp": 10.0}),
    ).run(plan)
    assert run.status == "success", run.summary()
    assert run.facts["target_delta_pp"] == 10.0
    print("[OK] LLM planner 的 submit_plan 可被 runtime 执行并通过 verifier")


def test_llm_planner_rejects_then_repairs_bad_tool():
    registry = build_registry()
    client = _ScriptedClient(
        [
            _plan_response([{"id": "x", "tool": "drop_database", "args": {}}]),
            _plan_response(
                [
                    {
                        "id": "d",
                        "tool": "diagnose_service_gap",
                        "args": {"constraint": "stock"},
                    }
                ]
            ),
        ]
    )
    plan = LLMPlanner(registry, client, max_attempts=2).plan("诊断")
    assert plan.steps[0].tool == "diagnose_service_gap"
    assert len(client.calls) == 2
    assert "上一次 submit_plan 无效" in client.calls[1][0][-1]["content"]
    print("[OK] 非法工具被拒绝并以结构化错误重试")


def test_llm_planner_retries_malformed_json():
    registry = build_registry()
    client = _ScriptedClient(
        [
            PlannerResponse(tool_calls=(ToolCall("submit_plan", "{not-json"),)),
            _plan_response(
                [
                    {
                        "id": "d",
                        "tool": "diagnose_service_gap",
                        "args": {"constraint": "stock"},
                    }
                ]
            ),
        ]
    )
    plan = LLMPlanner(registry, client, max_attempts=2).plan("诊断")
    assert plan.steps[0].id == "d"
    assert len(client.calls) == 2
    print("[OK] 非法 JSON 被 planner 捕获并重试")


def test_llm_planner_rejects_missing_submit_plan():
    registry = build_registry()
    client = _ScriptedClient(
        [PlannerResponse(tool_calls=(ToolCall("list_experiments", {}),))]
    )
    try:
        LLMPlanner(registry, client, max_attempts=1).plan("诊断")
    except PlannerError as exc:
        assert "没有调用 submit_plan" in str(exc)
    else:
        raise AssertionError("缺少 submit_plan 没有被拒绝")
    assert plan_tool_schema()["function"]["parameters"]["required"] == ["steps"]
    print("[OK] 缺少 submit_plan 与 schema 必填项均被拒绝")


def test_model_replanner_repairs_verifier_failure():
    registry = build_registry()
    initial = Plan((PlanStep("list", "list_experiments", {}),), goal="诊断")
    checker = Verifier(required_steps=("diag",))
    client = _ScriptedClient(
        [
            _plan_response(
                [
                    {
                        "id": "diag",
                        "tool": "diagnose_service_gap",
                        "args": {"constraint": "stock"},
                    }
                ]
            )
        ]
    )
    planner = LLMPlanner(registry, client)
    run = AgentRuntime(registry, checker).run(
        initial,
        replanner=planner.replan,
        question="库存是不是瓶颈？",
    )
    assert run.replanned, run.summary()
    assert run.replanned_by == "model", run.summary()
    assert run.status == "success", run.summary()
    assert [event.step_id for event in run.trace] == ["list", "diag"]
    assert "verifier 失败原因" in client.calls[0][0][-1]["content"]
    print("[OK] verifier 失败后模型重规划并恢复")


def test_model_replanner_error_falls_back_explicitly():
    registry = build_registry()
    initial = Plan((PlanStep("list", "list_experiments", {}),), goal="诊断")
    fallback = Plan(
        (PlanStep("diag", "diagnose_service_gap", {"constraint": "stock"}),),
        goal="诊断",
    )
    checker = Verifier(required_steps=("diag",))

    def broken(_context):
        raise RuntimeError("model endpoint down")

    run = AgentRuntime(registry, checker).run(
        initial,
        fallback_plan=fallback,
        replanner=broken,
        question="库存是不是瓶颈？",
    )
    assert run.replanned
    assert run.replanned_by == "fallback"
    assert "model endpoint down" in run.replan_error
    assert run.status == "success", run.summary()
    print("[OK] 模型重规划抛错时显式回退到脚本 fallback")


def test_openai_adapter_normalizes_tool_call_without_network():
    class _Function:
        name = "submit_plan"
        arguments = '{"steps": [{"id": "l", "tool": "list_experiments", "args": {}}]}'

    class _Call:
        function = _Function()

    class _Message:
        tool_calls = [_Call()]
        content = ""

    class _Choice:
        message = _Message()

    class _Response:
        choices = [_Choice()]

    class _Completions:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return _Response()

    class _Chat:
        def __init__(self):
            self.completions = _Completions()

    class _SDK:
        def __init__(self):
            self.chat = _Chat()

    sdk = _SDK()
    response = OpenAIPlannerClient(model="test-model", client=sdk).complete([], [])
    assert response.tool_calls[0].name == "submit_plan"
    assert response.tool_calls[0].arguments["steps"][0]["id"] == "l"
    assert sdk.chat.completions.kwargs["model"] == "test-model"
    assert sdk.chat.completions.kwargs["tool_choice"]["function"]["name"] == "submit_plan"
    print("[OK] OpenAI 兼容 adapter 只解析 submit_plan，不执行工具")


if __name__ == "__main__":
    test_plan_topo_and_cycle_rejected()
    test_registry_allowlist_and_schema()
    test_diagnosis_reads_real_benchmark()
    test_allocation_milp_beats_greedy()
    test_verifier_rejects_wrong_fact()
    test_adaptive_fallback_repairs_failed_step()
    test_budget_and_dependency_guardrails()
    test_llm_planner_emits_runtime_executable_dag()
    test_llm_planner_rejects_then_repairs_bad_tool()
    test_llm_planner_retries_malformed_json()
    test_llm_planner_rejects_missing_submit_plan()
    test_model_replanner_repairs_verifier_failure()
    test_model_replanner_error_falls_back_explicitly()
    test_openai_adapter_normalizes_tool_call_without_network()
    print("\nAgent v2 tests passed")
