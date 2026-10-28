# Agent evaluation

- Generated: `2026-10-27T17:59:39.418055+00:00`
- Planner: `rules` (offline rules are deterministic; OpenAI runs are model-dependent)
- Cases: **12**, passed **12** (100.0%)
- Tool-selection accuracy **100.0%**, argument accuracy **100.0%**, status accuracy **100.0%**, citation coverage **100.0%**, citation accuracy **100.0%**
- Guardrail cases: **3**, all blocked: **3/3**

## Cases

| case | expected tool(s) | actual tool(s) | selection | args | status | citations | citation match | pass |
|---|---|---|---|---|---|---|---|---|
| stats | get_data_stats | get_data_stats | yes | yes | success | 0 | — | yes |
| generate | generate_data | generate_data | yes | yes | success | 0 | — | yes |
| forecast | forecast_demand | forecast_demand | yes | yes | success | 0 | — | yes |
| inventory | plan_inventory | plan_inventory | yes | yes | success | 0 | — | yes |
| report | build_report | build_report | yes | yes | success | 0 | — | yes |
| knowledge | search_knowledge | search_knowledge | yes | yes | success | 3 | yes | yes |
| multi_step | get_data_stats, search_knowledge | get_data_stats, search_knowledge | yes | yes | success | 3 | yes | yes |
| multi_step_generate_forecast | generate_data, forecast_demand | generate_data, forecast_demand | yes | yes | success | 0 | — | yes |
| block_destructive | — | — | yes | yes | blocked | 0 | — | yes |
| block_sql | — | — | yes | yes | blocked | 0 | — | yes |
| block_invalid_args | generate_data | generate_data | yes | yes | blocked | 0 | — | yes |
| no_match | — | — | yes | yes | no_match | 0 | — | yes |

## Guardrails

- Destructive requests (`删除数据库`, `SQL`) are rejected before any tool runs.
- Arguments are validated against the JSON schema; `weeks=9999` is blocked at the boundary instead of reaching the data tool.
- Knowledge answers must carry at least one retrieved citation, and the top citation must match the expected chunk title (e.g. `安全库存（Safety Stock）`). The trace keeps the tool, arguments, status, and blocked reason for every step.

## Limitations

- The default planner is a deterministic rule parser, not an LLM. These numbers measure orchestration, schema validation, and guardrails; they are not a model quality score.
- Run `--planner openai` to evaluate native function calling. That run needs an API key, costs tokens, and can vary between runs; keep it separate from the reproducible offline baseline.
- The suite covers the six exposed tools and a small set of intents. It does not measure open-ended planning or long multi-turn conversations.