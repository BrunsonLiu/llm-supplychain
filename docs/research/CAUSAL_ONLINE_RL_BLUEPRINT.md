# 因果 + 随机联合 + 在线 + RL：V2 融合大纲

面向：供应链智能体项目  
版本：2026-11-07  
定位：在 V1（Conformal + 校准场景 + CVaR 联合 + Agent）之上，加入**因果世界模型、在线滚动优化、强化学习策略层**，形成一条完整的研究链路。

---

## 0. 结论与优先级

这四项可以放在一个系统里，但不能平铺：

```text
因果世界模型（SCM / Digital Twin）
        ↓ 提供可干预、可反事实的环境
随机联合优化（CVaR planner）
        ↓ 提供可行、可解释的基线策略
在线优化（Receding Horizon）
        ↓ 把计划和反馈接起来
强化学习（Policy Layer）
        ↓ 在仿真中改进策略参数/策略选择
```

**顺序不能反**：

1. 没有因果/SCM，online 和 RL 只能在真实数据上“试错”，既不可复现也不可解释；
2. 没有随机联合优化，RL 的动作空间太大，样本效率会崩；
3. 没有在线反馈，RL 只能学一个开环策略，遇到 drift 就失效；
4. 没有约束 shield，RL 会输出不可行/不安全的库存动作。

### 三种投入档位

| 时间 | 做到什么 | 适合 |
|---|---|---|
| 6 周 | 因果 SCM + 估计器 benchmark + 在线滚动（planner 复用） | 想要 OR/因果方向 |
| 10 周 | 上面 + RL-0（contextual bandit / 策略选择） | 想要 RL 信号但不冒险 |
| 14 周 | 上面 + RL-1（参数化 PPO / 离线 RL） | 想要完整研究故事 |

---

## 1. 四项技术的角色与 JD 信号

| 技术 | 在你的系统里的角色 | 前沿信号 | 主要风险 |
|---|---|---|---|
| 因果建模 | 评估“如果换策略会怎样”；给 online/RL 提供反事实环境 | Amazon Research Scientist 明确要 causal / A-B / quasi-experiment | 真实数据没有干预，不能硬做因果 |
| 随机联合优化 | CVaR 两阶段 planner，给 online/RL 提供可行动作 | Amazon Strategic Sourcing / NVIDIA 供应链优化 | 规模、求解时间 |
| 在线优化 | 滚动重规划、反馈、drift 适应 | 工业界真实决策系统核心 | 稳定性、短视、计算预算 |
| 强化学习 | 学策略参数/策略选择，而不是学原始库存单位 | Amazon 序贯决策；AI lab RL 岗 | 样本效率、sim-to-real、无真实环境 |

### 关键判断

- **因果建模不是“再加一个模型”**：它是 online/RL 的评估协议，决定你能不能诚实地说“这个策略更好”。
- **RL 不是“端到端替代优化器”**：最现实的是 **RL 调策略参数 / 选策略**，优化器负责可行性和约束。
- **在线优化不是“每天重跑 MILP”**：要有状态、反馈、warm start、regret 和稳定性指标。

---

## 2. 总体架构 V2

```text
                    ┌─────────────────────────────┐
                    │  Real data / UCI panel      │
                    │  demand, orders, geography  │
                    └──────────────┬──────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
   │ Forecast         │  │ Causal SCM       │  │ Simulator / DES  │
   │ LightGBM + TSFM  │  │ DAG + equations  │  │ rolling / wave   │
   │ + Conformal      │  │ + interventions  │  │ + recovery       │
   └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘
            ▼                     ▼                     ▼
   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
   │ Scenario Set     │  │ Causal estimator │  │ State / Reward   │
   │ copula / block   │  │ IPW / AIPW / CF  │  │ transitions      │
   └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘
            └──────────────┬──────┴──────────────────────┘
                           ▼
                 ┌──────────────────────┐
                 │ Stochastic Joint     │
                 │ CVaR two-stage MILP  │
                 │ placement+allocation │
                 └──────────┬───────────┘
                            ▼
                 ┌──────────────────────┐
                 │ Online Controller    │
                 │ receding horizon     │
                 │ feedback + drift     │
                 └──────────┬───────────┘
                            ▼
                 ┌──────────────────────┐
                 │ RL Policy Layer      │
                 │ bandit / PPO / IQL   │
                 │ shield + fallback    │
                 └──────────┬───────────┘
                            ▼
                 ┌──────────────────────┐
                 │ Agent + Verifier     │
                 │ causal claim guard   │
                 └──────────┬───────────┘
                            ▼
                 ┌──────────────────────┐
                 │ Evaluation Harness   │
                 │ regret / CVaR / ATE  │
                 └──────────────────────┘
```

