"""Post-condition verifier: step success, required facts, citations, budget."""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence

from .contracts import TraceEvent, Verification, require_facts


class Verifier:
    def __init__(
        self,
        required_steps: Sequence[str] = (),
        expected_facts: Optional[Mapping[str, Any]] = None,
        tolerance: float = 1e-6,
        citations_required: bool = False,
        min_facts: int = 0,
    ):
        self.required_steps = tuple(required_steps)
        self.expected_facts = dict(expected_facts or {})
        self.tolerance = float(tolerance)
        self.citations_required = bool(citations_required)
        self.min_facts = int(min_facts)

    def verify(self, trace: Sequence[TraceEvent], facts: Mapping[str, Any]) -> Verification:
        failures: list[str] = []
        if any(event.tool == "__budget__" for event in trace):
            failures.append("执行超过步数预算")
        by_step = {event.step_id: event for event in trace}
        for step_id in self.required_steps:
            event = by_step.get(step_id)
            if event is None:
                failures.append(f"必需步骤未执行: {step_id}")
            elif event.status != "success":
                failures.append(f"必需步骤 {step_id} 状态为 {event.status}")
        failures.extend(require_facts(facts, self.expected_facts, self.tolerance))
        if len(facts) < self.min_facts:
            failures.append(f"事实数不足: {len(facts)} < {self.min_facts}")
        if self.citations_required:
            citations = facts.get("citations")
            if not citations:
                failures.append("知识类回答缺少引用")
        return Verification(
            ok=not failures,
            failures=tuple(failures),
            checked_facts=len(self.expected_facts),
        )
