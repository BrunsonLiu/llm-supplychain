"""Deterministic Plan–Act–Verify–Replan runtime.

The runtime is model-agnostic: a scripted planner or an LLM planner emits the
same ``Plan`` DAG, and every execution produces a trace plus a verification
result. A fallback plan is the explicit repair path when verification fails.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from .contracts import AgentRun, Plan, TraceEvent, Verification
from .registry import ToolRegistry
from .verifier import Verifier

AnswerBuilder = Callable[[Mapping[str, Any], Sequence[TraceEvent]], str]


def default_answer(facts: Mapping[str, Any], trace: Sequence[TraceEvent]) -> str:
    if "finding" in facts:
        lines = [str(facts["finding"])]
        if "evidence" in facts:
            lines.append(f"证据：{facts['evidence']}")
        if "recommendation" in facts:
            lines.append(f"建议：{facts['recommendation']}")
        return "\n".join(lines)
    if "optimal_cost" in facts:
        return (
            f"OR 求解完成：最优成本 {facts['optimal_cost']}，"
            f"基线成本 {facts.get('greedy_cost', 'n/a')}，"
            f"gap {facts.get('optimality_gap_pct', 'n/a')}%。"
        )
    return "；".join(f"{key}={value}" for key, value in facts.items()) or "无可执行结果。"


class AgentRuntime:
    def __init__(
        self,
        registry: ToolRegistry,
        verifier: Optional[Verifier] = None,
        max_steps: int = 12,
        answer_builder: Optional[AnswerBuilder] = None,
    ):
        if max_steps < 1:
            raise ValueError("max_steps 必须 >= 1")
        self.registry = registry
        self.verifier = verifier
        self.max_steps = int(max_steps)
        self.answer_builder = answer_builder or default_answer

    def _execute(
        self,
        plan: Plan,
        trace: list[TraceEvent],
        facts: Dict[str, Any],
    ) -> None:
        status_by_id: Dict[str, str] = {}
        for index, step in enumerate(plan.topo()):
            if len(trace) >= self.max_steps:
                trace.append(
                    TraceEvent(
                        step_id=f"budget_{index}",
                        tool="__budget__",
                        args={},
                        status="blocked",
                        latency_ms=0.0,
                        error="超过 max_steps",
                    )
                )
                break
            failed_dep = [dep for dep in step.depends_on if status_by_id.get(dep) != "success"]
            if failed_dep:
                event = TraceEvent(
                    step_id=step.id,
                    tool=step.tool,
                    args=dict(step.args),
                    status="blocked",
                    latency_ms=0.0,
                    error="依赖失败: " + ", ".join(failed_dep),
                )
                trace.append(event)
                status_by_id[step.id] = event.status
                continue
            last = None
            for attempt in range(1, int(step.retries) + 2):
                result = self.registry.execute(step)
                last = TraceEvent(
                    step_id=step.id,
                    tool=step.tool,
                    args=dict(step.args),
                    status=result.status,
                    latency_ms=result.latency_ms,
                    message=result.message,
                    facts=result.facts,
                    attempt=attempt,
                    error="" if result.ok else result.message,
                )
                if result.ok:
                    break
            assert last is not None
            trace.append(last)
            status_by_id[step.id] = last.status
            if last.status == "success":
                facts.update(last.facts)
            elif step.optional:
                status_by_id[step.id] = "success"  # optional failure is tolerated

    def run(
        self,
        plan: Plan,
        fallback_plan: Optional[Plan] = None,
        verifier: Optional[Verifier] = None,
    ) -> AgentRun:
        started = time.perf_counter()
        trace: list[TraceEvent] = []
        facts: Dict[str, Any] = {}
        self._execute(plan, trace, facts)
        checker = verifier or self.verifier
        verification = (
            checker.verify(trace, facts)
            if checker is not None
            else Verification(ok=True, checked_facts=0)
        )
        replanned = False
        if not verification.ok and fallback_plan is not None:
            replanned = True
            self._execute(fallback_plan, trace, facts)
            verification = (
                checker.verify(trace, facts)
                if checker is not None
                else Verification(ok=True, checked_facts=0)
            )
        answer = self.answer_builder(facts, trace)
        failures = [event for event in trace if event.status in {"blocked", "error"}]
        budget_exceeded = any(event.tool == "__budget__" for event in trace)
        if budget_exceeded:
            status = "blocked"
        elif failures and not (replanned and verification.ok):
            status = "blocked" if all(event.status == "blocked" for event in failures) else "failed"
        elif verification.ok:
            status = "success"
        else:
            status = "failed"
        return AgentRun(
            status=status,
            answer=answer,
            facts=facts,
            trace=trace,
            verification=verification,
            replanned=replanned,
            plan=fallback_plan if replanned else plan,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
