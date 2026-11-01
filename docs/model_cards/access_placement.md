# 库存布点 MILP：变量、约束、结果与效度

Week 41 的模型卡片。它回答 Week 40 留下的问题：固定总量下，**用优化器选 DC 布点**能否比四个手选占比更好。

## 1. 问题设定

- 实例：`2011-11-28` 周 400 张真实发票、2,477 行、33,060 units、189 SKU、3 个 DC。
- 固定：每个 SKU 的总库存 = 100% 需求（Week45 另跑 125%/135%/140%/150% 情景）；DC 2× 周产能；transit −1 天；ATP accept-all；Week41–43 为 1 拣货员/DC，Week44 交互臂为 2 人；30 个到达种子。
- 决策：每个 SKU 在每个 DC 放多少库存 `y[d,s]`；等价于周前 DC→DC 调拨。
- 不建模：采购、在途、调拨前置期/费用、仓储/持有成本、COGS、退货、过期。

## 2. 需求侧

`demand[d,s]` 是 **需求的一个分区**，不是“每个 DC 都能服务的需求之和”：

- `access_oracle`：本周每条订单行分配给 **最佳准点 DC**（transit 最小、ship cost 次之）。这是 oracle，不能周前执行。
- `access_history`：前 6 周 `country × SKU` 数量，按当前周每个国家的准点份额选一个最佳 DC。数量是历史，但可达性仍用当前 destination/transit 矩阵，因此是半可部署估计。

早期版本把每条线同时计入所有可达 DC，结果在 100% 总量下覆盖率目标被当前布点“免费满足”，MILP 从不移动库存；改为分区后才产生非零调拨。

## 3. MILP

```
max   Σ_{d,s} z[d,s]
s.t.  Σ_d y[d,s] = stock_total[s]          ∀s
      z[d,s] ≤ y[d,s]                      ∀d,s
      z[d,s] ≤ round(demand[d,s])          ∀d,s
      min_share·T ≤ Σ_s y[d,s] ≤ max_share·T   ∀d
      y[d,s], z[d,s] ∈ Z≥0
```

- 主目标最大化“被库存覆盖的可达需求”。
- 次级项 `−Σ|y−current|` 让并列解不产生任意调拨；系数 1,000,000 远大于最大可能移动量。
- `min_share=10%`、`max_share=60%` 防止覆盖目标把几乎全部库存堆到一个 DC（早期 96/1/3 的解在拣选层没有意义）。
- 单线程、固定 seed、10s 上限；三次重复用于观察求解器/到达噪声。

**复杂度**：变量 `O(D·S)`，约束 `O(D·S + D + S)`；每个 SKU 是独立的覆盖子问题，CP-SAT 在 3 DC × 189 SKU 上 10s 内 `OPTIMAL`。

## 4. 结果（400 单 / 30 种子 / 3 次重复）

| policy | target OTIF | rest OTIF | all OTIF | backlog | fill | avg day | coverage | moved units |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline 34/28/38 | **97.5%** | **99.3%** | **99.1%** | 142 | 99.6% | 3.54 | — | 0 |
| access_history | 96.7% | 99.5% | 99.2% | 392 | 98.8% | 3.46 | 44.9% | 9,212 |
| access_oracle | 97.5% | 97.7% | 97.7% | 196 | 99.4% | 3.45 | 63.1% | 8,222 |

三次重复的 target 范围：

- baseline：97.5%
- access_history：95.0–97.5%
- access_oracle：97.5–97.5%

## 5. 结论

1. **没有稳健的端到端收益。** 历史需求版均值 −0.8pp（范围 95.0–97.5），低于 baseline；oracle 目标持平（97.5%）。两者差异都在 5pp 求解器/到达噪声附近。
2. **没有 Pareto 改进。** oracle 目标持平，但 rest −1.6pp、全量 −1.4pp；history 全量 +0.1pp，但 target −0.8pp、积压 392（baseline 142）。两者都至少输一个指标。
3. **覆盖代理与 OTIF 不对齐。** MILP 只最大化静态可达需求，看不到拣选队列、到达形状、DC 峰值负荷；把 60% 库存放到一个 DC 可能制造拣选瓶颈。历史版 coverage 只有 44.9%，oracle 63.1%，但 coverage 更高不等于 OTIF 更高。
4. **手选 baseline 在 target 持平下仍有更好的全量。** 这与 Week 40 的 null 一致：固定总量下，布点不是主要杠杆；Week39 的 150% 总量才是唯一把目标做到 100% 的臂。
5. **oracle 的 97.5% 不是策略上界**，只是“本周订单已知”的一个参照；不能把它写成可部署收益。

