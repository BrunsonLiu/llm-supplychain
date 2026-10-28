# End-to-end fulfillment benchmark (Week 9)

- Generated: `2026-10-27T20:51:45.543374+00:00`
- Orders: **400** real invoices / **2,477** lines / **33,060** units, week 2011-11-28
- DCs: **3**; stock covers **85.0%** of sampled demand. Promises 2/3/5 days map to pick cutoffs **12:00 / 16:00 / 18:00**.
- Picking: **1 picker(s) per DC**, wave cap **8 orders / 40 lines**, shift **600 min**. Release policy **在线 EDF 即时装满**.

## Assumptions

| Item | Assumption | Note |
|---|---|---|
| Promise mix | 30% / 50% / 20% express / standard / economy | No customer-promise field in Online Retail II; tiers are a declared seeded shuffle. |
| Promise → cutoff | 2d/3d/5d → 12:00/16:00/18:00 | One promise field drives both the allocation lateness penalty and the warehouse cutoff. |
| Arrivals | express 70.0%, standard 50.0%, economy 40.0% before the start | The rest arrive uniformly inside a declared tier window; no release timestamps exist in the data. |
| Picking capacity | 1 identical picker(s) per DC | No zones, skills, breaks or congestion; DCs do not share labor. |
| Wave labor | travel 72.0 m/min, 0.35 min/line + 0.02 min/unit, 3.0 min setup/wave | Same Week-6 model for every DC and every scenario. |
| Labor cost | €0.45/picker-minute | Added to the allocation cost to form the end-to-end total. |
| Pick-capacity proxy | cumulative pick-minutes per DC and promise tier | A linear surrogate inside the allocation MILP; the online simulation is the ground truth. |

## Methods

- **Allocation (Week 5)**: each order is assigned to at most two DCs under stock, weekly throughput and split limits. Greedy is deadline-first; the MILP minimises transport, fixed shipment, lateness and unmet penalties.
- **Pick tickets**: every shipped line becomes a ticket keyed by invoice and DC, so a split order creates one ticket per DC. Ticket quantities come from the allocation, not from a re-optimisation.
- **Online release (Week 8)**: per DC, the event-driven simulation forms waves from the arrived pool and dispatches them to that DC's pickers. A ticket is on time when its wave finishes before the promise cutoff.
- **End-to-end OTIF**: an order counts only when it is fully shipped, every shipped unit lands inside the promise, and every one of its pick tickets finishes before the cutoff. Allocation OTIF is therefore an upper bound.
- **Pick-capacity-aware allocation**: the MILP adds cumulative pick-minute budgets per DC at 240/480/600 minutes, counting 0.35 min per touched line, 0.02 min per unit and 0.5 min per shipment. Overload is soft and priced at €5 per pick-minute, and the service plan warm-starts the solve.
- **Release and staffing sweeps**: the same allocation is replayed under each release policy and under 1/2/3 pickers per DC to separate allocation effects from warehouse-execution effects.

## Scenario comparison

