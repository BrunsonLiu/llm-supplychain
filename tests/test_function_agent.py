# -*- coding: utf-8 -*-
"""Week-4 tests: tool schemas, rule planner, guardrails, citations, LLM loop, API.

Run: PYTHONPATH=src;. python tests/test_function_agent.py
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from supply import Database, FunctionCallingAgent, RulePlanner
from supply.function_agent import ToolSpec, _validate, default_tool_specs


def _agent(tmp: str, **kwargs) -> FunctionCallingAgent:
    db = Database(db_path=str(Path(tmp) / "agent.db"))
    kwargs.setdefault("documents_dir", str(ROOT / "data" / "documents"))
    return FunctionCallingAgent(db=db, **kwargs)


def test_tool_specs_are_valid_json_schema():
    specs = default_tool_specs()
    names = {spec.name for spec in specs}
    assert names == {
        "get_data_stats",
        "generate_data",
        "forecast_demand",
        "plan_inventory",
        "build_report",
        "search_knowledge",
    }
    for spec in specs:
        tool = spec.as_openai_tool()
        assert tool["type"] == "function"
        assert tool["function"]["name"] == spec.name
        assert tool["function"]["parameters"]["type"] == "object"
    assert _validate({}, {"type": "object", "properties": {}}) == []
    print("[OK] 工具 schema 结构合法")


def test_rule_planner_selects_tools_and_parses_arguments():
    planner = RulePlanner("生成数据 产品=3 周期=8；预测周期=4；库存周期=6；报告")
    calls = []
    while True:
        reply = planner.next()
        if not reply.tool_calls:
            break
        calls.append(reply.tool_calls[0])
    assert [c.name for c in calls] == [
        "generate_data",
        "forecast_demand",
        "plan_inventory",
        "build_report",
    ], calls
    assert calls[0].arguments == {"weeks": 8, "products": 3}
    assert calls[1].arguments == {"horizon": 4}
    assert calls[2].arguments == {"horizon": 6}
    assert [c.id for c in calls] == ["rule_1", "rule_2", "rule_3", "rule_4"]
    assert planner.has_plan()
    print("[OK] 规则规划器选择工具并解析参数")


def test_multi_step_pipeline_runs_in_order():
    with tempfile.TemporaryDirectory() as tmp:
        agent = _agent(tmp, enable_rag=False)
        result = agent.run("生成数据 产品=2 周期=12；预测周期=3；库存周期=3；报告")
        assert result["status"] == "success", result
        assert result["planner"] == "rules"
        assert [item["name"] for item in result["tool_calls"]] == [
            "generate_data",
            "forecast_demand",
            "plan_inventory",
            "build_report",
        ]
        assert all(item["status"] == "success" for item in result["tool_calls"])
        assert result["steps"] >= 4
        assert "补货计划完成" in result["answer"]
        print("[OK] 多步工具链按顺序执行")


def test_read_only_mode_blocks_mutating_tools():
    with tempfile.TemporaryDirectory() as tmp:
        agent = _agent(tmp, enable_rag=False, allow_writes=False)
        result = agent.run("统计; 生成数据 产品=2 周期=8")
        stats_call, generate_call = result["tool_calls"]
        assert stats_call["name"] == "get_data_stats"
        assert stats_call["status"] == "success"
        assert generate_call["status"] == "blocked"
        assert "不允许写操作" in generate_call["result"]["message"]
        assert result["blocked"], result
        print("[OK] 只读模式拦截写操作")


def test_guardrails_block_unsafe_and_invalid_arguments():
    with tempfile.TemporaryDirectory() as tmp:
        agent = _agent(tmp, enable_rag=False)
        unsafe = agent.run("清空数据库")
        assert unsafe["status"] == "blocked", unsafe
        assert unsafe["tool_calls"] == []
        assert "护栏拦截" in unsafe["answer"]

        invalid = agent.run("生成数据 周期=9999")
        assert invalid["status"] == "blocked", invalid
        assert invalid["tool_calls"][0]["status"] == "blocked"
        assert "参数校验失败" in invalid["blocked"][0]
        assert (
            Database(db_path=str(Path(tmp) / "agent.db"))
            .get_data_stats()["demand_records"]
            == 0
        )
        print("[OK] 护栏拦截危险请求与非法参数")


def test_unknown_tool_spec_rejected():
    spec = ToolSpec(
        name="generate_data",
        description="test",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
    )
    with tempfile.TemporaryDirectory() as tmp:
        agent = _agent(tmp, enable_rag=False, specs=[spec])
        assert agent._guard(
            type("Call", (), {"name": "get_data_stats", "arguments": {}})()
        ) == "工具 get_data_stats 不在 allowlist 中"
    print("[OK] allowlist 拒绝未注册工具")


def test_knowledge_answer_carries_structured_citations():
    with tempfile.TemporaryDirectory() as tmp:
        agent = _agent(tmp)
        result = agent.run("什么是安全库存？")
        assert result["status"] == "success", result
        assert result["citations"], "知识问答缺少引用"
        for item in result["citations"]:
            assert set(item) >= {"id", "source", "title", "score", "snippet"}
            assert item["source"].endswith(".txt")
            assert item["score"] >= 0.0
        assert "安全库存" in result["citations"][0]["title"]
        assert "参考来源" in result["answer"]
        print("[OK] 知识问答返回结构化引用")


def test_openai_tool_loop_plans_executes_and_answers():
    class FakeLLM:
        """Mimics chat_with_tools: one tool call, then a final message."""

        def __init__(self):
            self.messages = []
            self.rounds = 0

        def chat_with_tools(self, messages, tools, **kwargs):
            self.rounds += 1
            assert tools and tools[0]["type"] == "function"
            if self.rounds == 1:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "name": "get_data_stats",
                            "arguments": {},
                        }
                    ],
                }
            assert messages[-1]["role"] == "tool"
            return {"content": "数据库当前为空。", "tool_calls": []}

    with tempfile.TemporaryDirectory() as tmp:
        llm = FakeLLM()
        agent = _agent(tmp, enable_rag=False, llm=llm)
        result = agent.run("现在有多少条数据？")
        assert result["planner"] == "openai"
        assert result["status"] == "success", result
        assert result["answer"] == "数据库当前为空。"
        assert result["tool_calls"][0]["name"] == "get_data_stats"
        assert llm.rounds == 2
        print("[OK] OpenAI 原生 tool loop（规划-执行-回答）")


def test_openai_llm_parses_tool_calls_without_network():
    from types import SimpleNamespace
    from rag import OpenAILLM

    calls = [
        SimpleNamespace(
            id="call_1",
            function=SimpleNamespace(name="get_data_stats", arguments="{}"),
        ),
        SimpleNamespace(
            id="call_2",
            function=SimpleNamespace(name="search_knowledge", arguments="not-json"),
        ),
    ]
    message = SimpleNamespace(content=None, tool_calls=calls)

    class FakeCompletions:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    llm = OpenAILLM(api_key="test-key", model="fake-model")
    fake = FakeCompletions()
    llm.client = SimpleNamespace(chat=SimpleNamespace(completions=fake))

    result = llm.chat_with_tools(
        [{"role": "user", "content": "hi"}],
        [{"type": "function", "function": {"name": "get_data_stats"}}],
        tool_choice="auto",
    )
    assert result["content"] == ""
    assert result["tool_calls"][0] == {
        "id": "call_1",
        "name": "get_data_stats",
        "arguments": {},
    }
    assert result["tool_calls"][1]["arguments"] == {"__parse_error__": "not-json"}
    assert fake.kwargs["tool_choice"] == "auto"
    assert fake.kwargs["model"] == "fake-model"
    print("[OK] OpenAILLM 解析原生 tool_calls（含非法 JSON 兜底）")


def test_api_agent_endpoint_returns_trace():
    from fastapi.testclient import TestClient
    import app.main as api

    with tempfile.TemporaryDirectory() as tmp:
        db = Database(db_path=str(Path(tmp) / "api.db"))
        api._function_agents[("rules", True)] = FunctionCallingAgent(
            db=db, enable_rag=False
        )
        try:
            client = TestClient(api.app)
            response = client.post(
                "/agent",
                json={"prompt": "统计", "use_llm": False},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["status"] == "success"
            assert body["planner"] == "rules"
            assert body["tool_calls"] == [
                {
                    "step": 1,
                    "name": "get_data_stats",
                    "arguments": {},
                    "status": "success",
                }
            ]
            assert set(body) == {
                "status",
                "answer",
                "planner",
                "steps",
                "tool_calls",
                "citations",
                "blocked",
            }
        finally:
            api._function_agents.pop(("rules", True), None)
    print("[OK] POST /agent 返回执行轨迹")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=" * 56)
    print("Week 4 function-calling agent tests")
    print("=" * 56)
    tests = [
        test_tool_specs_are_valid_json_schema,
        test_rule_planner_selects_tools_and_parses_arguments,
        test_multi_step_pipeline_runs_in_order,
        test_read_only_mode_blocks_mutating_tools,
        test_guardrails_block_unsafe_and_invalid_arguments,
        test_unknown_tool_spec_rejected,
        test_knowledge_answer_carries_structured_citations,
        test_openai_tool_loop_plans_executes_and_answers,
        test_openai_llm_parses_tool_calls_without_network,
        test_api_agent_endpoint_returns_trace,
    ]
    for test in tests:
        test()
    print("=" * 56)
    print("All function-agent tests passed")
    print("=" * 56)


if __name__ == "__main__":
    main()