## 5b. 负荷 cap 扩展（Week 42）

Week41 的 coverage 代理看不到“库存停在哪会压垮哪个 DC 的拣选”。Week42 加一个 stock-implied 拣选分钟 cap：

```
L[d] = Σ_s y[d,s] · c
L[d] ≤ capacity[d] + overload[d]
max coverage − penalty · Σ_d overload[d] − moves
```

`c = 0.052` 分钟/件（订单行 0.35 + 件 0.02 + 发货 0.5 的加权总分钟 / 总件数），`capacity = 1 拣货员 × 600 分钟`，超载用 `10,000,000 / 0.001 min` 的软惩罚。

| 策略 | 目标 OTIF | 非目标 | 全量 | 积压 | 覆盖率 | 峰值拣选 |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 96.7% | 99.0% | 98.7% | 168 | — | — |
| history | 96.7% | 99.4% | 99.2% | 263 | 44.9% | — |
| history + load | 95.0% | 99.3% | 98.8% | 116 | 26.1% | 600 min |
| oracle | 96.7% | 97.9% | 97.8% | 172 | 63.1% | — |
| oracle + load | 95.8% | 98.2% | 98.0% | 149 | 37.7% | 600 min |

结论：

- cap **确实生效**：load 臂把 DC 占比拉到 35/30/35，峰值 600 min、软超载 0。
- 但它是 **目标 ↔ 积压 trade-off**，不是 Pareto 改进：history 目标 −1.7pp、覆盖率 44.9%→26.1%，积压 263→116；oracle 目标 −0.8pp、覆盖率 63.1%→37.7%，积压 172→149。
- `history` 的 target/rest/all 均值看似 Pareto，但 target 范围 95.0–97.5 与 baseline 重叠、积压 263 vs 168，不能称稳健收益。
- `L[d]` 仍是 placement proxy，不是真实队列；600 min 是声明容量，不建模到达顺序/波次释放。

完整报告：[`benchmarks/ACCESS_LOAD_REPORT.md`](../../benchmarks/ACCESS_LOAD_REPORT.md)。

## 5c. covered 负荷（Week 43）

Week42 的 stock-implied cap 把“停在 DC 的库存”全部算作拣选工作，历史臂因此丢掉 1.7pp target。Week43 把负荷改成只按该 DC **实际覆盖的需求**：

```
L[d] = Σ_s z[d,s] · c
```

其余同 Week42：`c=0.052 min/件`、`600 min/DC`、软超载惩罚。新增 `access_history_load_covered` / `access_oracle_load_covered`。

| 策略 | 目标 OTIF | 非目标 | 全量 | 积压 | 覆盖率 | 峰值拣选 | 调拨 |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 96.7% | 99.1% | 98.8% | 153 | — | — | 0 |
| history | 97.5% | 99.0% | 98.8% | 307 | 44.9% | — | 9,212 |
| history + covered | 96.7% | 99.2% | 98.9% | 148 | 26.1% | 600 min | 383 |
| oracle | 96.7% | 97.4% | 97.3% | 180 | 63.1% | — | 8,222 |
| oracle + covered | 97.5% | 98.9% | 98.7% | 131 | 37.7% | 600 min | 0 |

结论：

