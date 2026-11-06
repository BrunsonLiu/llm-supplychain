# 前沿技术融合蓝图：从“预测—优化”到“可验证的决策智能”

面向：供应链智能体项目  
版本：2026-11-06  
定位：不是再加功能，而是把现有系统升级成一条**可以讲清楚研究贡献**的前沿链路。

---

## 0. 一句话定位

把项目从：

> LightGBM 预测 → 库存规则 → CP-SAT 分单 → Agent 编排

升级成：

> **概率预测（TSFM + LightGBM）→ Conformal 校准 → 校准场景生成 → CVaR 随机联合优化 → LLM Agent 规划/验证/重规划 → 数字孪生评估**

这条链路的每一层都能单独发一篇 workshop paper，也能在面试里被追问 30 分钟不塌。

---

## 1. 先说实话：什么算前沿，什么已经是你的存量

### 1.1 你的项目已经有的，不要重复造

我核对了代码，现有能力比“普通预测项目”强：

- `src/supply/forecasting/backtest.py`：rolling-origin 回测，输出 `model/fold/cutoff/sku/horizon/week/actual/pred/scale`；
- `src/supply/e2e/stochastic.py`：**Week-14 两阶段随机布点**，用过去 6 周作为等权场景，目标含 `E[unmet] + CVaR`，已经有两阶段和 CVaR 变量；
- `src/supply/e2e/joint.py`：**Week-13 joint MILP**，把布点和分配放在一个模型里，但只针对已知目标周，是上界/反事实；
- `src/supply/agent_v2/`：`LLMPlanner` 输出 typed Plan DAG，`AgentRuntime` 做 Plan–Act–Verify–Replan，`Verifier` 做确定性校验；
- `src/supply/e2e/` 里已有 DES/rolling/robustness 等评估。

所以：

- **“加一个 CVaR”不是前沿增量**，你已经有了；
- **“加一个 LLM Planner”也不是**，你也有骨架；
- 真正缺的是：**场景从哪来、是否校准、布点和分配是否联合、Agent 是否真的可靠**。

### 1.2 2026 的前沿分层

| 层级 | 技术 | 判断 |
|---|---|---|
| S：研究前沿 | Agent post-training / computer use、RL reasoning、decision-focused learning、TSFM | 真前沿，但门槛高 |
| A：前沿边缘、可落地 | Conformal + CVaR 联合优化、verifier-grounded test-time compute、因果/实验 | 最适合你 |
| B：成熟但值钱 | LP/MIP、LightGBM、DES、RAG | 你的底座 |
| C：不要碰 | 供应链量子优化、通用“AI 大脑”、纯 Prompt 堆叠 | 没有可辩护的增量 |

### 1.3 本蓝图选的八项技术

**基础层（V1）**

1. **时序基础模型（TSFM）**：Chronos / TimesFM / Moirai，作为零样本/概率预测的另一条腿；
2. **Conformal Prediction / CQR**：给预测区间分布无关的覆盖校准；
3. **校准场景生成 + CVaR 两阶段随机联合优化**：把不确定性真正带进布点和分配；
4. **Agentic orchestration + verifier + test-time compute**：让 LLM 只做规划和调用，不做算术；
5. **Decision-focused evaluation（可选 stretch）**：用下游决策成本而不是 WMAPE 评价预测。

**决策闭环层（V2，详见 `CAUSAL_ONLINE_RL_BLUEPRINT.md`）**

6. **因果建模（SCM / 数字孪生）**：在模型内做 `do()` 干预和反事实评估，不在观测数据上硬编因果；
7. **在线优化（receding horizon）**：滚动重规划、反馈、drift 适应，量化 regret 和稳定性；
8. **强化学习策略层**：先做 contextual bandit 策略选择，再做参数化 PPO；RL 不直接输出库存单位。

**不选**：量子优化、GNN、自己预训练大模型、多 Agent swarm、真实数据上的端到端 RL。理由：没有干预数据、没有算力、没有可辩护的因果识别。

---

## 2. 目标架构

