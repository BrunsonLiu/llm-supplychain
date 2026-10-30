"""Typed contracts for the planner–executor–verifier agent runtime.

The shapes are deliberately small: a tool contract, a validated plan DAG, a
trace event and a verification result. The runtime is deterministic and does
not depend on an LLM; an LLM planner can emit the same ``Plan`` objects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


class ContractError(ValueError):
    """Raised when a tool contract or plan violates the runtime contract."""


@dataclass(frozen=True)
class ToolContract:
    name: str
    description: str
    parameters: Dict[str, Any]
    side_effects: bool = False
    cost: float = 1.0
    tags: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ContractError("tool name 不能为空")
        if self.parameters.get("type") != "object":
            raise ContractError(f"{self.name}: parameters 顶层必须是 object")


@dataclass
class ToolResult:
    status: str
    data: Dict[str, Any] = field(default_factory=dict)
    message: str = ""
    latency_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == "success"

    @property
    def facts(self) -> Dict[str, Any]:
        facts = self.data.get("facts", {})
        return dict(facts) if isinstance(facts, Mapping) else {}


@dataclass(frozen=True)
class PlanStep:
    id: str
    tool: str
    args: Mapping[str, Any] = field(default_factory=dict)
    depends_on: Tuple[str, ...] = ()
    retries: int = 0
    optional: bool = False
    note: str = ""


@dataclass(frozen=True)
class Plan:
    steps: Tuple[PlanStep, ...]
    goal: str = ""

    def __post_init__(self) -> None:
        if not self.steps:
            raise ContractError("plan 至少需要一步")
        self.topo()  # fail fast on duplicate ids/cycles/missing deps

    def by_id(self) -> Dict[str, PlanStep]:
        return {step.id: step for step in self.steps}

    def topo(self) -> List[PlanStep]:
        steps = self.by_id()
        if len(steps) != len(self.steps):
            raise ContractError("plan 中存在重复 step id")
        indegree = {step.id: len(step.depends_on) for step in self.steps}
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in steps:
                    raise ContractError(f"{step.id}: 依赖 {dep} 不存在")
        ready = [step.id for step in self.steps if indegree[step.id] == 0]
        ordered: List[PlanStep] = []
        while ready:
            current = ready.pop(0)
            ordered.append(steps[current])
            for step in self.steps:
                if current in step.depends_on:
                    indegree[step.id] -= 1
                    if indegree[step.id] == 0:
                        ready.append(step.id)
        if len(ordered) != len(self.steps):
            raise ContractError("plan 存在环")
        return ordered

    def describe(self) -> str:
        return " → ".join(f"{step.id}:{step.tool}" for step in self.topo())


@dataclass
class TraceEvent:
    step_id: str
    tool: str
    args: Dict[str, Any]
    status: str
    latency_ms: float
    message: str = ""
    facts: Dict[str, Any] = field(default_factory=dict)
    attempt: int = 1
    error: str = ""

    def compact(self) -> Dict[str, Any]:
        return {
            "step": self.step_id,
            "tool": self.tool,
            "args": self.args,
            "status": self.status,
            "latency_ms": round(self.latency_ms, 3),
            "facts": self.facts,
            "attempt": self.attempt,
            **({"error": self.error} if self.error else {}),
        }


@dataclass(frozen=True)
class Verification:
    ok: bool
    failures: Tuple[str, ...] = ()
    checked_facts: int = 0

    @property
    def reason(self) -> str:
        return "; ".join(self.failures)


@dataclass
class AgentRun:
    status: str
    answer: str
    facts: Dict[str, Any]
    trace: List[TraceEvent]
    verification: Verification
    replanned: bool = False
    plan: Optional[Plan] = None
    elapsed_ms: float = 0.0

    def summary(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "answer": self.answer,
            "facts": self.facts,
            "verified": self.verification.ok,
            "verification_failures": list(self.verification.failures),
            "replanned": self.replanned,
            "steps": len(self.trace),
            "elapsed_ms": round(self.elapsed_ms, 3),
            "plan": self.plan.describe() if self.plan else "",
            "trace": [event.compact() for event in self.trace],
        }


def _validate(value: Any, schema: Dict[str, Any], path: str = "args") -> List[str]:
    """Validate the JSON-schema subset used by tool contracts."""
    errors: List[str] = []
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            return [f"{path} 必须是对象"]
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key} 缺失")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    errors.append(f"{path}.{key} 不是允许的参数")
        for key, item in value.items():
            if key in props:
                errors.extend(_validate(item, props[key], f"{path}.{key}"))
        return errors
    if expected == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return [f"{path} 必须是整数"]
    elif expected == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return [f"{path} 必须是数字"]
    elif expected == "string":
        if not isinstance(value, str):
            return [f"{path} 必须是字符串"]
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path} 长度不足")
    elif expected == "array":
        if not isinstance(value, list):
            return [f"{path} 必须是数组"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path} 不在允许取值内")
    if "minimum" in schema and isinstance(value, (int, float)) and value < schema["minimum"]:
        errors.append(f"{path} 小于最小值 {schema['minimum']}")
    if "maximum" in schema and isinstance(value, (int, float)) and value > schema["maximum"]:
        errors.append(f"{path} 大于最大值 {schema['maximum']}")
    return errors


def validate_args(args: Mapping[str, Any], contract: ToolContract) -> List[str]:
    return _validate(dict(args), contract.parameters)


def require_facts(
    facts: Mapping[str, Any],
    expected: Mapping[str, Any],
    tolerance: float = 1e-6,
) -> List[str]:
    """Compare numeric/string facts with a tolerance; returns human-readable errors."""
    failures: List[str] = []
    for key, wanted in expected.items():
        if key not in facts:
            failures.append(f"缺少事实 {key}")
            continue
        got = facts[key]
        if isinstance(wanted, (int, float)) and not isinstance(wanted, bool):
            if not isinstance(got, (int, float)) or isinstance(got, bool):
                failures.append(f"{key} 不是数值: {got!r}")
            elif abs(float(got) - float(wanted)) > tolerance:
                failures.append(
                    f"{key} 期望 {wanted}，实际 {got}（容差 {tolerance}）"
                )
        elif got != wanted:
            failures.append(f"{key} 期望 {wanted!r}，实际 {got!r}")
    return failures