- covered cap 也真的生效（峰值 600 min、超载 0），但只调拨 383 单位（history 原版 9,212，Week42 stock cap 1,179）；target 回到 96.7%，不再像 Week42 那样掉到 95.0%。
- `history + covered` 对 baseline 是 Pareto-looking：target 持平、rest +0.1pp、all +0.1pp、积压 153→148；但 target 范围 95.0–97.5 与 baseline 重叠，收益小于 5pp 噪声，不能称稳健收益。
- `oracle + covered` 修好 oracle 自己（target +0.8pp、all +1.4pp、积压 180→131），但仍低于 baseline 的 rest/all；fixed-total 布点仍不是主杠杆。
- **负荷 basis 比 cap 数值更关键。** 下一步应接真实波次/到达队列；继续调 600 min 只会改变代理内部的分配。
- **配对检验（90 对 `(repeat, seed)`）：** `history + covered` 的 target 差值恰好 **0.00pp**，全量 **+0.08pp ±0.06**，积压 **−5.3 ±1.7**；`history` 原版 target +0.83pp，但全量 0.00、积压 +153.7。covered 的改善统计上可测，但约等于 400 单里 0.3 单，运营上可忽略。

完整报告：[`benchmarks/ACCESS_LOAD_COVERED_REPORT.md`](../../benchmarks/ACCESS_LOAD_COVERED_REPORT.md)。

## 5d. 两拣货员容量交互（Week 44）

Week43 的 covered 效应只有 +0.08pp，一个可能是“拣货产能不足，布点效应被排队吃掉”。Week44 保持同一 covered 布点，把每 DC 拣货员从 1 人加到 2 人（其余 400 单 × 30 种子 × 3 重复不变）。

| 策略（2 拣货员/DC） | 目标 OTIF | 非目标 | 全量 | 积压 | 覆盖率 | 峰值拣选 |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 97.5% | 99.2% | 99.0% | 313 | — | — |
| history | 95.8% | 98.4% | 98.2% | 474 | 44.9% | — |
| history + covered | 97.5% | 99.1% | 98.9% | 138 | 26.1% | 600 min |
| oracle | 97.5% | 97.5% | 97.5% | 242 | 63.1% | — |
| oracle + covered | 96.7% | 99.1% | 98.8% | 154 | 37.7% | 600 min |

结论：

- **加第二个拣货员没有制造 covered 优势。** covered history target 与 baseline 持平 97.5%，但 all 98.9% vs 99.0%、rest 99.1% vs 99.2%；积压 138 vs 313 主要来自 baseline 第 3 次重复的 688 单位尾部，不是稳定收益。
- **配对检验不支持容量交互。** 90 对 `(repeat, seed)`：covered history Δtarget **0.00pp**、Δall **−0.08pp ±0.06**、Δbacklog **−175 ±58**；target 没升、全量略降。
- **1→2 人对 baseline 也只是噪声级变化**：target 96.7%→97.5%、all 98.8%→99.0%、backlog 153→313，方向不一致；不能把加人写成稳健杠杆。
- 线性拣选分钟代理仍不是真实波次/到达队列；结论是“这个代理下容量不是缺失机制”，不是“真实仓库加人无效”。

完整报告：[`benchmarks/ACCESS_LOAD_COVERED_P2_REPORT.md`](../../benchmarks/ACCESS_LOAD_COVERED_P2_REPORT.md)。

## 5e. 库存总量服务前沿（Week 45）

Week41–44 的布点/负荷/加人效应都在 0.1–0.2pp 量级。Week45 固定同一批订单与布点臂，只把每 SKU 总库存从 100% 需求提到 125%/135%/140%/150%，检验服务是被布点还是被总量约束。

**baseline 布点（34/28/38）的前沿：**

| 总库存 | 库存单位 | 目标 OTIF | 全量 OTIF | 积压 |
|---:|---:|---:|---:|---:|
| 100% | 33,060 | 96.7% | 98.8% | 153 |
| 125% | 41,323 | 96.7% | 99.1% | 38 |
| 135% | 44,635 | 99.2% | 99.8% | 1.7 |
| 140% | 46,281 | 100.0% | 99.9% | 0.7 |
| 150% | 49,595 | 100.0% | 99.9% | 0.7 |

结论：