```text
                         ┌────────────────────────────┐
                         │  Data / Backtest Harness    │
                         │  panel, folds, actuals      │
                         └─────────────┬──────────────┘
                                       │
              ┌────────────────────────┼────────────────────────┐
              │                        │                        │
              ▼                        ▼                        ▼
   ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
   │ LightGBM / 统计   │    │ TSFM zero-shot   │    │ 历史残差 / 层级   │
   │ point forecast   │    │ Chronos/TimesFM  │    │ reconciliation   │
   └────────┬─────────┘    └────────┬─────────┘    └────────┬─────────┘
            └──────────────┬────────┴───────────────────────┘
                           ▼
                 ┌──────────────────────┐
                 │ Conformal Calibrator │
                 │ split / CQR / Mondrian│
                 └──────────┬───────────┘
                            ▼
                 ┌──────────────────────┐
                 │ Scenario Generator   │
                 │ copula / block boot  │
                 │ scenario reduction   │
                 └──────────┬───────────┘
                            ▼
                 ┌──────────────────────┐
                 │ Stochastic Joint     │
                 │ CVaR two-stage MILP  │
                 │ placement+allocation │
                 └──────────┬───────────┘
                            ▼
          ┌─────────────────┴─────────────────┐
          ▼                                   ▼
┌──────────────────┐               ┌──────────────────┐
│ Digital Twin/DES │               │ Agent Runtime    │
│ policy evaluation│               │ Plan→Act→Verify  │
│ stress / CVaR    │               │ →Replan / abstain│
└────────┬─────────┘               └────────┬─────────┘
         └─────────────────┬─────────────────┘
                           ▼
              ┌──────────────────────────┐
              │ Frontier Benchmark       │
              │ JSON + figures + report  │
              └──────────────────────────┘
```

V2 在这条链路上再加三个闭环：**SCM 因果世界模型**（提供可干预环境）、**Online Controller**（反馈与 drift）、**RL Policy Layer**（策略选择/参数化策略）。三者的接口、公式、实验和 14 周路线图见：

- [CAUSAL_ONLINE_RL_BLUEPRINT.md](CAUSAL_ONLINE_RL_BLUEPRINT.md)

### 设计原则

1. **Agent 不计算**：只发 Plan DAG，数字来自工具；Verifier 对照工具 `facts` 校验。
2. **预测和决策解耦但可联合评估**：预测指标（WMAPE/CRPS/coverage）和决策指标（OTIF/CVaR/cost）都报，避免“预测准但决策差”。
3. **每个模块都能单独 fallback**：TSFM 不可用 → LightGBM；Conformal 失败 → 经验分位数；MILP 超时 → 现有 `stochastic_placement`；LLM 不可用 → scripted planner。
4. **不引入不可复现的重依赖**：TSFM 作为 optional extra，CPU 可跑；CI 默认不下载大模型。

---

## 3. 与现有代码的映射

| 新模块 | 复用的现有代码 | 建议新文件 | 说明 |
|---|---|---|---|
| 概率预测 | `BacktestResult.predictions`、`features.py`、`lgbm.py`、`metrics.py` | `forecasting/probabilistic.py`、`forecasting/tsfm.py` | 输出 quantiles，不破坏现有点预测 |
| Conformal | 同上，按 `cutoff/week` 切校准/测试 | `forecasting/conformal.py` | 先校准 LightGBM，再接 TSFM |
| 场景生成 | `DemandScenario`、`ScenarioSet`、`build_demand_scenarios` | `e2e/scenarios.py` | 保持 `ScenarioSet` 接口，直接喂现有模型 |
| 随机联合优化 | `stochastic_placement`、`joint_plan`、`E2EInstance` | `e2e/stochastic_joint.py` | 新增“布点+分配”两阶段 CVaR |
| Agent 工具 | `ToolRegistry`、`LLMPlanner`、`AgentRuntime`、`Verifier` | `agent_v2/decision_tools.py` | 注册 forecast/scenario/optimize/simulate |
| Agent 可靠性 | `AgentRuntime` trace、`Verifier` | `agent_v2/reliability.py` | 100+ 任务、false success、成本/延迟 |
| 评估 | `scripts/run_backtest.py`、`benchmarks/*.json` | `scripts/run_frontier_bench.py` | 统一产物、config hash、git SHA |
| 因果 SCM | 需求面板、`E2EInstance`、DES | `causal/scm.py`、`causal/estimators.py` | DAG、`do()`、ATE/CATE、敏感性 |
| 在线优化 | `rolling.py`、`rolling_e2e.py`、`stochastic_joint.py` | `e2e/online.py` | receding horizon、regret、drift |
| RL 策略 | `rolling.py`、DES、`stochastic_joint.py` | `rl/env.py`、`rl/train.py`、`rl/shield.py` | bandit → PPO，动作参数化 + shield |

