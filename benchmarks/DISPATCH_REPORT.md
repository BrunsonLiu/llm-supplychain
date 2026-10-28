# Outbound dispatch and carrier cutoffs (Week 16)

- Generated: `2026-10-28T11:22:44.114473+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Seeds: **30** | cells: **10** | pickers/DC: **1** | shift **600 min**
- Allocation: **MILP 拣选容量感知（Week-9 分单）** (FEASIBLE) | allocation OTIF ceiling **53.0%** | solver **60 s**
- Dock cost: **€220/departure** + **€0.15/order-hour** | longest hold **24.0 h**

## Assumptions

| Item | Assumption | Note |
|---|---|---|
| Departures | 13:00 and 19:00 per DC, plus single-departure variants 13:00 / 15:00 / 19:00 | declared line-haul timetable, relative to the 08:00 shift |
| Carrier cutoff | departure minus 30 min | declared load-close buffer; a missed ticket rolls to the next departure |
| Lane | DC × destination country | orders on one lane can consolidate; they never share a truck across countries |
| Truck capacity | 300 orders / departure | declared ceiling; not binding in this instance, so the timetable is compared on timing, not rationing |
| Dispatch policy | immediate / hold to 6 / promise-aware 6 and 10 | declared rules; the promise rule holds to the last departure that still meets the promise |
| Promise deadline | dispatch day ≤ promise days − transit days | derived from the Week-8 promise and transit geometry; no carrier SLA data exists |
| Dock cost | €220 per departure + €0.15 per order-hour | declared planning rates, used only to compare cells |
| Arrivals | prior-week empirical curves (Week 15) | only the dock layer is new; allocation, stock, layout and pick cutoffs are unchanged |

## Cells

| Cell | Policy | Departures | Min load | Pickers / DC | Pick noise σ |
|---|---|---|---|---|---|
| 仅拣选截单（Week-15 口径） | 无（仅拣选截单） | — | — | — | 0.00 |
| 双班 13:00/19:00 · 即时发车 | 即时发车 | 13:00, 19:00 | — | — | 0.00 |
| 双班 · 凑 6 单/日终 | 凑批 / 日终 | 13:00, 19:00 | 6 | — | 0.00 |
| 双班 · 承诺感知 6 单 | 承诺感知 | 13:00, 19:00 | 6 | — | 0.00 |
| 双班 · 承诺感知 10 单 | 承诺感知 | 13:00, 19:00 | 10 | — | 0.00 |
| 单班 13:00 · 即时发车 | 即时发车 | 13:00 | — | — | 0.00 |
| 单班 15:00 · 即时发车 | 即时发车 | 15:00 | — | — | 0.00 |
| 单班 19:00 · 即时发车 | 即时发车 | 19:00 | — | — | 0.00 |
| 承诺感知 6 单 · 噪声 σ=0.25 | 承诺感知 | 13:00, 19:00 | 6 | — | 0.25 |
| 承诺感知 6 单 · 加 1 名拣货员/DC | 承诺感知 | 13:00, 19:00 | 6 | 2 | 0.00 |

## Service: pick cutoff versus delivery

Pick-cutoff OTIF is the Week 9-15 definition (every ticket finished before 12:00/16:00/18:00). Dock OTIF is the customer definition: every leg is shipped and `departure day + transit days ≤ promise days`.

| Cell | Pick-cutoff OTIF | Dock OTIF | Dock − pick | Roll to next day | Mean wait (min) |
|---|---|---|---|---|---|
| 仅拣选截单（Week-15 口径） | 36.8% | 36.8% | +0.0 pp | 0.0% | 0 |
| 双班 13:00/19:00 · 即时发车 | 36.8% | 53.0% | +16.2 pp | 9.3% | 275 |
| 双班 · 凑 6 单/日终 | 36.8% | 53.0% | +16.2 pp | 9.3% | 283 |
| 双班 · 承诺感知 6 单 | 36.8% | 53.0% | +16.2 pp | 9.8% | 293 |
| 双班 · 承诺感知 10 单 | 36.8% | 53.0% | +16.2 pp | 9.7% | 295 |
| 单班 13:00 · 即时发车 | 36.8% | 40.5% | +3.8 pp | 60.6% | 830 |
| 单班 15:00 · 即时发车 | 36.8% | 46.5% | +9.8 pp | 41.6% | 676 |
| 单班 19:00 · 即时发车 | 36.8% | 53.0% | +16.2 pp | 9.3% | 450 |
| 承诺感知 6 单 · 噪声 σ=0.25 | 35.3% | 53.0% | +17.7 pp | 11.4% | 305 |
| 承诺感知 6 单 · 加 1 名拣货员/DC | 53.0% | 53.0% | +0.0 pp | 0.9% | 220 |

Two departures at 13:00/19:00 deliver **53.0%** against an allocation ceiling of **53.0%**: the dock itself loses **0.0 pp** on this instance.

## Departures, consolidation and cost

| Cell | Departures | Orders / departure | Dispatch cost (€) | Holding cost (€) | Dock cost (€) |
|---|---|---|---|---|---|
| 仅拣选截单（Week-15 口径） | 0.0 | 0.0 | 0 | 0 | 0 |
| 双班 13:00/19:00 · 即时发车 | 30.8 | 21.1 | 6,769 | 447 | 7,215 |
| 双班 · 凑 6 单/日终 | 26.2 | 24.8 | 5,764 | 459 | 6,223 |
| 双班 · 承诺感知 6 单 | 26.1 | 24.9 | 5,735 | 475 | 6,210 |
| 双班 · 承诺感知 10 单 | 25.3 | 25.7 | 5,559 | 479 | 6,038 |
| 单班 13:00 · 即时发车 | 27.5 | 23.6 | 6,050 | 1,346 | 7,396 |
| 单班 15:00 · 即时发车 | 26.4 | 24.6 | 5,808 | 1,097 | 6,905 |
| 单班 19:00 · 即时发车 | 22.3 | 29.2 | 4,899 | 731 | 5,629 |
| 承诺感知 6 单 · 噪声 σ=0.25 | 26.4 | 24.6 | 5,801 | 494 | 6,295 |
| 承诺感知 6 单 · 加 1 名拣货员/DC | 23.5 | 27.6 | 5,170 | 357 | 5,527 |

## Paired differences on dock OTIF

Every comparison uses the same seed set and the same allocation, so the paired difference isolates the dispatch change. The interval is the 95% CI of the per-seed difference.

| Comparison | Metric | Δ mean | 95% CI | Win rate | Tie rate | n |
|---|---|---|---|---|---|---|
| 双班 13:00/19:00 · 即时发车 − 仅拣选截单（Week-15 口径） | 交付 OTIF（含发车） | +16.2 pp | ±0.5 pp | 100.0% | 0.0% | 30 |
| 双班 · 凑 6 单/日终 − 双班 13:00/19:00 · 即时发车 | 交付 OTIF（含发车） | 0.0 pp | ±0.00 pp | 0.0% | 100.0% | 30 |
| 双班 · 承诺感知 6 单 − 双班 · 凑 6 单/日终 | 交付 OTIF（含发车） | 0.0 pp | ±0.00 pp | 0.0% | 100.0% | 30 |
| 双班 · 承诺感知 10 单 − 双班 13:00/19:00 · 即时发车 | 交付 OTIF（含发车） | 0.0 pp | ±0.00 pp | 0.0% | 100.0% | 30 |
| 单班 13:00 · 即时发车 − 双班 13:00/19:00 · 即时发车 | 交付 OTIF（含发车） | -12.5 pp | ±0.4 pp | 0.0% | 0.0% | 30 |
| 单班 15:00 · 即时发车 − 双班 13:00/19:00 · 即时发车 | 交付 OTIF（含发车） | -6.5 pp | ±0.4 pp | 0.0% | 0.0% | 30 |
| 单班 19:00 · 即时发车 − 双班 13:00/19:00 · 即时发车 | 交付 OTIF（含发车） | 0.0 pp | ±0.00 pp | 0.0% | 100.0% | 30 |
| 承诺感知 6 单 · 噪声 σ=0.25 − 双班 · 承诺感知 6 单 | 交付 OTIF（含发车） | 0.0 pp | ±0.00 pp | 0.0% | 93.3% | 30 |
| 承诺感知 6 单 · 加 1 名拣货员/DC − 双班 · 承诺感知 6 单 | 交付 OTIF（含发车） | 0.0 pp | ±0.00 pp | 0.0% | 100.0% | 30 |

## Lane detail (seed 1, promise-aware 6)

The lane table is one representative seed. Lanes sharing a DC but shipping to different countries are separate departures even when they leave at the same minute.

| DC | Lane | Tickets | Units | Departures | Mean wait (min) | Roll rate |
|---|---|---|---|---|---|---|
| London | United Kingdom | 225 | 9,461 | 3 | 326 | 15.6% |
| Frankfurt | United Kingdom | 195 | 8,826 | 3 | 337 | 16.4% |
| Rotterdam | United Kingdom | 187 | 7,408 | 2 | 196 | 0.0% |
| Frankfurt | France | 10 | 702 | 1 | 442 | 0.0% |
| Frankfurt | Germany | 9 | 511 | 2 | 494 | 11.1% |
| Rotterdam | France | 6 | 79 | 1 | 419 | 0.0% |
| London | EIRE | 2 | 19 | 1 | 361 | 0.0% |
| London | France | 2 | 31 | 1 | 455 | 0.0% |
| London | Germany | 2 | 38 | 1 | 76 | 0.0% |
| Rotterdam | Germany | 2 | 46 | 1 | 404 | 0.0% |
| Frankfurt | Denmark | 1 | 109 | 1 | 2,462 | 100.0% |
| Frankfurt | Finland | 1 | 71 | 1 | 382 | 0.0% |

## Findings

- **The pick cutoff is not the customer promise.** Scoring the same picks at delivery lifts OTIF from 36.8% to 53.0% +16.2 pp (±0.5), win rate 100.0%. The 12:00/16:00/18:00 cutoffs embed a multi-hour buffer before the 19:00 departure; Week 9-15 OTIF is therefore a warehouse KPI that understates customer service by roughly 16 pp on this instance.
- **The dock is not the bottleneck.** With two departures the dock converts 53.0% of orders against an allocation ceiling of 53.0%; stock and DC assignment, not the line-haul, set the service level. The dock only creates loss when a ticket finishes after the last carrier cutoff (18:30 here).
- **Consolidation is nearly free.** Holding to 6 orders or the end of the day changes dock OTIF by +0.0 pp (±0.0) while removing **4.6 departures/day** and **€1,005/day** of declared dispatch cost. Loads rise from 21.1 to 24.8 tickets per departure.
- **One late departure is free service-wise.** Dropping the 13:00 run and keeping only 19:00 changes OTIF by +0.0 pp (±0.0) while removing **8.5 departures/day**; the price is **+175 min** average dock dwell. A carrier that consolidates to a single evening trailer does not hurt the customer promise here.
- **A single early cutoff costs service.** Moving to one 15:00 departure moves dock OTIF by **-6.5 pp (±0.4)**: tickets finished after 14:30 roll to the next day and express orders with `transit = promise` miss. The same mechanism moves OTIF by -12.5 pp (±0.4) at a single 13:00 departure.
- **The dock buffer absorbs pick noise.** Lognormal σ=0.25 moves the pick-cutoff rate by -1.5 pp but dock OTIF by -0.02 pp (±0.02): the same late tickets still catch the evening trailer. Noise would bite only if it pushed work past 18:30.
- **Extra picking capacity cannot beat the allocation ceiling.** A second picker per DC lifts the pick-cutoff rate by +16.2 pp and closes the gap to the dock, but dock OTIF moves by +0.0 pp (±0.0) because it is capped by the allocation. Capacity spend at this load is better directed at fill/placement.
- **Scope.** The timetable, carrier cutoffs, lane rule, truck ceiling and dock rates are declared. The arrival shape is the Week-15 calibration; the allocation is fixed across every cell, so this benchmark isolates the outbound layer.

## Limitations

- 发车时刻、装车提前量、车道划分、车辆上限与月台费率是声明值，公开数据中没有承运商时刻表。
- 承诺截止日由 Week-8 的承诺与转运几何推导，不是承运商 SLA；转运日按距离每 700 km 一天取整。
- 拣选完成时间来自仿真的班次时钟，不是仓库扫描时间；月台装卸、门位与司机等待未建模。
- 每个 DC×目的国视为一条车道，未建模多站路由、承运商体积上限与预约时段。
- 分单固定为 Week-9 容量感知 MILP，库存与订单集在所有格之间不变，因此只隔离出库层。
- 月台成本（€220/车 + €0.15/单·小时）是规划代理，不含已经在分单运输成本中的干线变动费用。