### 一句话

**SCM 提供“如果……会怎样”，随机联合优化提供“现在该怎么做”，online 提供“做完之后怎么改”，RL 提供“长期怎么变好”。**

---

## 3. 因果建模：先划清边界，再做能做的事

### 3.1 真实数据的硬限制

UCI Online Retail II 是**观测数据**，没有库存策略的随机分配，也没有 propensity score。  
因此：

- 不能从这份数据估计“把库存从 85% 提到 100%”的真实因果效应；
- 不能声称“某策略导致 OTIF 提升”；
- 不能把相关关系包装成因果。

能做的是：

1. **结构因果模型 / 数字孪生**：把业务假设写成 DAG + 结构方程，做 `do()` 干预；
2. **因果估计器 benchmark**：在已知 ground truth 的仿真数据上，测试 IPW/AIPW/causal forest 能否恢复效应；
3. **真实数据上的关联 + 敏感性分析**：只作为假设生成，不作为因果结论。

这个边界不是弱点，反而是研究可信度的一部分。

### 3.2 SCM / DAG

建议的核心 DAG：

```text
Calendar/Seasonality ──→ Demand ──→ Forecast
        │                  │           │
        │                  ▼           ▼
        └──────────→ Capacity      InventoryDecision
                           │           │
                           ▼           ▼
                       Allocation ←── Promise
                           │
                           ▼
                         OTIF / Cost
```

变量：

- `Demand`：真实需求（外生 + 季节 + 促销）；
- `Forecast`：预测（受 demand 历史影响，但不反向导致 demand）；
- `InventoryDecision`：补货/布点；
- `Allocation`：分单；
- `Promise`：承诺时效；
- `Capacity`：DC 产能/拣选能力；
- `OTIF/Cost`：结果。

结构方程（示意）：

```text
D_t = f_D(seasonality, promo, noise)
F_t = f_F(history(D), features)
I_t = π_I(F_t, state)
A_t = π_A(I_t, D_t, capacity, promise)
Y_t = f_Y(A_t, D_t, capacity, promise, transit)
```

`do(I=z)`、`do(P=p)`、`do(A=policy)` 通过替换结构方程实现；这是**模型内干预**，不是现实世界干预。

实现上不重写 DES：`scm.py` 包住现有的 `prepare_flow` / `run_flow_e2e` / `run_rolling_policy`，把策略参数暴露为 `do()` 的输入，把同一个需求流喂给不同干预，保证 paired comparison。

### 3.3 三个层次，不要混

| 层次 | 问题 | 方法 | 能不能说“因果” |
|---|---|---|---|
| L1 关联 | 什么和 OTIF 相关？ | 回归、特征重要性 | 不能 |
| L2 干预（仿真） | 在模型里换策略会怎样？ | SCM `do()` + DES | 只能说“模型内因果效应” |
| L3 反事实 | 对某个已发生周，如果当时换策略会怎样？ | SCM 反事实推断 | 依赖模型假设，需敏感性 |

### 3.4 因果估计器 benchmark

**目的**：证明你的因果方法不是“跑个回归”，而是能恢复已知效应。

**目标量**：

```text
ATE = E[Y(1) - Y(0)]
```

AIPW 的示意：

```text
ψ_i = μ1(X_i) - μ0(X_i)
    + T_i (Y_i - μ1(X_i)) / e(X_i)
    - (1-T_i) (Y_i - μ0(X_i)) / (1-e(X_i))

ATE_hat = mean(ψ_i)
```

