# Joint allocation and stock placement (Week 13)

- Generated: `2026-10-28T04:23:56.543515+00:00`
- Orders: **400** real invoices / **2477** lines / **33060** units, week 2011-11-28
- Seeds per cell: **30**; stress cells: **4**; stock placements: **4** (the two joint scenarios share one implied placement)
- Picking: **1 picker(s) per DC**, wave cap **8 orders / 40 lines**, shift **600.0 min**
- Destination history: **189** SKUs with history, **0** fallback, weeks 2011-10-03..2011-11-21
- DC throughput cap: London 65% / Rotterdam 47% / Frankfurt 41%

## Assumptions

| Item | Assumption | Note |
|---|---|---|
| Stock total | each SKU's total units stay fixed | Only placement moves; the order set and 85% coverage are unchanged. |
| Destination mix | prior 8 weeks of units by destination region | UK -> London; EU split 45/55 Rotterdam/Frankfurt by declaration. |
| Capacity cap | each DC holds at most its share of weekly throughput | Excess is redistributed by remaining DC headroom; the cap is a unit share, not a slot or SKU-level storage limit. |
| Joint placement | allocation sees only per-SKU total stock | The implied placement is a known-week upper bound, not a forecast. |
| Allocation | Week-9 two-stage MILP, 30 s service + 60 s load-aware | Time-limited `FEASIBLE`; pick capacity is linear minutes. |
| Execution | arrivals and pick durations resampled per seed | Same seeds and cells as Weeks 10-12. |

## Methods

- **Declared placement**: Week-5 baseline 34/28/38 plus the deterministic per-SKU jitter, then the Week-9 capacity-aware allocation.
- **Destination placement**: per-SKU prior-week UK/EU mix mapped to the three DCs, then the same capacity-aware allocation.
- **Capacity-capped destination placement**: the same mix with each DC's per-SKU share clipped at `throughput / total stock`, then the excess redistributed by remaining headroom. This is the deployable comparator.
- **Joint placement + re-solved allocation**: the joint MILP's implied placement, then the standard capacity-aware allocation on that placement.
- **Joint plan**: one MILP allocates orders and lets placement follow, with a destination-mix reserve for unallocated units.
- **Solver status**: both allocation stages are time-limited; the joint bound is loose once the service bonus makes the objective negative, so the solve time and `FEASIBLE` status are reported but no bound gap is claimed as solution quality.
- **Replay**: for each placement and seed, redraw arrivals, rerun the Week-8 online release per DC, and recompute Week-9 end-to-end OTIF.

## Stock placements

| Placement | Source | DC mix | Stock units | Coverage | Note |
|---|---|---|---|---|---|
| Week-5 基线 34/28/38 | declared | London 35% / Rotterdam 28% / Frankfurt 37% | 9,932 / 7,823 / 10,349 | 85.0% | 声明占比 + 确定性 SKU 抖动 |
| 目的地历史布点 | history | London 86% / Rotterdam 6% / Frankfurt 8% | 24,207 / 1,753 / 2,144 | 85.0% | 前 8 周目的地占比；UK→London，欧洲内按 45%/55% 声明拆分 |
| 目的地历史 + 产能封顶 | history | London 63% / Rotterdam 19% / Frankfurt 18% | 17,705 / 5,273 / 5,126 | 85.0% | 目的地历史按 DC 周产能封顶，超额按剩余产能再分配；封顶后 London ≤ 65% |
| 联合方案的隐含布点 | plan | London 47% / Rotterdam 29% / Frankfurt 24% | 13,251 / 8,024 / 6,829 | 85.0% | 联合 MILP 按周内订单落位，剩余库存按目的地占比保留 |

## Allocation outcomes

