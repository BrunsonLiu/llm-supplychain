"""Function-calling agent with explicit tool schemas and guardrails.

The numeric tools already exist in :mod:`supply.tools`; this module exposes
them to an LLM as JSON-schema tools and runs the tool-call loop. With an
OpenAI-compatible client the planner is the model's native function calling.
Without an API key a deterministic rule planner is used, so the demo and the
evaluation suite run offline and reproducibly.

Guardrails are explicit: a tool allowlist, schema validation of every
argument, a hard step limit, and a citation requirement for knowledge answers.
Blocked calls are recorded in the trace instead of being executed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from .database import Database
from .rag_tool import RAGTool
from .tools import DataTool, ForecastTool, InventoryTool, ReportTool

MAX_STEPS = 8
_SYSTEM_PROMPT = (
    "你是电商仓配/供应链决策助手。只能调用提供的工具，不得编造数据。"
    "知识类问题必须给出工具返回的引用；工具失败时如实说明。"
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]
    mutates: bool = False

    def as_openai_tool(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class PlannerReply:
    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)


def _object(properties: Dict[str, Any], required: Sequence[str] = ()) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def default_tool_specs() -> List[ToolSpec]:
    return [
        ToolSpec(
            name="get_data_stats",
            description="读取数据库中的产品数、需求记录数、预测数与订单数。只读。",
            parameters=_object({}),
        ),
        ToolSpec(
            name="generate_data",
            description="生成模拟周度需求数据，会覆盖同键记录。仅在用户明确要求生成/加载数据时调用。",
            parameters=_object(
                {
                    "weeks": {
                        "type": "integer",
                        "minimum": 4,
                        "maximum": 520,
                        "description": "历史周数，默认 104",
                    },
                    "products": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 26,
                        "description": "产品数量，默认 5",
                    },
                }
            ),
            mutates=True,
        ),
        ToolSpec(
            name="forecast_demand",
            description="用历史需求预测未来若干周的 SKU/产品需求，并写入预测表。",
            parameters=_object(
                {
                    "horizon": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 52,
                        "description": "预测周数，默认 12",
                    }
                }
            ),
            mutates=True,
        ),
        ToolSpec(
            name="plan_inventory",
            description="根据已有预测生成补货建议（安全库存、目标库存、EOQ），并写入订单表。",
            parameters=_object(
                {
                    "horizon": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 52,
                        "description": "补货周期数，默认 12",
                    }
                }
            ),
            mutates=True,
        ),
        ToolSpec(
            name="build_report",
            description="汇总当前数据库的预测与库存建议，生成 Markdown 决策报告。",
            parameters=_object({}),
        ),
        ToolSpec(
            name="search_knowledge",
            description="检索供应链知识库并返回带来源引用的回答。适合概念、方法、流程类问题。",
            parameters=_object(
                {
                    "question": {"type": "string", "minLength": 1},
                    "top_k": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "description": "检索片段数，默认 3",
                    },
                },
                required=("question",),
            ),
        ),
    ]


_UNSAFE = ("删除", "清空", "drop", "delete", "rm -rf", "shell", "sql", "执行命令")
_KNOWLEDGE = ("什么是", "如何", "为什么", "怎么", "介绍", "解释", "？", "?")


def _validate(value: Any, schema: Dict[str, Any], path: str = "arguments") -> List[str]:
    """Small JSON-schema validator for the subset used by the tool specs."""
    errors: List[str] = []
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            return [f"{path} 必须是对象"]
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key} 缺失")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{path}.{key} 不是允许的参数")
        for key, item in value.items():
            if key in properties:
                errors.extend(_validate(item, properties[key], f"{path}.{key}"))
        return errors
    if expected == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append(f"{path} 必须是整数")
            return errors
    elif expected == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"{path} 必须是数字")
            return errors
    elif expected == "string":
        if not isinstance(value, str):
            errors.append(f"{path} 必须是字符串")
            return errors
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path} 长度不足")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path} 不在允许取值内")
    if "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{path} 小于最小值 {schema['minimum']}")
    if "maximum" in schema and value > schema["maximum"]:
        errors.append(f"{path} 大于最大值 {schema['maximum']}")
    return errors


class RulePlanner:
    """Deterministic offline planner used when no LLM tool client is available.

    It only chooses tools and arguments. The agent still executes the same
    validated tool-call loop, so the guardrail and trace code is shared.
    """

    def __init__(self, prompt: str):
        self._queue = self._parse(prompt)
        self._refused = any(token in prompt.lower() for token in _UNSAFE)
        self._index = 0

    @staticmethod
    def _split(prompt: str) -> List[str]:
        parts = re.split(r"[;；\n]+|，(?=再|然后)|,?\s*然后", prompt)
        return [part.strip() for part in parts if part.strip()]

    @staticmethod
    def _number(segment: str, patterns: Sequence[str], default: int) -> int:
        for pattern in patterns:
            match = re.search(pattern, segment)
            if match:
                return int(match.group(1))
        return default

    def _parse(self, prompt: str) -> List[ToolCall]:
        calls: List[ToolCall] = []
        for segment in self._split(prompt):
            call = self._parse_segment(segment)
            if call:
                calls.append(call)
        return calls

    def _parse_segment(self, segment: str) -> Optional[ToolCall]:
        text = segment.lower()
        if "报告" in segment or "总结" in segment or "report" in text:
            return ToolCall("", "build_report", {})
        if any(word in segment for word in _KNOWLEDGE):
            return ToolCall("", "search_knowledge", {"question": segment, "top_k": 3})
        if "统计" in segment or "概况" in segment or "数据状态" in segment:
            return ToolCall("", "get_data_stats", {})
        if "生成" in segment and "数据" in segment:
            weeks = self._number(
                segment, (r"周期\s*[=为]?\s*(\d+)", r"(\d+)\s*周"), 104
            )
            products = self._number(segment, (r"产品\s*[=为]?\s*(\d+)", r"(\d+)\s*个产品"), 5)
            return ToolCall("", "generate_data", {"weeks": weeks, "products": products})
        if "补货" in segment or "库存" in segment:
            horizon = self._number(
                segment, (r"周期\s*[=为]?\s*(\d+)", r"(\d+)\s*周"), 12
            )
            return ToolCall("", "plan_inventory", {"horizon": horizon})
        if "预测" in segment or "forecast" in text:
            horizon = self._number(
                segment, (r"周期\s*[=为]?\s*(\d+)", r"h(?:orizon)?\s*[=为]?\s*(\d+)", r"(\d+)\s*周"), 12
            )
            return ToolCall("", "forecast_demand", {"horizon": horizon})
        if "数据" in segment:
            return ToolCall("", "get_data_stats", {})
        return None

    def next(self) -> PlannerReply:
        if self._refused:
            return PlannerReply(
                content="该请求涉及删除/清空数据库或执行外部命令，已被护栏拒绝。"
            )
        if self._index < len(self._queue):
            call = self._queue[self._index]
            call.id = f"rule_{self._index + 1}"
            self._index += 1
            return PlannerReply(tool_calls=[call])
        return PlannerReply(content="")

    @property
    def name(self) -> str:
        return "rules"

    @property
    def refused(self) -> bool:
        return self._refused

    def has_plan(self) -> bool:
        return bool(self._queue) and not self._refused


class OpenAIToolPlanner:
    """Thin adapter around an OpenAI-compatible client's native tool calling."""

    def __init__(self, llm: Any, system_prompt: str = _SYSTEM_PROMPT):
        self.llm = llm
        self.messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]

    @property
    def name(self) -> str:
        return "openai"

    def next(self, tools: Sequence[ToolSpec]) -> PlannerReply:
        reply = self.llm.chat_with_tools(
            self.messages, [tool.as_openai_tool() for tool in tools]
        )
        calls = [
            ToolCall(
                id=item.get("id") or f"call_{index + 1}",
                name=item["name"],
                arguments=item.get("arguments") or {},
            )
            for index, item in enumerate(reply.get("tool_calls", []))
        ]
        self.messages.append(
            {
                "role": "assistant",
                "content": reply.get("content") or "",
                **(
                    {
                        "tool_calls": [
                            {
                                "id": call.id,
                                "type": "function",
                                "function": {
                                    "name": call.name,
                                    "arguments": json.dumps(
                                        call.arguments, ensure_ascii=False
                                    ),
                                },
                            }
                            for call in calls
                        ]
                    }
                    if calls
                    else {}
                ),
            }
        )
        return PlannerReply(content=reply.get("content") or "", tool_calls=calls)

    def observe(self, call: ToolCall, result: Dict[str, Any]) -> None:
        self.messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "name": call.name,
                "content": json.dumps(result, ensure_ascii=False, default=str),
            }
        )