- **+25% 库存主要买积压，不买目标服务**：全量 +0.25pp、积压 153→38，但 target 仍 96.7%，说明 Top10 目标的迟到不是总量不够，而是尾段/到达/拣选时机。
- **140% 是首个达到 ~100% target 的网格点**：135% 时 target 99.2%/all 99.8%，140% 时 100%/99.9%，150% 不再增加；这是网格边界，不是插值最小值。
- **边际收益迅速递减**：100→125% 约 72 单位库存/积压单位，125→135% 约 90，135→140% 约 1,646，140→150% 为 0。库存总量是主杠杆，但不是线性杠杆。
- **布点在 125%–140% 下仍无稳定贡献**：125% 时 covered history target 96.7%/all 99.25%、baseline 96.7%/99.08%；135% 时 covered target 100% 但 all 99.6% 低于 baseline 99.8%，积压 5.0 vs 1.7；140% 时 covered 与 baseline 持平。
- **不是“多备货就对了”**：未建模采购/持有/跌价/资金成本；150% 只是服务上界情景，不是成本最优库存策略。
- **库存是 oracle 上界**：库存量乘的是目标周实际需求；Week49 历史均值 140% 只有 target 70%，加到 200% 也只到 82.5%。本节的绝对服务应读作“SKU 结构已正确”的上界。

完整报告：[`benchmarks/ACCESS_STOCK_FRONTIER_REPORT.md`](../../benchmarks/ACCESS_STOCK_FRONTIER_REPORT.md)。

## 5f. 库存-成本决策（Week 46）

Week45 只给服务量纲。Week46 把前沿转成 `total cost = h × stock + p × backlog`，其中 `h=€0.10/unit-week` 是示例持有成本，`p = ratio × h` 是每单位积压的缺货惩罚。**不新增仿真，只做成本决策层。**

| 相邻档位 | 新增库存 | 积压减少 | break-even `p/h` |
|---|---:|---:|---:|
| 100% → 125% | +8,263 | 115.0 | **71.9** |
| 125% → 135% | +3,312 | 36.7 | **90.3** |
| 135% → 140% | +1,646 | 1.0 | **1,646.0** |
| 140% → 150% | +3,314 | 0.0 | 被 140% 支配 |

在本网格内：

- `p/h < 71.9` → 100%
- `71.9–90.3` → 125%
- `90.3–1,646` → 135%
- `> 1,646` → 140%
- 150% 永远不会最优（服务与 140% 相同、库存更多）

这把“多备货”变成可审计的缺货/持有成本条件，而不是固定百分比；但 `h` 是示例值，持有成本按整周库存计、积压只是缺货代理，未计 lost sales、商誉、跌价、资金占用和前置期，成本金额不是会计数字。

完整报告：[`benchmarks/ACCESS_STOCK_COST_REPORT.md`](../../benchmarks/ACCESS_STOCK_COST_REPORT.md)。

## 5g. 跨周验证（Week 47）

目标周从 `2011-11-28` 换到更早的 `2011-11-21`，同样 400 单 / 30 种子 / 3 重复 / 同布点臂，只跑 100%/125%/140% 三档：

| 总库存 | 库存单位 | 目标 OTIF | 全量 OTIF | 积压 |
|---:|---:|---:|---:|---:|
| 100% | 32,609 | 96.7% | 98.8% | 172.0 |
| 125% | 40,757 | 97.5% | 99.5% | 28.3 |
| 140% | 45,652 | 100.0% | 99.9% | 0.7 |

结论：

- **140% 的服务阈值复现**：125% 仍只到 target 97.5%，140% 才到 100%/all 99.9%；“125% 不够、140% 到 ceiling”不是单周偶然。
- **成本 break-even 不稳定**：OOS `100→125` = **56.7**、`125→140` = **176.9**；in-sample 为 71.9 / 90.3 / 1,646（多一个 135% 点）。`p/h=100` 时 in-sample 选 135%，OOS 只能选 125%；`p/h=200` 时 OOS 已选 140%，in-sample 仍选 135%。成本档位对周和网格敏感，不能把 Week46 阈值当常数。
- **布点仍只有小效应**：100% covered history all 99.1% vs baseline 98.8%；125% 99.7% vs 99.5%；140% 100.0% vs 99.9%，均 0.1–0.3pp。
- **库存单位随周需求变化**：100% 为 32,609（in-sample 33,060），140% 为 45,652（in-sample 46,281）；百分比是需求倍数，不是固定预算。
- 只验证一个 holdout 周，OOS 无 135%/150%，不是多周补货/持有成本策略。

完整报告：[`benchmarks/ACCESS_STOCK_OOS_REPORT.md`](../../benchmarks/ACCESS_STOCK_OOS_REPORT.md) 与 [`benchmarks/ACCESS_STOCK_OOS_COST_REPORT.md`](../../benchmarks/ACCESS_STOCK_OOS_COST_REPORT.md)。

