# Stock deployment under execution risk (Week 11)

- Generated: `2026-10-27T21:41:46.730930+00:00`
- Orders: **400** real invoices / **2477** lines / **33060** units, week 2011-11-28
- Seeds per cell: **30**; stress cells: **4**; stock plans: **4**
- Picking: **1 picker(s) per DC**, wave cap **8 orders / 40 lines**, shift **600.0 min**

## Assumptions

| Item | Assumption | Note |
|---|---|---|
| Stock split | declared DC shares + deterministic per-SKU jitter | Total stock and the order set stay fixed; only placement moves. |
| Allocation | one pick-capacity-aware MILP per plan, 60 s budget | Re-solved for each split, so cost/OTIF differences mix placement and solver quality. |
| Execution | arrivals and pick durations resampled per seed | Same seeds across plans; the stock split is the only structural change. |
| Network | 3 DCs, declared transit days, capacity and handling costs | No replenishment, DC-to-DC transfer or demand shift. |

## Methods

- **Stock plans**: the Week-5 default split, a balanced split, and two one-sided splits (Rotterdam-heavy and London-heavy) to bound the frontier.
- **Allocation**: for each plan, solve the Week-5 service-weighted MILP with the Week-9 pick-capacity proxy, using one 30 s service warm start and one 60 s load-aware solve.
- **Replay**: for each plan and seed, redraw arrivals, rerun the Week-8 event-driven release per DC, and recompute the Week-9 end-to-end OTIF.
- **Statistics**: mean with a normal 95% interval, P10/P50/P90, worst-decile mean, over-shift probability, and a per-DC workload snapshot at the first seed.

## Stock plans

| 库存布点 | 声明占比 | 实际占比 | 库存件数 | 覆盖率 | 说明 |
|---|---|---|---|---|---|
| 基线 34/28/38 | London 34% / Rotterdam 28% / Frankfurt 38% | 35% / 28% / 37% | 9,932 / 7,823 / 10,349 | 85.0% | Week-5 默认布点（London / Rotterdam / Frankfurt） |
| 均衡 33/33/34 | London 33% / Rotterdam 33% / Frankfurt 34% | 34% / 33% / 33% | 9,624 / 9,201 / 9,279 | 85.0% | 从 Frankfurt 挪 4pp、从 London 挪 1pp 到 Rotterdam |
| Rotterdam 偏重 30/40/30 | London 30% / Rotterdam 40% / Frankfurt 30% | 31% / 40% / 29% | 8,773 / 11,144 / 8,187 | 85.0% | 再向 Rotterdam 集中 10pp，测试是否过度 |
| London 偏重 40/24/36 | London 40% / Rotterdam 24% / Frankfurt 36% | 41% / 24% / 35% | 11,641 / 6,691 / 9,772 | 85.0% | 反向：把库存拉回 UK 近端，削弱 Rotterdam 缓冲 |

## Allocation outcomes

| 库存布点 | 状态 | 件数满足 | 票据 | 分单 OTIF（上界） | 分单成本 (€) | 求解 (s) |
|---|---|---|---|---|---|---|
| 基线 34/28/38 | FEASIBLE | 83.2% | 647 | 53.8% | 62,332 | 60.10 |
| 均衡 33/33/34 | FEASIBLE | 82.8% | 673 | 55.5% | 63,282 | 60.08 |
| Rotterdam 偏重 30/40/30 | FEASIBLE | 82.5% | 666 | 53.8% | 63,568 | 60.10 |
| London 偏重 40/24/36 | FEASIBLE | 83.2% | 668 | 54.0% | 62,264 | 60.10 |

## End-to-end OTIF distribution