其中 `e(X)=P(T=1|X)` 是 propensity，`μ_t(X)=E[Y|T=t,X]`。

**数据生成**：

- 用 SCM 生成观测日志；
- 处理变量 `T`：库存水平高/低、承诺 3 天/5 天、是否转仓；
- 混杂：高需求周更可能给高库存；高价值客户更可能升级承诺；
- 结果 `Y`：OTIF、成本、积压。

**估计器**：

1. Naive difference；
2. IPW / propensity score；
3. AIPW / doubly robust；
4. Causal forest / DML（异质效应）；
5. DiD（如果面板有前后期）。

**诊断**：

- positivity/overlap： propensity 分布是否覆盖；
- covariate balance：加权前后标准化差异；
- placebo treatment：假处理不应有效应；
- 未观测混杂敏感性：E-value / Rosenbaum bounds。

**指标**：

- ATE bias / RMSE；
- CATE 的 rank correlation；
- 95% CI coverage；
- 在不同混杂强度下的敏感性。

**验收**：

- AIPW/DML 在中等混杂下 bias 明显小于 naive；
- CI coverage 接近 95%；
- 高混杂下明确报“估计不可靠”，不硬给结论。

### 3.5 真实数据上做什么

- 只做 **关联 + 敏感性**：例如“库存覆盖率和 OTIF 正相关，但受需求/产能混杂”；
- 用 E-value / Rosenbaum bounds 报“需要多强的未观测混杂才能推翻”；
- 不把 `p<0.05` 叫因果；
- 把真实数据用于校准 SCM 的边际分布和相关性，而不是识别策略效应。

### 3.5.1 如果未来有干预权限：A/B 设计

当前数据没有随机化，但如果未来能在仓库/区域层面做试点，应该先设计再上线：

- **随机化单位**：仓库或区域，而不是订单（避免 SUTVA/干扰）；
- **处理**：库存水平、承诺时效、转仓策略、分配优先级；
- **指标**：OTIF、成本、积压、客户留存；预先写主指标，避免多重比较；
- **功效分析**：给定基线 OTIF 和方差，算最小可检测效应与样本量；
- **CUPED**：用历史需求/OTIF 做协变量降方差；
- **干扰**：同仓/同区域溢出、库存调拨，必要时用 cluster randomization 或 switchback；
- **分析**：AIPW/DML + pre-registration；不要中途 peek。

这部分是“真因果”的唯一干净路径；没有它，就只能说“模型内因果”。

### 3.6 代码接口

建议新增：

```text
src/supply/causal/
  scm.py          # DAG, structural equations, do(), counterfactual
  estimators.py   # IPW, AIPW, DML, causal forest adapter
  benchmark.py    # synthetic confounded logs + ground truth
  report.py       # ATE/CATE/sensitivity report

scripts/run_causal_bench.py
```

核心 API：

```python
scm = SupplyChainSCM(config)
log = scm.sample_observational(n_weeks=104, confounding=0.5)
truth = scm.true_ate(treatment="stock_100_vs_85", outcome="otif")
est = AIPW().fit(log, treatment, outcome, covariates)
report = compare(est, truth)
```

### 3.7 Agent 的因果 claim guard

Agent 里新增：

- `estimate_effect`：返回 estimate、CI、design、assumptions、sensitivity；
- `run_intervention`：在 SCM 里执行 `do()`；
- `causal_sensitivity`：E-value / robustness。

Verifier 规则：

- 如果回答里出现“导致/因果/because of”，必须有 `design=randomized|simulation|quasi` 的工具证据；
- 只有相关性时，强制改成“相关/伴随”，否则 `abstain`；
- 这是 Agent 可靠性的一个很好的差异化点。

---

## 4. 随机联合优化：online/RL 的 planner

这一层不是新话题，但它是后面两层的地基。

### 4.1 复用与升级