## 5h. 种子级成本稳定性（Week 48）

对 90 个 `(repeat, seed)` 逐格重算最便宜档位，不新增仿真；变化的是到达/拣选噪声，需求/库存份额/布局/承诺固定。

| 数据 | `p/h` | seed 选择分布 | 种子众数 | 均值数据选择 |
|---|---:|---|---:|---:|
| in-sample | 100 | 125% 67% / 135% 33% | **125%** | **135%** |
| in-sample | 200 | 135% 100% | 135% | 135% |
| in-sample | 2,000 | 135% 67% / 140% 33% | **135%** | **140%** |
| OOS | 100 | 125% 100% | 125% | 125% |
| OOS | 200 | 140% 100% | 140% | 140% |

结论：

- **均值决策会偏激进**：`p/h=100` 时 2/3 的 seed 选 125%，均值却选 135%；`p/h=2,000` 时 2/3 选 135%，均值却选 140%。成本阈值是区域，不是锐线。
- **OOS 在 3 档上一致**：100% 的 seed 分别选 125%/140%；但 OOS 无 135%，无法判断 135% 是否更便宜。
- **不是 90 个独立需求样本**：3 个 repeat 共享同一组 30 个 seed；只变到达/拣选噪声。
- `h=€0.10` 与缺货惩罚比仍是示例，未计 lost sales/商誉/跌价/资金占用/前置期。

完整报告：[`benchmarks/ACCESS_SEED_COST_REPORT.md`](../../benchmarks/ACCESS_SEED_COST_REPORT.md)。

## 5i. 库存基准：oracle vs 历史均值（Week 49）

Week45–48 的每 SKU 库存 = `stock_factor × 目标周实际需求`，是 **oracle 库存上界**。Week49 用同 400 单，将库存改为前 6 周 SKU 均值 × 采样订单/历史发票缩放，不使用目标周需求：

| 基准 | 倍数 | 单位 | 覆盖 | target | all | 积压 |
|---|---:|---:|---:|---:|---:|---:|
| 目标周实际需求 | 140% | 46,281 | 140.0% | 100.0% | 99.9% | 0.7 |
| 前 6 周均值 | 140% | 44,824 | 135.6% | 70.0% | 93.9% | 2,123 |
| 前 6 周均值 | 180% | 57,626 | 174.3% | 79.2% | 96.7% | 1,448 |
| 前 6 周均值 | 200% | 64,039 | 193.7% | 82.5% | 97.2% | 1,281 |

结论：

- **总量接近，服务差 30pp**：同样 140%，46,281 vs 44,824 单位，target 100% vs 70%；差的是 per-SKU 结构，不是总库存。
- **多备总量补不回来**：历史 200% 为 64,039 单位（目标需求 194%），仍只有 target 82.5%/all 97.2%；aggregate overstock 不能修复 SKU mix。
- **Week45–48 是 oracle 上界**：成本决策、跨周、种子稳定性都继承；不要把绝对服务水平当可部署承诺。
- 历史均值是朴素下界，无预测/前置期/补货；真实预测应介于两者之间。

完整报告：[`benchmarks/ACCESS_STOCK_BASIS_REPORT.md`](../../benchmarks/ACCESS_STOCK_BASIS_REPORT.md)。

## 5j. 安全库存政策（Week 50）

在前 6 周均值上再加 `z × 标准差`，其中 z=1.645（≈95%）/2.326（≈99%）：

| 政策 | 库存 | 覆盖 | target | all | 积压 |
|---|---:|---:|---:|---:|---:|
| oracle 140% | 46,281 | 140.0% | 100.0% | 99.9% | 0.7 |
| 历史 140% | 44,824 | 135.6% | 70.0% | 93.9% | 2,123 |
| 历史 200% | 64,039 | 193.7% | 82.5% | 97.2% | 1,281 |
| mean+zσ，z=1.645 | 61,537 | 186.1% | 77.5% | 96.6% | 1,082 |
| mean+zσ，z=2.326 | 73,748 | 223.1% | 79.2% | 97.1% | 880 |

