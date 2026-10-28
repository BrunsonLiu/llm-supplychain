# Promise quoting and the service frontier (Week 18)

- Generated: `2026-10-28T15:51:20.145925+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Seeds: **30** | quoting policies: **11** | pickers/DC: **1** | milp **60 s/policy**
- Baseline promise: avg **3.10 d** | 2-day **30.0%** | 5-day **20.0%**

## Assumptions

| Item | Assumption | Note |
|---|---|---|
| Quote tiers | 2 / 3 / 5 days | declared customer-facing tiers |
| ATP rule | 1 handling day + slowest line's fastest in-stock DC | split legs allowed; stock snapshot only |
| Stock check | each line must have stock at some DC | no reservation or cross-order stock competition |
| Priority | promise maps to 2/3/5-day pick cutoff | `ATP+固定优先级` keeps the baseline cutoffs |
| Arrivals | Week-15/10 draw, held fixed across policies | quoting changes the cutoff, not the arrival minute |
| Allocation | Week-9 capacity-aware MILP, re-solved per policy | solver noise is inside the policy effect |
| Delivery | departure day + transit days ≤ quoted days | two departures 13:00/19:00, no door limit |
| Static SLA | the Week-15 baseline promise vector | common yardstick for delivery speed |

## Promise frontier

`按报价 OTIF` scores against each policy's own promise; `按基线 SLA OTIF` scores the same deliveries against the fixed Week-15 promise, so a policy cannot win by quoting a longer promise alone. Cells with an identical promise vector share one allocation, so `ATP 封顶 2 天`/`全部报 2 天`, `ATP 封顶 3 天`/`全部报 3 天` and `ATP + 1 天缓冲`/`全部报 5 天` are exact aliases, not independent runs.

| 回放格 | 平均承诺 (天) | 2 天占比 | 5 天占比 | 分单 fill | 分单 OTIF | 拣选截单 OTIF | 按报价 OTIF | 按基线 SLA OTIF |
|---|---|---|---|---|---|---|---|---|
| 固定 2/3/5 混合（Week-15 基线） | 3.10 | 30.0% | 20.0% | 83.2% | 51.5% | 37.0% | 51.5% | 51.5% |
| ATP：按库存与转运日报最快层 | 3.47 | 0.0% | 23.7% | 83.1% | 50.2% | 48.2% | 50.2% | 40.4% |
| ATP · 沿用基线截单优先级 | 3.47 | 0.0% | 23.7% | 83.1% | 50.2% | 32.8% | 48.5% | 41.0% |
| ATP + 1 天缓冲 | 5.00 | 0.0% | 100.0% | 83.0% | 54.0% | 50.1% | 54.0% | 43.7% |
| ATP 封顶 2 天 | 2.00 | 100.0% | 0.0% | 82.3% | 38.5% | 11.4% | 32.1% | 36.6% |
| ATP 封顶 3 天 | 3.00 | 0.0% | 0.0% | 82.7% | 46.7% | 32.3% | 44.1% | 37.3% |
| 全部报 2 天 | 2.00 | 100.0% | 0.0% | 82.3% | 38.5% | 11.4% | 32.1% | 36.6% |
| 全部报 3 天 | 3.00 | 0.0% | 0.0% | 82.7% | 46.7% | 32.3% | 44.1% | 37.3% |
| 全部报 5 天 | 5.00 | 0.0% | 100.0% | 83.0% | 54.0% | 50.1% | 54.0% | 43.7% |
| ATP · 加 1 名拣货员/DC | 3.47 | 0.0% | 23.7% | 83.1% | 50.2% | 50.2% | 50.2% | 41.0% |
| ATP · 拣选噪声 σ=0.25 | 3.47 | 0.0% | 23.7% | 83.1% | 50.2% | 47.6% | 50.2% | 40.2% |

## Allocation per policy

| 格 | 报价规则 | 状态 | fill | 分单 OTIF | 成本 (€) | 求解 (s) | 平均承诺 |
|---|---|---|---|---|---|---|---|
| 固定 2/3/5 混合（Week-15 基线） | static | FEASIBLE | 83.2% | 51.5% | 62,418 | 60.4 | 3.10 |
| ATP：按库存与转运日报最快层 | atp | FEASIBLE | 83.1% | 50.2% | 61,441 | 60.1 | 3.47 |
| ATP · 沿用基线截单优先级 | atp | FEASIBLE | 83.1% | 50.2% | 61,441 | 60.1 | 3.47 |
| ATP + 1 天缓冲 | atp_buffer | FEASIBLE | 83.0% | 54.0% | 60,565 | 60.1 | 5.00 |
| ATP 封顶 2 天 | atp_cap2 | FEASIBLE | 82.3% | 38.5% | 66,330 | 60.6 | 2.00 |
| ATP 封顶 3 天 | atp_cap3 | FEASIBLE | 82.7% | 46.8% | 62,947 | 60.1 | 3.00 |
| 全部报 2 天 | all_2 | FEASIBLE | 82.3% | 38.5% | 66,330 | 60.6 | 2.00 |
| 全部报 3 天 | all_3 | FEASIBLE | 82.7% | 46.8% | 62,947 | 60.1 | 3.00 |
| 全部报 5 天 | all_5 | FEASIBLE | 83.0% | 54.0% | 60,565 | 60.1 | 5.00 |
| ATP · 加 1 名拣货员/DC | atp | FEASIBLE | 83.1% | 50.2% | 61,441 | 60.1 | 3.47 |
| ATP · 拣选噪声 σ=0.25 | atp | FEASIBLE | 83.1% | 50.2% | 61,441 | 60.1 | 3.47 |

## Paired comparisons versus the static baseline

Same order set and arrival seeds; right − static.

| 对比（右 − 基线） | 指标 | Δ | 胜率 | 持平率 | n |
|---|---|---|---|---|---|
| ATP：按库存与转运日报最快层 | 报价 OTIF | -1.3 pp (±0.0) | 0.0% | 0.0% | 30 |
| ATP · 沿用基线截单优先级 | 报价 OTIF | -3.0 pp (±0.1) | 0.0% | 0.0% | 30 |
| ATP + 1 天缓冲 | 报价 OTIF | +2.5 pp (±0.0) | 100.0% | 0.0% | 30 |
| ATP 封顶 2 天 | 报价 OTIF | -19.4 pp (±0.4) | 0.0% | 0.0% | 30 |
| ATP 封顶 3 天 | 报价 OTIF | -7.4 pp (±0.3) | 0.0% | 0.0% | 30 |
| 全部报 2 天 | 报价 OTIF | -19.4 pp (±0.4) | 0.0% | 0.0% | 30 |
| 全部报 3 天 | 报价 OTIF | -7.4 pp (±0.3) | 0.0% | 0.0% | 30 |
| 全部报 5 天 | 报价 OTIF | +2.5 pp (±0.0) | 100.0% | 0.0% | 30 |
| ATP · 加 1 名拣货员/DC | 报价 OTIF | -1.3 pp (±0.0) | 0.0% | 0.0% | 30 |
| ATP · 拣选噪声 σ=0.25 | 报价 OTIF | -1.3 pp (±0.0) | 0.0% | 0.0% | 30 |
| ATP：按库存与转运日报最快层 | 基线 SLA OTIF | -11.0 pp (±0.1) | 0.0% | 0.0% | 30 |
| ATP · 沿用基线截单优先级 | 基线 SLA OTIF | -10.5 pp (±0.0) | 0.0% | 0.0% | 30 |
| ATP + 1 天缓冲 | 基线 SLA OTIF | -7.8 pp (±0.1) | 0.0% | 0.0% | 30 |
| ATP 封顶 2 天 | 基线 SLA OTIF | -14.9 pp (±0.2) | 0.0% | 0.0% | 30 |
| ATP 封顶 3 天 | 基线 SLA OTIF | -14.2 pp (±0.2) | 0.0% | 0.0% | 30 |
| 全部报 2 天 | 基线 SLA OTIF | -14.9 pp (±0.2) | 0.0% | 0.0% | 30 |
| 全部报 3 天 | 基线 SLA OTIF | -14.2 pp (±0.2) | 0.0% | 0.0% | 30 |
| 全部报 5 天 | 基线 SLA OTIF | -7.8 pp (±0.1) | 0.0% | 0.0% | 30 |
| ATP · 加 1 名拣货员/DC | 基线 SLA OTIF | -10.5 pp (±0.0) | 0.0% | 0.0% | 30 |
| ATP · 拣选噪声 σ=0.25 | 基线 SLA OTIF | -11.3 pp (±0.2) | 0.0% | 0.0% | 30 |

## Findings

- **Stock, not the quote, sets the fast end.** The Week-15 draw quotes 3.10 days on average with 30.0% 2-day orders; ATP quotes 3.47 days with 0.0% 2-day orders. At 85% stock coverage the slowest line of most orders has no fast in-stock DC, so ATP removes the 2-day tier instead of pretending it is available.
- **An honest quote does not buy reliability.** ATP changes quoted OTIF by -1.3 pp (±0.0) and the common-SLA OTIF by -11.0 pp (±0.1). The static mix keeps a 2-day tier that pulls allocation and picking forward; without it, the promised date is longer but the delivery is slower, so the static mix dominates on both readings.
- **The cutoff map is not the main loss.** Quoting ATP while keeping the Week-15 cutoffs changes quoted OTIF by -3.0 pp (±0.1) and the common-SLA OTIF by -10.5 pp (±0.0) versus static. Against plain ATP the same allocation moves quoted OTIF by about −1.7 pp but the common SLA by about +0.5 pp: allocation and the promise objective dominate, the cutoff map only trades one metric for the other.
- **Uniform promises bracket the static mix.** Quoting 2 days to everyone moves quoted OTIF by -19.4 pp (±0.4) and the common SLA by -14.9 pp (±0.2); 3 days moves it by -7.4 pp (±0.3) and -14.2 pp (±0.2); 5 days moves it by +2.5 pp (±0.0) and -7.8 pp (±0.1). All-5 wins the promise-OTIF column by quoting the longest promise, but loses the common SLA by 7.8 pp; the 2/3/5 mix is the best common-SLA policy in this run.
- **The stock-aware 5-day tail helps against a uniform 3-day quote.** ATP quotes 76.3% 3-day and 23.7% 5-day; versus all-3 it gains about +6.2 pp quoted OTIF and +3.2 pp common SLA. The tail is not useless, but it does not close the gap to the static 2-day priority.
- **Caps and buffers collapse to uniforms.** At this stock level ATP never finds a 2-day order, so the 2-day cap is all-2 (-19.4 pp (±0.4) quoted), the 3-day cap is all-3 (-7.4 pp (±0.3)), and the +1-day buffer is all-5 (+2.5 pp (±0.0)). They are commercial levers, not independent ATP variants.
- **Picking capacity and noise barely move the promise metric.** Against plain ATP, a second picker per DC leaves quoted OTIF at 50.2% and moves the common SLA by +0.6 pp; pick noise σ=0.25 also leaves quoted OTIF at 50.2% and moves the common SLA by -0.2 pp. The pick layer raises pick OTIF (48.2% → 50.2% with the extra picker), but the delivery day is set by the quote and the departure, not by a few minutes of pick noise.
- **Scope.** The quote uses only the current stock snapshot and declared transit days; it ignores future replenishment, competition between orders for the same stock, cancellations and order changes. Only 2/3/5-day tiers exist; the common SLA is the Week-15 baseline promise, not a measured customer tolerance.

## Limitations

- ATP 报价只用当前库存快照与声明转运日，不考虑未来补货、订单之间的库存竞争与取消/改单。
- 承诺只允许 2/3/5 天三档；1 天与 4 天被并入相邻档，报价粒度是声明值。
- 每个不同的承诺向量重解一次 Week-9 容量感知 MILP；相同承诺向量的回放格共享同一分单（所以封顶/缓冲会退化成对应的统一报价）。求解器时间预算内的差异仍会混入 static 与 ATP 的差异。
- 报价改变截单层，但到达分钟固定为基线抽样，以隔离“报价/截单”而不是“到达时机”的变化。
- static-SLA 用 Week-15 基线承诺作为共同 SLA，只衡量送达速度，不代表客户真实可接受时效。
- 库存、转运日、DC 产能与订单集都是声明/固定值，只验证一个目标周，绝对 OTIF 不可迁移。
