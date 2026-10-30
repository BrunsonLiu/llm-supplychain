"""Stepwise ReAct-style agent over the same guarded tool registry.

``AgentRuntime`` executes a plan that was produced up front.  This module is the
complementary loop for questions where the next tool depends on what the last
one returned: the model calls one business tool per turn, sees a compact
observation, and decides the next action.  It still has no execution privilege:
every call goes through ``ToolRegistry`` allowlist/schema checks, every result is
recorded as a ``TraceEvent``, and a final ``Verifier`` decides whether the run is
successful.

This is an optional path.  The 30-task benchmark uses the deterministic plan
runtime; tests here use fake clients and make no network calls.

``finish.answer`` is model prose: the verifier checks trace/facts, not semantic
entailment.  A failed ReAct run is therefore not auto-repaired by a fallback.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .contracts import AgentRun, PlanStep, ToolResult, TraceEvent, Verification
from .llm_planner import PlannerClient, PlannerResponse, ToolCall
from .registry import ToolRegistry
from .runtime import AnswerBuilder, abstain_answer, default_answer
from .verifier import Verifier

FINISH = "finish"

REACT_SYSTEM_PROMPT = """你是供应链决策 Agent。每一轮只能调用一个业务工具，或调用 finish 结束。
- 先观察工具返回的事实，再决定下一步；不要预设后面一定有什么结果；
- 工具名和参数必须严格来自 schema，不要发明工具、字段或 benchmark 数字；
- 工具失败时先读错误，再换合法参数/工具，不要重复同一个坏调用；
- finish.answer 只能总结已经通过工具获得的事实，不要编造；
- 不做算术，不绕过 allowlist，不调用写操作。"""


def _finish_schema() -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": FINISH,
            "description": "结束调查并给出基于已观察事实的回答。",
            "parameters": {
                "type": "object",
                "properties": {"answer": {"type": "string", "minLength": 1}},
                "required": ["answer"],
                "additionalProperties": False,
            },
        },
    }


def react_tools(registry: ToolRegistry) -> List[Dict[str, Any]]:
    tools = []
    for contract in registry.catalog():
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": contract["name"],
                    "description": contract["description"],
                    "parameters": contract["parameters"],
                },
            }
        )
    tools.append(_finish_schema())
    return tools


def _arguments(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"工具参数不是合法 JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("工具参数必须是对象")
        return parsed
    raise ValueError("工具参数必须是对象")


def _observation(result: ToolResult) -> str:
    payload = {
        "status": result.status,
        "message": result.message,
        "facts": result.facts,
        "data": result.data,
    }
    return json.dumps(payload, ensure_ascii=False, default=str)[:6000]


class ReActAgent:
    """One-tool-per-turn agent loop with guarded execution and verification."""

    def __init__(
        self,
        registry: ToolRegistry,
        client: PlannerClient,
        verifier: Optional[Verifier] = None,
        max_steps: int = 8,
        answer_builder: Optional[AnswerBuilder] = None,
        system_prompt: str = REACT_SYSTEM_PROMPT,
    ):
        if max_steps < 1:
            raise ValueError("max_steps 必须 >= 1")
        self.registry = registry
        self.client = client
        self.verifier = verifier
        self.max_steps = int(max_steps)
        self.answer_builder = answer_builder or default_answer
        self.system_prompt = system_prompt
        self.tools = react_tools(registry)

    def _finish_answer(self, response: PlannerResponse) -> Optional[str]:
        for call in response.tool_calls:
            if call.name != FINISH:
                continue
            args = _arguments(call.arguments)
            answer = args.get("answer")
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("finish.answer 必须是非空字符串")
            return answer
        return None

    def run(self, question: str) -> AgentRun:
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"业务问题：{question}"},
        ]
        trace: List[TraceEvent] = []
        facts: Dict[str, Any] = {}
        answer = ""
        finished = False

        for index in range(self.max_steps):
            response = self.client.complete(messages, self.tools)
            if not response.tool_calls:
                messages.append({"role": "assistant", "content": response.content or ""})
                messages.append(
                    {
                        "role": "user",
                        "content": "没有收到工具调用。请调用一个业务工具或 finish。",
                    }
                )
                continue

            call = response.tool_calls[0]
            try:
                args = _arguments(call.arguments)
            except ValueError as exc:
                trace.append(
                    TraceEvent(
                        step_id=f"s{index}",
                        tool=call.name,
                        args={},
                        status="blocked",
                        latency_ms=0.0,
                        error=str(exc),
                    )
                )
                messages.append(
                    {
                        "role": "user",
                        "content": f"参数无效：{exc}。请修正后调用一个工具。",
                    }
                )
                continue

            if call.name == FINISH:
                try:
                    answer = self._finish_answer(response) or ""
                except ValueError as exc:
                    messages.append(
                        {"role": "user", "content": f"finish 无效：{exc}。请重试。"}
                    )
                    continue
                trace.append(
                    TraceEvent(
                        step_id="finish",
                        tool=FINISH,
                        args=dict(args),
                        status="success",
                        latency_ms=0.0,
                    )
                )
                finished = True
                break

            result = self.registry.execute(
                PlanStep(id=f"s{index}", tool=call.name, args=args)
            )
            event = TraceEvent(
                step_id=f"s{index}",
                tool=call.name,
                args=dict(args),
                status=result.status,
                latency_ms=result.latency_ms,
                message=result.message,
                facts=result.facts,
                error="" if result.ok else result.message,
            )
            trace.append(event)
            if result.ok:
                facts.update(result.facts)
            messages.append(
                {
                    "role": "assistant",
                    "content": f"调用 {call.name}({json.dumps(args, ensure_ascii=False)})",
                }
            )
            messages.append(
                {"role": "user", "content": "观察结果：" + _observation(result)}
            )

        if not finished:
            trace.append(
                TraceEvent(
                    step_id=f"budget_{self.max_steps}",
                    tool="__budget__",
                    args={},
                    status="blocked",
                    latency_ms=0.0,
                    error="超过 max_steps 仍未 finish",
                )
            )

        checker = self.verifier
        verification = (
            checker.verify(trace, facts)
            if checker is not None
            else Verification(ok=True, checked_facts=0)
        )
        if not finished:
            status = "blocked"
            if not answer:
                answer = self.answer_builder(facts, trace)
        elif verification.ok:
            status = "success"
        else:
            status = "failed"
            answer = abstain_answer(verification)
        return AgentRun(
            status=status,
            answer=answer or self.answer_builder(facts, trace),
            facts=facts,
            trace=trace,
            verification=verification,
            plan=None,
        )
