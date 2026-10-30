# Agent v2 LLM planner（function calling）

## 1. 它解决什么

Agent v2 的 runtime 已经能执行带依赖的 `Plan` DAG，但 30 任务基准里的 planner 是脚本 DAG。`llm_planner.py` 把同一个 `Plan` 接口接到 OpenAI 兼容的 `chat.completions` function calling 上：

```
业务问题
  → LLM 调用 submit_plan（只提交计划）
  → LLMPlanner 校验 allowlist / JSON Schema / 依赖 / 环
  → 非法计划带错误回传，最多 max_attempts 次
  → AgentRuntime 执行 Plan DAG
  → Verifier 检查步骤、数字、引用、预算
  → 通过则回答；失败则模型 replan 或显式 fallback
```

模型驱动 replan 的入口是 `AgentRuntime(..., replanner=planner.replan)`。runtime 把原计划、compact trace、已得事实和 verifier failures 放进 context；模型重新提交 `submit_plan`。如果模型连续失败/超时，runtime 才使用脚本 `fallback_plan`，并在 `AgentRun.summary()` 中区分 `replanned_by="model"` 与 `"fallback"`，同时保留 `replan_error`。

模型不执行工具、不做算术、不写数据库。所有数字来自工具，所有工具调用经过 `ToolRegistry` 的 allowlist 和参数校验。

## 2. 契约

```python
PlanStep(id, tool, args, depends_on, retries, optional, note)
Plan(steps, goal)
```

`submit_plan` 的参数：

```json
{
  "goal": "诊断目标 OTIF 的瓶颈",
  "steps": [
    {"id": "list", "tool": "list_experiments", "args": {}},
    {"id": "diag", "tool": "diagnose_service_gap",
     "args": {"constraint": "stock"}, "depends_on": ["list"]}
  ]
}
```

planner 在构建 `Plan` 前逐项检查：

1. `steps` 非空，`id` 唯一；
2. `tool` 必须在 `ToolRegistry` allowlist；
3. `args` 必须通过该工具的 JSON Schema（类型、枚举、上下界、未知字段）；
4. `depends_on` 只能引用已定义的 step id；
5. `Plan` 构造时再做拓扑排序/环检测。

任何一项失败都不会进入 runtime；错误会作为下一条 user message 回传，要求模型只调用 `submit_plan` 修正。超过 `max_attempts` 抛 `PlannerError`。

## 3. 为什么强制 `submit_plan`

OpenAI function calling 默认可以一次返回多个业务工具调用，但没有原生 DAG 依赖表达。强制单个 `submit_plan` 有三个好处：

- **计划与执行分离**：模型只输出计划，runtime 才执行；trace 可以完整审计。
- **可校验**：planner 在副作用发生前拒绝非法工具/参数/依赖。
- **可修复**：错误是结构化的（缺字段、枚举不对、依赖不存在），可以直接回传重试，而不是让模型猜。

这不是让模型“更自由”，而是让模型的输出更窄、更可验证。

## 4. 失败模式

| 失败 | 处理 |
|---|---|
| 没调用 `submit_plan` | `PlannerError`，不执行任何工具 |
| 工具不在 allowlist | 拒绝并回传可用工具名 |
| 参数枚举/类型错 | 拒绝并回传 schema 错误 |
| 依赖不存在 / 成环 | 拒绝；不会执行半截计划 |
| 计划合法但工具运行失败 | runtime trace 标记；verifier 判 failed；模型 replan 或 fallback plan 修复 |
| replan 模型超时/抛错 | 记录 `replan_error`，退回脚本 fallback；不伪装成模型修复 |
| 模型编造数字 | verifier 用 `require_facts` 对照工具事实；不通过 |

## 5. 真实模型评测边界

**本仓库没有跑真实 LLM。** `LLMPlanner` 与 `OpenAIPlannerClient` 已实现，测试使用 fake client，覆盖：

- 合法 `submit_plan` 被 runtime 执行并通过 verifier；
- 非法工具 / 非法 JSON 被拒绝后重试成功；
- 缺少 `submit_plan` 被拒绝；
- verifier 失败后模型 replan 成功，`replanned_by="model"`；
- 模型 replan 抛错时显式回退到脚本 fallback，保留 `replan_error`；
- OpenAI adapter 只解析 `tool_calls`，不访问网络。

真实评测需要 `OPENAI_API_KEY`（或兼容端点），并且必须单独报告：

- 任务成功率与 verifier 通过率，不能只报“模型答了”；
- 假成功（工具返回错数但模型报 success）；
- token、延迟、每任务成本；
- 同一 prompt 的多次采样方差；
- 模型版本/温度/工具 schema 变化。

没有这些数字，就不能把 Agent v2 的 30 任务结果说成“LLM 规划能力”。

## 6. 可选的 ReAct 单步循环

静态 `Plan` DAG 适合“步骤在规划时已经知道”的问题；如果下一步取决于上一步返回的事实（例如先看诊断结果、再决定比较哪个 arm），可以用 `ReActAgent`：

```
用户问题 → 模型选一个工具 → Registry 校验/执行 → observation 回填
        → 模型再选一个工具 ... → finish → Verifier
```

与静态 DAG 共用 `ToolRegistry`、`TraceEvent`、`Verifier`，区别只是每次只执行一个工具并观察结果。非法工具/参数不会中断循环，而是作为 blocked observation 回填；`max_steps` 用尽会追加 `__budget__` 事件并判 `blocked`。`finish.answer` 只是回答文本，是否通过仍由 verifier 的事实检查决定。

ReAct 使用 OpenAI adapter 时要设 `forced_tool=None`（`tool_choice="auto"`），否则 adapter 会强制模型调用 `submit_plan`：

```python
client = OpenAIPlannerClient(model="gpt-4o-mini", forced_tool=None)
run = ReActAgent(registry, client, Verifier(...)).run("库存还是产能是瓶颈？")
```

ReAct 没有进入 30 任务基准，也没有跑真实模型；测试覆盖“先观察再 finish / 非法工具恢复 / 步数预算 / 验证失败 abstain”，全部 fake client。`finish.answer` 是模型 prose，verifier 只检查 trace/事实，不做语义蕴含检查；验证失败时 runtime 用显式 abstain 替换模型 prose。ReAct 的失败不会被 fallback 自动修复，需要上层显式处理。

## 7. 复现

```bash
# 离线：fake client 测试，不访问网络
PYTHONPATH=src;. python tests/test_agent_v2.py

# 真实模型：需要 key；不要在 CI 里跑
export OPENAI_API_KEY=...
PYTHONPATH=src;. python - <<'PY'
from supply.agent_v2 import AgentRuntime, LLMPlanner, OpenAIPlannerClient, Verifier, build_registry
registry = build_registry()
planner = LLMPlanner(registry, OpenAIPlannerClient(model="gpt-4o-mini"))
plan = planner.plan("库存还是产能是目标 OTIF 的瓶颈？")
print(AgentRuntime(registry, Verifier(required_steps=("diag",))).run(plan).summary())
PY
```