结论：

- **99% 安全库存仍只有 target 79.2%**：73,748 单位（223% 覆盖）远高于 oracle 140% 的 46,281 单位，但 target 低 20.8pp。
- **安全库存按波动分配，不按目标周高需求 SKU 分配**：z=1.645 的 61,537 单位只到 77.5%，比库存更多的历史 200%（64,039）低 5pp。
- z=2.326 相对历史 200% 主要买积压下降（1,281→880），target/all 反而略降；它改善尾部缺货，不保证命中目标周 SKU。
- 可部署政策仍缺目标周 SKU/DC 结构预测；这是对“加安全库存就能补 oracle”的反例，不是“所有安全库存都无用”。

完整报告：[`benchmarks/ACCESS_STOCK_SAFETY_REPORT.md`](../../benchmarks/ACCESS_STOCK_SAFETY_REPORT.md)。

## 5k. LightGBM 预测库存（Week 51）

用现有 rolling-origin LightGBM 的目标周预测定库存，只用目标周之前的实际/预测总量校准，不使用目标周需求：

| 政策 | 库存 | 覆盖 | target | all | 积压 |
|---|---:|---:|---:|---:|---:|
| oracle 140% | 46,281 | 140.0% | 100.0% | 99.9% | 0.7 |
| 历史 140% | 44,824 | 135.6% | 70.0% | 93.9% | 2,123 |
| 历史 200% | 64,039 | 193.7% | 82.5% | 97.2% | 1,281 |
| 安全 z=2.326 | 73,748 | 223.1% | 79.2% | 97.1% | 880 |
| forecast-140 | 48,806 | 147.6% | 75.0% | 88.3% | 1,407 |
| forecast-160 | 55,776 | 168.7% | 85.0% | 91.6% | 945 |

结论：

- **target 略好、tail 更差**：forecast-160 比历史 200% 少 8,263 单位，target +2.5pp，但 all −5.7pp。
- **target 优势不稳健**：同库存 55,776 单位重跑，target 85.0%→81.7%（3.3pp）；+2.5pp 落在噪声内，−5.7pp all 损失更大。
- **forecast-140 也不是免费**：48,806 单位 target 75.0%，比历史 140% 高 5pp，但 all 88.3% vs 93.9%，且多 3,982 单位。
- **仍远低于 oracle**：forecast-160 85.0% vs oracle 140% 100%；瓶颈仍是 SKU/DC 需求位置。
- 预测只覆盖 200 个主 SKU；预测分配误差本身已拉低 all-service。未重训/调参，只有 1 个目标周。

完整报告：[`benchmarks/ACCESS_STOCK_FORECAST_REPORT.md`](../../benchmarks/ACCESS_STOCK_FORECAST_REPORT.md)。

## 5l. SKU 结构与总量分解（Week 52）

固定总量、只换 SKU 结构，以及固定历史结构、只加总量：

| 政策 | 库存 | target | all | 积压 |
|---|---:|---:|---:|---:|
| 实际结构 @46,281 | 46,281 | 100.0% | 99.9% | 0.7 |
| 实际结构 @44,824 | 44,824 | 100.0% | 99.9% | 1.3 |
| 历史结构 @44,824 | 44,824 | 70.0% | 93.9% | 2,123 |
| 历史结构 @46,288 | 46,288 | 72.5% | 95.2% | 1,980 |
| 历史结构 @64,039 | 64,039 | 82.5% | 97.2% | 1,281 |

结论：

- **同总量 44,824，结构差 30pp target**：实际 100.0% vs 历史 70.0%；积压 1.3 vs 2,123。
- **同历史结构，加 1,464 单位只买 +2.5pp target**；加到 64,039（+19,215）也只 82.5%。
- **SKU 结构是第一阶，总量是二阶**；实际结构仍是 oracle，可部署问题是预测 SKU 结构。
- 只隔离 per-SKU 总量，DC 份额/jitter 未变；一周、400 单、30 种子 ×3。

完整报告：[`benchmarks/ACCESS_STOCK_MIX_REPORT.md`](../../benchmarks/ACCESS_STOCK_MIX_REPORT.md)。

## 5m. 预测 SKU 结构（Week 53）

