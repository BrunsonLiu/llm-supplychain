# Agent v2 benchmark

- Generated: `2026-10-30T14:42:09.380338+00:00`
- Tasks: **30** | policies: `raw, verified, adaptive`

## Summary

| policy | success | success rate | verifier pass | false success | abstain | replans | avg steps | avg ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| raw | 27/30 | 90.0% | 100.0% | 1 | 0 | 0 | 1.4 | 7.11 |
| verified | 27/30 | 90.0% | 76.7% | 0 | 7 | 0 | 1.4 | 0.89 |
| adaptive | 30/30 | 100.0% | 86.7% | 0 | 4 | 3 | 1.5 | 1.11 |

## By category

| category | raw | verified | adaptive |
|---|---:|---:|---:|
| allocation | 4/4 | 4/4 | 4/4 |
| comparison | 8/8 | 8/8 | 8/8 |
| diagnosis | 4/4 | 4/4 | 4/4 |
| guardrail | 4/4 | 4/4 | 4/4 |
| multi_step | 3/3 | 3/3 | 3/3 |
| recovery | 0/3 | 0/3 | 3/3 |
| summary | 4/4 | 4/4 | 4/4 |

## Findings

- **Raw 完成不等于正确。** `raw` 成功 27/30，但有 1 个假成功（工具返回错误数字仍报 success）；`verified` 27/30，假成功 0；`adaptive` 30/30。
- **Verifier 的作用是拒绝错误事实。** `verified` 对 7 个任务未通过验证（4 个预期拦截 + 3 个需修复；verifier pass 76.7%），其中 7 个验证失败任务输出显式 abstain；`adaptive` 用 fallback 重规划 3 次后 3/3 恢复，另有 4 个 abstain，均为 guardrail 的预期阻断，不是恢复失败。
- **Guardrail 在注册表层就生效。** 非法枚举、未知工具、坏依赖和超预算都不会进入 handler；这比在 prompt 里要求模型“不要调用”更可靠。
- **这不是模型能力分数。** 规划器是脚本 DAG；要测 LLM 规划，需要把同一个 `Plan` 接口接到真实 function calling，并单独报告 token/延迟/方差。

## Task matrix

| task | category | raw | verified | adaptive |
|---|---|---|---|---|
| diag_stock | diagnosis | pass | pass | pass |
| diag_dc | diagnosis | pass | pass | pass |
| diag_transit | diagnosis | pass | pass | pass |
| diag_local | diagnosis | pass | pass | pass |
| cmp_stock_target | comparison | pass | pass | pass |
| cmp_stock_rest | comparison | pass | pass | pass |
| cmp_dc_target | comparison | pass | pass | pass |
| cmp_dc_all | comparison | pass | pass | pass |
| cmp_transit_1 | comparison | pass | pass | pass |
| cmp_transit_2 | comparison | pass | pass | pass |
| cmp_local_target | comparison | pass | pass | pass |
| cmp_local_backlog | comparison | pass | pass | pass |
| sum_stock | summary | pass | pass | pass |
| sum_dc | summary | pass | pass | pass |
| sum_transit | summary | pass | pass | pass |
| sum_local | summary | pass | pass | pass |
| alloc_opt | allocation | pass | pass | pass |
| alloc_greedy | allocation | pass | pass | pass |
| alloc_gap | allocation | pass | pass | pass |
| alloc_flows | allocation | pass | pass | pass |
| multi_stock | multi_step | pass | pass | pass |
| multi_dc | multi_step | pass | pass | pass |
| multi_transit | multi_step | pass | pass | pass |
| guard_invalid_enum | guardrail | pass | pass | pass |
| guard_unknown_tool | guardrail | pass | pass | pass |
| recover_missing_experiment | recovery | fail(blocked) | fail(blocked) | pass |
| recover_infeasible_tight | recovery | fail(failed) | fail(failed) | pass |
| guard_bad_dependency | guardrail | pass | pass | pass |
| guard_budget | guardrail | pass | pass | pass |
| recover_wrong_fact | recovery | fail(success) | fail(failed) | pass |
