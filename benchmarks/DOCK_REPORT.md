# Dock doors and loading capacity (Week 17)

- Generated: `2026-10-28T12:01:41.294764+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Seeds: **30** | cells: **11** | pickers/DC: **1** | shift **600 min**
- Allocation: **MILP 拣选容量感知（Week-9 分单）** (FEASIBLE) | allocation OTIF ceiling **51.0%** | solver **60 s**
- Door budget: **480 min/day per DC** | load **75 min/truck + 0.50 min/ticket** | dock cost **€220/departure + €0.15/order-hour**

## Assumptions

| Item | Assumption | Note |
|---|---|---|
| Departures | 13:00 and 19:00 per DC; single 19:00 variant | same timetable as Week 16 |
| Carrier cutoff | departure minus 30 min | a missed ticket rolls to the next departure |
| Lane | DC × destination country | orders on one lane consolidate; no cross-country trailer |
| Truck capacity | 300 orders / departure | declared ceiling; not binding in this instance |
| Doors | 0 (unlimited) / 1 / 2 / 4 per DC | declared loading resource; 0 reproduces Week 16 |
| Door budget | 480 min per DC per day | declared 8-hour loading budget; shared by every lane at that DC |
| Loading time | 75 min per truck + 0.50 min per ticket | declared linear loading proxy |
| Promise deadline | dispatch day ≤ promise days − transit days | derived from the Week-8 geometry |
| Dock cost | €220 per departure + €0.15 per order-hour | declared planning rates, used to compare cells |
| Arrivals | prior-week empirical curves (Week 15) | only the door layer is new |

## Cells

| 格 | 规则 | 门位/DC | 单车装车 (min) | 拣货员/DC | 噪声 σ |
|---|---|---|---|---|---|
| 仅拣选截单（Week-15 口径） | 无（对照） | 不限 | 75 | — | 0.00 |
| 双班 13:00/19:00 · 门位不限（Week-16 基线） | 即时 | 不限 | 75 | — | 0.00 |
| 双班 · 1 个门位/DC | 即时 | 1 | 75 | — | 0.00 |
| 双班 · 2 个门位/DC | 即时 | 2 | 75 | — | 0.00 |
| 双班 · 4 个门位/DC | 即时 | 4 | 75 | — | 0.00 |
| 1 个门位 · 承诺感知 6 单 | 承诺感知 | 1 | 75 | — | 0.00 |
| 2 个门位 · 承诺感知 6 单 | 承诺感知 | 2 | 75 | — | 0.00 |
| 1 个门位 · 单班 19:00 | 即时 | 1 | 75 | — | 0.00 |
| 1 个门位 · 加 1 名拣货员/DC | 即时 | 1 | 75 | 2 | 0.00 |
| 1 个门位 · 单车装车 60 分钟 | 即时 | 1 | 60 | — | 0.00 |
| 1 个门位 · 拣选噪声 σ=0.25 | 即时 | 1 | 75 | — | 0.25 |

## Service: pick cutoff versus delivery

Dock OTIF requires every leg to be shipped and `departure day + transit days ≤ promise days`. A lane that cannot load inside the remaining door budget waits for the next slot and may roll to the next day.

| 格 | 拣选截单 OTIF | 交付 OTIF | 交付 − 截单 | 滚存率 | 平均等车 (min) |
|---|---|---|---|---|---|
| 仅拣选截单（Week-15 口径） | 35.9% | 35.9% | +0.0 pp | 0.0% | 0 |
| 双班 13:00/19:00 · 门位不限（Week-16 基线） | 35.9% | 51.0% | +15.1 pp | 9.8% | 278 |
| 双班 · 1 个门位/DC | 35.9% | 45.7% | +9.8 pp | 19.7% | 386 |
| 双班 · 2 个门位/DC | 35.9% | 51.0% | +15.1 pp | 9.8% | 278 |
| 双班 · 4 个门位/DC | 35.9% | 51.0% | +15.1 pp | 9.8% | 278 |
| 1 个门位 · 承诺感知 6 单 | 35.9% | 50.9% | +15.0 pp | 10.8% | 302 |
| 2 个门位 · 承诺感知 6 单 | 35.9% | 51.0% | +15.1 pp | 10.4% | 298 |
| 1 个门位 · 单班 19:00 | 35.9% | 51.0% | +15.1 pp | 10.2% | 459 |
| 1 个门位 · 加 1 名拣货员/DC | 51.0% | 48.1% | -2.9 pp | 22.0% | 440 |
| 1 个门位 · 单车装车 60 分钟 | 35.9% | 50.2% | +14.3 pp | 11.5% | 296 |
| 1 个门位 · 拣选噪声 σ=0.25 | 33.9% | 46.7% | +12.8 pp | 19.0% | 375 |

## Door capacity, consolidation and cost

Door utilization is loaded door-minutes divided by `doors × 480 min × DCs × active departure days`. A blocked count is one lane-slot that could not load because the daily door budget was exhausted.

| 格 | 车次/天 | 每车票据 | 门位利用率 | 门位阻塞 | 单车装车 (min) | 月台成本 (€) |
|---|---|---|---|---|---|---|
| 仅拣选截单（Week-15 口径） | 0.0 | 0.0 | — | — | — | 0 |
| 双班 13:00/19:00 · 门位不限（Week-16 基线） | 30.3 | 21.7 | — | — | — | 7,115 |
| 双班 · 1 个门位/DC | 28.2 | 23.3 | 66.7% | 10.9 | 87 | 6,830 |
| 双班 · 2 个门位/DC | 30.3 | 21.7 | 45.1% | 0.0 | 86 | 7,115 |
| 双班 · 4 个门位/DC | 30.3 | 21.7 | 22.6% | 0.0 | 86 | 7,115 |
| 1 个门位 · 承诺感知 6 单 | 25.9 | 25.4 | 56.7% | 1.5 | 88 | 6,187 |
| 2 个门位 · 承诺感知 6 单 | 25.9 | 25.4 | 28.4% | 0.0 | 88 | 6,180 |
| 1 个门位 · 单班 19:00 | 21.7 | 30.2 | 68.0% | 2.1 | 90 | 5,535 |
| 1 个门位 · 加 1 名拣货员/DC | 24.9 | 26.4 | 75.3% | 11.0 | 88 | 6,192 |
| 1 个门位 · 单车装车 60 分钟 | 29.2 | 22.5 | 72.2% | 6.7 | 71 | 6,910 |
| 1 个门位 · 拣选噪声 σ=0.25 | 28.3 | 23.2 | 68.0% | 10.5 | 87 | 6,848 |

## Paired comparisons

Right − left, same arrival seed, metric = delivered OTIF.

| 对比 | Δ 交付 OTIF | 胜率 | 持平率 | n |
|---|---|---|---|---|
| 双班 13:00/19:00 · 门位不限（Week-16 基线） − 仅拣选截单（Week-15 口径） | +15.1 pp (±0.5) | 100.0% | 0.0% | 30 |
| 双班 · 1 个门位/DC − 双班 13:00/19:00 · 门位不限（Week-16 基线） | -5.3 pp (±1.6) | 0.0% | 0.0% | 30 |
| 双班 · 2 个门位/DC − 双班 13:00/19:00 · 门位不限（Week-16 基线） | +0.0 pp (±0.0) | 0.0% | 100.0% | 30 |
| 双班 · 4 个门位/DC − 双班 13:00/19:00 · 门位不限（Week-16 基线） | +0.0 pp (±0.0) | 0.0% | 100.0% | 30 |
| 1 个门位 · 承诺感知 6 单 − 双班 · 1 个门位/DC | +5.3 pp (±1.5) | 100.0% | 0.0% | 30 |
| 2 个门位 · 承诺感知 6 单 − 双班 · 2 个门位/DC | +0.0 pp (±0.0) | 0.0% | 100.0% | 30 |
| 1 个门位 · 单班 19:00 − 双班 · 1 个门位/DC | +5.3 pp (±1.6) | 100.0% | 0.0% | 30 |
| 1 个门位 · 加 1 名拣货员/DC − 双班 · 1 个门位/DC | +2.5 pp (±1.5) | 46.7% | 3.3% | 30 |
| 1 个门位 · 单车装车 60 分钟 − 双班 · 1 个门位/DC | +4.5 pp (±1.5) | 100.0% | 0.0% | 30 |
| 1 个门位 · 拣选噪声 σ=0.25 − 双班 · 1 个门位/DC | +1.0 pp (±1.0) | 23.3% | 46.7% | 30 |

## Lane detail (seed 1, 1 door + promise-aware 6)

| DC | 车道 | 票据 | 件数 | 车次 | 平均等车 (min) | 滚存率 |
|---|---|---|---|---|---|---|
| London | United Kingdom | 231 | 9,450 | 3 | 325 | 16.0% |
| Frankfurt | United Kingdom | 192 | 8,837 | 3 | 305 | 13.0% |
| Rotterdam | United Kingdom | 188 | 7,383 | 2 | 201 | 0.0% |
| Frankfurt | France | 11 | 683 | 2 | 266 | 0.0% |
| Frankfurt | Germany | 9 | 516 | 1 | 346 | 0.0% |
| Rotterdam | France | 6 | 105 | 1 | 437 | 0.0% |
| London | EIRE | 4 | 32 | 1 | 228 | 0.0% |
| London | France | 3 | 44 | 1 | 348 | 0.0% |
| Frankfurt | Finland | 2 | 84 | 1 | 1,477 | 100.0% |
| London | Germany | 2 | 38 | 1 | 76 | 0.0% |
| Frankfurt | Denmark | 1 | 113 | 1 | 2,480 | 100.0% |
| Frankfurt | Netherlands | 1 | 40 | 1 | 1,548 | 100.0% |

## Findings

- **Unconstrained doors reproduce Week 16.** With no door limit the dock delivers 51.0% against an allocation ceiling of 51.0% (+15.1 pp (±0.5) versus the pick cutoff), so the Week-16 conclusion depends on unlimited loading capacity.
- **One door is enough to make the dock bind.** With 1 door per DC the dock delivers 45.7% (-5.3 pp (±1.6) versus open doors); 2 doors recover to 51.0% (+0.0 pp (±0.0)) and 4 doors to 51.0%. The door budget, not the carrier cutoff, is the binding resource at this load.
- **Consolidation relieves the door.** Promise-aware 6 raises the trailer load and changes delivered OTIF by +5.3 pp (±1.5) at 1 door, almost fully recovering the door loss while removing departures and door-minutes. Holding is a capacity lever, not only a cost lever.
- **A single late departure also relieves the door.** Keeping only 19:00 changes delivered OTIF by +5.3 pp (±1.6) at 1 door and removes departures; the trade-off is longer dock dwell.
- **Extra picking capacity cannot substitute for a door.** A second picker changes delivered OTIF by +2.5 pp (±1.5) at 1 door while pushing the pick-cutoff KPI to the allocation ceiling: faster picking feeds the same loading queue, so the dock remains the binding resource.
- **Loading time matters.** A 60-minute load instead of 75 changes delivered OTIF by +4.5 pp (±1.5) at 1 door: a faster dock recovers service without adding a door.
- **Pick noise is secondary to door capacity.** Lognormal σ=0.25 changes delivered OTIF by +0.98 pp (±1.00) at 1 door with 46.7% ties: no material effect, because the daily door budget dominates the tail.
- **Scope.** Door count, loading window, loading minutes, timetable, lane rule and rates are declared. Allocation, stock and arrivals are fixed across cells, so this benchmark isolates the dock-door layer; absolute OTIF is not transferable.

## Limitations

- 门位数量、装车窗口、单车装车分钟与按票装车分钟是声明值，公开数据没有月台作业记录。
- 门位按“每 DC 每日装车分钟预算”建模，不模拟具体门位占用、叉车、装卸工排班与司机等待。
- 装车分钟按车 + 票线性计算，未区分整托/散件、车辆类型与装车先后。
- 发车时刻、装车截止、车道与车辆上限沿用 Week-16 的声明值；承诺截止仍由承诺与转运几何推导。
- 分单固定为 Week-9 容量感知 MILP，库存与订单集在所有格之间不变，因此只隔离月台门位层。
- 月台成本（€220/车 + €0.15/单·小时）是规划代理，不含装车人工与门位固定成本。