### 关键判断

- `stochastic.py` 已经有两阶段 CVaR，所以新模型不要叫“stochastic optimization”，要叫 **calibrated scenario + joint stochastic optimization**；
- `joint.py` 是已知周上界，新模型要做 **deployable**：先布点，后看需求，再分配；
- `LLMPlanner` 已经有 typed plan，不要重写 Agent 框架，重心放在 **tool grounding + verifier + test-time compute + 评测**。

---

## 4. 模块详细设计

### M1. 概率预测层

**目标**：给每个 SKU/周/ horizon 输出 `p10/p50/p90`，并保留 point forecast 作为 baseline。

**输入**

- `panel`：`sku, week, quantity, country, ...`
- 现有 `BacktestConfig` 的 folds，保证时间不泄漏。

**方法**

1. **LightGBM point**：复用现有模型，作为 baseline；
2. **LightGBM quantile**：用 `objective="quantile"`，训练 `alpha=0.1/0.5/0.9` 三个模型；
3. **TSFM zero-shot**：
   - Chronos-Bolt：直接输出分位数；
   - TimesFM：输出 point/quantile（取决于版本），没有 quantile 就用 point + conformal；
   - Moirai：作为第三个零样本对照，不必全量跑。
4. **融合**：按验证集 WMAPE/CRPS 做加权，权重固定在 calibration 之前，避免测试泄漏。

**输出契约**

```text
sku, week, horizon, model, p10, p50, p90, coverage_target, calibration, fold
```

**注意**

- 4,707 个 SKU 全量跑 TSFM 在 CPU 上会很慢：先抽样 200–500 个主 SKU + 冷启动/稀疏子集；
- 周序列只有 104 周，TSFM 的 context 足够，但零样本不一定优于 LightGBM；
- 负结果也是结果，只要预注册指标、解释清楚。

**验收**

- 概率预测在 80/90/95% 目标下，经验 coverage 误差 ≤ 2pp；
- 区间宽度不能比经验分位数方法宽 > 10%；
- CRPS 不劣于 LightGBM point + 残差分位数。

---

### M2. Conformal 校准层

**目标**：把“模型自己的分位数”变成“有覆盖保证/可诊断”的区间。

**方法**

1. **Split conformal**：
   - 校准集：test cutoff 之前 26 周；
   - 非一致性分数：`|actual - pred| / scale`；
   - 分位数：`ceil((n+1)(1-alpha))/n`；
2. **CQR**：
   - 用 LightGBM quantile 得到初始区间 `[l, u]`；
   - 非一致性分数：`max(l - actual, actual - u)`；
   - 校准后得到 `[l - q, u + q]`；
3. **Mondrian**：
   - 按 SKU 销量分桶（高/中/低/零销量）或 horizon 分组校准；
   - 解决全局 coverage 被大 SKU 主导的问题；
4. **时间序列修正**：
   - 可交换性在时间序列上不严格成立；
   - 用 rolling/block calibration，报告 empirical coverage，不宣称无条件 guarantee。

**输出**

- `coverage_report.json`：目标 coverage、经验 coverage、平均宽度、分桶 coverage；
- `quantiles_calibrated.parquet`：给场景生成用。

**验收**

- 90% 目标下，整体 coverage 88–92%；
- 低销量 SKU 的 coverage 不低于 85%；
- 与“正态假设/固定安全系数”对比，宽度更窄或尾部更好。

---

### M3. 场景生成层

