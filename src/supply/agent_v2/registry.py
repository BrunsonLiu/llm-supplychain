"""Allowlist tool registry with schema validation and timed execution."""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, Iterable, Mapping, Optional

from .contracts import (
    ContractError,
    Plan,
    PlanStep,
    ToolContract,
    ToolResult,
    validate_args,
)

Handler = Callable[[Mapping[str, Any]], ToolResult]


class ToolRegistry:
    def __init__(self) -> None:
        self._contracts: Dict[str, ToolContract] = {}
        self._handlers: Dict[str, Handler] = {}
        self._calls: Dict[str, int] = {}

    def register(self, contract: ToolContract, handler: Handler) -> "ToolRegistry":
        if contract.name in self._contracts:
            raise ContractError(f"工具重复注册: {contract.name}")
        self._contracts[contract.name] = contract
        self._handlers[contract.name] = handler
        return self

    def contract(self, name: str) -> Optional[ToolContract]:
        return self._contracts.get(name)

    def names(self) -> list[str]:
        return sorted(self._contracts)

    def catalog(self) -> list[Dict[str, Any]]:
        return [
            {
                "name": c.name,
                "description": c.description,
                "side_effects": c.side_effects,
                "cost": c.cost,
                "tags": list(c.tags),
                "parameters": c.parameters,
            }
            for c in sorted(self._contracts.values(), key=lambda item: item.name)
        ]

    def calls(self) -> Dict[str, int]:
        return dict(self._calls)

    def execute(self, step: PlanStep) -> ToolResult:
        started = time.perf_counter()
        contract = self._contracts.get(step.tool)
        if contract is None:
            return ToolResult(
                status="blocked",
                message=f"工具 {step.tool} 不在 allowlist 中",
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        errors = validate_args(step.args, contract)
        if errors:
            return ToolResult(
                status="blocked",
                message="参数校验失败: " + "; ".join(errors),
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        self._calls[step.tool] = self._calls.get(step.tool, 0) + 1
        try:
            result = self._handlers[step.tool](step.args)
        except Exception as exc:  # noqa: BLE001 - tool failures are trace data
            return ToolResult(
                status="error",
                message=f"{type(exc).__name__}: {exc}",
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        if not isinstance(result, ToolResult):
            result = ToolResult(status="success", data=dict(result))
        result.latency_ms = (time.perf_counter() - started) * 1000
        return result
