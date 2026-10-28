# Empirical intraday arrivals (Week 15)

- Generated: `2026-10-28T06:31:16.494921+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Arrival window: **Mon–Fri 08:00–18:00** from Online Retail II `InvoiceDate` | prior weeks **6** | target week is a **holdout**
- Seeds: **30** | cells: **8** | pickers/DC: **1** | shift **600 min** | wave cap **8 orders / 40 lines**
- Allocation: **MILP 拣选容量感知（Week-9 分单）** (FEASIBLE) | solver **60 s**

## Assumptions

| Item | Assumption | Note |
|---|---|---|
| Arrival shape | prior-week hourly shares of invoice lines | Mon–Fri, inside the business window; shapes are observed, the clock is invoice creation |
| On-site share | 70% / 50% / 40% for express / standard / economy | declared, unchanged from Weeks 8-14 |
| Tier windows | 120 / 360 / 480 min | declared; the curve is rescaled into each window |
| Pick cutoffs | 12:00 / 16:00 / 18:00 | declared mapping from the 2/3/5-day promise |
| Congestion | lognormal multiplier σ declared | no pick-duration data exists in the public dataset |
| Allocation | Week-9 capacity-aware MILP, time-limited | stock, slots, layout and promises are fixed across cells |

## Observed intraday curve

Shares are the fraction of a week's in-window invoice lines per clock hour. Weekends are excluded from the shape estimate; the excluded share is reported.

| Week | Role | Weekday lines | In window | Coverage | Weekend share | 08 | 09 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | Peak |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2011-10-17 | 经验曲线 | 11,676 | 11,581 | 99.2% | 12.9% | 1.6% | 6.5% | 9.0% | 9.7% | 18.6% | 17.9% | 11.5% | 13.3% | 6.8% | 5.1% | 12:00 |
| 2011-10-24 | 经验曲线 | 11,236 | 10,664 | 94.9% | 20.5% | 2.8% | 2.4% | 8.0% | 4.2% | 14.5% | 18.1% | 14.4% | 6.9% | 11.8% | 16.8% | 13:00 |
| 2011-10-31 | 经验曲线 | 12,924 | 12,822 | 99.2% | 20.9% | 1.1% | 6.0% | 6.7% | 8.5% | 13.7% | 11.3% | 26.0% | 20.5% | 4.8% | 1.5% | 14:00 |
| 2011-11-07 | 经验曲线 | 15,918 | 14,650 | 92.0% | 15.8% | 1.8% | 9.4% | 10.6% | 8.6% | 19.6% | 12.8% | 8.8% | 9.1% | 10.0% | 9.3% | 12:00 |
| 2011-11-14 | 经验曲线 | 17,374 | 17,232 | 99.2% | 16.0% | 2.3% | 4.2% | 8.3% | 7.3% | 13.1% | 11.8% | 10.1% | 27.2% | 8.2% | 7.5% | 15:00 |
| 2011-11-21 | 经验曲线 | 17,062 | 16,871 | 98.9% | 12.9% | 2.4% | 10.5% | 5.6% | 11.9% | 11.2% | 16.1% | 11.8% | 17.2% | 10.7% | 2.7% | 15:00 |
| 2011-11-28 | 目标周留出诊断 | 16,535 | 16,133 | 97.6% | 10.9% | 1.6% | 2.7% | 8.6% | 9.9% | 11.6% | 11.0% | 12.8% | 19.5% | 18.8% | 3.5% | 15:00 |

Target-week coverage of weekday lines inside the window: **97.6%**; weekend share of its lines: **10.9%**. Mean total-variation distance to uniform: **0.222**; mean pairwise distance among prior weeks: **0.216** (max 0.330).

## Benchmark cells

| Cell | Arrival | Policy | Pick noise σ | Pickers / DC |
|---|---|---|---|---|
| 均匀到达 · EDF（Week-10 对照） | 均匀（声明） | edf | 0.00 | 1 |
| 声明尖峰 · EDF（Week-10 对照） | 尖峰（声明） | edf | 0.00 | 1 |
| 前 6 周平均经验曲线 · EDF | 前几周平均经验曲线 | edf | 0.00 | 1 |
| 逐周经验曲线 · EDF | 逐周经验曲线 | edf | 0.00 | 1 |
| 逐周经验曲线 · 节省重批 | 逐周经验曲线 | savings | 0.00 | 1 |
| 声明尖峰 · 节省重批 | 尖峰（声明） | savings | 0.00 | 1 |
| 逐周经验曲线 · 噪声 σ=0.25 | 逐周经验曲线 | edf | 0.25 | 1 |
| 逐周经验曲线 · 加 1 名拣货员/DC | 逐周经验曲线 | edf | 0.00 | 2 |

## Where mid-shift orders land

Each mid-shift order draws a minute inside its tier window. The table averages that relative position across seeds and orders.

| Cell | Mid-shift orders | Mean window fraction | Median window fraction | Arrive after half | Arrive after 3/4 | Mean shift minute |
|---|---|---|---|---|---|---|
| 均匀到达 · EDF（Week-10 对照） | 5,520 | 50.2% | 50.7% | 50.9% | 24.4% | 173 |
| 声明尖峰 · EDF（Week-10 对照） | 5,520 | 50.0% | 50.3% | 50.9% | 9.7% | 172 |
| 前 6 周平均经验曲线 · EDF | 5,520 | 55.5% | 56.9% | 59.4% | 23.9% | 191 |
| 逐周经验曲线 · EDF | 5,520 | 55.5% | 56.5% | 59.3% | 24.2% | 191 |
| 逐周经验曲线 · 节省重批 | 5,520 | 55.5% | 56.5% | 59.3% | 24.2% | 191 |
| 声明尖峰 · 节省重批 | 5,520 | 50.0% | 50.3% | 50.9% | 9.7% | 172 |
| 逐周经验曲线 · 噪声 σ=0.25 | 5,520 | 55.5% | 56.5% | 59.3% | 24.2% | 191 |
| 逐周经验曲线 · 加 1 名拣货员/DC | 5,520 | 55.5% | 56.5% | 59.3% | 24.2% | 191 |

## End-to-end OTIF distribution

Every cell is replayed on the same seeds with the same allocation; only the arrival draw, release policy, noise or picker count changes.

| Cell | Mean | 95% CI | P10 | P50 | P90 | Worst 10% mean | n |
|---|---|---|---|---|---|---|---|
| 均匀到达 · EDF（Week-10 对照） | 37.4% | ±0.5% | 35.5% | 38.0% | 39.0% | 34.5% | 30 |
| 声明尖峰 · EDF（Week-10 对照） | 37.3% | ±0.5% | 35.5% | 37.2% | 39.0% | 34.8% | 30 |
| 前 6 周平均经验曲线 · EDF | 36.7% | ±0.5% | 35.2% | 36.9% | 38.3% | 34.3% | 30 |
| 逐周经验曲线 · EDF | 36.7% | ±0.4% | 35.5% | 36.6% | 38.0% | 34.8% | 30 |
| 逐周经验曲线 · 节省重批 | 38.5% | ±0.6% | 36.0% | 38.8% | 40.3% | 35.7% | 30 |
| 声明尖峰 · 节省重批 | 38.6% | ±0.7% | 36.2% | 38.5% | 40.6% | 35.6% | 30 |
| 逐周经验曲线 · 噪声 σ=0.25 | 34.9% | ±1.0% | 31.5% | 34.4% | 38.8% | 31.1% | 30 |
| 逐周经验曲线 · 加 1 名拣货员/DC | 52.0% | ±0.0% | 52.0% | 52.0% | 52.0% | 52.0% | 30 |

## Paired differences

Differences are `right − left` on shared seeds within each cell pair; the interval is the normal approximation over seeds.

| Comparison | Δ OTIF | 95% CI | Win | Loss | Tie | n |
|---|---|---|---|---|---|---|
| 逐周经验曲线 · EDF − 均匀到达 · EDF（Week-10 对照） | -0.7% | ±0.5% | 30.0% | 63.3% | 6.7% | 30 |
| 逐周经验曲线 · EDF − 声明尖峰 · EDF（Week-10 对照） | -0.6% | ±0.5% | 23.3% | 60.0% | 16.7% | 30 |
| 逐周经验曲线 · EDF − 前 6 周平均经验曲线 · EDF | -0.0% | ±0.2% | 46.7% | 43.3% | 10.0% | 30 |
| 逐周经验曲线 · 节省重批 − 逐周经验曲线 · EDF | +1.8% | ±0.6% | 83.3% | 13.3% | 3.3% | 30 |
| 声明尖峰 · 节省重批 − 声明尖峰 · EDF（Week-10 对照） | +1.3% | ±0.7% | 80.0% | 20.0% | 0.0% | 30 |
| 逐周经验曲线 · 噪声 σ=0.25 − 逐周经验曲线 · EDF | -1.8% | ±0.9% | 23.3% | 70.0% | 6.7% | 30 |
| 逐周经验曲线 · 加 1 名拣货员/DC − 逐周经验曲线 · EDF | +15.3% | ±0.4% | 100.0% | 0.0% | 0.0% | 30 |

## Execution risk

Shift length 600 min; 1 picker(s) per DC.

| Cell | Picked on time | Tardy minutes | Makespan (min) | Labor / ticket (min) |
|---|---|---|---|---|
| 均匀到达 · EDF（Week-10 对照） | 78.3% | 8,032 | 731 | 3 |
| 声明尖峰 · EDF（Week-10 对照） | 78.5% | 8,060 | 731 | 3 |
| 前 6 周平均经验曲线 · EDF | 78.0% | 8,228 | 731 | 3 |
| 逐周经验曲线 · EDF | 78.0% | 8,152 | 731 | 3 |
| 逐周经验曲线 · 节省重批 | 80.0% | 6,998 | 729 | 3 |
| 声明尖峰 · 节省重批 | 80.4% | 6,835 | 728 | 3 |
| 逐周经验曲线 · 噪声 σ=0.25 | 74.2% | 11,105 | 754 | 3 |
| 逐周经验曲线 · 加 1 名拣货员/DC | 100.0% | 0 | 466 | 3 |

| Cell | Over-shift rate | Mean makespan | P90 makespan | n |
|---|---|---|---|---|
| 均匀到达 · EDF（Week-10 对照） | 100.0% | 731 | 735 | 30 |
| 声明尖峰 · EDF（Week-10 对照） | 100.0% | 731 | 735 | 30 |
| 前 6 周平均经验曲线 · EDF | 100.0% | 731 | 734 | 30 |
| 逐周经验曲线 · EDF | 100.0% | 731 | 734 | 30 |
| 逐周经验曲线 · 节省重批 | 100.0% | 729 | 731 | 30 |
| 声明尖峰 · 节省重批 | 100.0% | 728 | 730 | 30 |
| 逐周经验曲线 · 噪声 σ=0.25 | 100.0% | 754 | 787 | 30 |
| 逐周经验曲线 · 加 1 名拣货员/DC | 0.0% | 466 | 483 | 30 |

## Interpretation

- **The observed day is back-loaded.** The target week peaks at 15:00 with 19.5% of in-window lines in that hour and 65.6% after the halfway point; the prior-week curves sit 0.222 (total variation) away from uniform. The target curve is a holdout: its distance to the prior mean is 0.161, closer than 86.7% of prior-week pairs, so it is reported but never used.
- **Uniform vs empirical.** End-to-end OTIF moves from 37.4% (uniform) to 36.7% (week curves), -0.7% ±0.5% with a 30.0% win rate, so the declared uniform window is optimistic: the observed curve delivers fewer end-to-end on-time orders.
- **Spike vs empirical.** The spike cell scores 37.3%; the week curves add -0.6% ±0.5% (win rate 23.3%), so the declared spike still understates how late the real day runs.
- **Average curve vs weekly draws.** Using one mean curve gives -0.0% ±0.2% against resampling a prior week per seed (win rate 46.7%); the average curve summarises the weekly draws without material bias.
- **Release policy under each arrival family.** Savings re-batching adds +1.8% ±0.6% under the week curves and +1.3% ±0.7% under the declared spike; the re-batch gain survives calibration, so it is not a spike artefact.
- **Congestion noise stacks on the arrival shape.** Adding σ=0.25 pick-duration noise moves OTIF by -1.8% ±0.9% on the same curves; the arrival calibration does not remove execution risk.
- **Capacity still dominates.** A second picker per DC moves OTIF from 36.7% to 52.0% (+15.3% ±0.4%, win rate 100.0%); with 1 picker(s) per DC the chain is capacity-bound regardless of the arrival shape.
- **The observed clock stresses the promise design.** Only 22.8% of target-week weekday lines are invoiced before 12:00 and 77.7% before 16:00. The 12:00 express cutoff is a declared policy, not a target the observed timing can meet; invoice creation time is also not a DC receipt scan, so this is a design warning rather than a measured service level.
- **Scope.** Only the intraday shape is calibrated. Promise windows, the 70/50/40 on-site share, pick cutoffs, pick-duration noise, stock, layout and the allocation are unchanged from Weeks 9-10, so the comparison isolates arrival timing.

## Limitations

- `InvoiceDate` is the retailer's invoice creation timestamp, not a warehouse receipt scan; the curve is a public proxy for intraday demand timing.
- The shape is estimated on 6 prior weeks with Mon–Fri filtering and a 08:00–18:00 window; the 2–5% of lines outside the window and the weekend lines are excluded from the shape, not from the demand.
- Only the arrival shape is calibrated. Pick minutes, congestion σ, stock, slots, layout, promises and the allocation remain the Week-9/10 declarations.
- The curve is rescaled into each declared tier window, so a late-day peak shifts arrivals later inside a short express window rather than making them infeasible; absolute timing is not a clock replay.
- One target week, one warehouse layout, one labour model and one allocation; differences are conditional on those choices and absolute OTIF is not transferable.
- Week curves are resampled by seed index, so the empirical cell mixes shape noise with seed noise; paired intervals compare cells on the same seeds but not on identical arrival times.
