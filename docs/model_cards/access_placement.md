# 库存布点 MILP：变量、约束、结果与效度

Week 41 的模型卡片。它回答 Week 40 留下的问题：固定总量下，**用优化器选 DC 布点**能否比四个手选占比更好。

## 1. 问题设定

- 实例：`2011-11-28` 周 400 张真实发票、2,477 行、33,060 units、189 SKU、3 个 DC。
- 固定：每个 SKU 的总库存 = 100% 需求；DC 2× 周产能；transit −1 天；ATP accept-all；1 拣货员/DC；30 个到达种子。
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

完整报告：[`benchmarks/ACCESS_LOAD_COVERED_REPORT.md`](../../benchmarks/ACCESS_LOAD_COVERED_REPORT.md)。

## 6. 效度威胁

- oracle 使用本周实际订单；history 使用前 6 周数量但仍用本周 destination/transit 矩阵，二者都不是完整因果策略。
- 调拨假设周前完成、无前置期/费用/批次；真实 DC 调拨需要运输时间、装载与成本。
- 库存按 SKU 总量 + 确定性 jitter 分配；target 只替换 stock 矩阵，jitter 已经包含在 current 中。
- 单周、单布局、单班次、单拣货员；布点 MILP 单线程固定 seed，但端到端分单 MILP 仍是 2 workers/8s 时间受限，跨臂重解会带来 1–3pp 差异；重复运行总波动约 2.5–5pp。
- 目标客群是样本内收入 Top10；没有 COGS/退货/履约成本，OTIF 不是利润。

## 7. 复现

```bash
PYTHONPATH=src;. python scripts/run_e2e_access.py --repeats 3
# 输出：benchmarks/ACCESS_REPORT.md + access_summary.json
# 快速试跑：--orders 80 --seeds 3 --milp-time 2 --service-time 1 --solver-time 2 --repeats 1

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
