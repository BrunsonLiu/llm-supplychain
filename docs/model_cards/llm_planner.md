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
  → 通过则回答；失败则显式 fallback / Replan
```

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
| 计划合法但工具运行失败 | runtime trace 标记；verifier 判 failed；由 fallback plan 修复 |
| 模型编造数字 | verifier 用 `require_facts` 对照工具事实；不通过 |

## 5. 真实模型评测边界

**本仓库没有跑真实 LLM。** `LLMPlanner` 与 `OpenAIPlannerClient` 已实现，测试使用 fake client，覆盖：

- 合法 `submit_plan` 被 runtime 执行并通过 verifier；
- 非法工具被拒绝后重试成功；
- 缺少 `submit_plan` 被拒绝；
- OpenAI adapter 只解析 `tool_calls`，不访问网络。

真实评测需要 `OPENAI_API_KEY`（或兼容端点），并且必须单独报告：

- 任务成功率与 verifier 通过率，不能只报“模型答了”；
- 假成功（工具返回错数但模型报 success）；
- token、延迟、每任务成本；
- 同一 prompt 的多次采样方差；
- 模型版本/温度/工具 schema 变化。

没有这些数字，就不能把 Agent v2 的 30 任务结果说成“LLM 规划能力”。

## 6. 复现

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