**目标**：把 marginal quantiles 变成**有相关性、有时间结构、可缩减**的 `ScenarioSet`，直接喂 `stochastic_placement` / 新联合模型。

**现有局限**

`build_demand_scenarios` 用过去 6 周等权、按目标总量缩放。它简单、可部署，但：

- 不能表达“下周整体需求高/低”；
- 不能表达 SKU 间相关；
- 不能表达尾部/极端场景；
- 场景数固定为 6，无法做 scenario reduction。

**新方法**

1. **Marginal**：从 M2 的 quantiles 反 CDF 采样；
2. **Dependence**：
   - Gaussian copula：对历史残差做 rank 变换，估计相关矩阵；
   - 或 block bootstrap：按周块重采样残差，保留跨 SKU 相关；
3. **Aggregate conditioning**：先抽总需求，再按 copula 分配 SKU 份额，保证总量合理；
4. **Scenario reduction**：
   - k-means / Wasserstein / greedy；
   - 20–50 个场景，带权重；
5. **输出**：`ScenarioSet`（保持现有 dataclass 兼容），每个场景有 `weight`。

**验证**

- 场景均值 vs 预测均值；
- 场景相关性 vs 历史相关性（Frobenius 误差）；
- 场景分位数 vs conformal 区间；
- 下游指标才是最终裁判。

**验收**

- 与“过去 6 周等权”相比，下游 CVaR 降低 ≥ 5%，OTIF 不下降；
- 场景数从 6 增加到 30 时，求解时间可控（< 3 分钟/实例）。

---

### M4. 随机联合优化层

**目标**：把 `stochastic_placement`（布点，固定总量）和 `joint_plan`（已知周联合）合起来，做**可部署的两阶段随机联合优化**。

**模型**

集合：

- `K` SKU，`D` DC，`S` 场景；
- `z[k,d]`：第一阶段布点整数；
- `y[s,k,d]`：第二阶段分配；
- `u[s,k]`：未满足需求；
- `Q[k]`：SKU 总库存（固定或由补货策略给出）。

约束：

```text
sum_d z[k,d] = Q[k]                          ∀k
y[s,k,d] <= z[k,d]                           ∀s,k,d
y[s,k,d] <= serviceable[s,k,d]               ∀s,k,d
sum_k y[s,k,d] <= throughput[d]              ∀s,d
sum_k pick_minutes(y[s,k,:]) <= capacity[d]  ∀s,d
sum_d y[s,k,d] + u[s,k] = demand[s,k]        ∀s,k
z, y integer >= 0
```

目标：

```text
min  (1 - beta) * Σ_s p_s * Cost_s
   + beta * CVaR_alpha(Cost)
   + service_penalty * Σ_s p_s * Σ_k u[s,k]
```

CVaR 线性化：

```text
CVaR = eta + 1/(1-alpha) * Σ_s p_s * e_s
e_s >= Cost_s - eta
e_s >= 0
```

`Cost_s` 包含 handling、transport、backlog、lost sale、pick overtime。  
`beta`、`alpha` 做敏感性问题；`beta=0` 是风险中性，`beta=1` 是纯 CVaR。

**求解**

- 小/中实例：OR-Tools `pywraplp` + SCIP；整数变量用 MILP；
- 大规模：scenario reduction + 时间限制 + warm start（用 `joint_plan` 或 `stochastic_placement` 解）；
- LP 松弛：用 GLOP 求对偶，输出 throughput/capacity 的 shadow price，做敏感性分析；
- fallback：超时则回退现有 `stochastic_placement`，记录 `fallback_reason`。

**输出**

```text
plan_id, method, stock[dc,sku], allocation[s,dc,sku],
expected_cost, cvar, otif, backlog, solve_time, gap,
duals{throughput, capacity}, fallback_reason
```

**对比**

| 方法 | 说明 |
|---|---|
| point + safety factor | 现有规则 baseline |
| deterministic joint | 已知周上界，不可部署 |
| empirical CVaR placement | 现有 `stochastic.py` |
| calibrated CVaR joint | 本蓝图主方法 |
| robust box | 保守 baseline |

**验收**