| 库存布点 | 压力格 | 均值 | 95% CI | P10 | P50 | P90 | 最差 10% 均值 | 最小 | 最大 | n |
|---|---|---|---|---|---|---|---|---|---|---|
| 基线 34/28/38 | 基准：均匀到达 · 确定性 | 39.6% | ±0.5% | 37.7% | 39.8% | 41.0% | 37.0% | 36.5% | 41.5% | 30 |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 37.6% | ±1.0% | 34.7% | 37.6% | 41.0% | 32.8% | 31.2% | 43.0% | 30 |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 35.0% | ±1.4% | 30.0% | 35.5% | 39.3% | 28.7% | 26.0% | 42.0% | 30 |
| 基线 34/28/38 | 加 1 名拣货员/DC | 53.7% | ±0.0% | 53.8% | 53.8% | 53.8% | 53.8% | 53.8% | 53.8% | 30 |
| 均衡 33/33/34 | 基准：均匀到达 · 确定性 | 38.8% | ±0.5% | 36.8% | 39.0% | 40.2% | 36.3% | 36.0% | 41.2% | 30 |
| 均衡 33/33/34 | 拣选噪声 σ=0.25 | 35.8% | ±1.2% | 31.9% | 35.5% | 39.9% | 30.2% | 29.0% | 43.0% | 30 |
| 均衡 33/33/34 | 重度拥堵 σ=0.40 | 32.6% | ±1.6% | 27.5% | 32.5% | 37.1% | 24.8% | 20.8% | 40.2% | 30 |
| 均衡 33/33/34 | 加 1 名拣货员/DC | 55.5% | ±0.0% | 55.5% | 55.5% | 55.5% | 55.5% | 55.5% | 55.5% | 30 |
| Rotterdam 偏重 30/40/30 | 基准：均匀到达 · 确定性 | 36.1% | ±0.5% | 33.8% | 36.4% | 38.0% | 33.6% | 33.2% | 38.5% | 30 |
| Rotterdam 偏重 30/40/30 | 拣选噪声 σ=0.25 | 33.5% | ±1.0% | 30.5% | 33.9% | 36.9% | 28.7% | 26.8% | 38.2% | 30 |
| Rotterdam 偏重 30/40/30 | 重度拥堵 σ=0.40 | 31.6% | ±1.4% | 25.9% | 31.5% | 36.0% | 24.7% | 23.5% | 38.2% | 30 |
| Rotterdam 偏重 30/40/30 | 加 1 名拣货员/DC | 53.7% | ±0.0% | 53.8% | 53.8% | 53.8% | 53.8% | 53.8% | 53.8% | 30 |
| London 偏重 40/24/36 | 基准：均匀到达 · 确定性 | 37.3% | ±0.6% | 35.2% | 37.2% | 39.5% | 34.7% | 34.2% | 40.5% | 30 |
| London 偏重 40/24/36 | 拣选噪声 σ=0.25 | 35.2% | ±1.1% | 31.0% | 35.2% | 39.6% | 30.8% | 30.5% | 40.5% | 30 |
| London 偏重 40/24/36 | 重度拥堵 σ=0.40 | 33.3% | ±1.4% | 28.2% | 33.2% | 38.6% | 27.3% | 27.0% | 40.8% | 30 |
| London 偏重 40/24/36 | 加 1 名拣货员/DC | 54.0% | ±0.0% | 54.0% | 54.0% | 54.0% | 54.0% | 54.0% | 54.0% | 30 |

Each row is one stock plan × stress cell. `95% CI` is the normal approximation; `worst 10% mean` averages the lowest decile of seeds.

## Execution risk