| Placement | Status | Unit fill | Tickets | Allocation OTIF (bound) | Allocation cost (€) | Solve (s) |
|---|---|---|---|---|---|---|
| Week-5 基线 34/28/38 | FEASIBLE | 83.2% | 654 | 50.7% | 62,421 | 60.09 |
| 目的地历史布点 | FEASIBLE | 66.5% | 498 | 43.5% | 85,615 | 60.19 |
| 目的地历史 + 产能封顶 | FEASIBLE | 79.0% | 608 | 58.2% | 66,724 | 60.10 |
| 联合布点 + 标准分单 | FEASIBLE | 82.8% | 652 | 52.5% | 61,362 | 60.10 |
| 联合规划（分单+布点） | FEASIBLE | 84.7% | 515 | 45.0% | 55,096 | 60.14 |

Costs are not comparable across placements: the joint scenarios put stock where the plan ships and pay no repositioning, so their transport cost is an optimistic lower bound.

## End-to-end OTIF distribution

| Placement | Stress cell | Mean | 95% CI | P10 | P50 | P90 | Worst 10% mean | n |
|---|---|---|---|---|---|---|---|---|
| Week-5 基线 34/28/38 | 基准：均匀到达 · 确定性 | 36.9% | ±0.4% | 35.2% | 37.0% | 38.3% | 34.6% | 30 |
| Week-5 基线 34/28/38 | 拣选噪声 σ=0.25 | 35.5% | ±0.9% | 32.5% | 35.4% | 38.5% | 31.8% | 30 |
| Week-5 基线 34/28/38 | 重度拥堵 σ=0.40 | 32.8% | ±1.3% | 28.7% | 32.8% | 37.0% | 26.9% | 30 |
| Week-5 基线 34/28/38 | 加 1 名拣货员/DC | 50.8% | ±0.0% | 50.7% | 50.7% | 50.7% | 50.7% | 30 |
| 目的地历史布点 | 基准：均匀到达 · 确定性 | 18.7% | ±0.4% | 17.2% | 18.8% | 19.8% | 16.6% | 30 |
| 目的地历史布点 | 拣选噪声 σ=0.25 | 17.6% | ±0.6% | 15.4% | 17.9% | 19.8% | 14.2% | 30 |
| 目的地历史布点 | 重度拥堵 σ=0.40 | 16.5% | ±0.9% | 13.7% | 16.8% | 19.1% | 12.0% | 30 |
| 目的地历史布点 | 加 1 名拣货员/DC | 43.5% | ±0.0% | 43.5% | 43.5% | 43.5% | 43.5% | 30 |
| 目的地历史 + 产能封顶 | 基准：均匀到达 · 确定性 | 30.2% | ±0.5% | 28.5% | 30.1% | 31.6% | 28.1% | 30 |
| 目的地历史 + 产能封顶 | 拣选噪声 σ=0.25 | 29.1% | ±0.7% | 26.4% | 29.2% | 31.3% | 25.0% | 30 |
| 目的地历史 + 产能封顶 | 重度拥堵 σ=0.40 | 27.8% | ±1.0% | 24.6% | 27.9% | 31.0% | 22.6% | 30 |
| 目的地历史 + 产能封顶 | 加 1 名拣货员/DC | 58.2% | ±0.0% | 58.2% | 58.2% | 58.2% | 58.2% | 30 |
| 联合布点 + 标准分单 | 基准：均匀到达 · 确定性 | 36.6% | ±0.4% | 35.2% | 36.5% | 38.3% | 34.7% | 30 |
| 联合布点 + 标准分单 | 拣选噪声 σ=0.25 | 34.0% | ±0.9% | 31.0% | 34.1% | 36.4% | 29.2% | 30 |
| 联合布点 + 标准分单 | 重度拥堵 σ=0.40 | 31.4% | ±1.3% | 27.8% | 31.4% | 34.6% | 25.0% | 30 |
| 联合布点 + 标准分单 | 加 1 名拣货员/DC | 52.5% | ±0.0% | 52.5% | 52.5% | 52.5% | 52.5% | 30 |
| 联合规划（分单+布点） | 基准：均匀到达 · 确定性 | 42.5% | ±0.2% | 41.7% | 42.5% | 43.5% | 41.4% | 30 |
| 联合规划（分单+布点） | 拣选噪声 σ=0.25 | 41.2% | ±0.6% | 38.7% | 41.5% | 43.2% | 38.0% | 30 |
| 联合规划（分单+布点） | 重度拥堵 σ=0.40 | 39.0% | ±1.1% | 34.4% | 39.6% | 42.8% | 32.6% | 30 |
| 联合规划（分单+布点） | 加 1 名拣货员/DC | 45.0% | ±0.0% | 45.0% | 45.0% | 45.0% | 45.0% | 30 |