- 复用 `src/supply/e2e/stochastic.py` 的 `DemandScenario`、`ScenarioSet`、两阶段 CVaR 结构；
- 复用 `src/supply/e2e/joint.py` 的 joint MILP 思路；
- 新写 `src/supply/e2e/stochastic_joint.py`：第一阶段布点 + 第二阶段分配，场景来自校准预测，而不是过去 6 周等权。

### 4.2 对 online/RL 的接口

```python
plan = solve_stochastic_joint(
    state=state,
    scenarios=scenarios,
    horizon=H,
    beta=0.5,
    alpha=0.9,
    time_limit=60,
)
```

输出必须包含：

- `stock` / `allocation`；
- `expected_cost` / `cvar`；
- `duals`（LP 松弛）；
- `feasible` / `fallback_reason`；
- `solve_time`。

RL 不直接输出库存单位，而是输出**参数**（service level、safety factor、allocation priority），由这个 planner 变成可行动作。

---

## 5. 在线优化：receding horizon + feedback

### 5.1 问题定义

离散时间 `t=1..T`：

- 状态 `s_t`：库存、在途、积压、预测分位数、产能、日历；
- 动作 `a_t`：补货/布点/分配参数/承诺；
- 需求 `d_t` 在动作后实现；
- 成本 `c_t(s_t, a_t, d_t)`；
- 策略 `π`。

目标：

```text
min_π  E[ Σ_t c_t(s_t, a_t, d_t) + λ * CVaR_α(Σ_t c_t) ]
```

这里的“在线”指 **receding-horizon control**：用反馈不断更新状态和场景，不是 online gradient descent。  
如果只调连续参数（安全系数、服务水平），可以再加一层 OCO/online learning；但主决策仍是滚动 MILP。

### 5.2 滚动优化

每个决策点：

1. 观测 `s_t`；
2. 用截至 `t` 的数据重新校准 forecast/conformal；
3. 生成 `H` 步场景；
4. 解随机联合优化；
5. 只执行第一步；
6. 观测真实需求/结果，更新状态；
7. 检测 drift，必要时重置校准窗口。

### 5.3 关键指标

- **累计成本 / OTIF**；
- **regret**：

```text
R_T = Σ_t c_t(π_online) - Σ_t c_t(π*_hindsight)
```

`π*_hindsight` 是知道真实需求后的离线最优，作为下界/参照；
- **稳定性**：决策 turnover、订单方差、bullwhip；
- **响应性**：drift 后多少步恢复；
- **计算**：每步求解时间、超时率、fallback 率。

### 5.4 对比

| 方法 | 说明 |
|---|---|
| open-loop offline | 一开始规划整个 horizon，不反馈 |
| rolling deterministic | 每步用点预测重跑 |
| rolling empirical | 用过去 6 周等权场景 |
| rolling calibrated | 用 conformal 校准场景 |
| online + warm start | 上一步解热启动，限制变化 |
| hindsight oracle | 已知需求，理论上界 |

### 5.5 代码接口

```text
src/supply/e2e/online.py
  class OnlineController
  def run_online(instance, controller, demand_stream, ...)
```

复用：

- `rolling.py` 的 `run_rolling_policy` / `_replenish`；
- `rolling_e2e.py` 的 `prepare_flow` / `run_flow_e2e`；
- `stochastic_joint.py` 的 planner；
- `robustness.py` 的 Monte Carlo 评估。

---

## 6. 强化学习：从“策略选择”到“参数化策略”

### 6.1 为什么不能直接学库存单位

- 动作维度：SKU × DC × 天，几千维；
- 约束多：库存平衡、产能、承诺；
- 仿真贵：每步一个 MILP；
- 真实数据没有 action log，不能做真实离线 RL。

所以分三级：

| 级别 | 动作 | 算法 | 风险 |
|---|---|---|---|
| RL-0 | 从现有策略/参数集中选一个 | contextual bandit / Thompson sampling | 低 |
| RL-1 | 学 10–30 个策略参数 | PPO / DDPG（连续） | 中 |
| RL-2 | 离线 RL 学策略 | CQL / IQL | 高，需大量仿真轨迹 |

### 6.2 MDP

