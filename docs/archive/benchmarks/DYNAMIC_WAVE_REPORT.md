# Online wave release benchmark (Week 8)

- Generated: `2026-10-27T20:01:59.803110+00:00`
- Orders: **200** real invoices / **1,269** lines / **18,748** units, week 2011-11-28
- Arrivals: **102** orders before the 08:00 start and **98** during the shift; per-tier arrival windows are declared assumptions.
- Shift: **2 pickers**, **600 min**; wave cap **8 orders / 40 lines**. Overtime is reported, not constrained.

## Assumptions

| Item | Assumption | Note |
|---|---|---|
| Promise tier mix | 20% / 50% / 30% | No customer-promise data in Online Retail II; tiers are assigned by seeded shuffle. |
| Cutoffs | 12:00 / 16:00 / 18:00 | Minutes 240 / 480 / 600 after the 08:00 shift start. |
| On-time arrival share | express 70.0%, standard 50.0%, economy 40.0% | No order-release timestamps; the rest arrive uniformly inside the tier window. |
| Arrival window | express 120 min, standard 360 min, economy 480 min | All windows close before the tier cutoff, so no order is late on arrival. |
| Pickers | identical workers | No skills, zones, breaks, or absenteeism. |
| Wait policy | window 15 min, fill ≥ 4 orders | An idle picker waits only while the candidate wave is below the fill target and the next arrival is inside the window. |
| Wave labor | Week-6 model | Travel at 72.0 m/min, 0.35 min/line + 0.02 min/unit, 3.0 min setup/wave. |

## Methods

- **Event-driven simulation**: orders arrive at a known minute; a free picker immediately forms a wave from the arrived-but-unpicked pool. No future order is visible to an online policy.
- **Online single-order**: one invoice per wave, released as soon as a picker is free. This is the no-batching control.
- **Online EDF fill**: take the available order with the earliest cutoff, then fill the wave with same-tier available orders up to wave capacity. The wave is dispatched immediately.
- **Online savings**: re-run the tier-aware Clarke-Wright merge over the available pool and dispatch the cluster containing the earliest order. This uses only past arrivals.
- **Online savings + wait**: same cluster rule, but an idle picker waits up to the declared window while the candidate cluster is below the fill target. The next arrival can join the cluster.
- **Offline reference**: all orders are visible at 08:00; tier-aware savings is solved once and scheduled EDF. It isolates the value of future information for the savings rule, but it is not a lower bound across all batching rules.

## Arrival profile

| 承诺层 | 截单 | 订单 | 开班前 | 开班前占比 | 班中到达 | 到达窗口 (min) | 平均到达 | 中位到达 | 截单后到达 |
|---|---|---|---|---|---|---|---|---|---|
| 特快 | 12:00 | 40 | 28 | 70.0% | 12 | 120 | 14.2 | 0.0 | 0 |
| 标准 | 16:00 | 100 | 50 | 50.0% | 50 | 360 | 86.2 | 3.9 | 0 |
| 经济 | 18:00 | 60 | 24 | 40.0% | 36 | 480 | 145.5 | 63.1 | 0 |

Seeded arrival draw: `42`. The arrival window is a policy assumption; Online Retail II has invoice dates, not intra-day release times.

## Scenario comparison

| 方案 | 类型 | 波次 | 单均工时 | 准时率 | 迟到单 | 迟到订单分钟 | 平均等待 | P90 等待 | 最大等待 | 空闲分钟 | Makespan | 加班 (min) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 在线按单释放 | 在线 | 200 | 8.31 | 57.5% | 85 | 8,632 | 319.4 | 634.6 | 682.2 | 1 | 831 | 231 |
| 在线 EDF 即时装满 | 在线 | 35 | 5.10 | 100.0% | 0 | 0 | 147.5 | 369.2 | 404.2 | 6 | 513 | 0 |
| 在线节省重批 | 在线 | 41 | 5.16 | 100.0% | 0 | 0 | 150.4 | 393.8 | 475.2 | 14 | 524 | 0 |
| 在线节省 + 等待凑波（15 min / ≥4 单） | 在线 | 39 | 5.13 | 100.0% | 0 | 0 | 170.6 | 435.3 | 536.9 | 100 | 563 | 0 |
| 在线节省 + 激进等待（30 min / ≥6 单） | 在线 | 36 | 5.07 | 71.0% | 58 | 2,048 | 244.2 | 552.1 | 642.4 | 356 | 685 | 85 |
| 离线参考（全量已知） | 离线 | 36 | 5.05 | 100.0% | 0 | 0 | — | — | — | 6 | 509 | 0 |

On-time is counted per order against its own cutoff at wave completion. Waiting time is measured from arrival to wave start; idle minutes are paid picker capacity that is not picking.

## Wait-policy tuning

