# Multi-day rolling allocation and replenishment (Week 19)

- Generated: `2026-10-28T17:34:38.575751+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Flow: **5** weekdays | day 0: 66 | day 1: 73 | day 2: 68 | day 3: 85 | day 4: 108
- MILP: **8s/day/policy**, stock factor **85%**, safety **10%**

## Assumptions

| Item | Assumption | Note |
|---|---|---|
| Order day | actual invoice weekday | Sat/Sun invoices land on Friday |
| Flow days | 5 weekdays | Monday–Friday of the target week |
| Allocation | Week-9 capacity-aware MILP, re-solved daily | only still-open lines and remaining stock |
| Delivery day | allocation day + declared transit days | transit already includes 1 handling day |
| Replenishment | order-up-to remaining-week cover | target declines from 85% weekly stock to zero; no extra total supply |
| Safety | +10% over the declining target | declared buffer, not a service-level policy |
| Baseline | one-shot weekly allocation | Week-18 allocation layer, same deadline rule |
| Scope | allocation only | picking, release, dispatch and doors are not replayed |

## Weekly snapshot vs rolling flow

`分单 OTIF` = every line allocated and `allocation day + transit ≤ order day + promise`; `fill` includes late allocations. The baseline is the same 400 orders and stock snapshot allocated once, so the difference is the timing/carryover effect.

| 策略 | 天数 | fill | 分单 OTIF | 迟到 units | 期末 backlog | 补货 units | 平均库存 |
|---|---|---|---|---|---|---|---|
| 单周一次性快照（Week-18 口径） | 1 | 83.0% | 53.2% | 12 | 5,616 | 0 | 28,104 |
| 不补货（仅 85% 初始库存） | 5 | 84.1% | 55.2% | 1,640 | 5,263 | 0 | 15,715 |
| 每日回补 · 1 天前置期 | 5 | 97.8% | 87.0% | 3,147 | 726 | 11,408 | 22,086 |
| 每日回补 · 2 天前置期 | 5 | 93.7% | 71.8% | 4,642 | 2,069 | 5,309 | 18,037 |
| 每日回补 +10% 安全量 · 1 天 | 5 | 98.2% | 87.5% | 3,447 | 580 | 12,873 | 23,054 |
| 每 2 天批量回补 · 1 天 | 5 | 96.7% | 81.0% | 5,294 | 1,085 | 8,400 | 19,659 |

## OTIF by order day

| 订单日 | 不补货（仅 85% 初始库存） | 每 2 天批量回补 · 1 天 | 每日回补 +10% 安全量 · 1 天 | 每日回补 · 1 天前置期 | 每日回补 · 2 天前置期 |
|---|---|---|---|---|---|
| 0 | 90.9% | 90.9% | 93.9% | 93.9% | 90.9% |
| 1 | 82.2% | 86.3% | 93.2% | 94.5% | 86.3% |
| 2 | 69.1% | 91.2% | 94.1% | 94.1% | 88.2% |
| 3 | 51.8% | 80.0% | 88.2% | 88.2% | 72.9% |
| 4 | 9.3% | 65.7% | 75.0% | 72.2% | 38.9% |

## Findings

- **A weekly snapshot hides the intra-week service decay.** The one-shot baseline allocates 83.0% of units at 53.2% OTIF; the no-replenishment flow is similar on fill (84.1%) but +2.0 pp on OTIF. The weekly number is not a service level: the no-replenishment by-day OTIF falls from 90.9% on Monday to 9.3% on Friday as the initial stock is consumed.
- **Daily re-optimization is not the same as one weekly allocation.** Even with no replenishment, rolling allocation is +2.0 pp versus the one-shot baseline: the weekly MILP commits stock to early orders, while the daily MILP can leave it for orders that are still open. This is a scheduling effect, not extra inventory.
- **Replenishment moves stock through the week; it does not create a second week of supply.** With a 1-day lead and a declining order-up-to target, OTIF moves +31.8 pp versus no replenishment, fill 97.8%, backlog 726 vs 5,263, with 11,408 units reordered. Because the target shrinks with the remaining week, the policy redistributes the same 85% stock toward later order days rather than lifting total availability.
- **Lead time is a service tax.** A 2-day lead moves OTIF -15.2 pp versus 1-day, with fill 93.7%, backlog 2,069 and late units 4,642 vs 3,147: a 2-day lead fits only the day-0 order into the five-day flow, so the last order days receive little or no replenishment.
- **A 10% safety add-on is not a free buffer.** It moves OTIF +0.5 pp and fill 98.2% versus the 1-day policy, while raising average inventory from 22,086 to 23,054; the extra units help only if the shortage is on the replenished SKU, and they are still capped by the 85% weekly snapshot.
- **Batching every two days is dominated by daily replenishment.** Batch OTIF is 81.0% vs 87.0% for daily 1-day; its ending backlog is also higher (1,085 vs 726), and late units rise to 5,294 vs 3,147. The batch delays allocation without clearing more units; the five-day flow is too short for the saved cycles to amortize.
- **Service decays within the week.** The by-day table is the operational warning: early orders are served from initial stock, late orders depend on replenishment timing. A weekly OTIF number can hide a Friday stockout.
- **Scope.** This is the inventory-carryover layer only. Picking, online release, dispatch and dock doors are not replayed; replenishment is a declining order-up-to cover with no MOQ, supplier capacity or DC transfer; the result is one week, one stock snapshot and one layout.

## Limitations

- 只重放分单层：拣选、在线释放、发车与月台不重跑；交付日按“分单日 + 声明转运日”计算，不含截单/发车/门位。
- 订单日来自发票日期（周一至周五）；周六/周日发票并入周五，仓库当日可用性没有单独建模。
- 补货采用剩余周 cover 的 order-up-to：目标从 85% 周库存线性降到 0，只把同一批库存往后几天移动，不额外创造总量；不做需求预测、MOQ、补货批量上限、供应商产能或 DC 间调拨。
- 前置期是声明值（1/2 天），到货只发生在早晨；安全量按目标 cover 的 10% 向上取整。
- 单周快照用 60s MILP，日滚动用 8s/天；求解器在时间预算内的差异会混入 OTIF；只验证一个目标周、一个库存/布局。
- 绝对 OTIF 不可迁移；结果用于比较库存结转与补货前置期的方向，不是生产承诺。
