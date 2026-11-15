# 四项前沿：2026 最新文献与代码落地对照

日期：2026-11-07  
范围：因果建模、随机联合优化、在线优化、强化学习  
原则：只写能追溯到论文/官方页面的内容；代码落地与“计划中”分开标注。

---

## 0. 一句话结论

四件事都已经有可运行的最小实现，但**只有前两件达到“可写研究贡献”的雏形**：

- 因果：SCM + AIPW/DML benchmark，能诚实评估估计器，但还不是 sequential DR；
- 随机联合：校准场景 + 成本感知 CVaR 两阶段模型，能跑真实小实例，但还不是 Conformal-DRO；
- 在线：通用 receding-horizon 接口 + bandit 策略选择回放，能测 regret，但不是 GAPSI/ICGPS；
- RL：RL-0 bandit + OPE，能学策略选择，但不是 deep RL / offline RL。

这个定位比“都做了”更可信。

---

## 1. 因果建模

### 1.1 最新前沿

- **Doubly Robust Causal Digital Twins**（arXiv:2610.31706，2026-10）  
  把数字孪生的反事实均值拆成“数据支持的部分”和“不支持的部分”：支持部分用 cross-fitted sequential doubly robust 估计，不支持部分给出与机制残差相容的界。核心不是“再拟合一个模型”，而是**把数据支持和机制假设分开**。

- **Double/debiased ML**（arXiv:1608.00060）  
  部分线性模型 + cross-fitting，是当前因果 ML 的标准基线之一。

- **Causal forests**（arXiv:1510.04342）  
  异质处理效应（CATE）的经典方法；适合回答“对哪类 SKU/区域更有效”，而不是只看 ATE。

### 1.2 本项目落地

代码：

- `src/supply/causal/scm.py`：显式 DAG + 结构方程 + `do()` 干预 + 已知 ATE；
- `src/supply/causal/estimators.py`：naive / IPW / AIPW / 两折 DML；
- `src/supply/causal/benchmark.py`：混杂数据生成 + bias/RMSE/CI coverage；
- `tests/test_causal.py`：DAG 环检测、可复现、naive 偏差、AIPW/DML 恢复真值。

已做到的：

- 能证明 naive 在混杂下偏、AIPW/DML 更接近真值；
- 有 propensity overlap、CI coverage 诊断；
- 明确声明：真实 UCI 数据没有干预，不能做真实因果结论。

还没做：

- sequential DR / 多期策略的 supported/unsupported 分解；
- causal forest/CATE 的正式实现；
- 真实 A/B 的 power analysis（目前只有设计文档）。

**下一步**：把 2610.31706 的“支持集 + 残差界”思想移植到单期 SCM，作为敏感性分析；不要硬做真实数据因果。

---

## 2. 随机联合优化

### 2.1 最新前沿

- **Conformal-DRO**（arXiv:2609.11073，2026-09）  
  用 nested conformal regions 构造未来潜在分布的 ambiguity set；在可交换性下，集合以至少 `1-alpha` 概率覆盖未来分布；最坏情况问题化为有限 LP，并给 selected decision 的期望成本一个有限样本证书。

- **Conformal Robustness in Prediction-Driven Decision-Making**（arXiv:2609.23170，2026-09）  
  讨论预测驱动决策下 conformal 不确定性的稳健性，适合连接到“预测误差 → 决策损失”。

- **Adaptive Conformal Inference**（arXiv:2106.00170）  
  用 `alpha_{t+1} = alpha_t + gamma (alpha - err_t)` 做在线覆盖反馈，适合分布漂移；本项目用它把静态 conformal 升级成 ACI。

- **Conformal PID Control**（arXiv:2307.16895）  
  把 conformal 校准看成控制问题，用 PID 思想调覆盖率；是 ACI 之后更激进的在线校准路线。

### 2.2 本项目落地

代码：