Same order pool, promise plan and arrival draw; only the wait window and fill target change. A zero wait reproduces the no-wait savings policy.

| 等待窗口 (min) | 最小成波单数 | 波次 | 单均工时 | 准时率 | 迟到订单分钟 | 平均等待 | P90 等待 | 最大等待 | 空闲分钟 | Makespan |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 4 | 41 | 5.16 | 100.0% | 0 | 150.4 | 393.8 | 475.2 | 14 | 524 |
| 0 | 6 | 41 | 5.16 | 100.0% | 0 | 150.4 | 393.8 | 475.2 | 14 | 524 |
| 0 | 8 | 41 | 5.16 | 100.0% | 0 | 150.4 | 393.8 | 475.2 | 14 | 524 |
| 10 | 4 | 38 | 5.11 | 100.0% | 0 | 162.9 | 420.6 | 512.6 | 80 | 551 |
| 10 | 6 | 38 | 5.11 | 98.5% | 1 | 196.6 | 471.5 | 561.9 | 179 | 600 |
| 10 | 8 | 37 | 5.10 | 96.5% | 76 | 211.6 | 489.3 | 580.0 | 225 | 622 |
| 20 | 4 | 38 | 5.12 | 100.0% | 0 | 191.4 | 475.5 | 572.1 | 174 | 599 |
| 20 | 6 | 35 | 5.05 | 85.0% | 598 | 223.2 | 519.2 | 613.9 | 281 | 645 |
| 20 | 8 | 36 | 5.07 | 63.5% | 4,304 | 289.9 | 590.3 | 682.5 | 419 | 717 |
| 30 | 4 | 37 | 5.09 | 93.0% | 137 | 201.3 | 497.9 | 589.1 | 231 | 625 |
| 30 | 6 | 36 | 5.07 | 71.0% | 2,048 | 244.2 | 552.1 | 642.4 | 356 | 685 |
| 30 | 8 | 36 | 5.06 | 63.5% | 4,717 | 300.8 | 593.0 | 683.2 | 433 | 723 |

## Load sensitivity

The same arrival assumptions are applied to progressively larger order pools. Low load tests whether waiting can fill waves without risking service; high load tests the cost of waiting behind a deep backlog.

| 订单数 | 方案 | 波次 | 单均工时 | 准时率 | 迟到订单分钟 | 平均等待 | 空闲分钟 | Makespan |
|---|---|---|---|---|---|---|---|---|
| 60 | 在线按单释放 | 60 | 9.12 | 100.0% | 0 | 54.9 | 198 | 373 |
| 60 | 在线 EDF 即时装满 | 33 | 7.41 | 100.0% | 0 | 23.7 | 301 | 373 |
| 60 | 在线节省重批 | 32 | 7.35 | 100.0% | 0 | 30.0 | 304 | 373 |
| 60 | 在线节省 + 等待凑波（15 min / ≥4 单） | 25 | 6.92 | 100.0% | 0 | 39.7 | 330 | 373 |
| 60 | 在线节省 + 激进等待（30 min / ≥6 单） | 15 | 6.26 | 100.0% | 0 | 91.8 | 381 | 378 |
| 60 | 离线参考（全量已知） | 13 | 6.09 | 100.0% | 0 | — | 4 | 185 |
| 120 | 在线按单释放 | 120 | 8.46 | 100.0% | 0 | 162.9 | 5 | 510 |
| 120 | 在线 EDF 即时装满 | 35 | 5.74 | 100.0% | 0 | 70.3 | 244 | 467 |
| 120 | 在线节省重批 | 36 | 5.77 | 100.0% | 0 | 71.6 | 240 | 467 |
| 120 | 在线节省 + 等待凑波（15 min / ≥4 单） | 31 | 5.58 | 100.0% | 0 | 92.6 | 264 | 467 |
| 120 | 在线节省 + 激进等待（30 min / ≥6 单） | 24 | 5.34 | 100.0% | 0 | 174.3 | 359 | 500 |
| 120 | 离线参考（全量已知） | 24 | 5.32 | 100.0% | 0 | — | 0 | 319 |
| 200 | 在线按单释放 | 200 | 8.31 | 57.5% | 8,632 | 319.4 | 1 | 831 |
| 200 | 在线 EDF 即时装满 | 35 | 5.10 | 100.0% | 0 | 147.5 | 6 | 513 |
| 200 | 在线节省重批 | 41 | 5.16 | 100.0% | 0 | 150.4 | 14 | 524 |
| 200 | 在线节省 + 等待凑波（15 min / ≥4 单） | 39 | 5.13 | 100.0% | 0 | 170.6 | 100 | 563 |
| 200 | 在线节省 + 激进等待（30 min / ≥6 单） | 36 | 5.07 | 71.0% | 2,048 | 244.2 | 356 | 685 |
| 200 | 离线参考（全量已知） | 36 | 5.05 | 100.0% | 0 | — | 6 | 509 |