Each row is one placement × stress cell. `95% CI` is the normal approximation; `worst 10% mean` averages the lowest decile of seeds.

## Execution risk

| Placement | Stress cell | Pick on-time | Pick on-time 95% CI | Tardy minutes | Tardy minutes P90 | Makespan | Makespan P90 | Over-shift |
|---|---|---|---|---|---|---|---|---|
| Week-5 基线 34/28/38 | 基准：均匀到达 · 确定性 | 78.5% | ±0.4% | 7,732 | 8,285 | 732 | 733 | 100.0% |
| Week-5 基线 34/28/38 | 拣选噪声 σ=0.25 | 75.2% | ±1.7% | 10,565 | 15,242 | 752 | 794 | 100.0% |
| Week-5 基线 34/28/38 | 重度拥堵 σ=0.40 | 70.5% | ±2.3% | 14,839 | 23,295 | 781 | 851 | 100.0% |
| Week-5 基线 34/28/38 | 加 1 名拣货员/DC | 100.0% | ±0.0% | 0 | 0 | 476 | 485 | 0.0% |
| 目的地历史布点 | 基准：均匀到达 · 确定性 | 65.8% | ±0.5% | 39,753 | 41,409 | 1,056 | 1,059 | 100.0% |
| 目的地历史布点 | 拣选噪声 σ=0.25 | 63.7% | ±0.9% | 43,560 | 50,180 | 1,081 | 1,134 | 100.0% |
| 目的地历史布点 | 重度拥堵 σ=0.40 | 62.1% | ±1.3% | 48,862 | 62,215 | 1,119 | 1,208 | 100.0% |
| 目的地历史布点 | 加 1 名拣货员/DC | 100.0% | ±0.0% | 0 | 0 | 534 | 538 | 0.0% |
| 目的地历史 + 产能封顶 | 基准：均匀到达 · 确定性 | 69.1% | ±0.3% | 44,213 | 45,566 | 1,078 | 1,080 | 100.0% |
| 目的地历史 + 产能封顶 | 拣选噪声 σ=0.25 | 68.0% | ±0.7% | 47,728 | 56,391 | 1,101 | 1,155 | 100.0% |
| 目的地历史 + 产能封顶 | 重度拥堵 σ=0.40 | 66.6% | ±1.0% | 53,052 | 65,798 | 1,139 | 1,236 | 100.0% |
| 目的地历史 + 产能封顶 | 加 1 名拣货员/DC | 100.0% | ±0.0% | 0 | 0 | 543 | 547 | 0.0% |
| 联合布点 + 标准分单 | 基准：均匀到达 · 确定性 | 81.0% | ±0.4% | 10,480 | 10,909 | 781 | 782 | 100.0% |
| 联合布点 + 标准分单 | 拣选噪声 σ=0.25 | 76.8% | ±1.1% | 13,416 | 19,272 | 801 | 859 | 100.0% |
| 联合布点 + 标准分单 | 重度拥堵 σ=0.40 | 72.3% | ±1.9% | 17,793 | 25,697 | 829 | 900 | 100.0% |
| 联合布点 + 标准分单 | 加 1 名拣货员/DC | 100.0% | ±0.0% | 0 | 0 | 476 | 485 | 0.0% |
| 联合规划（分单+布点） | 基准：均匀到达 · 确定性 | 91.7% | ±0.3% | 990 | 1,110 | 649 | 650 | 100.0% |
| 联合规划（分单+布点） | 拣选噪声 σ=0.25 | 88.7% | ±1.5% | 2,208 | 4,083 | 668 | 718 | 96.7% |
| 联合规划（分单+布点） | 重度拥堵 σ=0.40 | 83.6% | ±2.4% | 4,312 | 7,460 | 698 | 777 | 96.7% |
| 联合规划（分单+布点） | 加 1 名拣货员/DC | 100.0% | ±0.0% | 0 | 0 | 475 | 485 | 0.0% |