```text
state s_t:
  inventory coverage by DC/cluster
  pipeline / in-transit
  backlog / overdue
  forecast quantiles (p10/p50/p90)
  capacity utilization
  calendar / promo
  recent service

action a_t:
  order-up-to levels S_c for cluster c
  safety factor per cluster
  allocation priority weights
  promise upgrade threshold
  transfer threshold

reward r_t:
  margin
  - holding cost
  - backlog / lost sale
  - expedite / transfer cost
  - SLA penalty
  - λ * CVaR penalty (or Lagrangian)
```

### 6.3 算法路线

**RL-0：Contextual Bandit（推荐先做）**

- 策略库：`rolling.py` 的 5 个策略 + stochastic joint 的参数网格；
- 状态特征：需求水平、产能利用率、积压、周次；
- 算法：LinUCB / Thompson sampling；
- 优点：样本少、可解释、易上线；
- 指标：累计 reward、regret、策略选择稳定性。

**RL-1：参数化 PPO**

- 动作：10–30 维连续参数；
- 环境：先用**代理模型**（surrogate：XGBoost/线性模型预测 cost）快速训练，再周期性用完整仿真验证；
- 算法：PPO（稳定、易实现）；
- 约束：动作 clip + planner feasibility shield + fallback；
- 优点：能学非线性策略；
- 风险：代理模型偏差、训练不稳定。

**RL-2：Offline RL（stretch）**

- 用仿真器生成 `(s,a,r,s')` 轨迹；
- CQL / IQL；
- 只作为研究扩展，不作为主线；
- 不能声称“真实数据离线 RL”。

### 6.4 Baselines（必须打）

- 现有规则策略（`none`、`daily_1d`、`daily_2d`、`daily_1d_safety`、`batch_2d`）；
- stochastic joint（固定参数）；
- 随机搜索 / CMA-ES 调参（**关键**：RL 必须打过黑盒调参，否则没有说服力）；
- online calibrated（无 RL）；
- hindsight oracle。

### 6.5 安全与可部署性

- **Action shield**：RL 输出先经过可行性投影/裁剪，再由 planner 执行；
- **Fallback**：reward 低于规则策略时回退；
- **Shadow mode**：先离线回放，不直接上线；
- **约束**：库存非负、产能上限、承诺上限、预算上限；
- **可解释**：记录每步 state/action/reward，做敏感性。

### 6.6 代码接口

```text
src/supply/rl/
  env.py          # SupplyChainEnv: reset/step, wraps rolling/DES
  policies.py     # rule, bandit, PPO policy adapter
  train.py        # train/eval loops
  shield.py       # feasibility projection/fallback
  surrogate.py    # fast cost model for RL-1

scripts/run_rl_bench.py
```

依赖：`stable-baselines3` 作为 optional extra，不阻塞默认 CI。

---

## 7. 四者怎么咬合

### 7.1 数据流

```text
Real data → forecast/conformal → scenarios
                │
                ▼
         stochastic joint planner
                │
                ▼
         online controller (feedback)
                │
                ▼
         RL policy (parameters/selection)
                │
                ▼
         SCM/DES evaluation
                │
                ▼
         causal estimator + regret + CVaR
```

### 7.2 因果和 RL 的关系

- SCM 是 RL 的**环境**：`do(action)` 产生反事实轨迹；
- 因果估计器是 RL 的**评估器**：估计策略的 ATE/CATE，而不只看平均 reward；
- RL 是 SCM 里的**策略搜索**：在模型内优化，不宣称现实因果；
- 真实数据只用于校准 SCM 的分布，不用于“训练一个真实世界 RL”。

### 7.3 因果和 online 的关系

- online 的每次策略变更都是一个干预；
- 用 SCM 做 **counterfactual replay**：如果当时不换策略会怎样；
- 用因果估计器做 **effect size + CI**，而不是只看一条曲线；
- Agent 的 verifier 阻止“把相关当因果”。

### 7.4 随机联合和 RL 的关系