- 相同 OTIF 下，成本/CVaR 优于 empirical CVaR placement；
- 与 deterministic joint 的 gap 被量化（price of decomposition）；
- 30 个 rolling instances 上，至少 70% 实例不劣化；
- 求解时间有上限，失败可 fallback。

---

### M5. Agentic orchestration 层

**目标**：LLM 只做“选工具、排 DAG、解释”，不做算术；用 Verifier 和 test-time compute 提升可靠性。

**新增工具**

| 工具 | 输入 | 输出 |
|---|---|---|
| `forecast_probabilistic` | sku 集合、horizon、model | quantiles、coverage、model card |
| `build_scenarios` | forecast id、scenario 数、方法 | scenario id、权重、相关性诊断 |
| `solve_stochastic_joint` | scenario id、beta、alpha、time limit | plan、cost、CVaR、duals、gap |
| `simulate_policy` | plan id、stress 参数 | OTIF、cost、backlog、worst-case |
| `explain_tradeoff` | 两个 plan id | 差异、约束 binding、风险解释（只读 facts） |

**流程**

```text
Task
  → LLMPlanner 生成 Plan DAG（K 个候选，temperature）
  → ToolRegistry 执行
  → Verifier 校验：
       - 工具是否成功
       - 数字是否来自 facts
       - 约束是否满足（库存/产能/承诺）
       - 结论是否越权（不能编造因果）
  → 若失败：Replan（最多 N 次）
  → 若仍失败：abstain
  → 选择 verified success 最高的候选
```

**Test-time compute**

- best-of-K plans：K=1/4/8，比较 success、false success、cost、latency；
- verifier 作为 scorer，不用 LLM 自评；
- 记录 token、工具调用次数、wall-clock。

**可靠性 benchmark**

- 120 个任务，5 类：
  1. 诊断约束（哪一个是瓶颈）；
  2. 比较两个 arm；
  3. 给定预算选布点；
  4. 压力/对抗（缺数据、不可行、矛盾目标）；
  5. 解释 trade-off（不能编造数字）。
- 2 个 LLM + scripted planner baseline；
- 每个模型 3 个 temperature / seed；
- 指标：task success、verified success、false success、abstain、replan success、latency、tokens、tool calls。

**注意**

- 没有真实 API key 时，只能报 fake client 的单元测试，**不能编造真实模型数字**；
- `LLMPlanner` 已有 `OpenAIPlannerClient` 适配器，但默认测试不联网；
- Agent 的价值不是“更聪明”，而是“在约束下更可靠、可审计”。

**验收**

- false success 相对 single-plan 降低 ≥ 50%；
- verified success 不低于 scripted baseline；
- 成本/延迟在可接受范围（例如 P95 < 30s，单任务 < $0.05，按实际模型定价）。

---

### M6. 数字孪生与决策中心评估

**目标**：不只看 WMAPE，看决策后的服务、成本、尾部风险。

**评估协议**

- rolling-origin：每次用 cutoff 前数据训练/校准，预测未来 13 周；
- 30 seeds（场景采样/优化随机性）；
- paired bootstrap 10,000 次，报 95% CI；
- 压力测试：需求 +20%、产能 -20%、transit +1 天、promo spike；
- 失败分析：不可行、超时、fallback、coverage 失效。

**指标**

| 类别 | 指标 |
|---|---|
| 预测 | WMAPE、CRPS、coverage、interval width |
| 服务 | OTIF、fill rate、worst-week OTIF、CVaR_95(backlog) |
| 成本 | total cost、holding、backlog、expedite |
| 优化 | solve time、gap、infeasible rate、price of decomposition |
| Agent | success、verified success、false success、abstain、latency、tokens |
| 统计 | paired bootstrap CI、effect size |

**关键对比**

1. point + safety factor vs conformal；
2. empirical scenarios vs calibrated scenarios；
3. decomposed placement/allocation vs joint stochastic；
4. single plan vs best-of-K + verifier；
5. LightGBM vs TSFM vs ensemble（分稀疏/冷启动子集）。

---

### M7. 研究 harness

**脚本**