| 库存布点 | 压力格 | 拣选准时均值 | 准时 95% CI | 迟到分钟均值 | 迟到分钟 P90 | Makespan 均值 | Makespan P90 | 超班次概率 |
|---|---|---|---|---|---|---|---|---|
| 基线 34/28/38 | 基准：均匀到达 · 确定性 | 79.9% | ±0.5% | 7,437 | 7,873 | 731 | 734 | 100.0% |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 76.1% | ±1.5% | 10,219 | 14,447 | 750 | 791 | 100.0% |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 71.3% | ±2.3% | 14,636 | 21,484 | 780 | 840 | 100.0% |
| 基线 34/28/38 | 加 1 名拣货员/DC | 100.0% | ±0.0% | 0 | 0 | 476 | 486 | 0.0% |
| 均衡 33/33/34 | 基准：均匀到达 · 确定性 | 75.5% | ±0.5% | 6,808 | 7,206 | 718 | 722 | 100.0% |
| 均衡 33/33/34 | 拣选噪声 σ=0.25 | 70.6% | ±1.7% | 10,795 | 14,311 | 738 | 775 | 100.0% |
| 均衡 33/33/34 | 重度拥堵 σ=0.40 | 65.6% | ±2.3% | 16,198 | 23,308 | 771 | 819 | 100.0% |
| 均衡 33/33/34 | 加 1 名拣货员/DC | 100.0% | ±0.0% | 0 | 0 | 475 | 485 | 0.0% |
| Rotterdam 偏重 30/40/30 | 基准：均匀到达 · 确定性 | 76.5% | ±0.4% | 8,414 | 8,786 | 738 | 741 | 100.0% |
| Rotterdam 偏重 30/40/30 | 拣选噪声 σ=0.25 | 71.6% | ±1.6% | 12,050 | 16,390 | 760 | 800 | 100.0% |
| Rotterdam 偏重 30/40/30 | 重度拥堵 σ=0.40 | 67.8% | ±2.4% | 17,174 | 25,549 | 792 | 837 | 100.0% |
| Rotterdam 偏重 30/40/30 | 加 1 名拣货员/DC | 100.0% | ±0.0% | 0 | 0 | 476 | 486 | 0.0% |
| London 偏重 40/24/36 | 基准：均匀到达 · 确定性 | 78.2% | ±0.4% | 9,484 | 9,901 | 756 | 757 | 100.0% |
| London 偏重 40/24/36 | 拣选噪声 σ=0.25 | 75.2% | ±1.4% | 12,396 | 17,177 | 772 | 819 | 100.0% |
| London 偏重 40/24/36 | 重度拥堵 σ=0.40 | 71.6% | ±2.0% | 16,683 | 25,049 | 801 | 855 | 100.0% |
| London 偏重 40/24/36 | 加 1 名拣货员/DC | 100.0% | ±0.0% | 0 | 0 | 476 | 486 | 0.0% |

## Per-DC workload (seed 1, baseline cell)

| 库存布点 | DC | 票据 | 波次 | 拣选工时 | 准时票据 | 迟到票据 | 迟到分钟 | Makespan |
|---|---|---|---|---|---|---|---|---|
| 基线 34/28/38 | London | 239 | 32 | 730.5 | 147 | 92 | 6,071.2 | 730.5 |
| 基线 34/28/38 | Rotterdam | 198 | 26 | 563.8 | 198 | 0 | 0.0 | 563.8 |
| 基线 34/28/38 | Frankfurt | 210 | 32 | 673.9 | 171 | 39 | 1,377.7 | 673.9 |
| 均衡 33/33/34 | London | 237 | 31 | 716.3 | 156 | 81 | 4,310.5 | 716.3 |
| 均衡 33/33/34 | Rotterdam | 231 | 30 | 647.6 | 176 | 55 | 1,495.0 | 647.6 |
| 均衡 33/33/34 | Frankfurt | 205 | 30 | 647.4 | 176 | 29 | 657.1 | 647.4 |
| Rotterdam 偏重 30/40/30 | London | 226 | 30 | 666.4 | 180 | 46 | 1,830.7 | 666.4 |
| Rotterdam 偏重 30/40/30 | Rotterdam | 242 | 31 | 735.5 | 144 | 98 | 5,862.8 | 735.5 |
| Rotterdam 偏重 30/40/30 | Frankfurt | 198 | 27 | 593.2 | 198 | 0 | 0.0 | 593.2 |
| London 偏重 40/24/36 | London | 249 | 33 | 756.6 | 147 | 102 | 7,571.0 | 756.6 |
| London 偏重 40/24/36 | Rotterdam | 207 | 27 | 555.7 | 207 | 0 | 0.0 | 555.7 |
| London 偏重 40/24/36 | Frankfurt | 212 | 34 | 687.3 | 171 | 41 | 1,957.1 | 687.3 |