- `src/supply/forecasting/conformal.py`：split/Mondrian conformal 区间、经验覆盖评估、在线自适应 conformal（ACI）；
- `src/supply/e2e/scenarios.py`：bootstrap / Gaussian copula / conformal 场景生成，输出兼容现有 `ScenarioSet`；
- `src/supply/e2e/stochastic_joint.py`：第一阶段布点 + 第二阶段分配 + handling/shortage/holding 成本 + CVaR；
- `tests/test_conformal.py`、`tests/test_scenarios.py`、`tests/test_stochastic_joint.py`：覆盖、形状、权重、库存守恒、目标一致性；
- 真实小实例已跑通（`benchmarks/frontier/`）。

已做到的：

- 场景从“过去 6 周等权”升级为可配置的 bootstrap/copula；
- 真实回测预测上的 split/Mondrian conformal 校准，90% 目标经验覆盖约 88.0%（horizon 13）；
- 在线自适应 conformal（ACI）：长期覆盖约 92.3%，平均宽度 6,813.4，低于静态版本的 11,022.7；
- `build_conformal_scenarios` 把 conformal 区间接进场景，再跑 CVaR 联合；
- 新增 conformal 风险 cap：在 held-out 场景上校准 `CVaR_alpha(unmet)` 的 cap；当前小实例上 cap=1431，而无约束 CVaR unmet=1483.67；
- 固定库存总量时 cap 不可行（floor 1485 > cap 1431）；把库存总量变成第一阶段变量后 cap 可行（floor 23.2），见下表；
- 早期版本把库存上限写成「现有库存 × 3」，对需求集中的 SKU 不够，曾误判 cap 不可行；已改为「按峰值需求给上限」，本页数字为修正后版本；

### conformal 风险约束的杠杆对比（v5.6）

对同一个 conformal cap（1431），用二分法找每个杠杆能实际达到的最小 `CVaR_alpha(unmet)`（floor）：

| 杠杆 | floor | 相对 cap 的缺口 | 结论 |
|---|---:|---:|---|
| 无杠杆（固定库存/产能） | 1485.0 | +54.0 | 物理上无法满足 |
| 只加库存（上限 3× 峰值需求） | 23.2 | -1407.8 | cap 变得可行 |
| 只加产能（2×，0.5/单位） | 1485.0 | +54.0 | 完全无效 |
| 库存 + 产能 | 23.2 | -1407.8 | 与只加库存相同 |
| 只提速（1400 km/day，0 天处理） | 1485.0 | +54.0 | 完全无效 |

结论：这个小实例里网络**不是**吞吐或时效受限，唯一有效的杠杆是库存。产能/时效无效是负面结果，不是失败。

### 稳健性溢价前沿（同一个 cap，库存杠杆）

固定 `shortage_cost=2.0`，扫 holding cost。**单次实验**（1 个场景抽样）：

| holding | 无 cap 成本 | 满足 cap 成本 | 溢价 |
|---:|---:|---:|---:|
| 0.05 | 230.0 | 230.0 | 0.00 |
| 0.25 | 970.4 | 970.4 | 0.00 |
| 1.00 | 3020.1 | 3020.9 | 0.86 |
| 2.00 | 3081.5 | 3186.9 | 105.47 |
| 4.00 | 3197.5 | 3518.9 | 321.47 |

### 30-seed 重复实验（推翻单次数字）

每个 seed 独立抽 conformal 场景，并在另一批 held-out 场景上校准 cap：

| holding | 溢价均值 | 标准差 | 最小 | 最大 | 30 个 seed 中为正 |
|---:|---:|---:|---:|---:|---:|
| 0.05 | 0.00 | 0.00 | 0.00 | 0.00 | 0% |
| 0.25 | 0.00 | 0.00 | 0.00 | 0.00 | 0% |
| 1.00 | 0.24 | 0.67 | 0.00 | 3.55 | 47% |
| 2.00 | 37.34 | 21.23 | 0.72 | 92.60 | 100% |
| 4.00 | 143.68 | 64.03 | 52.34 | 308.60 | 100% |

结论（只写有证据的部分）：