## Paired comparisons

| Comparison | Stress cell | Δ OTIF | 95% CI | Win | Loss | Tie | n |
|---|---|---|---|---|---|---|---|
| 目的地历史布点 − Week-5 基线 34/28/38 | 基准：均匀到达 · 确定性 | -18.18% | ±0.5% | 0.0% | 100.0% | 0.0% | 30 |
| 目的地历史布点 − Week-5 基线 34/28/38 | 拣选噪声 σ=0.25 | -17.90% | ±0.8% | 0.0% | 100.0% | 0.0% | 30 |
| 目的地历史布点 − Week-5 基线 34/28/38 | 重度拥堵 σ=0.40 | -16.28% | ±1.1% | 0.0% | 100.0% | 0.0% | 30 |
| 目的地历史布点 − Week-5 基线 34/28/38 | 加 1 名拣货员/DC | -7.25% | ±0.0% | 0.0% | 100.0% | 0.0% | 30 |
| 目的地历史 + 产能封顶 − Week-5 基线 34/28/38 | 基准：均匀到达 · 确定性 | -6.73% | ±0.6% | 0.0% | 100.0% | 0.0% | 30 |
| 目的地历史 + 产能封顶 − Week-5 基线 34/28/38 | 拣选噪声 σ=0.25 | -6.38% | ±0.6% | 0.0% | 100.0% | 0.0% | 30 |
| 目的地历史 + 产能封顶 − Week-5 基线 34/28/38 | 重度拥堵 σ=0.40 | -5.04% | ±0.9% | 6.7% | 93.3% | 0.0% | 30 |
| 目的地历史 + 产能封顶 − Week-5 基线 34/28/38 | 加 1 名拣货员/DC | +7.50% | ±0.0% | 100.0% | 0.0% | 0.0% | 30 |
| 联合布点 + 标准分单 − Week-5 基线 34/28/38 | 基准：均匀到达 · 确定性 | -0.33% | ±0.6% | 40.0% | 56.7% | 3.3% | 30 |
| 联合布点 + 标准分单 − Week-5 基线 34/28/38 | 拣选噪声 σ=0.25 | -1.53% | ±0.7% | 20.0% | 80.0% | 0.0% | 30 |
| 联合布点 + 标准分单 − Week-5 基线 34/28/38 | 重度拥堵 σ=0.40 | -1.43% | ±0.8% | 23.3% | 73.3% | 3.3% | 30 |
| 联合布点 + 标准分单 − Week-5 基线 34/28/38 | 加 1 名拣货员/DC | +1.75% | ±0.0% | 100.0% | 0.0% | 0.0% | 30 |
| 联合规划（分单+布点） − Week-5 基线 34/28/38 | 基准：均匀到达 · 确定性 | +5.58% | ±0.4% | 100.0% | 0.0% | 0.0% | 30 |
| 联合规划（分单+布点） − Week-5 基线 34/28/38 | 拣选噪声 σ=0.25 | +5.73% | ±0.6% | 100.0% | 0.0% | 0.0% | 30 |
| 联合规划（分单+布点） − Week-5 基线 34/28/38 | 重度拥堵 σ=0.40 | +6.21% | ±0.9% | 100.0% | 0.0% | 0.0% | 30 |
| 联合规划（分单+布点） − Week-5 基线 34/28/38 | 加 1 名拣货员/DC | -5.75% | ±0.0% | 0.0% | 100.0% | 0.0% | 30 |
| 联合规划（分单+布点） − 联合布点 + 标准分单 | 基准：均匀到达 · 确定性 | +5.91% | ±0.5% | 100.0% | 0.0% | 0.0% | 30 |
| 联合规划（分单+布点） − 联合布点 + 标准分单 | 拣选噪声 σ=0.25 | +7.25% | ±0.8% | 100.0% | 0.0% | 0.0% | 30 |
| 联合规划（分单+布点） − 联合布点 + 标准分单 | 重度拥堵 σ=0.40 | +7.64% | ±1.1% | 96.7% | 3.3% | 0.0% | 30 |
| 联合规划（分单+布点） − 联合布点 + 标准分单 | 加 1 名拣货员/DC | -7.50% | ±0.0% | 0.0% | 100.0% | 0.0% | 30 |