| 方案 | 分单状态 | 订单填满 | 分单 OTIF | 端到端 OTIF | 拣选准时 | 拣选丢失单 | 票据 | 波次 | 单票工时 | 最长完工 | 分单成本 | 拣选成本 | 总成本 | 求解 (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 贪心分单（截止期优先） · 在线 EDF 即时装满 | HEURISTIC | 46.8% | 35.0% | 31.5% | 89.2% | 14 | 576 | 79 | 2.98 | 665 | 69,281 | 772 | 70,054 | 0.03 |
| MILP 成本最优 · 在线 EDF 即时装满 | FEASIBLE | 29.0% | 28.2% | 17.5% | 74.4% | 43 | 602 | 83 | 3.23 | 732 | 62,962 | 875 | 63,837 | 60.13 |
| MILP 服务优先 · 在线 EDF 即时装满 | FEASIBLE | 54.5% | 54.5% | 38.0% | 77.5% | 66 | 619 | 85 | 3.19 | 737 | 61,370 | 888 | 62,258 | 60.08 |
| MILP 拣选容量感知 · 在线 EDF 即时装满 | FEASIBLE | 54.5% | 54.5% | 39.0% | 79.1% | 62 | 617 | 84 | 3.19 | 734 | 61,309 | 885 | 62,194 | 60.08 |

All scenarios use the same orders, stock, promises and arrival draw. `分单 OTIF` is the Week-5 outcome; `端到端 OTIF` additionally requires every pick ticket to clear its cutoff. Cost columns are euros; labor is priced at €0.45 per picker-minute.

## Per-DC workload — pick-capacity-aware allocation

| DC | 票据 | 订单 | 波次 | 工时 (min) | 单票工时 | 准时票据 | 迟到票据 | 迟到分钟 | 最长完工 | 空闲分钟 |
|---|---|---|---|---|---|---|---|---|---|---|
| London | 233 | 233 | 31 | 733.8 | 3.15 | 148 | 85 | 5,958 | 734 | 0 |
| Rotterdam | 181 | 181 | 24 | 542.1 | 2.99 | 181 | 0 | 0 | 542 | 0 |
| Frankfurt | 203 | 203 | 29 | 690.0 | 3.40 | 159 | 44 | 1,762 | 690 | 0 |

Tickets, not orders, drive the workload: a split order appears at two DCs. Idle minutes are paid picker capacity with no wave in progress.

## Release-policy sweep

| 释放策略 | 波次 | 票据 | 单票工时 | 拣选准时 | 迟到票据 | 迟到分钟 | 最长完工 | 端到端 OTIF | 总成本 |
|---|---|---|---|---|---|---|---|---|---|
| 在线按单释放 | 617 | 617 | 6.37 | 24.1% | 468 | 164,758 | 1,482 | 9.5% | 63,079 |
| 在线 EDF 即时装满 | 84 | 617 | 3.19 | 79.1% | 129 | 7,720 | 734 | 39.0% | 62,194 |
| 在线节省重批 | 92 | 617 | 3.17 | 81.8% | 112 | 6,960 | 729 | 43.0% | 62,189 |
| 在线节省 + 等待凑波（15 min / ≥4 单） | 91 | 617 | 3.16 | 77.6% | 138 | 9,450 | 742 | 40.5% | 62,188 |

One allocation, four online policies. No policy sees future arrivals; waiting is bounded by the declared window and fill target.

## Picker sensitivity

| 每 DC 拣货员 | 分单 OTIF | 拣选准时 | 端到端 OTIF | 拣选丢失单 | 波次 | 单票工时 | 最长完工 | 拣选工时 |
|---|---|---|---|---|---|---|---|---|
| 1 | 54.5% | 79.1% | 39.0% | 62 | 84 | 3.19 | 734 | 1,965.9 |
| 2 | 54.5% | 100.0% | 54.5% | 0 | 142 | 3.54 | 476 | 2,186.5 |
| 3 | 54.5% | 100.0% | 54.5% | 0 | 214 | 3.97 | 476 | 2,446.4 |

Same allocation, same arrivals, only the number of pickers per DC changes. This isolates whether the end-to-end loss comes from allocation or from warehouse capacity.

## Declared assumptions

- 订单/行/数量/目的国来自 Online Retail II 真实发票
- DC 库存、产能、转运天数、SLA 承诺与费率是显式假设
- 库存按 SKU 需求 stock_factor 分配并加入确定性偏斜
- 承诺天数 2/3/5 映射到拣选截单 12:00/16:00/18:00
- 班中到达占比与到达窗口是显式假设
- 三个 DC 共用同一 ABC 布局与拣选工时模型，每 DC 独立拣货员

## Interpretation

1. **The load-aware plan moves both axes against greedy, but the pure cost model does not dominate it.** Load-aware allocation changes end-to-end OTIF by +7.5 percentage points and cuts €7,860 in total cost relative to greedy. The cost MILP lands at €63,837 against €62,194 for the load plan, with 21.5 percentage points less end-to-end OTIF. At this time limit both MILP plans are `FEASIBLE`, not proven optima, so the cost ranking between them is indicative.
2. **Allocation OTIF is an upper bound on end-to-end OTIF.** Under the load-aware plan 54.5% of orders are fully shipped on time, but only 39.0% also clear their pick cutoff: 62 orders are lost inside the warehouse, with 129 of 617 tickets finishing late (max 134 min).
3. **Batching is the largest labor lever in the chain.** On the same allocation, releasing one order per wave needs 617 waves and 3,932 pick-minutes; EDF fill needs 84 waves and 1,966 pick-minutes, a 50.0% reduction. End-to-end OTIF moves from 9.5% to 39.0%.
4. **Picking capacity, not allocation, sets end-to-end OTIF at 1 picker(s)/DC.** Going to 3 pickers/DC moves pick on-time from 79.1% to 100.0% and end-to-end OTIF from 39.0% to 54.5% on the same orders. At the higher staffing level end-to-end OTIF collapses onto allocation OTIF, so the remaining loss is upstream.
5. **These are feasible plans, not proven optima.** CP-SAT returns `FEASIBLE` on most 400-order runs, the reported gaps are wide, and repeated runs of the same model differ because the solve is time-limited with parallel workers. The pick-capacity constraint is a cumulative linear proxy for wave picking, and the promise-to-cutoff map, arrival process and labor minutes are declared assumptions, so the absolute OTIF levels are not transferable.

## Limitations

- The end-to-end chain is a simulation, not a forecast. Online Retail II provides invoices and quantities; DC stock, throughput, transit, promises, cutoffs and arrivals are declared assumptions.
- The pick layer replays a fixed allocation. It never asks the allocator to re-plan after a wave runs late, and it never rebalances pickers across DCs.
- The pick-capacity proxy is a cumulative linear budget. It ignores batching, travel sharing and wave setup, so it can reject or accept plans that the online simulation would score differently.
- CP-SAT allocations at 400 orders are time-limited `FEASIBLE` solutions with wide gaps; repeated runs differ. The scenario ranking is indicative, not a proven optimum ordering.
- Labor is one identical pool per DC with no breaks, zones, skills or congestion. Picking cost uses a flat €0.45/min rate.
- One trading week, one seed, one layout and one arrival draw. No confidence intervals or stochastic robustness are reported.
- Last-mile transit is captured only through the allocation's promise-day arithmetic; carrier performance and customer-facing delivery promises are outside the model.
