# Promise policy x dock doors (Week 25)

- Generated: `2026-10-28T19:23:59.193603+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Flow: **5** weekdays | day 0: 66 | day 1: 73 | day 2: 68 | day 3: 85 | day 4: 108
- Seeds: **30** | quote policies **['static', 'atp', 'all_3', 'all_5']** | doors/DC **[0, 1, 2]** | door window **480 min/day**

## Question

Week 21 found the dock was second-order under the fixed 2/3/5 promise: 0→1 door cost about 0.4 pp. Week 22/23 then showed ATP/all_3 can raise fill. This run asks whether that higher fill shifts the bottleneck to the dock. The door model is the same as Week 21: 480 minutes/day, 75 min/truck + 0.5 min/ticket, one picker per DC.

## Results

| 策略 | 报价 | 门位/DC | quoted OTIF | 原 SLA OTIF | 平均承诺 | fill | 失败订单 | backlog | 门位利用 | door blocked |
|---|---|---|---|---|---|---|---|---|---|---|
| 单周快照 | 固定 2/3/5 | — | 53.7% | 53.7% | 3.10 | 83.0% | 185.0 | 5,635 | 0.0% | 0.0 |
| 每日补货 · 固定 2/3/5 | 固定 2/3/5 | 0 | 86.0% | 86.0% | 3.10 | 97.7% | 56.0 | 745 | 0.0% | 0.0 |
| 每日补货 · 固定 2/3/5 | 固定 2/3/5 | 1 | 85.0% | 85.0% | 3.10 | 97.7% | 59.9 | 745 | 70.7% | 1.4 |
| 每日补货 · 固定 2/3/5 | 固定 2/3/5 | 2 | 86.0% | 86.0% | 3.10 | 97.7% | 56.0 | 745 | 36.1% | 0.0 |
| 每日补货 · ATP | ATP | 0 | 95.3% | 84.5% | 3.66 | 98.1% | 19.0 | 618 | 0.0% | 0.0 |
| 每日补货 · ATP | ATP | 1 | 92.7% | 82.9% | 3.66 | 98.1% | 29.1 | 618 | 76.0% | 3.8 |
| 每日补货 · ATP | ATP | 2 | 95.3% | 84.5% | 3.66 | 98.1% | 19.0 | 618 | 40.0% | 0.0 |
| 每日补货 · 全部 3 天 | 全部 3 天 | 0 | 93.3% | 83.5% | 3.00 | 98.2% | 27.0 | 601 | 0.0% | 0.0 |
| 每日补货 · 全部 3 天 | 全部 3 天 | 1 | 92.8% | 83.3% | 3.00 | 98.2% | 28.6 | 601 | 73.8% | 0.9 |
| 每日补货 · 全部 3 天 | 全部 3 天 | 2 | 93.3% | 83.5% | 3.00 | 98.2% | 27.0 | 601 | 37.4% | 0.0 |
| 每日补货 · 全部 5 天 | 全部 5 天 | 0 | 95.5% | 85.2% | 5.00 | 98.8% | 18.0 | 393 | 0.0% | 0.0 |
| 每日补货 · 全部 5 天 | 全部 5 天 | 1 | 92.2% | 83.0% | 5.00 | 98.8% | 31.0 | 393 | 76.5% | 3.7 |
| 每日补货 · 全部 5 天 | 全部 5 天 | 2 | 95.5% | 85.2% | 5.00 | 98.8% | 18.0 | 393 | 40.2% | 0.0 |

## Findings

- **固定 2/3/5: 0→1 door** quoted OTIF 86.0% → 85.0% (-1.0 pp), original SLA -1.0 pp, door utilization 70.7%, blocked 1.4 orders/day. The higher fill from this quote policy does make the dock bind.
  **1→2 doors** restores +1.0 pp to quoted 86.0% (blocked 0.0, utilization 36.1%). A second door is enough to clear the modeled queue here.
- **ATP: 0→1 door** quoted OTIF 95.3% → 92.7% (-2.5 pp), original SLA -1.6 pp, door utilization 76.0%, blocked 3.8 orders/day. The higher fill from this quote policy does make the dock bind.
  **1→2 doors** restores +2.5 pp to quoted 95.3% (blocked 0.0, utilization 40.0%). A second door is enough to clear the modeled queue here.
- **全部 3 天: 0→1 door** quoted OTIF 93.3% → 92.8% (-0.4 pp), original SLA -0.2 pp, door utilization 73.8%, blocked 0.9 orders/day. The higher fill from this quote policy does make the dock bind.
  **1→2 doors** restores +0.4 pp to quoted 93.3% (blocked 0.0, utilization 37.4%). A second door is enough to clear the modeled queue here.
- **全部 5 天: 0→1 door** quoted OTIF 95.5% → 92.2% (-3.2 pp), original SLA -2.3 pp, door utilization 76.5%, blocked 3.7 orders/day. The higher fill from this quote policy does make the dock bind.
  **1→2 doors** restores +3.2 pp to quoted 95.5% (blocked 0.0, utilization 40.2%). A second door is enough to clear the modeled queue here.
- **The promise effect is larger than the door effect at 0 doors.** ATP moves quoted OTIF from 86.0% to 95.3% (+9.3 pp), while 0→1 door moves the fixed policy by -1.0 pp. Promise and inventory still dominate the dock.
- **Week 21's “door is second-order” was conditional.** At the Week-21 fixed-promise fill it was second-order; at the 97.7–98.8% fill reached by daily replenishment + ATP/all_5, one door blocks 1.4–3.8 trucks/day and costs 0.4–3.2 pp. The bottleneck can move to the dock when upstream service improves, so the door layer must be re-checked after a quote/inventory change.
- **The all_3 loss is within solver noise.** Its 0→1 door delta is only 0.4 pp, so it should not be read as a standalone service effect; the 0.9 blocked trucks/day is the cleaner signal that the door starts to bind.
- **Do not read 0 doors as “free”.** 0 doors means no declared door-minute budget in this model, not unlimited real-world loading; the comparison is about whether the modeled dock minute budget binds.
- **Same-config spread is about 1.5 pp.** The static/accept-all daily cell was 87.5% quoted / 96.2% fill in Week 24 and 86.0% / 97.7% here under the same budget, so the static (−1.0 pp) and all_3 (−0.4 pp) door deltas are not clean policy effects. The ATP (−2.5 pp) and all_5 (−3.3 pp) drops plus their 3.7–3.8 blocked trucks/day are the stronger evidence; the 2-door restoration is consistent across all four policies.

## Limitations

- 门位是每日分钟预算（480 分钟、75 分钟/车 + 0.5 分钟/票），不是具体门位占用；未模拟叉车、装卸工排班、司机等待。
- 0 门位表示模型中没有门位分钟预算，不是无限真实装卸能力；结论只针对该预算是否绑定。
- 每个报价策略重解日滚动分单，quote 同时是分单截止期，fill/backlog 会随策略变化；门位差异与分单差异混合。
- ATP 只按当天开始时的在库量报价，不预留在途/未来/跨订单库存；旧订单不重报价，不模拟客户接受/取消。
- 日滚动每天只允许当天发车（max_days=0）；单周基线允许 3 天且所有订单视作周一。
- 分单后不接收拣选/发车/门位失败的回写；补货是声明 order-up-to，1/2 天前置期。
- 30 个种子在本配置下 OTIF/交付日完全相同；不是 30 个独立样本。
- MILP 时间预算下同一配置不同运行可差约 1pp；只验证 1 周、1 套库存/布局/劳动力。
