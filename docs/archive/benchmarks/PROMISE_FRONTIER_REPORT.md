# Promise-service frontier under daily replenishment (Week 23)

- Generated: `2026-10-28T18:54:59.692677+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Flow: **5** weekdays | day 0: 66 | day 1: 73 | day 2: 68 | day 3: 85 | day 4: 108
- Seeds: **30** | quote policies **['static', 'atp', 'atp_buffer', 'all_2', 'all_3', 'all_5']** | daily MILP **8s/day**

## Frontier definition

Two **two-dimensional** frontiers are reported, both with average quoted promise on the x-axis (shorter is better):

1. **原 SLA 前沿** — maximize the Week-20 fixed 2/3/5 OTIF; this is the customer-outcome frontier.
2. **quoted 前沿** — maximize the OTIF against the promise actually quoted; this is what a service dashboard would show.

A policy is marked **✔** on a frontier only if no other policy has both a shorter-or-equal average promise and a higher-or-equal service on that axis, with at least one strict improvement. The single-week snapshot is a reference and is excluded from both frontiers.

## Results

| 策略 | 报价 | quoted OTIF | 原 SLA OTIF | 平均承诺 | 2 天占比 | fill | 失败订单 | backlog | 原 SLA 前沿 | quoted 前沿 |
|---|---|---|---|---|---|---|---|---|---|---|
| 单周一次性快照 | 固定 2/3/5 | 52.0% | 52.0% | 3.10 | 30.0% | 82.9% | 192.0 | 5,647 | — | — |
| 每日 1 天补货 | 固定 2/3/5 | 86.8% | 86.8% | 3.10 | 30.0% | 98.0% | 53.0 | 657 | ✔ | 被 all_3 支配 |
| 每日 1 天补货 | ATP | 93.8% | 84.5% | 3.62 | 0.0% | 98.7% | 25.0 | 444 | 被 static 支配 | ✔ |
| 每日 1 天补货 | ATP+缓冲 | 95.0% | 84.5% | 5.00 | 0.0% | 98.1% | 20.0 | 620 | 被 static 支配 | ✔ |
| 每日 1 天补货 | 全部 2 天 | 65.7% | 78.0% | 2.00 | 100.0% | 96.3% | 137.0 | 1,239 | ✔ | ✔ |
| 每日 1 天补货 | 全部 3 天 | 92.5% | 82.0% | 3.00 | 0.0% | 98.2% | 30.0 | 581 | ✔ | ✔ |
| 每日 1 天补货 | 全部 5 天 | 95.0% | 84.0% | 5.00 | 0.0% | 98.5% | 20.0 | 503 | 被 static 支配 | ✔ |

## Findings

- **Two frontiers, not one winner.** The original-SLA frontier has 3 policies (固定 2/3/5、全部 2 天、全部 3 天); the quoted frontier has 5 (ATP、ATP+缓冲、全部 2 天、全部 3 天、全部 5 天). The difference is the point of the exercise: rewriting the promise moves a policy onto the quoted frontier without moving it onto the original-SLA frontier.
- **Daily replenishment still dominates the one-shot snapshot.** The baseline quoted OTIF is 52.0%; the best daily policy reaches 95.0%. The inventory decision is larger than which quote policy is used.
- **The fixed 2/3/5 mix is the shortest-promise policy that keeps the original SLA high.** It delivers 86.8% original SLA at 3.10 average days. `all_2` is shorter (2.00 days) but only 78.0% on the original SLA.
- **ATP is not on the original-SLA frontier.** It reaches 93.8% quoted OTIF, but its original SLA is 84.5% at 3.62 days; the fixed mix gives 86.8% at 3.10 days. ATP is therefore dominated on the customer-outcome axis (`static` has both a shorter promise and a higher original SLA), even though it is non-dominated on the quoted axis.
- **`all_5` is a quoted-metric extreme, not a service improvement.** It gives 95.0% quoted OTIF vs 86.8% for the fixed mix, but the original SLA is 84.0% vs 86.8% and the average promise is 5.00 vs 3.10 days. It is on the quoted frontier, not on the original-SLA frontier.
- **The quoted-vs-original gap is the warning.** `all_5` is +1.2 pp vs ATP on quoted OTIF but -0.5 pp on the original SLA; a dashboard that only shows the quoted number can rank a policy first while customers receive later deliveries.
- **Solver variation is visible.** These numbers are from a fresh CP-SAT run; the same configuration in Week 22 differed by a few tenths of a point on some cells (for example ATP quoted 95.0% vs 93.8%). The time-limited MILP is not bit-for-bit reproducible across runs; treat differences below ~1 pp as solver noise, not a policy effect.
- **Scope.** One week, one inventory/layout/labor model, deterministic 30-seed draw duplicated across policies. Quote tiers and transit days are declared; the frontier is a within-instance comparison, not a transferable service curve.

## Limitations

- 每个报价方案都重新求解日滚动分单；quote 同时是分单截止期，因此 fill/backlog 会随方案变化，前沿不是纯文案比较。
- ATP 只按当天开始时的在库量报价，不预留在途补货、未来到达或跨订单库存；同一天多张订单可能同时报 2 天。
- 旧订单保留到达时的绝对承诺日，不改单/不重报价；不模拟客户接受/拒绝/取消。
- 日滚动每天只允许当天发车（max_days=0）；单周基线允许 3 天且把所有订单视作周一。
- 分单后不接收拣选/发车/门位失败的回写；补货是声明 order-up-to，1/2 天前置期，不做预测/MOQ/供应商产能/DC 调拨。
- 30 个种子在本配置下 OTIF/交付日完全相同，前沿上的点是确定性边界，不是 30 个独立样本。
- 原 SLA 用 Week-20 固定 2/3/5 承诺，不是客户真实容忍度；只验证 1 周、1 套库存/布局/劳动力。
- Pareto 只在本次观测到的策略集合内成立；all_2/all_3/all_5 是压力测试，不代表商业上可接受的承诺菜单。