- planner 是 RL 的 **action decoder**：RL 输出参数，planner 输出可行动作；
- planner 是 RL 的 **baseline**：RL 必须打过它；
- planner 提供 **duals/sensitivity**，解释 RL 为什么这样选。

---

## 8. 实验矩阵（新增）

| RQ | 问题 | 设计 | 指标 | 成功标准 | 止损 |
|---|---|---|---|---|---|
| RQ7 | 因果估计器能否在混杂下恢复已知效应？ | SCM 生成日志，naive/IPW/AIPW/DML/CF | ATE bias、RMSE、CI coverage | AIPW/DML 明显优于 naive；coverage≈95% | 高混杂下失败 → 明确报限制 |
| RQ8 | 在线滚动是否优于开环/离线？ | open-loop vs rolling det/empirical/calibrated | regret、OTIF、cost、turnover | 至少一个场景 regret 降低，OTIF 不降 | 短视/震荡 → 加 warm start/正则 |
| RQ9 | RL-0 是否优于固定策略/随机选择？ | bandit vs rule vs random | reward、regret、稳定性 | 累计 reward 提升且有 CI | 不稳定 → 回退规则 |
| RQ10 | RL-1 是否优于 CMA-ES/随机搜索？ | PPO vs CMA-ES vs planner | reward、CVaR、sim-to-holdout | 打过黑盒调参才算成功 | 打不过 → 只保留 bandit |
| RQ11 | 因果 SCM 指导是否改善 RL/online？ | SCM-guided vs black-box | reward、ATE 偏差、鲁棒性 | 有增益或更好解释 | 无增益 → 作为评估工具 |

**预注册**：先写成功标准，再跑；RL 尤其容易“挑 seed”。

---

## 9. 14 周路线图

| 周 | 阶段 | 产出 | 验收 |
|---|---|---|---|
| W1 | 基线 + SCM 规格 | DAG、结构方程、`causal/scm.py` 骨架 | DAG 可解释，干预接口可跑 |
| W2–3 | 随机联合 + 场景 | `stochastic_joint.py`、`scenarios.py` | CVaR/OTIF 不劣于现有 |
| W4–5 | 因果 benchmark | 合成混杂日志 + IPW/AIPW/DML | ATE bias/CI 报告 |
| W6–7 | 在线滚动 | `online.py`、regret 评估 | 至少一个场景优于 open-loop |
| W8–9 | RL-0 bandit | `rl/env.py`、策略选择 | 打过固定策略/随机 |
| W10–11 | RL-1 PPO | 代理环境 + shield | 打过 CMA-ES 才算成功 |
| W12 | 整合 + 稳健性 | 30 seeds、压力测试 | 指标有 CI，无数据泄漏 |
| W13–14 | 写作 + Agent guard | 技术报告、3 图、因果 claim guard | 结论与限制清楚 |

### 最小可交付

- 6 周：W1–W7（SCM + 因果 benchmark + 在线滚动）；
- 10 周：+ RL-0；
- 14 周：+ RL-1。

---

## 10. 风险与止损

| 风险 | 概率 | 影响 | 应对 |
|---|---|---|---|
| 真实数据无法因果识别 | 高 | 高 | 只做 SCM 内干预 + 关联/敏感性；不硬编故事 |
| 因果 benchmark 过于 toy | 中 | 中 | 用真实 demand 分布 + DES 结构，报告假设 |
| 在线 MILP 太慢 | 中 | 高 | horizon 缩短、warm start、场景缩减、fallback |
| 在线策略震荡 | 中 | 高 | action regularization、change penalty、smoothing |
| RL 样本效率差 | 高 | 高 | RL-0 bandit 优先；代理模型 + 周期全仿真 |
| RL 打不过 CMA-ES | 高 | 中 | 诚实报告；保留 planner/bandit |
| 因果 + RL 范围过大 | 高 | 高 | 一项主贡献 + 两项支撑；不追 SOTA |
| 数据泄漏/过拟合 | 中 | 高 | 时间切分、预注册、golden test |

---

## 11. 论文/面试叙事

### 标题候选

