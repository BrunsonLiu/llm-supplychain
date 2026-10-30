"""Function-calling planner for Agent v2.

The planner only emits a typed ``Plan`` DAG; it never executes a tool or does
arithmetic.  A model calls the single ``submit_plan`` function, the planner
validates every step against the registry contracts, and the runtime executes
the plan with the normal trace + verifier.  Invalid plans are sent back once per
attempt as a structured error, so a model can repair a bad tool name or enum.

This module is model-agnostic.  ``OpenAIPlannerClient`` is an optional adapter
for an OpenAI-compatible ``chat.completions`` endpoint; tests use a fake client
and make no network calls.  No real-model numbers are claimed here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

from .contracts import Plan, PlanStep, validate_args
from .registry import ToolRegistry

SUBMIT_PLAN = "submit_plan"

SYSTEM_PROMPT = """你是供应链决策 Agent 的规划器，只负责规划，不负责计算或编造数字。
可用的业务工具见 tools 列表。你必须调用一次 submit_plan，提交一个带依赖的有向无环图：
- 每个 step 有唯一 id、tool、args，可选 depends_on（只能引用前面的 step id）；
- 工具名和参数必须严格来自工具 schema，不要发明工具或字段；
- 先用 list_experiments / diagnose_service_gap 取证，再用 compare_arms 或 OR 工具；
- 不需要的步骤不要加，最多使用 12 步；
- 不要输出自然语言结论，结论由 runtime 的 verifier 和 answer builder 生成。
如果上一次计划被拒绝，请根据错误信息修正后重新调用 submit_plan。"""


class PlannerError(RuntimeError):
    """Raised when the model does not produce a valid plan."""


@dataclass(frozen=True)
class ToolCall:
    name: str
    # A raw JSON string is intentionally allowed: the planner parses it and can
    # retry a malformed call instead of crashing inside the SDK adapter.
    arguments: Any


@dataclass(frozen=True)
class PlannerResponse:
    tool_calls: Tuple[ToolCall, ...] = ()
    content: str = ""


class PlannerClient(Protocol):
    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
    ) -> PlannerResponse:
        """Return one model response; may contain zero or more tool calls."""


def plan_tool_schema() -> Dict[str, Any]:
    """OpenAI-style function schema for the planner's only required call."""
    step_schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "minLength": 1},
            "tool": {"type": "string", "minLength": 1},
            "args": {"type": "object"},
            "depends_on": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["id", "tool"],
        "additionalProperties": False,
    }
    return {
        "type": "function",
        "function": {
            "name": SUBMIT_PLAN,
            "description": "提交一个经过校验的供应链工具调用 DAG。",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "steps": {"type": "array", "items": step_schema},
                },
                "required": ["steps"],
                "additionalProperties": False,
            },
        },
    }


def _tool_schemas(registry: ToolRegistry) -> List[Dict[str, Any]]:
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
    tools.append(plan_tool_schema())
    return tools


