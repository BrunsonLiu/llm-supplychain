# 一页技术报告：Conformal 风险控制下的两阶段履约决策

版本：v5.9.0　日期：2026-11-15　数据：Online Retail II（UCI）

---

## 1. 问题

一个仓网每周要决定两件事：

- **第一阶段**：每个 SKU 在每个 DC 放多少库存（需求未知）；
- **第二阶段**：需求来了以后怎么分配、缺多少。

企业真正关心的是：

> 要在分布漂移下**保证服务水平**，要付多少成本？

本报告把这个说法变成一个可检验的命题，并给出答案。

---

## 2. 模型

第一阶段（不确定需求前决策）：

```text
z[k,d] ∈ Z+         SKU k 在 DC d 的布点
s[k]   ∈ Z+          SKU k 的总库存（可设上限）
cap[d] ∈ Z+         DC d 的周产能（可扩张）
```

第二阶段（每个场景 s）：

```text
y[s,k,d] ≤ z[k,d]          只能从已布点发货
y[s,k,d] ≤ serviceable[s,k,d]  时效/可服务性约束
Σ_d y[s,k,d] + u[s,k] = D[s,k]  缺货变量
Σ_k y[s,k,d] ≤ cap[d]          产能约束
```

目标：期望成本 + CVaR，成本 = handling + holding × 库存 + shortage × 缺货。

风险约束（本报告核心）：

```text
CVaR_alpha( Σ_k u[s,k] ) ≤ cap_risk
```

`cap_risk` 不是拍的，而是**在 held-out 场景上做 split-conformal 校准**得到的：

1. 用校准集上的固定布点算出每个场景的未满足量；
2. 取 conformal 上分位（`ceil((n+1)(1-δ))/n`）；
3. 得到 `cap_risk`。

这是**场景级**的 conformal 校准，不是 Conformal-DRO ambiguity set，也不是对下游策略的有限样本保证——这一点必须先说清楚。

---

## 3. 四张表

### 表 1：conformal 校准本身

| 目标 | 经验覆盖 | 平均宽度 |
|---|---:|---:|
| 90% | 88.0% | 11,022.7 |
| 90%（ACI 在线） | 92.3% | 6,813.4 |

静态 split-conformal 略保守（88% < 90%），ACI 把长期覆盖拉回 92.3%，宽度小 38%。

### 表 2：固定库存下，风险 cap 无法满足

| 指标 | 数值 |
|---|---:|
| conformal cap | 1,431.0 |
| 无约束 CVaR(unmet) | 1,483.7 |
| 固定库存下最小可行 floor | 1,485.0 |
| 缺口 | **+54.0** |

### 表 3：三种杠杆，只有一个有效

| 杠杆 | 可达到的最小 CVaR(unmet) | 结论 |
|---|---:|---|
| 无杠杆 | 1,485.0 | 不可行 |
| 加库存 | **23.2** | 可行 |
| 加产能（2×） | 1,485.0 | 无效 |
| 提速（1400 km/day） | 1,485.0 | 无效 |

这个网络不是吞吐受限，也不是时效受限，唯一有效杠杆是库存。

### 表 4：稳健性溢价 —— 30 seed

固定 shortage = 2.0：

| holding | 溢价均值 | 标准差 | 为正的 seed 占比 |
|---:|---:|---:|---:|
| 0.05 | 0.00 | 0.00 | 0% |
| 0.25 | 0.00 | 0.00 | 0% |
| 1.00 | 0.24 | 0.67 | 47% |
| 2.00 | 37.34 | 21.23 | **100%** |
| 4.00 | 143.68 | 64.03 | **100%** |

### 表 5：跨 9 个网络，门槛跟着 shortage 走

| 网络变体 | shortage | onset holding |
|---|---:|---:|
| base / tight / loose / few_skus / small / large / mid_pop | 2.0 | **2.0**（全部） |
| shortage_1 | 1.0 | **1.0** |
| shortage_4 | 4.0 | **4.0** |

`onset` = 最便宜的、在 ≥80% seed 上产生正溢价的 holding。

---

## 4. 三条结论

**结论 1：conformal 风险 cap 在固定库存下通常不可行。**
不是求解器问题，是物理问题：库存总量不能动时，未满足量有下界（本例 1,485 > 1,431）。

**结论 2：能动的杠杆只有库存。**
产能和时效在这个网络上完全不影响 CVaR(unmet)，说明真正的约束是「货放在哪」，不是「能处理多少」或「送多快」。

**结论 3：服务保证贵不贵，由成本比决定，不是网络结构决定。**

```text
溢价 > 0  ⟺  holding_cost > shortage_cost
```

9 个网络、3 个 shortage 水平、每个 10 seed：onset 恰好等于 shortage_cost。
机理是一行比较：多备一单位花 `holding`，少缺一单位省 `shortage`。所以 `h < s` 时无约束最优解本来就满足 cap，溢价恒为 0。

**推论**：conformal 风险控制的价值不在于「更聪明的算法」，而在于**把服务水平写成可校验的约束**；它什么时候付钱，由单位经济学决定，不由模型新颖度决定。

---

## 5. 四条限制

1. **场景级校准，不是策略级保证。** cap 是在固定布点上校准的，不构成对优化后策略的有限样本保证；真正的 Conformal-DRO 未实现。
2. **小样本。** 单数据集、单实例、每 seed 仅 6 个场景；6 个场景时 CVaR 近似 worst-case，cap 估计很噪。
3. **门槛结论依赖建模选择。** 「库存可自由调整 + 缺货按单位计罚」是前提；阶梯罚金、合约约束、产能锁定都可能移动门槛。
4. **单次实验会骗人。** 同一实验单次抽样得到的溢价是 30-seed 均值的 2–3 倍（h=2：105.5 vs 37.3；h=4：321.5 vs 143.7）。这类结论必须重复抽样。

---

## 6. 复现

```bash
python scripts/run_frontier_bench.py --quick --lever-seeds 30 --cross-instances 10
```

产物：

- `benchmarks/frontier/joint_conformal.json`：cap 校准 + 约束前后对比
- `benchmarks/frontier/levers.json`：杠杆 floor 对比 + 价格前沿
- `benchmarks/frontier/levers_seeds.json`：30 seed 溢价
- `benchmarks/frontier/instances.json`：9 网络 × 10 seed onset

测试：385 个通过。