The snapshot shows how the stock split moves pick load across DCs; it is not averaged over seeds.

## Interpretation

1. **The default split is not beaten by any declared alternative.** `基线 34/28/38` stays the best placement at 39.6% end-to-end OTIF; the runner-up (`均衡 33/33/34`) is 38.8%, 0.9% lower, and the two 95% intervals do not overlap, so the gap is larger than this sample's noise. Reallocating stock is not a free lever here: the declared default already sits at the front of this frontier.
2. **A higher allocation bound does not survive the pick layer.** `均衡 33/33/34` lifts the allocation bound from 53.8% to 55.5% (+1.8%) but its end-to-end mean is 38.8%, -0.9% versus the default and ships +26 more pick tickets than the default. The bound prices promise feasibility and stock, not the extra wave and pick work that the split creates.
3. **The placement frontier is not monotone.** `Rotterdam 偏重 30/40/30` lands at 36.1%, the lowest of 4 placements and 3.6% below `基线 34/28/38`. The ranking is not monotone in how concentrated the stock is, so no single 'more balanced wins' rule holds for this instance.
4. **The ranking survives congestion.** Under severe pick-time noise (σ=0.40) the best placement is `基线 34/28/38` at 35.0%, ahead of `London 偏重 40/24/36` at 33.3% (+1.7%); the same plan wins both the mean and the stress cell.
5. **Tail service ranks the plans the same way as the mean.** `Rotterdam 偏重 30/40/30` has both the lowest mean (36.1%) and the lowest worst-decile mean (33.6%), so the ordering is not a mean-only artifact.
6. **With enough pick capacity the ranking reverts to the allocation bound.** Adding a picker per DC moves every plan to its own bound (largest gap 0.0%), and `均衡 33/33/34` now leads at 55.5% versus 53.7% for the default. The placement that loses at one picker is the better one once the pick bottleneck is removed, so stock placement and pick capacity are joint decisions.
7. **Declared assumptions, not observed inventory.** The stock splits, the per-SKU jitter, the DC capacity, transit days and the pick-time model are assumptions. The counterfactual re-solves the allocation for each split and replays the same order set, arrivals and congestion draws; it does not model replenishment, transfers between DCs or demand shifting.

## Declared assumptions

- 订单/行/数量/目的国来自 Online Retail II 真实发票
- DC 库存、产能、转运天数、SLA 承诺与费率是显式假设
- 库存按 SKU 需求 stock_factor 分配并加入确定性偏斜
- 承诺天数 2/3/5 映射到拣选截单 12:00/16:00/18:00
- 班中到达占比与到达窗口是显式假设
- 三个 DC 共用同一 ABC 布局与拣选工时模型，每 DC 独立拣货员
- 库存总量固定，只改变各 DC 的库存占比；每 SKU 按最大余数法拆分并带确定性抖动
- 每个布点重新求解分单 MILP，布点差异与求解器差异混合
- 所有布点共享同一订单集、到达种子与拥堵 σ，但分单可行集不同，不能做逐种子配对

## Limitations

- Stock is placed by declared shares plus a jitter, not by observed inventory; the counterfactual says what would happen under this model, not what a retailer should do without a demand and replenishment model.
- The allocation is a time-limited `FEASIBLE` MILP per plan; solver variation mixes with the placement effect, and the plans are not optimised jointly with the stock split.
- The order set, promises, layout, slots and picker count are fixed; only stock placement changes. Replenishment, transfers, demand shifts and supplier constraints are outside the chain.
- The normal 95% interval is an approximation, comparisons across plans are unpaired (different stock implies different feasible sets), and the worst-decile mean is noisy with 30 seeds.