def _as_arguments(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value or "{}")
        except json.JSONDecodeError as exc:
            raise PlannerError(f"submit_plan 参数不是合法 JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise PlannerError("submit_plan 参数必须是对象")
        return parsed
    raise PlannerError("submit_plan 参数必须是对象")


class LLMPlanner:
    """Turn a model's ``submit_plan`` call into a validated ``Plan``."""

    def __init__(
        self,
        registry: ToolRegistry,
        client: PlannerClient,
        max_attempts: int = 3,
        max_steps: int = 12,
        system_prompt: str = SYSTEM_PROMPT,
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts 必须 >= 1")
        if max_steps < 1:
            raise ValueError("max_steps 必须 >= 1")
        self.registry = registry
        self.client = client
        self.max_attempts = int(max_attempts)
        self.max_steps = int(max_steps)
        self.system_prompt = system_prompt
        self.tools = _tool_schemas(registry)

    def _parse(self, response: PlannerResponse) -> Plan:
        calls = [call for call in response.tool_calls if call.name == SUBMIT_PLAN]
        if not calls:
            names = [call.name for call in response.tool_calls]
            raise PlannerError(
                "模型没有调用 submit_plan"
                + (f"（实际调用: {names}）" if names else "")
            )
        payload = _as_arguments(calls[0].arguments)
        raw_steps = payload.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise PlannerError("submit_plan.steps 必须是非空数组")
        if len(raw_steps) > self.max_steps:
            raise PlannerError(
                f"submit_plan.steps 超过 {self.max_steps} 步：{len(raw_steps)}"
            )

        steps: List[PlanStep] = []
        seen = set()
        for index, raw in enumerate(raw_steps):
            if not isinstance(raw, Mapping):
                raise PlannerError(f"steps[{index}] 必须是对象")
            step_id = raw.get("id")
            tool = raw.get("tool")
            if not isinstance(step_id, str) or not step_id:
                raise PlannerError(f"steps[{index}].id 必须是非空字符串")
            if step_id in seen:
                raise PlannerError(f"step id 重复: {step_id}")
            seen.add(step_id)
            if not isinstance(tool, str) or not tool:
                raise PlannerError(f"{step_id}.tool 必须是非空字符串")
            contract = self.registry.contract(tool)
            if contract is None:
                raise PlannerError(
                    f"{step_id}: 工具 {tool} 不在 allowlist 中"
                    f"（可用: {', '.join(self.registry.names())}）"
                )
            args = raw.get("args", {})
            if not isinstance(args, Mapping):
                raise PlannerError(f"{step_id}.args 必须是对象")
            errors = validate_args(args, contract)
            if errors:
                raise PlannerError(f"{step_id}: 参数校验失败: {'; '.join(errors)}")
            depends_raw = raw.get("depends_on", [])
            if not isinstance(depends_raw, list) or not all(
                isinstance(item, str) for item in depends_raw
            ):
                raise PlannerError(f"{step_id}.depends_on 必须是字符串数组")
            depends = tuple(depends_raw)
            for dep in depends:
                if dep not in seen:
                    raise PlannerError(
                        f"{step_id}: 依赖 {dep} 不存在或尚未定义"
                    )
            steps.append(
                PlanStep(
                    id=step_id,
                    tool=tool,
                    args=dict(args),
                    depends_on=depends,
                )
            )
        goal = payload.get("goal", "")
        if not isinstance(goal, str):
            raise PlannerError("submit_plan.goal 必须是字符串")
        try:
            return Plan(steps=tuple(steps), goal=goal)
        except Exception as exc:  # ContractError from cycle/duplicate semantics
            raise PlannerError(f"Plan 构建失败: {exc}") from exc

    def plan(self, question: str, context: str = "") -> Plan:
        content = f"业务问题：{question}"
        if context:
            content += f"\n上下文：{context}"
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": content},
        ]
        last_error = ""
        for _ in range(self.max_attempts):
            response = self.client.complete(messages, self.tools)
            try:
                return self._parse(response)
            except PlannerError as exc:
                last_error = str(exc)
                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content or "（未提交有效计划）",
                    }
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"上一次 submit_plan 无效：{last_error}。"
                            "请只调用 submit_plan，修正工具名/参数/依赖后重试。"
                        ),
                    }
                )
        raise PlannerError(
            f"{self.max_attempts} 次尝试后仍无合法计划；最后错误：{last_error}"
        )

    def replan(self, context: Mapping[str, Any]) -> Plan:
        """Repair a failed plan from the runtime's verification context.

        The model sees the original plan, compact trace, facts already obtained
        and the verifier failures.  It re-emits ``submit_plan``; the same
        allowlist/schema checks apply.  A raised ``PlannerError`` is caught by
        the runtime and reported as ``replan_error``.
        """
        plan = context.get("plan")
        trace = context.get("trace", ())
        facts = context.get("facts", {})
        verification = context.get("verification")
        trace_lines = []
        for event in trace:
            compact = event.compact() if hasattr(event, "compact") else event
            trace_lines.append(json.dumps(compact, ensure_ascii=False, default=str))
        reasons = (
            "; ".join(verification.failures)
            if verification is not None and getattr(verification, "failures", None)
            else "验证未通过"
        )
        context_text = "\n".join(
            [
                "原计划（可能已部分执行）："
                + (plan.describe() if hasattr(plan, "describe") else str(plan)),
                f"verifier 失败原因：{reasons}",
                "已执行 trace：",
                *trace_lines,
                "已获得事实："
                + json.dumps(facts, ensure_ascii=False, default=str)[:4000],
                "请只提交修复后的 submit_plan；不要重复已经成功的取数步骤，"
                "不要编造事实，失败步骤要么修正参数，要么用合法 fallback 工具。",
            ]
        )
        return self.plan(str(context.get("question", "")), context=context_text)


class OpenAIPlannerClient:
    """Optional adapter for an OpenAI-compatible chat.completions endpoint.

    The client is injectable so tests and offline examples can use a fake SDK.
    The planner forces ``submit_plan`` as the tool choice and reads only the
    returned function call; it never executes a business tool itself.
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        client: Optional[Any] = None,
        temperature: float = 0.0,
    ):
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - depends on env
                raise RuntimeError(
                    "缺少 openai；请安装 openai 或注入一个兼容 client"
                ) from exc
            client = OpenAI()
        self.client = client
        self.model = model
        self.temperature = temperature

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
    ) -> PlannerResponse:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=list(messages),
            tools=list(tools),
            tool_choice={"type": "function", "function": {"name": SUBMIT_PLAN}},
            temperature=self.temperature,
        )
        message = response.choices[0].message
        calls: List[ToolCall] = []
        for call in getattr(message, "tool_calls", None) or []:
            raw_arguments = call.function.arguments
            try:
                arguments = _as_arguments(raw_arguments)
            except PlannerError:
                # Preserve the raw payload so LLMPlanner can report a
                # structured error and retry instead of crashing here.
                arguments = raw_arguments
            calls.append(ToolCall(name=call.function.name, arguments=arguments))
        return PlannerResponse(
            tool_calls=tuple(calls),
            content=getattr(message, "content", "") or "",
        )