- 单次实验把溢价放大了约 2–3 倍：h=2 从 105.47 降到 37.34，h=4 从 321.47 降到 143.68；
- 但**方向是稳的**：holding 便宜（0.05/0.25）时 30 个 seed 全部为 0，服务保证免费；
- holding ≥ 2.0 时 30 个 seed 全部为正（100%），溢价真实存在；
- h=1.0 只有 47% 为正，**和 0 无法区分**；所以转折点在 1.0 与 2.0 之间，不是之前说的「在 holding≈1 处跳变」；
- 溢价不是免费的：h=4 时中位数感受约为 144，最高到 309。

限制：单实例；每个 seed 只有 6 个场景，CVaR 近似 worst-case；30 seed 只说明「跨场景抽样」稳健，不说明跨实例稳健。

### 跨实例：门槛是成本比，不是网络结构（v5.9）

9 个网络变体（SKU 组合、订单量、库存松紧、长尾 SKU、短缺成本），每个 10 seed，预测不确定性固定为 ±35%：

| 实例 | shortage | onset holding | h=1 溢价/正例率 | h=2 | h=4 | h=8 |
|---|---:|---:|---:|---:|---:|---:|
| base | 2.0 | **2.0** | 0.0 / 10% | 23.5 / 100% | 2038 / 100% | 6068 / 100% |
| tight_stock | 2.0 | **2.0** | 0.0 / 20% | 18.7 / 100% | 1790 / 100% | 5334 / 100% |
| loose_stock | 2.0 | **2.0** | 0.0 / 0% | 26.3 / 100% | 2182 / 100% | 6492 / 100% |
| few_skus | 2.0 | **2.0** | 0.0 / 0% | 29.1 / 100% | 2359 / 100% | 7017 / 100% |
| small_orders | 2.0 | **2.0** | 0.0 / 0% | 7.6 / 100% | 720 / 100% | 2144 / 100% |
| large_orders | 2.0 | **2.0** | 0.0 / 0% | 40.6 / 100% | 3408 / 100% | 10143 / 100% |
| mid_popularity | 2.0 | **2.0** | 0.0 / 0% | 5.5 / 100% | 509 / 100% | 1516 / 100% |
| shortage_1 | 1.0 | **1.0** | 23.5 / 100% | 1031 / 100% | 3046 / 100% | 7075 / 100% |
| shortage_4 | 4.0 | **4.0** | 0.0 / 0% | 0.0 / 0% | 23.5 / 100% | 4053 / 100% |

`onset holding` = 最便宜的、在 ≥80% seed 上产生正溢价的 holding。

结论：

- **onset 恰好等于 shortage_cost**（1.0→1.0，2.0→2.0，4.0→4.0），7 个网络变体全部落在 2.0；
- 机理是一行成本比较：多备一单位花 holding，少缺一单位省 shortage，所以 h<s 时无约束最优解本来就满足 cap，溢价恒为 0；h>s 时 cap 才真正约束；
- 所以 conformal 服务保证的「贵不贵」是**成本比问题**，不是 assortment / 订单量 / 库存松紧的问题；
- 溢价幅度确实随网络规模变（large_orders 在 h=8 是 10143，small_orders 只有 2144），但门槛不变。

限制：仍是 9 个小实例、每个 6 个场景、单一数据集（Online Retail II）；门槛等于 shortage 的结论依赖「库存可自由调整 + 缺货按单位计罚」这一建模选择，真实的阶梯罚金/合约约束可能移动门槛。
- 成本感知的两阶段 CVaR 联合模型；
- 与现有 `stochastic.py`/`joint.py` 兼容，没有破坏旧测试。

还没做：

- 真正的 Conformal-DRO：ambiguity set 的有限样本证书、最坏情况 LP；
- 校准覆盖率与决策成本之间的显式 frontier；
- 场景相关性的正式统计检验。

**下一步**：把 interval 只当“采样截断”升级成 conformal ambiguity radius；在联合模型里加“最坏场景”约束，形成 Conformal-DRO 的简化版。

