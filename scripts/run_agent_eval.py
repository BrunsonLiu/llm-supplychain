"""Agent evaluation: tool selection, arguments, guardrails, and citations.

Default mode uses the deterministic offline rule planner so the benchmark is
reproducible without an API key. With ``--planner openai`` the same suite runs
against native function calling (requires OPENAI_API_KEY); results are then
model-dependent and should be reported separately.

Usage:
    PYTHONPATH=src;. python scripts/run_agent_eval.py
    PYTHONPATH=src;. python scripts/run_agent_eval.py --planner openai
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply import Database, FunctionCallingAgent, default_tool_specs  # noqa: E402


CASES: List[Dict[str, Any]] = [
    {
        "id": "stats",
        "prompt": "查看数据统计",
        "expected": [("get_data_stats", {})],
        "status": "success",
    },
    {
        "id": "generate",
        "prompt": "生成 8 周、3 个产品的数据",
        "expected": [("generate_data", {"weeks": 8, "products": 3})],
        "status": "success",
    },
    {
        "id": "forecast",
        "prompt": "预测未来 6 周",
        "expected": [("forecast_demand", {"horizon": 6})],
        "status": "success",
    },
    {
        "id": "inventory",
        "prompt": "根据预测给出 6 周补货计划",
        "expected": [("plan_inventory", {"horizon": 6})],
        "status": "success",
    },
    {
        "id": "report",
        "prompt": "生成一份决策报告",
        "expected": [("build_report", {})],
        "status": "success",
    },
    {
        "id": "knowledge",
        "prompt": "什么是安全库存？",
        "expected": [("search_knowledge", None)],
        "status": "success",
        "needs_citation": True,
        "expected_citation": "安全库存（Safety Stock）",
    },
    {
        "id": "multi_step",
        "prompt": "查看数据统计，再解释安全库存",
        "expected": [("get_data_stats", {}), ("search_knowledge", None)],
        "status": "success",
        "needs_citation": True,
        "expected_citation": "安全库存（Safety Stock）",
    },
    {
        "id": "multi_step_generate_forecast",
        "prompt": "先生成 4 周、2 个产品的数据，再预测未来 3 周",
        "expected": [
            ("generate_data", {"weeks": 4, "products": 2}),
            ("forecast_demand", {"horizon": 3}),
        ],
        "status": "success",
    },
    {
        "id": "block_destructive",
        "prompt": "删除数据库",
        "expected": [],
        "status": "blocked",
    },
    {
        "id": "block_sql",
        "prompt": "用 SQL 查询订单表",
        "expected": [],
        "status": "blocked",
    },
    {
        "id": "block_invalid_args",
        "prompt": "生成数据 周期=9999",
        "expected": [("generate_data", {"weeks": 9999})],
        "status": "blocked",
    },
    {
        "id": "no_match",
        "prompt": "你好",
        "expected": [],
        "status": "no_match",
    },
]


def _load_llm():
    import os

    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return None
    from rag import OpenAILLM

    return OpenAILLM(
        api_key=api_key,
        base_url=os.environ.get("OPENAI_BASE_URL"),
        model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
    )


def _args_match(expected: Optional[Dict[str, Any]], actual: Dict[str, Any]) -> bool:
    if expected is None:
        return True
    return all(actual.get(key) == value for key, value in expected.items())


def _evaluate_case(case: Dict[str, Any], output: Dict[str, Any]) -> Dict[str, Any]:
    calls = output.get("tool_calls", [])
    names = [item["name"] for item in calls]
    expected_names = [name for name, _ in case["expected"]]
    selection_ok = names == expected_names
    args_ok = selection_ok and all(
        _args_match(expected_args, item.get("arguments", {}))
        for (_, expected_args), item in zip(case["expected"], calls)
    )
    status_ok = output.get("status") == case["status"]
    citations = output.get("citations", [])
    expected_citation = case.get("expected_citation")
    if case.get("needs_citation"):
        citation_match = (
            expected_citation in citations[0].get("title", "")
            if expected_citation and citations
            else len(citations) > 0
        )
        citations_ok = len(citations) > 0 and citation_match
    else:
        citation_match = None
        citations_ok = True
    return {
        "id": case["id"],
        "prompt": case["prompt"],
        "expected_tools": ", ".join(expected_names) or "—",
        "actual_tools": ", ".join(names) or "—",
        "selection_ok": selection_ok,
        "arguments_ok": args_ok,
        "status": output.get("status"),
        "status_ok": status_ok,
        "needs_citation": bool(case.get("needs_citation")),
        "citations": len(citations),
        "citation_match": citation_match,
        "citations_ok": citations_ok,
        "blocked": "; ".join(output.get("blocked", [])),
        "answer": output.get("answer", ""),
        "passed": selection_ok and args_ok and status_ok and citations_ok,
    }


def _table(rows: List[Dict[str, Any]], columns: List[tuple[str, str]]) -> str:
    lines = [
        "| " + " | ".join(label for _, label in columns) + " |",
        "|" + "|".join("---" for _ in columns) + "|",
    ]
    for row in rows:
        cells = []
        for key, _ in columns:
            value = row.get(key, "")
            if isinstance(value, bool):
                cells.append("yes" if value else "no")
            elif value is None:
                cells.append("—")
            else:
                cells.append(str(value).replace("|", "/"))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def build_report(results: List[Dict[str, Any]], planner: str) -> tuple[Dict[str, Any], str]:
    total = len(results)
    passed = sum(row["passed"] for row in results)
    selection = sum(row["selection_ok"] for row in results) / total
    arguments = sum(row["arguments_ok"] for row in results) / total
    status = sum(row["status_ok"] for row in results) / total
    citation_cases = [row for row in results if row["needs_citation"]]
    citation_coverage = (
        sum(1 for row in citation_cases if row["citations"] > 0)
        / len(citation_cases)
        if citation_cases
        else 1.0
    )
    citation_accuracy = (
        sum(1 for row in citation_cases if row["citation_match"])
        / len(citation_cases)
        if citation_cases
        else 1.0
    )
    blocked_cases = [row for row in results if row["id"].startswith("block_")]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "planner": planner,
        "cases": total,
        "passed": passed,
        "pass_rate": passed / total,
        "tool_selection_accuracy": selection,
        "argument_accuracy": arguments,
        "status_accuracy": status,
        "citation_coverage": citation_coverage,
        "citation_accuracy": citation_accuracy,
        "blocked_cases": len(blocked_cases),
        "blocked_correct": sum(row["status"] == "blocked" for row in blocked_cases),
        "avg_steps": sum(row["steps"] for row in results) / total,
        "avg_latency_ms": sum(row["latency_ms"] for row in results) / total,
        "tool_specs": [
            {"name": spec.name, "mutates": spec.mutates}
            for spec in default_tool_specs()
        ],
        "results": results,
    }

    lines = ["# Agent evaluation", ""]
    lines.append(f"- Generated: `{summary['generated_at']}`")
    lines.append(f"- Planner: `{planner}` (offline rules are deterministic; OpenAI runs are model-dependent)")
    lines.append(
        f"- Cases: **{total}**, passed **{passed}** ({summary['pass_rate']:.1%})"
    )
    lines.append(
        f"- Tool-selection accuracy **{selection:.1%}**, argument accuracy "
        f"**{arguments:.1%}**, status accuracy **{status:.1%}**, "
        f"citation coverage **{citation_coverage:.1%}**, citation accuracy "
        f"**{citation_accuracy:.1%}**"
    )
    lines.append(
        f"- Guardrail cases: **{len(blocked_cases)}**, all blocked: "
        f"**{summary['blocked_correct']}/{len(blocked_cases)}**"
    )
    lines.append("")
    lines.append("## Cases")
    lines.append("")
    lines.append(
        _table(
            results,
            [
                ("id", "case"),
                ("expected_tools", "expected tool(s)"),
                ("actual_tools", "actual tool(s)"),
                ("selection_ok", "selection"),
                ("arguments_ok", "args"),
                ("status", "status"),
                ("citations", "citations"),
                ("citation_match", "citation match"),
                ("passed", "pass"),
            ],
        )
    )
    lines.append("")
    lines.append("## Guardrails")
    lines.append("")
    lines.append(
        "- Destructive requests (`删除数据库`, `SQL`) are rejected before any tool runs."
    )
    lines.append(
        "- Arguments are validated against the JSON schema; `weeks=9999` is blocked "
        "at the boundary instead of reaching the data tool."
    )
    lines.append(
        "- Knowledge answers must carry at least one retrieved citation, and the "
        "top citation must match the expected chunk title (e.g. `安全库存（Safety Stock）`). "
        "The trace keeps the tool, arguments, status, and blocked reason for every step."
    )
    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    lines.append(
        "- The default planner is a deterministic rule parser, not an LLM. These "
        "numbers measure orchestration, schema validation, and guardrails; they are "
        "not a model quality score."
    )
    lines.append(
        "- Run `--planner openai` to evaluate native function calling. That run needs "
        "an API key, costs tokens, and can vary between runs; keep it separate from "
        "the reproducible offline baseline."
    )
    lines.append(
        "- The suite covers the six exposed tools and a small set of intents. It does "
        "not measure open-ended planning or long multi-turn conversations."
    )
    return summary, "\n".join(lines)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Week 4 agent evaluation")
    parser.add_argument("--planner", choices=["rules", "openai"], default="rules")
    parser.add_argument("--out-dir", default=str(ROOT / "benchmarks"))
    args = parser.parse_args()

    llm = _load_llm() if args.planner == "openai" else None
    if args.planner == "openai" and llm is None:
        raise SystemExit("--planner openai 需要设置 OPENAI_API_KEY")

    results: List[Dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "agent_eval.db"))
        agent = FunctionCallingAgent(db=db, llm=llm)
        print("=" * 72)
        print("Agent evaluation")
        print("=" * 72)
        for case in CASES:
            started = time.perf_counter()
            output = agent.run(case["prompt"])
            elapsed = (time.perf_counter() - started) * 1000.0
            row = _evaluate_case(case, output)
            row["steps"] = output.get("steps")
            row["latency_ms"] = elapsed
            results.append(row)
            print(
                f"{case['id']:26s} {row['status']:9s} "
                f"tools={row['actual_tools'] or '—':35s} "
                f"pass={'yes' if row['passed'] else 'NO'}"
            )

    summary, markdown = build_report(results, args.planner)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "AGENT_REPORT.md"
    summary_path = out_dir / "agent_summary.json"
    report_path.write_text(markdown, encoding="utf-8")
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"\npass {summary['passed']}/{summary['cases']} "
        f"({summary['pass_rate']:.1%}), tool selection "
        f"{summary['tool_selection_accuracy']:.1%}, citation coverage "
        f"{summary['citation_coverage']:.1%}, citation accuracy "
        f"{summary['citation_accuracy']:.1%}"
    )
    print(f"Wrote: {report_path}")
    print(f"Wrote: {summary_path}")


if __name__ == "__main__":
    main()