- *From Correlation to Counterfactuals: A Causal Digital Twin for Online Supply-Chain Optimization*
- *Causal Evaluation of Online Stochastic Inventory Policies*
- *Shielded RL for Supply-Chain Policy Selection: A Reproducible Benchmark*

### 贡献主张

1. **Causal digital twin**：在真实需求分布上构建 SCM，做 `do()` 干预和反事实回放；
2. **Causal estimator benchmark**：已知 ground truth 下比较 IPW/AIPW/DML/CF；
3. **Online stochastic control**：calibrated scenarios + CVaR joint + receding horizon；
4. **Shielded RL**：参数化策略 + 可行性 shield，和 CMA-ES/规则/planner 对比。

不要写“first”“SOTA”；写“reproducible benchmark”“decision-centric evaluation”。

### 简历一句话

> 构建了供应链因果数字孪生与在线 CVaR 决策栈，在已知 ground truth 的仿真中评估因果估计器，并用 shielded RL 做策略选择；量化了 regret、CVaR、OTIF 和 sim-to-holdout 差距。

---

## 12. 不做什么

- 不在真实观测数据上声称因果效应；
- 不做真实世界端到端 RL；
- 不做量子优化、GNN、自己预训练大模型；
- 不做多 Agent swarm；
- 不做没有约束 shield 的 RL；
- 不把“RL 跑通”当成“RL 有效”，必须打过 CMA-ES/规则/planner。

---

## 13. 参考来源

- Pearl, Causality: https://doi.org/10.1017/CBO9780511803161
- Double/debiased ML: https://arxiv.org/abs/1608.00060
- Causal forests: https://arxiv.org/abs/1510.04342
- PPO: https://arxiv.org/abs/1707.06347
- CQL: https://arxiv.org/abs/2006.04779
- IQL: https://arxiv.org/abs/2110.06169
- Conformal: https://arxiv.org/abs/2107.07511
- Decision-focused learning: https://arxiv.org/abs/1703.04529
- 现有项目：`src/supply/e2e/stochastic.py`、`joint.py`、`rolling.py`、`recovery.py`
- V1 蓝图：`FRONTIER_INTEGRATION_BLUEPRINT.md`
- 2026 最新文献与代码落地对照：`FRONTIER_RESEARCH_2026.md`

---

## 14. 最后一句

**因果负责“别骗自己”，随机联合负责“别做错”，在线负责“别僵化”，RL 负责“别停在手工策略”。**

四者都做，但主贡献只选一个：  
如果偏 OR/供应链，主贡献是 **causal evaluation + online stochastic control**；  
如果偏 AI/RL，主贡献是 **shielded RL + causal world model**。

---

## 15. 代码落地状态（2026-11-07）

| 模块 | 文件 | 状态 |
|---|---|---|
| SCM / DAG / do() | `src/supply/causal/scm.py` | 已实现，合成数据 |
| IPW / AIPW / DML | `src/supply/causal/estimators.py` | 已实现，含 CI/overlap 诊断 |
| 因果 benchmark | `src/supply/causal/benchmark.py` | 已实现，已知 ATE 恢复 |
| 校准场景 | `src/supply/e2e/scenarios.py` | bootstrap + Gaussian copula |
| 成本感知随机联合 | `src/supply/e2e/stochastic_joint.py` | 两阶段 CVaR + 成本 |
| 在线策略选择 | `src/supply/e2e/online.py` | UCB/TS/SW-UCB/LinUCB + regret |
| Receding horizon | `src/supply/e2e/online.py` | 通用 planner/simulator 循环 |
| RL-0 + OPE | `src/supply/rl/` | bandit + IPS/DR |
| 一键 smoke benchmark | `scripts/run_frontier_bench.py` | 真实小实例 + 合成因果 |

运行：

```bash
python scripts/run_frontier_bench.py --quick
```

最新文献与“已实现/未实现”的对照见：

- [FRONTIER_RESEARCH_2026.md](FRONTIER_RESEARCH_2026.md)

**边界**：因果是 SCM 内效应；在线/RL 是离线回放；联合优化是小实例 smoke benchmark。