固定历史总量，只把 SKU 结构换成 LightGBM 预测份额：

| 政策 | 库存 | target | all | 积压 |
|---|---:|---:|---:|---:|
| 实际结构 | 44,824 | 100.0% | 99.9% | 1.3 |
| 历史结构 | 44,824 | 70.0% | 93.9% | 2,123 |
| 预测结构 | 44,826 | 70.0% | 87.3% | 1,740 |
| 预测结构 | 51,221 | 74.2% | 90.0% | 1,261 |
| 历史结构 | 64,039 | 82.5% | 97.2% | 1,281 |
| 预测点值 | 55,776 | 85.0% | 91.6% | 945 |

结论：

- **同总量预测结构 target 70.0% = 历史结构 70.0%**，all 反而 87.3% vs 93.9%；预测份额不是更好的结构。
- 预测结构加到 51,221 也只 74.2%，仍远低于实际结构 100%。
- Week51 点值 85.0% 不能解释为“结构更好”：点值还多 4,555 单位且分配不同；更一致的解释是更多总量。
- 只覆盖 200 个主 SKU，缺失用历史份额；没有 SKU×DC 需求模型。一周、400 单、30 种子 ×3。

完整报告：[`benchmarks/ACCESS_FORECAST_SHARE_REPORT.md`](../../benchmarks/ACCESS_FORECAST_SHARE_REPORT.md)。

## 5n. 前一周 SKU 结构（Week 54）

固定历史总量，只把结构换成前一周实际份额：

| 政策 | 库存 | target | all | 积压 |
|---|---:|---:|---:|---:|
| 实际结构 | 44,824 | 100.0% | 99.9% | 1.3 |
| 历史均值结构 | 44,824 | 70.0% | 93.9% | 2,123 |
| LightGBM 结构 | 44,826 | 70.0% | 87.3% | 1,740 |
| 前一周结构 | 44,833 | 49.2% | 84.6% | 4,787 |
| 预测点值 | 55,776 | 85.0% | 91.6% | 945 |

结论：

- **前一周结构明显更差**：target 49.2% vs 历史 70.0%，all 84.6% vs 93.9%，积压 4,787 vs 2,123。
- 三种可部署结构信号（历史、LightGBM、前一周）都不行；只有实际结构 100%。
- 加总量也修不了坏结构；预测点值 55,776 到 85% target 但 all 仍 91.6%。
- 前一周是相邻周且目标周有季节切换，是压力案例，不是一般性否定持久化。一周、400 单、30 种子 ×3。

完整报告：[`benchmarks/ACCESS_LAST_WEEK_REPORT.md`](../../benchmarks/ACCESS_LAST_WEEK_REPORT.md)。

## 5o. 目的国 DC 结构（Week 55）

用前 6 周目的国×SKU 需求，把每个 SKU 的库存放到最近 DC，总量固定 44,824：

| 政策 | 库存 | target | all | 积压 |
|---|---:|---:|---:|---:|
| 实际结构 | 44,824 | 100.0% | 99.9% | 1.3 |
| 历史均值结构 | 44,824 | 70.0% | 93.9% | 2,123 |
| LightGBM 结构 | 44,826 | 70.0% | 87.3% | 1,740 |
| 前一周结构 | 44,833 | 49.2% | 84.6% | 4,787 |
| 目的国 DC 结构 | 44,824 | 71.7% | 92.0% | 2,152 |
| 预测点值 | 55,776 | 85.0% | 91.6% | 945 |

结论：

- **同总量没有赢**：target +1.7pp、all −1.9pp、积压 +29，接近噪声。
- 库存集中到约 90%/7%/2%（London 主导），救 target、伤 tail，未改变 SKU 组成。
- 历史/预测/前一周/目的国 DC 四种可部署结构信号都不行，只有实际结构 100%。
- 目的国≠实际 DC 需求；DC 需求由分单 MILP 内生决定。一周、400 单、30 种子 ×3。

完整报告：[`benchmarks/ACCESS_DC_MIX_REPORT.md`](../../benchmarks/ACCESS_DC_MIX_REPORT.md)。

## 6. 效度威胁