```text
scripts/run_frontier_bench.py
  --stage forecast|conformal|scenarios|optimize|agent|all
  --config configs/frontier.yaml
  --out-dir benchmarks/frontier
```

**产物**

```text
benchmarks/frontier/
  manifest.json          # git SHA, config hash, seeds, versions
  forecast_metrics.json
  coverage_report.json
  scenario_diagnostics.json
  optimization_results.json
  agent_reliability.json
  figures/*.png
```

**测试**

- synthetic coverage test：已知分布，验证 conformal coverage；
- scenario shape/weight 测试；
- optimizer feasibility + objective consistency；
- agent contract + verifier tests；
- golden test：固定 seed，指标不漂移。

**CI**

- 默认 CPU、无网络、无大模型；
- TSFM/LLM 测试标记 `slow`/`network`，单独 job；
- 不让 CI 下载 GB 级权重。

---

## 5. 数据契约

### 5.1 预测分位数

```text
sku: str
week: date
horizon: int
model: str
p10/p50/p90: float
coverage_target: float
calibration: str  # none|split|cqr|mondrian
fold: int
```

### 5.2 场景

```text
scenario_id: int
week: date
sku: str
demand: int
weight: float
method: str  # empirical|copula|block_bootstrap
```

内部仍用 `DemandScenario`/`ScenarioSet`，避免破坏现有求解器。

### 5.3 决策计划

```text
plan_id: str
method: str
stock: list[list[int]]        # D x K
allocation: list[list[list[int]]]  # S x D x K
expected_cost: float
cvar: float
otif: float
backlog: float
solve_time_s: float
gap: float
duals: dict
fallback_reason: str
```

### 5.4 Agent trace

```text
run_id, task_id, model, temperature,
plan, tool_calls, verification,
success, false_success, abstain,
replan_count, latency_ms, tokens
```

---

## 6. 实验矩阵

| RQ | 问题 | 设计 | 主要指标 | 成功标准 | 止损 |
|---|---|---|---|---|---|
| RQ1 | Conformal 是否改善覆盖且不牺牲宽度？ | split/CQR/Mondrian vs 正态/经验分位数 | coverage、width、CRPS | coverage 误差 ≤2pp，宽度不差 >10% | 覆盖仍差 → 只报诊断，不吹保证 |
| RQ2 | 校准场景是否改善下游决策？ | 历史周等权 vs copula/block bootstrap | CVaR、OTIF、cost | CVaR ↓≥5%，OTIF 不降 | 无改善 → 保留为 ablation |
| RQ3 | 联合随机优化比分解好多少？ | empirical placement vs calibrated joint | price of decomposition、cost、CVaR | 量化 gap，70% 实例不劣化 | 太慢/不可行 → 缩场景/回退 |
| RQ4 | TSFM 是否在稀疏/冷启动上有价值？ | zero-shot vs LightGBM vs ensemble | WMAPE、CRPS、决策指标 | 至少一个子集显著改善 | 全线不如 → 诚实负结果 |
| RQ5 | verifier/test-time compute 是否提升 Agent 可靠性？ | single plan vs best-of-K + verifier | false success、verified success、cost | false success ↓≥50% | 成本爆炸 → 限 K/abstain |
| RQ6 | decision-focused 是否优于 WMAPE 训练？ | WMAPE vs SPO+/决策损失 | downstream cost、CVaR | 成本改善且有 CI | 不稳定 → 只作讨论 |

V2 新增五组实验，见 [CAUSAL_ONLINE_RL_BLUEPRINT.md](CAUSAL_ONLINE_RL_BLUEPRINT.md)：

- **RQ7 因果估计器**：已知 ground truth 下比较 naive/IPW/AIPW/DML/causal forest；
- **RQ8 在线优化**：open-loop vs rolling calibrated，量化 regret、OTIF、turnover；
- **RQ9 RL-0**：contextual bandit 策略选择 vs 固定策略/随机；
- **RQ10 RL-1**：参数化 PPO vs CMA-ES/随机搜索（打不过黑盒调参就不算成功）；
- **RQ11 SCM-guided**：因果世界模型指导是否改善 online/RL 的可解释性与鲁棒性。