The same arrival seed is replayed for both placements; the delta is `alternative − left`. Win/loss/tie counts are over seeds.

## Per-DC workload (seed 1, baseline cell)

| Placement | DC | Tickets | Waves | Labor (min) | On-time tickets | Tardy tickets | Tardy minutes | Makespan |
|---|---|---|---|---|---|---|---|---|
| Week-5 基线 34/28/38 | London | 242 | 32 | 731.5 | 148 | 94 | 6,000.3 | 731.5 |
| Week-5 基线 34/28/38 | Rotterdam | 202 | 26 | 558.2 | 199 | 3 | 13.7 | 558.2 |
| Week-5 基线 34/28/38 | Frankfurt | 210 | 29 | 675.8 | 165 | 45 | 1,364.4 | 675.8 |
| 目的地历史布点 | London | 298 | 40 | 1,058.9 | 141 | 157 | 36,808.9 | 1,058.9 |
| 目的地历史布点 | Rotterdam | 100 | 33 | 295.1 | 100 | 0 | 0.0 | 422.3 |
| 目的地历史布点 | Frankfurt | 100 | 35 | 321.1 | 100 | 0 | 0.0 | 444.6 |
| 目的地历史 + 产能封顶 | London | 305 | 42 | 1,079.9 | 125 | 180 | 43,455.0 | 1,079.9 |
| 目的地历史 + 产能封顶 | Rotterdam | 154 | 25 | 430.2 | 154 | 0 | 0.0 | 448.0 |
| 目的地历史 + 产能封顶 | Frankfurt | 149 | 30 | 454.0 | 149 | 0 | 0.0 | 454.0 |
| 联合布点 + 标准分单 | London | 241 | 32 | 781.8 | 133 | 108 | 10,169.5 | 781.8 |
| 联合布点 + 标准分单 | Rotterdam | 204 | 27 | 575.6 | 199 | 5 | 75.3 | 575.6 |
| 联合布点 + 标准分单 | Frankfurt | 207 | 31 | 595.1 | 207 | 0 | 0.0 | 595.1 |
| 联合规划（分单+布点） | London | 163 | 23 | 649.5 | 137 | 26 | 577.5 | 649.5 |
| 联合规划（分单+布点） | Rotterdam | 175 | 24 | 546.9 | 166 | 9 | 317.5 | 546.9 |
| 联合规划（分单+布点） | Frankfurt | 177 | 25 | 550.4 | 177 | 0 | 0.0 | 550.4 |

The snapshot shows how placement moves pick load across DCs; it is not averaged over seeds.

## Interpretation