- oracle 使用本周实际订单；history 使用前 6 周数量但仍用本周 destination/transit 矩阵，二者都不是完整因果策略。
- 调拨假设周前完成、无前置期/费用/批次；真实 DC 调拨需要运输时间、装载与成本。
- 库存按 SKU 总量 + 确定性 jitter 分配；target 只替换 stock 矩阵，jitter 已经包含在 current 中。
- 单周、单布局、单班次；Week44 只把每 DC 拣货员从 1 人换到 2 人，没有排班/波次释放交互；Week45 的 125%/135%/140%/150% 是库存情景，Week46 的 `h=€0.10` 与缺货惩罚比是示例，Week47 只验证一个 holdout 周且没有 135%/150%，Week48 的 90 格只变到达/拣选噪声、不是 90 个独立需求周；Week49 证明 Week45–48 的库存是目标周需求 oracle，历史均值 140% 只有 target 70%；Week50 的 z=2.326 安全库存用 223% 覆盖也只到 target 79.2%；Week51 的 LightGBM 预测 160% 用 55,776 单位到 target 85.0%，all 仍只有 91.6%；Week52 同总量对照显示实际/历史 SKU 结构差 30pp target；Week53 固定总量换成预测结构仍只有 70.0%；Week54 前一周结构只有 49.2%；Week55 目的国 DC 结构 71.7%/92.0%，只是 ~2pp 交换；十一者都不是成本最优补货决策。布点 MILP 单线程固定 seed，但端到端分单 MILP 仍是 2 workers/8s 时间受限，跨臂重解会带来 1–3pp 差异；重复运行总波动约 2.5–5pp。
- 目标客群是样本内收入 Top10；没有 COGS/退货/履约成本，OTIF 不是利润。

## 7. 复现

```bash
PYTHONPATH=src;. python scripts/run_e2e_access.py --repeats 3
# 输出：benchmarks/ACCESS_REPORT.md + access_summary.json
# 快速试跑：--orders 80 --seeds 3 --milp-time 2 --service-time 1 --solver-time 2 --repeats 1
# covered + 2 拣货员：python scripts/run_e2e_access.py --pickers 2 --load-aware \
#   --load-basis covered --repeats 3 --stem ACCESS_LOAD_COVERED_P2 --week 44
# 库存前沿：--stock-factor 1.25 / 1.35 / 1.4 / 1.5 + build_access_stock_frontier.py
# 成本决策：python scripts/build_access_stock_cost.py
# 跨周验证：--target-week 2011-11-21（100/125/140）+ build_access_stock_frontier.py --week 47 --stem ACCESS_STOCK_OOS
# 种子级：python scripts/build_access_seed_cost.py
# 库存基准：--stock-basis history（1.4/1.8/2.0）+ build_access_stock_basis.py
# 安全库存：--stock-basis safety --safety-z 1.645/2.326 + build_access_stock_policy.py
# 预测库存：--stock-basis forecast --forecast-model lightgbm + build_access_stock_forecast.py
# 结构分解：build_access_stock_mix.py（同总量实际/历史结构）
# 预测结构：--stock-basis forecast_share + build_access_forecast_share.py
# 前一周结构：--stock-basis last_week_share + build_access_last_week.py
# 目的国 DC 结构：--stock-basis dc_mix + build_access_dc_mix.py

# 负荷 cap 扩展（Week 42）
PYTHONPATH=src;. python scripts/run_e2e_access.py --load-aware --repeats 3 \
  --stem ACCESS_LOAD --week 42
# 输出：benchmarks/ACCESS_LOAD_REPORT.md + access_load_summary.json

# covered 负荷（Week 43）
PYTHONPATH=src;. python scripts/run_e2e_access.py --load-aware --load-basis covered \
  --repeats 3 --stem ACCESS_LOAD_COVERED --week 43
# 输出：benchmarks/ACCESS_LOAD_COVERED_REPORT.md + access_load_covered_summary.json
```

相关文档：[Week 40 布点报告](../../benchmarks/PLACEMENT_REPORT.md)、[Week 42 负荷报告](../../benchmarks/ACCESS_LOAD_REPORT.md)、[Week 43 covered 负荷报告](../../benchmarks/ACCESS_LOAD_COVERED_REPORT.md)、[约束诊断](binding_constraint.md)、[分单 MILP](allocation_milp.md)。
