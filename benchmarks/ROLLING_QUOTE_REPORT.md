# Rolling replenishment with daily promise re-quoting (Week 22)

- Generated: `2026-10-28T18:36:12.177566+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Flow: **5** weekdays | day 0: 66 | day 1: 73 | day 2: 68 | day 3: 85 | day 4: 108
- Seeds: **30** | replenishment **['none', 'daily_1d']** | quote policies **['static', 'atp', 'atp_buffer']** | daily MILP **8s/day** | stock **85%**

## Assumptions

| Item | Assumption | Note |
|---|---|---|
| Daily quote | ATP from start-of-day on-hand stock | new orders only |
| Old orders | keep the absolute promise quoted at arrival | not re-quoted |
| Quote tiers | 2 / 3 / 5 days | fastest in-stock DC per line |
| Dynamic quote | `atp` / `atp_buffer` | buffer maps 2→3 and 3→5 |
| Replenishment | order-up-to remaining-week cover | 1/2-day lead, no MOQ |
| Pick / dispatch | empirical arrivals + EDF, two departures | `max_days=0` |
| Scoring | quoted promise and original static SLA | both absolute dates |

## Results

`quoted OTIF` uses the promise actually quoted to the customer; `原 SLA OTIF` uses the Week-20 fixed 2/3/5 promise as a common baseline. A longer quote can raise quoted OTIF while lowering the original SLA; both are shown so a quote policy cannot win by simply buying time.

| 策略 | 报价 | quoted OTIF | 原 SLA OTIF | 平均承诺 | 2 天占比 | fill | 失败订单 | backlog | 平均交付日 |
|---|---|---|---|---|---|---|---|---|---|
| 单周一次性快照 | static | 52.3% | 52.3% | 3.10 | 30.0% | 83.1% | 191.0 | 5,597 | 2.61 |
| 不补货 · 日滚动端到端 | static | 54.3% | 54.3% | 3.10 | 30.0% | 84.0% | 183.0 | 5,290 | 3.93 |
| 不补货 · 日滚动端到端 | atp | 62.8% | 52.5% | 4.36 | 0.0% | 84.4% | 149.0 | 5,162 | 4.10 |
| 不补货 · 日滚动端到端 | atp_buffer | 63.0% | 52.5% | 5.00 | 0.0% | 84.4% | 148.0 | 5,166 | 4.07 |
| 每日 1 天补货 · 日滚动端到端 | static | 87.2% | 87.2% | 3.10 | 30.0% | 98.0% | 51.0 | 672 | 4.49 |
| 每日 1 天补货 · 日滚动端到端 | atp | 95.0% | 84.8% | 3.63 | 0.0% | 98.4% | 20.0 | 516 | 4.52 |
| 每日 1 天补货 · 日滚动端到端 | atp_buffer | 95.7% | 85.5% | 5.00 | 0.0% | 98.1% | 17.0 | 612 | 4.54 |

## Paired differences

| 对比 | n | Δ quoted | Δ 原 SLA | 95% CI | 胜 | 负 | 平 |
|---|---|---|---|---|---|---|---|
| none@atp − none@static | 30 | +8.5 pp | -1.7 pp | ±0.0 | 100.0% | 0.0% | 0.0% |
| none@atp_buffer − none@static | 30 | +8.8 pp | -1.7 pp | ±0.0 | 100.0% | 0.0% | 0.0% |
| none@static − single_week@static | 30 | +2.0 pp | +2.0 pp | ±0.0 | 100.0% | 0.0% | 0.0% |
| daily_1d@atp − daily_1d@static | 30 | +7.8 pp | -2.5 pp | ±0.0 | 100.0% | 0.0% | 0.0% |
| daily_1d@atp_buffer − daily_1d@static | 30 | +8.5 pp | -1.7 pp | ±0.0 | 100.0% | 0.0% | 0.0% |
| daily_1d@static − single_week@static | 30 | +35.0 pp | +35.0 pp | ±0.0 | 100.0% | 0.0% | 0.0% |

## OTIF by order day

| 策略 | 报价 | 周一 | 周二 | 周三 | 周四 | 周五 |
|---|---|---|---|---|---|---|
| 单周一次性快照 | static | 52.3% | — | — | — | — |
| 不补货 · 日滚动端到端 | static | 90.9% | 84.9% | 70.6% | 45.9% | 7.4% |
| 不补货 · 日滚动端到端 | atp | 97.0% | 95.9% | 80.9% | 55.3% | 13.9% |
| 不补货 · 日滚动端到端 | atp_buffer | 97.0% | 95.9% | 80.9% | 62.4% | 9.3% |
| 每日 1 天补货 · 日滚动端到端 | static | 93.9% | 94.5% | 94.1% | 88.2% | 73.1% |
| 每日 1 天补货 · 日滚动端到端 | atp | 98.5% | 100.0% | 100.0% | 95.3% | 86.1% |
| 每日 1 天补货 · 日滚动端到端 | atp_buffer | 98.5% | 100.0% | 100.0% | 96.5% | 88.0% |

## Findings

- **Daily ATP raises quoted OTIF while lowering the original SLA.** With 1-day replenishment, quoted OTIF rises +7.8 pp (87.2% → 95.0%), but the original SLA falls -2.5 pp and the average quote moves +0.53 days. The quote is not a free service gain; it combines a longer promise with allocation re-prioritization.
- **The quote is not a pure wording A/B.** The allocation MILP also uses the quoted promise as a deadline, so daily ATP changes fill (98.0% → 98.4%) and backlog (672 → 516). Part of the quoted-OTIF gain is more units allocated, not just a longer promise; the original-SLA column keeps the customer baseline fixed.
- **Buffering buys a small service gain at a large promise cost.** `atp_buffer` gives 95.7% quoted OTIF vs 95.0% for raw ATP (+0.8 pp), and the original SLA moves +0.8 pp; but the average quote is 5.00 vs 3.63 days. The extra day is not free.
- **Without replenishment, re-quoting cannot create stock.** No-replenishment quoted OTIF is 62.8% with ATP vs 54.3% with the fixed mix; the average quote is 4.36 vs 3.10 days. This separates the quote decision from the inventory decision.
- **Daily replenishment still dominates the quote policy.** Daily static quoted OTIF is 87.2% vs 52.3% for the one-shot snapshot (+35.0 pp). The biggest service lever remains inventory, not the wording of the promise.
- **The seed intervals are zero.** Every seed gives the same order-level OTIF and delivery day, so the paired differences are deterministic boundaries, not 30 independent samples.
- **Scope.** This is allocation + pick + dispatch + a daily quote. It does not model customer acceptance, cancellations, re-quotes, carrier capacity, dock doors or a second departure day. Quote tiers, replenishment lead time and transit days are declared values.

## Limitations

- ATP 只按当天开始时的在库量报价，不把在途补货、未来到达或跨订单库存预留放进报价；同一天多张订单可能同时被报 2 天，分单时再竞争库存。
- 报价只允许 2/3/5 三档；新订单按 ATP 最快档报价，旧订单保留到达时的绝对承诺日，不做改单/取消/客户拒绝。
- 日滚动每天只允许当天发车（max_days=0）；单周基线把所有订单视作周一且允许 3 天发车，两者不是同一发车自由度。
- 分单后不接收拣选/发车/门位失败的回写：未装车订单不进入次日 backlog 重试，库存已按分单扣减，失败被保守地当作终态。
- 补货为剩余周 cover 的 order-up-to，1/2 天前置期；不做预测/MOQ/供应商产能/DC 调拨；只有 1 个目标周、1 套库存/布局/劳动力。
- 单周基线 60s、日滚动 8s/天，求解器差异会混入 OTIF；30 个种子可能给出相同结果，配对 CI 为 0 时要按确定性边界读。
- 静态 SLA 用 Week-20 的固定 2/3/5 承诺，不是客户真实容忍度；报价更短不等于更好，报价更长也不一定保住原 SLA。