1. **The joint solve, not the declared split, tops the known week.** At the deterministic baseline cell, `联合规划（分单+布点）` reaches 42.5% end-to-end OTIF versus 36.9% for `Week-5 基线 34/28/38` (+5.6%); the 95% intervals do not overlap in the normal approximation. This is a plan-driven scenario: it sees the week's orders, so read it as a hindsight bound rather than a deployable policy.
2. **Capacity-blind history is a demand signal, not a placement.** The prior-week UK/EU mix does not beat the declared split at the baseline cell (18.7% vs 36.9%, -18.2%). It concentrates stock wherever demand was, ignoring whether that DC can pick it.
3. **A deployable history mix must be capped to DC throughput.** Raw destination history is capacity-blind and scores 18.7%; clipping each DC's share at its weekly capacity lifts it to 30.2% (+11.5%). Against the declared split the capped placement is -6.7% (30.2% vs 36.9%).
4. **Joint allocation adds service beyond placement alone.** Joint placement with the standard allocation reaches 36.6%; the joint plan adds +5.9% (42.5%). The two stages interact, so solving them separately leaves value on the table.
5. **The allocation bound is not the service level.** The joint plan's own allocation OTIF is 45.0%, below the declared allocation's 50.7%, yet 94% of it survives the pick layer versus 73% for the declared split (42.5% vs 36.9%). The joint plan trades unpickable promises for tickets the shift can finish; a higher bound that the warehouse cannot execute is not worth more service.
6. **Extra pick capacity closes the execution gap.** With two pickers per DC every placement returns to its own allocation bound (largest gap 0.0%); `目的地历史 + 产能封顶` then leads at 58.2%. Placement and pick capacity are still joint decisions. The joint plan gains only +2.5%: its placement and allocation are fixed once solved, so extra pickers cannot re-optimise them. A static plan is tuned to the capacity it saw.
7. **Congestion does not reverse the ordering by itself.** Under σ=0.40 the best placement is `联合规划（分单+布点）` at 39.0%; compare it with the one-picker baseline before treating the ranking as robust.
8. **The plan-driven placement is an upper bound, not a policy.** It places stock after seeing the week's orders. The capacity-capped destination history is the deployable comparator; the gap between them is the value of hindsight, not a forecast improvement.

## Declared assumptions

- 订单/行/数量/目的国来自 Online Retail II 真实发票
- DC 库存、产能、转运天数、SLA 承诺与费率是显式假设
- 库存按 SKU 需求 stock_factor 分配并加入确定性偏斜
- 承诺天数 2/3/5 映射到拣选截单 12:00/16:00/18:00
- 班中到达占比与到达窗口是显式假设
- 三个 DC 共用同一 ABC 布局与拣选工时模型，每 DC 独立拣货员
- 库存总量按 SKU 固定，只改变各 DC 的库存位置；目的地历史只使用本周之前的数据
- 联合布点与联合规划看到本周订单，是已知周的上界，不是可部署的预测策略
- 所有场景共享订单集、到达种子与拥堵 σ，但分单可行集不同，配对只共享随机种子
- 联合 MILP 的拣选容量约束是线性分钟代理，不是波次仿真

## Limitations

- The destination mix is a proxy for demand, not a forecast; it ignores promotions, seasonality and the current week's orders, and the EU split inside the continent is declared rather than estimated. The capacity cap uses aggregate weekly throughput, so a DC can still be capped by unit count while being short of the exact SKUs the week needs.
- The plan-driven placement is hindsight: it sees the sampled week's orders. Its service level is an upper bound on joint planning for a known week, not a deployable policy.
- Both MILPs are time-limited `FEASIBLE`; the 60 s bound is loose and solver variation can mix with the placement effect. Pick capacity is a linear minute proxy, not a wave simulation.
- The joint placements have no repositioning cost: the model assumes stock can sit at the shipping DC at the start of the week, so its allocation cost is not comparable with the declared placement's transport cost. A real deployment would pay to move or hold that stock.
- The order set, promises, layout, slots and picker count are fixed; replenishment, DC-to-DC transfers, supplier constraints and demand shifts are outside the chain.
- The normal 95% interval is an approximation; placement comparisons are paired on arrival and noise seeds but not on solver outcomes, and the worst-decile mean is noisy with 30 seeds.