## Schedule detail — online savings + wait

| 波次 | 拣货员 | 开始 | 结束 | 工时 (min) | 订单 | 最紧截单 | 迟到单 | 最大迟到 (min) |
|---|---|---|---|---|---|---|---|---|
| W1 | P1 | 08:00 | 08:25 | 24.7 | 7 | 12:00 | 0 | 0 |
| W2 | P2 | 08:00 | 08:24 | 24.3 | 6 | 12:00 | 0 | 0 |
| W3 | P2 | 08:24 | 08:53 | 28.3 | 7 | 12:00 | 0 | 0 |
| W4 | P1 | 08:39 | 08:49 | 10.3 | 4 | 12:00 | 0 | 0 |
| W5 | P1 | 08:49 | 09:26 | 37.0 | 5 | 12:00 | 0 | 0 |
| W6 | P2 | 08:53 | 09:27 | 33.9 | 5 | 12:00 | 0 | 0 |
| W7 | P1 | 09:26 | 09:48 | 21.6 | 4 | 12:00 | 0 | 0 |
| W8 | P2 | 09:27 | 09:53 | 26.7 | 4 | 16:00 | 0 | 0 |
| W9 | P1 | 10:05 | 10:20 | 15.5 | 2 | 12:00 | 0 | 0 |
| W10 | P2 | 10:05 | 10:31 | 26.5 | 8 | 16:00 | 0 | 0 |

## Interpretation

1. **Batching, not forecasting, is the first lever.** Releasing one order per wave needs 8.31 min/order and reaches 57.5% on-time; filling the same arrived pool to wave capacity drops it to 5.10 min/order and reaches 100.0%. The fill rule uses no future information. The no-batching control is only safe while capacity is ample: it still meets every cutoff at 60/120 orders, but not at 200.
2. **Online fill is within 1.0% of the offline reference on labor.** The offline reference needs 5.05 min/order and 36 waves; online EDF fill returns 5.10 min/order and 35 waves, both at 100.0% on-time. The reference sees the whole day but uses a different batching rule, so this is not a like-for-like comparison, and it is not proof that the online rule is optimal.
3. **Future information is worth something even under the same rule.** Seeing all orders at 08:00 saves 5 waves (41 → 36) and 0.11 min/order (5.16 → 5.05) for the savings rule. The online version still reaches 100.0% on-time with 0 late order-minutes, so at this load the information gap shows up in labor rather than service.
4. **A short wait buys little at this load.** A 15-min window with a fill target of 4 changes 41 → 39 waves and saves 0.03 min/order (0.6%), but adds 20.3 min of average waiting, 86 idle picker-minutes and 40 minutes of makespan. On-time is unchanged at 100.0%.
5. **An aggressive wait crosses the service cliff.** Saving 0.09 min/order (1.8%) costs 58 tardy orders and 2,048 late order-minutes: on-time falls from 100.0% to 71.0%, and average waiting rises to 244.2 min. The wait window is a service-level decision, not a free labor knob.
6. **The same aggressive wait turns from free to harmful as load rises.** At 60 orders it saves 1.09 min/order while staying at 100.0% on-time. At 120 orders the aggressive wait is still safe and lands on 24 waves at 5.34 min/order, close to the offline reference's 24 waves at 5.32. At 200 orders it saves only 0.09 min/order and drops on-time to 71.0% with 2,048 late order-minutes. The wait window should scale with the backlog instead of being a fixed constant.
7. **The result is a simulation, not a forecast.** Arrival times, onsite shares, promise tiers, picker count and labor minutes are declared assumptions. The useful claim is conditional: under this arrival process and this capacity, immediate fill-to-capacity protects service, while waiting only pays when the queue is thin.

## Limitations

- Arrival timestamps, per-tier onsite shares and arrival windows are synthetic. Online Retail II records an invoice date, not the minute an order was released to the warehouse.
- The arrival draw is uniform within each tier window; it has no intra-day burstiness, no order cancellations, and no due-date changes after arrival.
- Online policies see the arrived pool only. They do not forecast future arrivals, and they do not re-optimise picker assignment when a wave finishes early.
- The wait rule only considers the next arrival and a single fill target. It is a heuristic, not a dynamic programme over the arrival distribution.
- The offline reference uses the same tier-aware savings rule and EDF; it is not a lower bound on labor or tardiness across all batching rules. The online fill rule can beat it on wave count while losing on travel.
- Pickers are identical and never blocked: no zones, skills, breaks, congestion, replenishment delays, or handover time between waves.
- One trading week, one warehouse layout, one arrival seed, and one promise mix. No stochastic robustness or confidence interval is reported.
- On-time is measured at wave completion against a declared cutoff; last-mile transit and customer-facing delivery promises are outside this layer.
