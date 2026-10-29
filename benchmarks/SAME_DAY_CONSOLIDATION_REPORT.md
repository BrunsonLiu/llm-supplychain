# Same-day dispatch consolidation (Week 26)

- Generated: `2026-10-29T11:13:34.702864+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Flow: **5** weekdays | day 0: 66 | day 1: 73 | day 2: 68 | day 3: 85 | day 4: 108
- Seeds: **30** | quote policies **['static', 'atp']** | doors/DC **[1, 2]** | dispatch modes **['immediate', 'same6', 'same12']**

## Question

Week 25 showed that one door starts blocking at high fill. Instead of adding a second door, can the warehouse hold parcels between the two same-day departures (13:00 and 19:00) to consolidate a load? The test is deliberately **same-day**: `max_days=0`, so no order is carried to the next day. `roll_rate` must stay 0 for the result to be a same-day lever.
The threshold is per lane (DC × destination country), not per DC: `min_load=6/12` means “wait for 6/12 tickets on this lane, otherwise use the last departure of the same day”.

## Results

| 策略 | 门位/DC | 发车方式 | quoted OTIF | 原 SLA | fill | 发车数 | 单/车 | 门位利用 | blocked/日 | roll | 等待(min) | dock 成本 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 每日补货 · 固定 2/3/5 | 1 | 立即发车（逐单） | 86.4% | 86.4% | 97.8% | 65.0 | 9.44 | 71.9% | 0.3 | 0.0% | 210 | 14,615 |
| 每日补货 · 固定 2/3/5 | 1 | 同日凑 6 单 | 86.5% | 86.5% | 97.8% | 61.6 | 9.96 | 68.4% | 0.0 | 0.0% | 238 | 13,909 |
| 每日补货 · 固定 2/3/5 | 1 | 同日凑 12 单 | 86.5% | 86.5% | 97.8% | 59.8 | 10.26 | 66.5% | 0.0 | 0.0% | 248 | 13,529 |
| 每日补货 · 固定 2/3/5 | 2 | 立即发车（逐单） | 86.5% | 86.5% | 97.8% | 65.2 | 9.41 | 36.1% | 0.0 | 0.0% | 210 | 14,674 |
| 每日补货 · 固定 2/3/5 | 2 | 同日凑 6 单 | 86.5% | 86.5% | 97.8% | 61.6 | 9.96 | 34.2% | 0.0 | 0.0% | 238 | 13,909 |
| 每日补货 · 固定 2/3/5 | 2 | 同日凑 12 单 | 86.5% | 86.5% | 97.8% | 59.8 | 10.26 | 33.3% | 0.0 | 0.0% | 248 | 13,529 |
| 每日补货 · ATP | 1 | 立即发车（逐单） | 93.3% | 82.8% | 98.5% | 69.9 | 8.76 | 77.1% | 2.8 | 0.0% | 219 | 15,713 |
| 每日补货 · ATP | 1 | 同日凑 6 单 | 94.5% | 83.5% | 98.5% | 62.5 | 9.89 | 69.4% | 0.0 | 0.0% | 247 | 14,125 |
| 每日补货 · ATP | 1 | 同日凑 12 单 | 94.5% | 83.5% | 98.5% | 60.0 | 10.31 | 66.8% | 0.0 | 0.0% | 259 | 13,593 |
| 每日补货 · ATP | 2 | 立即发车（逐单） | 94.5% | 83.5% | 98.5% | 72.7 | 8.51 | 40.0% | 0.0 | 0.0% | 220 | 16,341 |
| 每日补货 · ATP | 2 | 同日凑 6 单 | 94.5% | 83.5% | 98.5% | 62.5 | 9.89 | 34.7% | 0.0 | 0.0% | 247 | 14,125 |
| 每日补货 · ATP | 2 | 同日凑 12 单 | 94.5% | 83.5% | 98.5% | 60.0 | 10.31 | 33.4% | 0.0 | 0.0% | 259 | 13,593 |

## Findings

- **每日补货 · ATP, 1 door, 同日凑 6 单:** quoted OTIF 93.3% → 94.5% (+1.2 pp), blocked 2.8 → 0.0/day, departures 69.9 → 62.5, dock cost 15,713 → 14,125 (-10.1%), roll 0.0%.
- **每日补货 · ATP, 1 door, 同日凑 12 单:** quoted OTIF 93.3% → 94.5% (+1.2 pp), blocked 2.8 → 0.0/day, departures 69.9 → 60.0, dock cost 15,713 → 13,593 (-13.5%), roll 0.0%.
- **每日补货 · ATP, 2 door, 同日凑 6 单:** quoted OTIF 94.5% → 94.5% (+0.0 pp), blocked 0.0 → 0.0/day, departures 72.7 → 62.5, dock cost 16,341 → 14,125 (-13.6%), roll 0.0%.
- **每日补货 · ATP, 2 door, 同日凑 12 单:** quoted OTIF 94.5% → 94.5% (+0.0 pp), blocked 0.0 → 0.0/day, departures 72.7 → 60.0, dock cost 16,341 → 13,593 (-16.8%), roll 0.0%.
- **每日补货 · 固定 2/3/5, 1 door, 同日凑 6 单:** quoted OTIF 86.4% → 86.5% (+0.1 pp), blocked 0.3 → 0.0/day, departures 65.0 → 61.6, dock cost 14,615 → 13,909 (-4.8%), roll 0.0%.
- **每日补货 · 固定 2/3/5, 1 door, 同日凑 12 单:** quoted OTIF 86.4% → 86.5% (+0.1 pp), blocked 0.3 → 0.0/day, departures 65.0 → 59.8, dock cost 14,615 → 13,529 (-7.4%), roll 0.0%.
- **每日补货 · 固定 2/3/5, 2 door, 同日凑 6 单:** quoted OTIF 86.5% → 86.5% (+0.0 pp), blocked 0.0 → 0.0/day, departures 65.2 → 61.6, dock cost 14,674 → 13,909 (-5.2%), roll 0.0%.
- **每日补货 · 固定 2/3/5, 2 door, 同日凑 12 单:** quoted OTIF 86.5% → 86.5% (+0.0 pp), blocked 0.0 → 0.0/day, departures 65.2 → 59.8, dock cost 14,674 → 13,529 (-7.8%), roll 0.0%.
- **At one door, consolidation is a partial substitute for a second door.** ATP goes 93.3% → 94.5% and blocked 2.8 → 0.0; the 2-door immediate cell is 94.5%. The gain comes from fewer, larger same-day waves, not from holding to the next day.
- **Static matches the 2-door point estimate after consolidation.** 1-door immediate 86.4% → 86.5%; 2-door immediate is 86.5%. The 0.1 pp gain is within solver noise; the cleaner effects are blocked 0.3 → 0.0/day and the lower departure count.
- **12 is better than 6 on cost, equal on service.** At ATP/1 door, same6 and same12 both give 94.5%; same12 uses 60.0 vs 62.5 departures and costs 13,593 vs 14,125. The trade is about 12 more minutes of average waiting.
- **A second door is not required for this point estimate, but it is not operationally equivalent.** 1-door same12 has door utilization 66.8% and no blocked trucks; 2-door same12 has 33.4%. The second door buys peak/variability cushion that this deterministic run does not exercise.
- **Consolidation is not free in customer waiting.** Mean wait rises by roughly 30–44 minutes because more parcels use the 19:00 wave; in this model that is a small holding-cost line, but a real carrier cutoff or customer expectation could make it material.
- **Do not compare `dock_cost` across door levels.** Blocked departures do not run, so a 1-door cell can look cheaper while serving less. The valid comparison is immediate vs consolidated **within the same door and quote policy**.
- **The load factor is not the story.** Capacity is 300 orders/truck; the observed load factor is only ~3%, so these are not “full trucks”. The saving is fewer departure events (`dispatch_cost=220` each), not cube utilization.
- **`roll_rate=0` is the key scope check.** If a run shows positive roll, it is no longer same-day consolidation and the delivery-day comparison is contaminated by next-day holding.
- **Static's service effect is not robust across repeat runs.** Two runs of the same static/1-door/immediate cell gave 85.7–86.4% and 0.3–2.3 blocked trucks/day; the departure/cost saving is stable, but static's +0.1 pp is not. ATP's 2.8→0 blocked and +1.2 pp were directionally stable in both runs, but this is still one week and one inventory/layout.

## Limitations

- 只做同日集批：max_days=0、hold_day=0，订单只在当天 13:00/19:00 两班之间等待；roll_rate 必须为0，否则已不是同日口径。
- min_load 是每条 lane（DC × 目的国）的门槛，不是每个 DC 的总单量；没有跨 lane/跨 DC 拼车。
- 容量是 300 单/车，实测装载率只有约 3%，所以节省来自减少发车事件（220/车），不是装满车厢/体积。
- dock 成本只含发车 + 等待（0.15/单/小时），不含门位固定成本、司机工资、承运商阶梯价、迟到赔付；不能跨门位比较 dock_cost，因为 blocked 的车没有发。
- 门位是每日分钟预算（480 分钟、75 分钟/车 + 0.5 分钟/票），不是具体门位占用；未模拟叉车、装卸工排班、司机等待。
- ATP 只按当天开始时的在库量报价，不预留在途/未来/跨订单库存；旧订单不重报价，不模拟客户接受/取消。
- 日滚动每天只允许当天发车（max_days=0）；分单后不接收拣选/发车/门位失败的回写；补货是声明 order-up-to，1/2 天前置期。
- 30 个种子在本配置下 OTIF/交付日完全相同；不是 30 个独立样本。
- MILP 时间预算下同一配置不同运行可差约 1.5pp；只验证 1 周、1 套库存/布局/劳动力。