**预注册**：先写指标和成功标准，再跑；避免“跑完挑一个好看的结果”。

---

## 7. 里程碑（基础版 10 周，MVP 在第 3 周末）

### P0：基线与 Conformal（Week 1）

- 冻结现有 benchmark；
- 实现 `forecasting/conformal.py`；
- 输出 coverage/width 报告；
- 单测：synthetic coverage、时间切分无泄漏。

**验收**：90% 目标 coverage 88–92%；文档记录假设与限制。

### P1：场景 + 随机联合（Week 2–3）

- 实现 `e2e/scenarios.py`；
- 实现 `e2e/stochastic_joint.py`；
- 复用 `E2EInstance`/`ScenarioSet`；
- 对比 empirical placement、deterministic joint、calibrated joint。

**验收**：至少 70% rolling instances 不劣化；CVaR 有改善；求解可 fallback。

### P2：TSFM 对照（Week 4–5）

- `forecasting/tsfm.py` 适配 Chronos/TimesFM；
- 抽 200–500 SKU + 稀疏子集；
- 零样本 vs LightGBM vs ensemble；
- 负结果也写清楚。

**验收**：完成 ablation 表；若 TSFM 全线不如，明确“不作为主线”。

### P3：Agent 可靠性（Week 6–8）

- `agent_v2/decision_tools.py` 注册新工具；
- `agent_v2/reliability.py` 120 任务；
- best-of-K + verifier；
- 2 个模型 + scripted baseline；
- 记录 false success / cost / latency。

**验收**：false success ↓≥50%；无真实 API key 时明确标注“未跑真实模型”。

### P4：Decision-focused + 论文（Week 9–10，可选）

- 用 SPO+/决策损失微调/重加权预测模型；
- 或只做敏感性/对偶分析；
- 写 8–12 页技术报告；
- 3 张主图 + 1 张表。

**验收**：有明确 negative/positive result；不夸大。

### V2：因果 + 在线 + RL（14 周）

基础版做完后，按 [CAUSAL_ONLINE_RL_BLUEPRINT.md](CAUSAL_ONLINE_RL_BLUEPRINT.md) 的 14 周路线图继续：

- W1：SCM DAG + 结构方程；
- W2–3：随机联合 + 校准场景；
- W4–5：因果估计器 benchmark；
- W6–7：在线 receding horizon；
- W8–9：RL-0 contextual bandit；
- W10–11：RL-1 参数化 PPO；
- W12–14：稳健性、Agent claim guard、写作。

**6 周最小版**：W1–W7（SCM + 因果 benchmark + 在线滚动），RL 作为 stretch。

---

## 8. 论文/作品集叙事

### 标题候选

- *Calibrated Forecasts, Better Decisions: Conformal Scenario Optimization for Supply Chains*
- *From Prediction to Verified Decisions: A Frontier Benchmark for Supply-Chain Agents*
- *Price of Decomposition: Joint Stochastic Placement and Allocation under Calibrated Uncertainty*

### Abstract 骨架

1. 问题：预测误差和决策目标不一致，点预测 + 安全系数无法控制尾部风险；
2. 方法：TSFM/LightGBM → conformal → copula scenarios → CVaR joint → agent verifier；
3. 实验：UCI Online Retail II，rolling-origin，30 seeds；
4. 结果：coverage、CVaR、OTIF、price of decomposition；
5. 限制：单数据集、时间序列可交换性不严格、Agent 成本。

### 三张主图

1. **Coverage–width frontier**：不同校准方法；
2. **Service–cost frontier**：point/deterministic/empirical/calibrated joint；
3. **Reliability–cost frontier**：single plan vs best-of-K + verifier。

### 简历一句话

> 构建了从概率预测、conformal 校准、场景生成到 CVaR 随机联合优化的决策栈，并用 verifier-grounded Agent 做可审计编排；在 30 seeds 上量化了覆盖率、尾部服务和分解代价。

---

## 9. 风险与止损

