# Agent v2 runtime：语义、不变量与复杂度

这份 model card 描述 Agent v2 的**执行语义**，不描述业务模型本身。目标是把“智能体”从 demo 话术拆成可检查的契约：什么能执行、什么时候停止、失败如何分类、哪些结论不能从 benchmark 推出来。

## 1. 形式化对象

| 对象 | 定义 |
|---|---|
| 工具契约 `C` | `(name, parameters, side_effects, cost, tags)`；`parameters` 是 JSON Schema 子集（type/required/enum/min/max/additionalProperties） |
| 步骤 `s` | `(id, tool, args, depends_on, retries, optional)` |
| 计划 `P` | 有限步骤集合 `S` 与依赖边 `E`，要求 DAG：无重复 id、无缺失依赖、无环 |
| trace `τ` | 按执行顺序记录的 `(step_id, tool, args, status, latency, facts, error, attempt)` |
| facts `f` | 成功步骤返回的 `data.facts` 合并；后写覆盖同名键 |
| verifier `V` | `(required_steps, expected_facts, tolerance, citations_required, min_facts, budget)` → `ok, failures` |
| replanner `R` | `ctx = (question, plan, trace, facts, verification)` → 新 `Plan` 或 `None` |
| fallback `F` | 预先声明的确定性 `Plan`，只在模型 replan 失败或没有 replanner 时使用 |

执行语义：

```
τ, f ← execute(P)
if V(τ, f) fails:
    P' ← R(ctx)            # 可选，模型修复
    if P' is not None:
        τ, f ← execute(P')
    elif F is not None:
        τ, f ← execute(F)
answer ← answer_builder(f, τ)
status ← status_of(τ, V, replanned)
```

`execute` 按拓扑序串行执行；只有依赖步骤 `status == "success"` 才执行当前步骤。`optional=True` 的失败不阻塞下游，但 trace 仍保留失败状态。

## 2. 不变量

这些不变量在 `ToolRegistry`、`Plan`、`AgentRuntime` 三层分别强制：

1. **allowlist 先于 handler。** 未知工具返回 `blocked`，不进入任何业务函数。
2. **schema 先于 handler。** 缺字段、坏类型、坏枚举、越界、未知字段返回 `blocked`。
3. **依赖失败不执行。** 上游不是 `success` 时，下游记 `blocked`，不会“带病执行”。
4. **步数预算硬阻断。** 达到 `max_steps` 后追加 `__budget__` 事件；verifier 把预算事件判为失败，runtime 状态为 `blocked`。
5. **verifier 在 answer 之前，失败则 abstain。** 没有 verifier 的 `raw` 只表示“未验证”，不是“正确”；有 verifier 且失败时，runtime 返回 `未通过验证，拒绝给出结论`，不会把模型 prose 或工具拼接答案当结论。facts/trace 仍保留供审计。
6. **replan 最多一次。** 模型 replan 与脚本 fallback 不会无限递归；`replanned_by` 记录来源，`replan_error` 保留模型修复失败原因。
7. **模型没有执行权。** LLM 只输出 `submit_plan` / 单步工具名与参数；执行、校验、计时、trace 都由 runtime 完成。

## 3. 复杂度

设计划有 `V` 步、`E` 条依赖、工具 schema 检查成本 `S_i`、工具执行成本 `T_i`：

- 拓扑排序/环检测：`O(V + E)`，在 `Plan` 构造时执行一次。
- 计划校验：`O(Σ S_i)`，与参数对象大小线性相关。
- 执行：`O(Σ T_i)`；当前是串行执行，没有并行调度。
- trace/facts 内存：`O(V + |f|)`；工具返回的大对象会进入 trace，报告层负责截断。
- replan：最多增加一次执行与一次模型调用；模型 token 成本不在 runtime 的 `max_steps` 约束内，必须单独计费/限流。

## 4. 失败分类

| 阶段 | 失败 | 状态 | 是否执行了业务工具 |
|---|---|---|---|
| 规划 | 非法 JSON / 未知工具 / 坏参数 / 坏依赖 / 环 | `blocked`（planner 抛 `PlannerError`） | 否 |
| 执行 | 工具抛异常 / 返回 `error` | `failed` 或 `blocked` | 是，已记录 trace |
| 验证 | 必需步骤缺失、数字不符、引用缺失、事实不足 | `failed`，answer 为 abstain | 是 |
| 修复 | 模型 replan 抛错/超次数 | 退回 fallback；`replan_error` 保留 | 取决于 fallback |
| 预算 | 超过 `max_steps` | `blocked` | 只执行预算内的步骤 |

`false success`（工具返回错数但状态 success）只在**没有 verifier** 的 `raw` 策略出现；`verified`/`adaptive` 的 verifier 会把它判失败。benchmark report 单独报告这个指标。

## 5. 评估协议

30 任务、7 个类别、三种策略：

- `raw`：只执行，无 verifier；衡量“完成”而非“正确”。
- `verified`：执行 + verifier；衡量拒绝能力，但不会修。
- `adaptive`：执行 + verifier + 脚本 fallback；衡量显式修复。

指标：任务成功、假成功、verifier 通过率、重规划次数、平均步数。任务矩阵和逐任务状态见 `benchmarks/AGENT_V2_REPORT.md`。

**边界**：planner 是脚本 DAG；数字只反映 runtime/verifier/fallback，不反映 LLM 规划能力。`LLMPlanner`/`ReActAgent` 有 fake-client 测试，但没有真实模型评测，因此不能把 30 任务结果外推成模型分数。

## 6. 效度威胁

- **脚本计划是上界式对照**：它知道正确工具序列；真实 LLM 会选错工具、漏步骤、参数漂移。
- **benchmark 任务少且围绕已提交的 4–5 个实验**：类别覆盖有限，不能估计开放域任务成功率。
- **数字验证是精确匹配 + 容差**：能抓错数，但不能判断因果解释是否成立。
- **串行执行**：延迟和 token 成本没有被联合优化；真实 agent 还需要并发、缓存、限流和预算计费。
- **工具只读**：没有写操作，因此“副作用安全”没有被真实写路径检验。
- **ReAct 不在 30 任务里**：单步观察循环只有单元测试，没有端到端任务基准。

## 7. 复现

```bash
# runtime/verifier/planner/ReAct 全部离线测试
PYTHONPATH=src;. python tests/test_agent_v2.py

# 30 任务消融
PYTHONPATH=src;. python scripts/run_agent_v2_benchmark.py
```

相关文档：[LLM planner](llm_planner.md)、[约束诊断](binding_constraint.md)、[分单 MILP](allocation_milp.md)。
