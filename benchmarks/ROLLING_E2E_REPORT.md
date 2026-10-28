# Multi-day rolling end-to-end benchmark (Week 20)

- Generated: `2026-10-28T18:00:18.469889+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Flow: **5** weekdays | day 0: 66 | day 1: 73 | day 2: 68 | day 3: 85 | day 4: 108
- Seeds: **30** | daily MILP **8s/day** | baseline **60s** | stock **85%**

## Assumptions

| Item | Assumption | Note |
|---|---|---|
| Order day | actual invoice weekday | Sat/Sun invoices land on Friday |
| Daily allocation | Week-9 capacity-aware MILP | only open lines and remaining stock |
| Pick | empirical arrival curve + EDF, Week-16 stack | re-drawn per day and seed |
| Daily dispatch | immediate, `max_days=0` | a missed last departure fails the order |
| Weekly baseline | all orders on Monday, promise dispatch, `max_days=3` | Week-16 dock freedom |
| Replenishment | declining order-up-to remaining-week cover | 1/2-day lead, no MOQ |
| OTIF | absolute `order_day + promise` | not the daily relative promise |
| Scope | allocation + pick + dispatch | doors/loading resources are not replayed |

## End-to-end results

`端到端 OTIF` means every line was allocated, every ticket left on the day's last departure, and `allocation day + ship + transit ≤ order day + promise`.

| 策略 | 种子 | 端到端 OTIF | P10 | P50 | P90 | fill | 失败订单 | backlog | 平均交付日 |
|---|---|---|---|---|---|---|---|---|---|
| 单周一次性快照 · 端到端 | 30 | 51.2% | 51.2% | 51.2% | 51.2% | 82.8% | 195.0 | 5,670 | 2.69 |
| 不补货 · 日滚动端到端 | 30 | 55.0% | 55.0% | 55.0% | 55.0% | 83.9% | 180.0 | 5,337 | 3.99 |
| 每日 1 天补货 · 日滚动端到端 | 30 | 86.8% | 86.8% | 86.8% | 86.8% | 96.1% | 53.0 | 1,279 | 4.49 |
| 每日 2 天补货 · 日滚动端到端 | 30 | 72.2% | 72.2% | 72.2% | 72.2% | 93.9% | 111.0 | 2,023 | 4.35 |

**End-to-end OTIF by order day**（单周基线把所有订单视作周一，只有周一列）：

| 策略 | 周一 | 周二 | 周三 | 周四 | 周五 |
|---|---|---|---|---|---|
| 单周一次性快照 · 端到端 | 51.2% | — | — | — | — |
| 不补货 · 日滚动端到端 | 92.4% | 83.6% | 67.6% | 50.6% | 8.3% |
| 每日 1 天补货 · 日滚动端到端 | 92.4% | 94.5% | 94.1% | 88.2% | 72.2% |
| 每日 2 天补货 · 日滚动端到端 | 90.9% | 86.3% | 88.2% | 72.9% | 40.7% |

## Paired differences

| 对比 | n | Δ OTIF | 95% CI | 胜 | 负 | 平 |
|---|---|---|---|---|---|---|
| daily_1d − none | 30 | +31.8 pp | ±0.0 | 100.0% | 0.0% | 0.0% |
| daily_2d − none | 30 | +17.3 pp | ±0.0 | 100.0% | 0.0% | 0.0% |
| none − single_week | 30 | +3.8 pp | ±0.0 | 100.0% | 0.0% | 0.0% |
| daily_1d − single_week | 30 | +35.5 pp | ±0.0 | 100.0% | 0.0% | 0.0% |
| daily_2d − single_week | 30 | +21.0 pp | ±0.0 | 100.0% | 0.0% | 0.0% |

All paired intervals are zero because every seed gave the same order-level OTIF and average delivery day in this configuration: picking cleared the last departure regardless of the arrival draw. The 30 seeds are effectively one deterministic draw, not a 30-sample statistic.

## Findings

- **The pick/dispatch layer is not the main bottleneck in this setup.** The one-shot weekly baseline reaches 51.2% end-to-end; the 1-day rolling flow reaches 86.8%. With same-day dispatch and EDF, picking usually clears the last departure, so end-to-end OTIF stays close to the allocation-layer number. This is conditional on one picker, the empirical arrival curves and 85% stock; it does not mean picking can be ignored.
- **Replenishment still buys service after picking and dispatch.** With no replenishment, end-to-end OTIF is 55.0%; daily 1-day replenishment is 86.8% (+31.8 pp). Fill is 83.9% vs 96.1% and backlog 5,337 vs 1,279.
- **The intra-week shape survives the pick/dispatch layer.** Friday end-to-end OTIF is 72.2% with daily 1-day replenishment vs 8.3% without replenishment. The weekly average would hide that the last order day is still the weakest.
- **Lead time survives the pick/dispatch layer.** A 2-day lead gives 72.2% end-to-end vs 86.8% for 1-day (-14.5 pp); the extra day of stock cover is not enough to offset the later replenishment.
- **Daily dispatch is deliberately harsh.** The daily cell allows only the two declared departures on the allocation day (`max_days=0`); a ticket that misses the 19:00 cutoff is a failure, whereas the weekly baseline can hold for three days. The near-equality of allocation and end-to-end OTIF says the cutoff was not binding for most orders in this week, not that it is harmless in general.
- **Scope.** Picking uses the Week-16 empirical arrivals and EDF; doors, loading minutes and carrier consolidation are not replayed this week. Replenishment is a declining order-up-to cover with no forecast, MOQ, supplier capacity or DC transfer. The result is one target week and one stock/layout.

## Limitations

- 日滚动每天只允许当天最后发车（max_days=0）；错过当天发车的票据直接失败，不滚到次日。单周基线用 Week-16 的 3 天发车窗口，两者不是同一发车自由度。
- 只重放“分单 → 经验到达 → EDF 拣选 → 截单 → 发车”；门位/装车资源不重跑，门位默认 0（不限制）。
- 单周基线把所有订单视作周一到达，用承诺日从周一起算；日滚动按真实订单日算绝对承诺。两者不是逐单同口径，单周基线只作“一次性分单”的端到端对照。
- 补货为剩余周 cover 的 order-up-to，1/2 天前置期；不做预测/MOQ/供应商产能/DC 调拨。
- 订单日按发票日期映射，周六/周日并入周五；单周基线与日滚动用同一批种子，但日滚动每天重新抽样到达曲线，不是逐日配对的同一批到达。
- 单周基线 60s、日滚动 8s/天，求解器差异会混入 OTIF；只验证 1 个目标周、1 套库存/布局/劳动力。
- 绝对 OTIF 不可迁移；结论用于比较“多日库存结转 + 拣选/发车”的方向。
- 分单后不接收拣选/发车失败的回写：未装车订单不进入次日 backlog 重试，且库存已按分单扣减；失败订单被保守地当作终态。