class FunctionCallingAgent:
    """Tool-calling loop shared by the real LLM planner and the offline planner."""

    def __init__(
        self,
        db: Optional[Database] = None,
        documents_dir: Optional[str] = None,
        llm: Any = None,
        embeddings: Any = None,
        enable_rag: bool = True,
        specs: Optional[Sequence[ToolSpec]] = None,
        max_steps: int = MAX_STEPS,
        allow_writes: bool = True,
        project_root: Optional[Path] = None,
    ):
        self.db = db or Database()
        self.max_steps = int(max_steps)
        if self.max_steps < 1:
            raise ValueError("max_steps 必须 >= 1")
        self.allow_writes = allow_writes
        self.project_root = Path(project_root or Path(__file__).resolve().parents[2])
        self.data_tool = DataTool(self.db)
        self.forecast_tool = ForecastTool(self.db)
        self.inventory_tool = InventoryTool(self.db)
        self.report_tool = ReportTool(self.db)
        self.rag_tool = (
            RAGTool(documents_dir=documents_dir, embeddings=embeddings, llm=llm)
            if enable_rag
            else None
        )
        self.specs = list(specs or default_tool_specs())
        self.spec_by_name = {spec.name: spec for spec in self.specs}
        self._handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
            "get_data_stats": self._get_data_stats,
            "generate_data": self._generate_data,
            "forecast_demand": self._forecast_demand,
            "plan_inventory": self._plan_inventory,
            "build_report": self._build_report,
            "search_knowledge": self._search_knowledge,
        }
        self.llm = llm

    # ---- tool handlers -------------------------------------------------
    def _get_data_stats(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "success", "stats": self.db.get_data_stats()}

    def _generate_data(self, args: Dict[str, Any]) -> Dict[str, Any]:
        weeks = int(args.get("weeks", 104))
        products = int(args.get("products", 5))
        result = self.data_tool.run(f"生成数据 产品={products} 周期={weeks}")
        return {**result, "weeks": weeks, "products": products}

    def _forecast_demand(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.forecast_tool.run(f"预测周期={int(args.get('horizon', 12))}")

    def _plan_inventory(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.inventory_tool.run(f"库存周期={int(args.get('horizon', 12))}")

    def _build_report(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.report_tool.run("报告")

    def _search_knowledge(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self.rag_tool is None:
            return {"status": "error", "message": "RAG 工具未启用"}
        return self.rag_tool.run(
            str(args["question"]), top_k=int(args.get("top_k", 3))
        )

    # ---- guardrails ----------------------------------------------------
    def _guard(self, call: ToolCall) -> Optional[str]:
        spec = self.spec_by_name.get(call.name)
        if spec is None:
            return f"工具 {call.name} 不在 allowlist 中"
        if spec.mutates and not self.allow_writes:
            return f"工具 {call.name} 会修改数据，当前请求不允许写操作"
        errors = _validate(call.arguments, spec.parameters)
        if errors:
            return "参数校验失败: " + "; ".join(errors)
        return None

    # ---- execution -----------------------------------------------------
    def _final_answer(self, calls: List[Dict[str, Any]]) -> str:
        if not calls:
            return "没有可执行的工具调用。"
        lines = []
        for item in calls:
            result = item["result"]
            if item["status"] != "success":
                lines.append(f"- {item['name']}: {result.get('message', '失败')}")
            elif item["name"] == "search_knowledge":
                lines.append(result.get("answer", ""))
            elif item["name"] == "build_report":
                lines.append(result.get("report", ""))
            elif item["name"] == "forecast_demand":
                forecast = result.get("forecast", {})
                lines.append(
                    f"- 预测完成：{len(forecast)} 个产品 × {result.get('horizon')} 期"
                )
            elif item["name"] == "plan_inventory":
                lines.append(
                    f"- 补货计划完成：{len(result.get('orders', {}))} 个产品 × "
                    f"{result.get('horizon')} 期"
                )
            elif item["name"] == "get_data_stats":
                lines.append(f"- 数据统计：{result.get('stats', {})}")
            else:
                lines.append(f"- {result.get('message', item['name'] + ' 完成')}")
        return "\n".join(line for line in lines if line).strip()

    def run(self, prompt: str) -> Dict[str, Any]:
        if self.llm is not None and hasattr(self.llm, "chat_with_tools"):
            planner = OpenAIToolPlanner(self.llm)
            planner.messages.append({"role": "user", "content": prompt})
            use_openai = True
        else:
            planner = RulePlanner(prompt)
            use_openai = False

        trace: List[Dict[str, Any]] = []
        citations: List[Dict[str, Any]] = []
        blocked: List[str] = []
        final = ""
        steps = 0

        for steps in range(1, self.max_steps + 1):
            reply = planner.next(self.specs) if use_openai else planner.next()
            if not reply.tool_calls:
                final = reply.content
                break
            for call in reply.tool_calls:
                error = self._guard(call)
                if error is not None:
                    blocked.append(error)
                    result = {"status": "error", "message": error}
                    trace.append(
                        {
                            "step": steps,
                            "name": call.name,
                            "arguments": call.arguments,
                            "status": "blocked",
                            "result": result,
                        }
                    )
                else:
                    try:
                        result = self._handlers[call.name](call.arguments)
                    except Exception as exc:  # noqa: BLE001 - report tool failure
                        result = {"status": "error", "message": str(exc)}
                    status = result.get("status", "success")
                    trace.append(
                        {
                            "step": steps,
                            "name": call.name,
                            "arguments": call.arguments,
                            "status": status,
                            "result": result,
                        }
                    )
                    if call.name == "search_knowledge" and result.get("citations"):
                        citations.extend(result["citations"])
                if use_openai:
                    planner.observe(call, result)

        if not final:
            final = self._final_answer(trace)
        if not use_openai and planner.refused and not trace:
            final = ""
        if not use_openai and planner.refused:
            blocked.append("请求涉及删除/清空数据库或执行外部命令")
        if blocked:
            final = (final + "\n\n" if final else "") + "护栏拦截：" + "; ".join(blocked)
        if any(item["name"] == "search_knowledge" for item in trace) and not citations:
            final = (final + "\n\n" if final else "") + "知识库未检索到可引用内容。"
        if citations and "参考来源" not in final:
            final += "\n\n参考来源：\n" + "\n".join(
                f"[{item['id']}] {item['source']} · {item['title']}"
                for item in citations
            )
        success = any(item["status"] == "success" for item in trace)
        failed = any(item["status"] == "error" for item in trace)
        if blocked and not success:
            status = "blocked"
        elif failed and not success:
            status = "error"
        elif not trace and not use_openai and not planner.has_plan():
            status = "no_match"
            final = "没有匹配的工具。可以尝试：数据统计、生成数据、预测、补货、报告或知识问答。"
        else:
            status = "success"
        return {
            "status": status,
            "answer": final.strip(),
            "planner": "openai" if use_openai else "rules",
            "steps": steps,
            "tool_calls": trace,
            "citations": citations,
            "blocked": blocked,
        }