---

## 3. 在线优化

### 3.1 最新前沿

- **Online Policy Selection for Inventory Problems**（arXiv:2411.19269）  
  GAPSI：feature-enhanced base-stock policy，处理 inventory 中的不可微问题；面向多产品、lost sales、易腐、仓容、lead time。

- **Thompson Sampling for Repeated Newsvendor**（arXiv:2502.09900，v2 2026-01）  
  在 censored feedback 下分析 TS 的 frequentist/Bayesian regret；说明 TS 如何在“订货量足够大以解除 censoring”和“主动增加订货量获取信息”之间权衡。

- **In-Context Learning for Data-Driven Censored Inventory Control**（arXiv:2605.14840，2026-05）  
  ICGPS：用离线元训练的生成模型 + in-context 后验采样；把 censored feedback 归约到 bandit convex optimization，给出 Bayesian regret 界。

- **OR-Transformer**（arXiv:2609.01933，2026-09）  
  面向 1,024 个 item 的联合补货，item-permutation-equivariant Transformer + pathwise gradient；在线决策比 rolling-horizon MILP 快 4M 倍以上（论文报告）。

### 3.2 本项目落地

代码：

- `src/supply/e2e/online.py`：
  - `run_online_bandit`：UCB/Thompson/epsilon-greedy/SW-UCB/LinUCB 的策略选择；
  - `run_receding_horizon`：通用 planner → simulator → feedback 循环，支持 hindsight oracle 和 regret；
  - `evaluate_rolling_policies`：把现有 `run_rolling_policy` 接进回放。
- `src/supply/rl/bandit.py`：无依赖 bandit 实现；
- `scripts/run_frontier_bench.py`：真实小实例上的按订单日/多实例回放。

已做到的：

- 有 regret、switch count、policy matrix；
- 有非平稳版本 SW-UCB；
- 在线“回放”而非实时上线，明确标注。

还没做：

- GAPSI / ICGPS 级别的 inventory-specific online learner；
- censored demand 的显式处理；
- 真正的 receding-horizon MILP 在每个订单日滚动（当前 `run_rolling_policy` 是日级重解，但策略固定）。

**下一步**：把 `run_receding_horizon` 接到日级 `stochastic_joint`，每步只执行第一天；用真实订单日做 feedback。

---

## 4. 强化学习

### 4.1 最新前沿

- **Offline Dynamic Inventory and Pricing Strategy**（arXiv:2504.09831，v2 2026-03）  
  处理 censored + dependent demand 的离线序贯定价/库存；用高阶 MDP + 专门 Bellman 方程，属于 offline RL / survival analysis 交叉。

- **OR-Transformer**（arXiv:2609.01933）  
  大规模联合补货的 deep RL，说明 RL 在“高维、相关需求、共享固定订货成本”下的前沿形态。

- **CQL / IQL**（arXiv:2006.04779 / arXiv:2110.06169）  
  离线 RL 的两个常用基线；适合有大量仿真轨迹、但没有安全在线探索的场景。

### 4.2 本项目落地

代码：

- `src/supply/rl/bandit.py`：RL-0 策略选择；
- `src/supply/rl/ope.py`：IPS / doubly robust off-policy evaluation；
- `tests/test_online_rl.py`：bandit 收敛、LinUCB、OPE 恢复目标策略价值、receding horizon。

已做到的：

- RL-0 可运行、可解释、可回退；
- OPE 能把 logged data 转成策略价值估计；
- 没有 deep RL 依赖，不会拖垮 CI。

还没做：

- FQE/CQL/IQL 的正式实现；
- 参数化 PPO + surrogate + action shield；
- 真实离线数据（没有 action/propensity，不能做真实 offline RL）。

**下一步**：用 `stochastic_joint` 仿真器生成 `(s,a,r,s')`，先做 FQE，再做 CQL/IQL；不要直接上 PPO。

---

## 5. 最新前沿 vs 本项目：一页表

