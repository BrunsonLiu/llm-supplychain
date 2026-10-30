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
| baseline 34/28/38 | **95.8%** | **99.1%** | **98.7%** | 141 | 99.6% | 3.53 | — | 0 |
| access_history | 94.2% | 98.8% | 98.3% | 214 | 99.4% | 4.04 | 47.1% | 8,619 |
| access_oracle | 97.5% | 97.4% | 97.4% | 174 | 99.5% | 3.44 | 63.1% | 8,222 |

三次重复的 target 范围：

- baseline：95.0–97.5%
- access_history：92.5–95.0%
- access_oracle：97.5–97.5%

## 5. 结论

1. **没有稳健的端到端收益。** 历史需求版均值 −1.7pp（范围 92.5–95.0），低于 baseline；oracle +1.7pp（范围 97.5），但 baseline 的上界也是 97.5%。两者差异都在 5pp 求解器/到达噪声附近。
2. **oracle 不是 Pareto 改进。** target +1.7pp，但 rest −1.7pp、全量 −1.3pp；它把服务从非目标挪到目标，不是“同样库存服务更多订单”。
3. **覆盖代理与 OTIF 不对齐。** MILP 只最大化静态可达需求，看不到拣选队列、到达形状、DC 峰值负荷；把 60% 库存放到一个 DC 可能制造拣选瓶颈。历史版 coverage 只有 47.1%，oracle 63.1%，但 coverage 更高不等于 OTIF 更高。
4. **手选 baseline 仍然最好。** 这与 Week 40 的 null 一致：固定总量下，布点不是主要杠杆；Week39 的 150% 总量才是唯一把目标做到 100% 的臂。
5. **oracle 的 97.5% 不是策略上界**，只是“本周订单已知”的一个参照；不能把它写成可部署收益。

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
```

相关文档：[Week 40 布点报告](../../benchmarks/PLACEMENT_REPORT.md)、[约束诊断](binding_constraint.md)、[分单 MILP](allocation_milp.md)。