| 风险 | 概率 | 影响 | 应对 |
|---|---|---|---|
| TSFM 全面不如 LightGBM | 高 | 中 | 作为 ablation，不挡主线 |
| Conformal 在时间序列上 coverage 不稳 | 中 | 高 | rolling calibration，报经验 coverage，不吹 guarantee |
| 随机 MILP 太大/超时 | 中 | 高 | 场景缩减、时间限制、warm start、fallback |
| Agent 成本高/不稳定 | 高 | 中 | K 上限、verifier、abstain、scripted baseline |
| 真实 LLM 无 API key | 中 | 中 | 只报 fake client 单测，明确“未跑真实模型” |
| 范围蔓延 | 高 | 高 | 一个旗舰 + 两个增强，不碰量子/GNN |
| 数据泄漏 | 中 | 高 | 时间切分、校准集在 cutoff 前、golden test |

---

## 10. 不做什么

- **不做量子优化**：没有硬件/数据/岗位信号，投入产出比极低；
- **不做 GNN**：供应链网络图信息可以用特征/约束表达，收益不确定；
- **不自己预训练 TSFM/LLM**：没有算力，直接用开源权重；
- **不做多 Agent swarm**：单 Agent + verifier 更可控；
- **不做真实数据上的端到端 RL**：没有干预数据和可靠环境；RL 只在 SCM/仿真里训练，动作参数化 + 约束 shield；
- **不把“Prompt 调通”叫前沿**：Agent 的贡献在可靠性评测和工具 grounding。

---

## 11. 验收清单

- [ ] `forecasting/conformal.py`：coverage/width 报告，单测通过；
- [ ] `e2e/scenarios.py`：与 `ScenarioSet` 兼容，诊断报告；
- [ ] `e2e/stochastic_joint.py`：可部署、CVaR、fallback、duals；
- [ ] `forecasting/tsfm.py`：可选依赖，不阻塞 CI；
- [ ] `agent_v2/decision_tools.py`：4 个工具，schema/verifier；
- [ ] `agent_v2/reliability.py`：120 任务，真实/模拟结果分开标注；
- [ ] `scripts/run_frontier_bench.py`：manifest、JSON、图；
- [ ] README/PORTFOLIO 更新：只写有证据的数字；
- [ ] 一页 limitations：单数据集、时间序列假设、Agent 成本；
- [ ] 不出现“最前沿/首次”这类无法证明的词。

---

## 12. 参考来源

- Chronos: https://arxiv.org/abs/2403.07815
- TimesFM: https://arxiv.org/abs/2310.10688
- Moirai: https://arxiv.org/abs/2402.02592
- Conformal Prediction: https://arxiv.org/abs/2107.07511
- Decision-focused learning: https://arxiv.org/abs/1703.04529
- Test-time compute: https://arxiv.org/abs/2408.03314
- Anthropic, Building effective agents: https://www.anthropic.com/engineering/building-effective-agents
- Pearl, Causality: https://doi.org/10.1017/CBO9780511803161
- Double/debiased ML: https://arxiv.org/abs/1608.00060
- Causal forests: https://arxiv.org/abs/1510.04342
- PPO: https://arxiv.org/abs/1707.06347
- CQL: https://arxiv.org/abs/2006.04779
- IQL: https://arxiv.org/abs/2110.06169
- 岗位 JD 调研（同目录）：`FRONTIER_TECH_JD_2026.md`
- V2 因果/在线/RL 大纲（同目录）：`CAUSAL_ONLINE_RL_BLUEPRINT.md`
- 2026 最新文献与代码落地对照（同目录）：`FRONTIER_RESEARCH_2026.md`

---

## 13. 最后一句

**最前沿的融合，不是把八个热词都接上，而是让“不确定性”从预测一路传到决策，再让因果和在线反馈检验决策，最后让 Agent 对决策负责。**

如果只能做一件事：做 **M2 + M3 + M4**，把“校准场景 + CVaR 联合优化”打穿。  
如果还能做第二件：做 **SCM + 因果 benchmark + online**，把“策略到底有没有用”讲清楚。  
如果还有第三件：做 **RL-0 策略选择**，不要一上来做端到端 PPO。

这三层加起来，已经足够支撑一个 985 本硕在供应链/OR/因果/RL 方向上的差异化叙事。