| 方向 | 最新代表 | 本项目状态 | 差距 |
|---|---|---|---|
| 因果 | Doubly Robust Causal Twins 2610.31706 | SCM + AIPW/DML benchmark | 无 sequential DR / 支持集界 |
| Conformal | ACI 2106.00170 / Conformal-DRO 2609.11073 | 静态 split/Mondrian + ACI 在线校准 | 无 conformal ambiguity set / DRO |
| 随机联合 | Conformal-DRO 2609.11073 | conformal 场景 + 成本感知 CVaR 联合 | 无 conformal ambiguity set / 有限样本证书 |
| 在线 | GAPSI 2411.19269 / ICGPS 2605.14840 | bandit 策略选择 + receding-horizon 接口 | 无 inventory-specific learner |
| RL | Offline inventory 2504.09831 / OR-Transformer 2609.01933 | RL-0 bandit + OPE | 无 FQE/CQL/IQL / deep RL |

### 5.1 当前 smoke 结果（不是研究结论）

`python scripts/run_frontier_bench.py --quick` 生成 `benchmarks/frontier/`：

| 阶段 | 结果 | 说明 |
|---|---|---|
| 因果 SCM | true ATE 0.1484；DML 平均绝对偏差 0.0071 | 合成数据，3 次重复 |
| Conformal 静态 | 90% 目标；经验覆盖 88.0%；平均宽度 11,022.7 | 真实回测，horizon 13，单目标周 |
| Conformal ACI | 长期覆盖 92.3%；平均宽度 6,813.4 | 只有 3 个可评估周，初步结果 |
| 场景 | 6 场景 × 11 SKU；目标 1,522 单位 | 真实小实例 |
| 随机联合 | status OPTIMAL；期望成本 2,200.09；CVaR 2,397.43；gap 0 | 单实例，非 30-seed |
| Conformal 联合 | status OPTIMAL；期望成本 4,942.79；CVaR 5,948.40 | 单实例；区间更保守，成本更高 |
| Conformal risk cap | cap 1,431；固定库存 floor 1,485（不可行）；可调库存 floor 23.2（可行，成本 81.89） | 成本按 holding=0.01 计，见溢价前沿 |
| 在线 UCB1 | 10 轮累计 reward 8.638；hindsight regret 0.561 | 2 个 seed × 5 订单日，离线回放 |
| RL-0 LinUCB | 10 轮累计 reward 8.088；regret 1.111 | 样本太少，不能证明优于 UCB |

这些数字只用于确认链路能跑通，不是论文级结果。

---

## 6. 诚实边界

- **因果**：SCM 内效应，不是 UCI 真实因果；没有随机化就不能声称策略因果。
- **随机联合**：CVaR 场景模型，不是 Conformal-DRO；没有有限样本证书。
- **在线**：回放，不是线上 A/B；策略在一周内固定。
- **RL**：RL-0 策略选择，不是端到端 deep RL；没有真实 action log。

这四条边界应该写进 README/论文 limitations，而不是藏起来。

---

## 7. 参考

- 2610.31706: https://arxiv.org/abs/2610.31706
- 1608.00060: https://arxiv.org/abs/1608.00060
- 1510.04342: https://arxiv.org/abs/1510.04342
- 2609.11073: https://arxiv.org/abs/2609.11073
- 2609.23170: https://arxiv.org/abs/2609.23170
- 2411.19269: https://arxiv.org/abs/2411.19269
- 2502.09900: https://arxiv.org/abs/2502.09900
- 2605.14840: https://arxiv.org/abs/2605.14840
- 2609.01933: https://arxiv.org/abs/2609.01933
- 2504.09831: https://arxiv.org/abs/2504.09831
- ACI: https://arxiv.org/abs/2106.00170
- Conformal PID: https://arxiv.org/abs/2307.16895
- Beyond exchangeability: https://arxiv.org/abs/2202.13415
- CQL: https://arxiv.org/abs/2006.04779
- IQL: https://arxiv.org/abs/2110.06169
