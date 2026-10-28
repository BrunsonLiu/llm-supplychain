# Rolling end-to-end with dock doors (Week 21)

- Generated: `2026-10-28T18:18:33.963357+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Flow: **5** weekdays | day 0: 66 | day 1: 73 | day 2: 68 | day 3: 85 | day 4: 108
- Seeds: **30** | doors/DC **[0, 1, 2]** | daily MILP **8s/day** | baseline **60s** | stock **85%**

## Assumptions

| Item | Assumption | Note |
|---|---|---|
| Order day | actual invoice weekday | Sat/Sun invoices land on Friday |
| Daily allocation | Week-9 capacity-aware MILP | only open lines and remaining stock |
| Pick | empirical arrivals + EDF | re-drawn per day and seed |
| Daily dispatch | immediate, `max_days=0` | missed last departure fails the order |
| Weekly baseline | all orders Monday, promise dispatch, `max_days=3` | Week-16 freedom |
| Dock doors | 0/1/2 per DC, 480 min/day | 75 min/truck + 0.5 min/ticket |
| Replenishment | declining order-up-to remaining-week cover | 1/2-day lead, no MOQ |
| OTIF | absolute `order_day + promise` | pick, dispatch and door all included |

## Results

`端到端 OTIF` requires every line allocated, every ticket shipped, and `allocation day + ship + transit ≤ order day + promise`. Door minutes are a daily budget per DC; a blocked ticket is unshipped and therefore fails.

| 策略 | 门位/DC | 端到端 OTIF | P10 | P90 | fill | 失败订单 | backlog | 平均交付日 | 门位利用 | 阻塞 |
|---|---|---|---|---|---|---|---|---|---|---|
| 单周一次性快照 | 0 | 53.3% | 53.2% | 53.2% | 83.0% | 187.0 | 5,619 | 2.70 | 0.0% | 0.0 |
| 单周一次性快照 | 1 | 53.2% | 53.0% | 53.2% | 83.0% | 187.3 | 5,619 | 2.71 | 56.3% | 3.6 |
| 单周一次性快照 | 2 | 53.3% | 53.2% | 53.2% | 83.0% | 187.0 | 5,619 | 2.70 | 31.8% | 0.0 |
| 不补货 · 日滚动端到端 | 0 | 54.7% | 54.8% | 54.8% | 84.2% | 181.0 | 5,232 | 3.94 | 0.0% | 0.0 |
| 不补货 · 日滚动端到端 | 1 | 54.7% | 54.5% | 54.8% | 84.2% | 181.2 | 5,232 | 3.93 | 68.7% | 0.3 |
| 不补货 · 日滚动端到端 | 2 | 54.7% | 54.8% | 54.8% | 84.2% | 181.0 | 5,232 | 3.94 | 34.5% | 0.0 |
| 每日 1 天补货 · 日滚动端到端 | 0 | 87.0% | 87.0% | 87.0% | 96.2% | 52.0 | 1,258 | 4.49 | 0.0% | 0.0 |
| 每日 1 天补货 · 日滚动端到端 | 1 | 86.6% | 86.4% | 87.0% | 96.2% | 53.5 | 1,258 | 4.48 | 69.7% | 1.2 |
| 每日 1 天补货 · 日滚动端到端 | 2 | 87.0% | 87.0% | 87.0% | 96.2% | 52.0 | 1,258 | 4.49 | 35.5% | 0.0 |

## Door effect by policy

| 对比 | n | Δ OTIF | 95% CI | 胜 | 负 | 平 |
|---|---|---|---|---|---|---|
| none@1门 − none@0门 | 30 | -0.0 pp | ±0.1 | 0.0% | 13.3% | 86.7% |
| none@2门 − none@0门 | 30 | +0.0 pp | ±0.0 | 0.0% | 0.0% | 100.0% |
| daily_1d@1门 − daily_1d@0门 | 30 | -0.4 pp | ±0.2 | 0.0% | 70.0% | 30.0% |
| daily_1d@2门 − daily_1d@0门 | 30 | +0.0 pp | ±0.0 | 0.0% | 0.0% | 100.0% |
| daily_1d@0门 − none@0门 | 30 | +32.3 pp | ±0.0 | 100.0% | 0.0% | 0.0% |
| daily_1d@0门 − single_week@0门 | 30 | +33.8 pp | ±0.0 | 100.0% | 0.0% | 0.0% |
| daily_1d@1门 − none@1门 | 30 | +31.9 pp | ±0.2 | 100.0% | 0.0% | 0.0% |
| daily_1d@1门 − single_week@1门 | 30 | +33.4 pp | ±0.2 | 100.0% | 0.0% | 0.0% |
| daily_1d@2门 − none@2门 | 30 | +32.3 pp | ±0.0 | 100.0% | 0.0% | 0.0% |
| daily_1d@2门 − single_week@2门 | 30 | +33.8 pp | ±0.0 | 100.0% | 0.0% | 0.0% |

## OTIF by order day

| 策略 | 门位/DC | 周一 | 周二 | 周三 | 周四 | 周五 |
|---|---|---|---|---|---|---|
| 单周一次性快照 | 0 | 53.3% | — | — | — | — |
| 单周一次性快照 | 1 | 53.2% | — | — | — | — |
| 单周一次性快照 | 2 | 53.3% | — | — | — | — |
| 不补货 · 日滚动端到端 | 0 | 92.4% | 84.9% | 66.2% | 49.4% | 8.3% |
| 不补货 · 日滚动端到端 | 1 | 92.4% | 84.9% | 65.9% | 49.4% | 8.3% |
| 不补货 · 日滚动端到端 | 2 | 92.4% | 84.9% | 66.2% | 49.4% | 8.3% |
| 每日 1 天补货 · 日滚动端到端 | 0 | 93.9% | 94.5% | 94.1% | 88.2% | 72.2% |
| 每日 1 天补货 · 日滚动端到端 | 1 | 93.9% | 94.5% | 94.0% | 88.2% | 70.9% |
| 每日 1 天补货 · 日滚动端到端 | 2 | 93.9% | 94.5% | 94.1% | 88.2% | 72.2% |

## Findings

- **One door is a second-order constraint in the daily flow.** Daily 1-day replenishment gives 86.6% with one door vs 87.0% with unlimited doors (-0.4 pp), with 1.2 blocked tickets on average and 69.7% door utilization. The daily flow spreads trucks across five days, but the one-shot baseline here is also only -0.1 pp, so this cell does not reproduce Week 17's larger door loss. Door effects are conditional on the load and arrival pattern.
- **A second door adds no measurable service here.** Two doors give 87.0% vs 87.0% with unlimited doors (+0.0 pp), utilization 35.5%. Door minutes are not the binding resource in the daily flow at this load.
- **The one-shot baseline is also not door-constrained at this load.** Single-week OTIF is 53.3% with unlimited doors and 53.2% with one door (-0.1 pp); its problem is inventory/allocation, not dock minutes.
- **Replenishment still dominates door capacity.** At unlimited doors, daily 1-day replenishment is 87.0% vs 54.7% without replenishment (+32.3 pp). At one door, the corresponding comparison is 86.6% vs 54.7%. The inventory decision is larger than the door decision in this instance.
- **Scope.** This is allocation + pick + dispatch + a daily door-minute budget. It does not model individual door occupancy, forklifts, dock workers, driver waiting, carrier consolidation or a second departure day; door minutes, load minutes and the 480-minute window are declared values. Replenishment is a declining order-up-to cover with no forecast, MOQ, supplier capacity or DC transfer.

## Limitations

- 门位是“每 DC 每日分钟预算”（默认 480 分钟，75 分钟/车 + 0.5 分钟/票），不模拟具体门位占用、叉车/装卸工排班、司机等待与预约时段。
- 日滚动每天只允许当天发车（max_days=0）；单周基线把所有订单视作周一且允许 3 天发车，两者不是同一发车自由度。
- 分单后不接收拣选/发车/门位失败的回写：未装车订单不进入次日 backlog 重试，库存已按分单扣减，失败被保守地当作终态。
- 补货为剩余周 cover 的 order-up-to，1/2 天前置期；不做预测/MOQ/供应商产能/DC 调拨；只有 1 个目标周、1 套库存/布局/劳动力。
- 单周基线 60s、日滚动 8s/天，求解器差异会混入 OTIF；30 个种子在本配置下可能给出相同 OTIF，配对 CI 为 0 时要按确定性边界读，而不是 30 个独立样本。
- 绝对 OTIF 不可迁移；门位/装车费率与工时都是声明值，结论只用于比较“多日库存结转 + 门位资源”的方向。
