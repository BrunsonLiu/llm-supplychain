# Mid-shift write-back under stock-placement imbalance (Week 12)

- Generated: `2026-10-27T22:59:19.048250+00:00`
- Orders: **400** real invoices / **2477** lines / **33060** units, week 2011-11-28
- Seeds per cell: **30**; stress cells: **4**; stock placements: **3**; policies: **4**
- Review at **120.0 min**, transfer lead **30.0 min**, fee **€10.0/ticket**, minimum projected gain **5.0 min**
- Picking: **1 picker(s) per DC**, wave cap **8 orders / 40 lines**, shift **600.0 min**, EDF release

## Assumptions

| Item | Assumption | Note |
|---|---|---|
| Review | phase 1 runs to the declared minute; waves already started are locked | Only pick tickets in not-yet-started waves are movable. |
| Transfer | the ticket's stock moves to the target DC; target starts after review + lead | Target transit must still fit the customer promise; weekly capacity is checked. |
| Projection | deterministic EDF replay of each DC's remaining queue | The planner sees planned minutes, not future noise. The oracle policy only knows the realised late set. |
| Execution | phase 2 resamples pick durations with a shared seed | All policies share the same phase-2 draw, so differences isolate moves. |
| Network | 3 DCs, declared transit days, DC stock and capacity | No replenishment, transfer transport schedule or demand shift. |

## Methods

- **Phase split**: run the Week-8 online release from shift start to the review minute, lock every wave that has started, and keep the remaining tickets as the movable set.
- **Projection**: replay each DC's movable tickets with EDF from the review state, using deterministic wave minutes and the pickers' carry-over free times.
- **Policies**: `none` freezes the allocation but still replays phase 2; `reroute` moves projected-late tickets; `balance` moves any pending ticket whose projected end improves by at least the declared minimum; `oracle` uses the realised late set from phase 1 as its candidate list.
- **Choice rule**: for each candidate, estimate the target's completion from its free time, transfer arrival, cutoff-window workload and single-ticket minutes; require promise-feasible transit, weekly DC capacity, an on-time estimate for late candidates, and the minimum gain.
- **Replay**: resample arrivals per seed, run phase 1, apply each policy, replay phase 2 per DC and recompute end-to-end OTIF against the same allocation bound.
- **Statistics**: mean with a normal 95% interval, P10/P50/P90, worst-decile mean, paired policy deltas on shared seeds, and over-shift probability.

## Stock placements

| 库存布点 | 声明占比 | 实际占比 | 库存件数 | 覆盖率 | 分单界 OTIF | 分单成本 (€) |
|---|---|---|---|---|---|---|
| 基线 34/28/38 | London 34% / Rotterdam 28% / Frankfurt 38% | 35% / 28% / 37% | 9,932 / 7,823 / 10,349 | 85.0% | 53.0% | 62,309 |
| 均衡 33/33/34 | London 33% / Rotterdam 33% / Frankfurt 34% | 34% / 33% / 33% | 9,624 / 9,201 / 9,279 | 85.0% | 57.2% | 63,177 |
| London 偏重 40/24/36 | London 40% / Rotterdam 24% / Frankfurt 36% | 41% / 24% / 35% | 11,641 / 6,691 / 9,772 | 85.0% | 54.5% | 62,612 |

Each placement is re-solved through the same Week-11 allocation chain; the allocation bound is the ceiling that write-back cannot exceed.

## Policy impact by stress cell

| 库存布点 | 压力格 | 回写策略 | 端到端 OTIF | 95% CI | Δ vs 无回写 | 胜/平/负 | 调动票据 | 回写成本 (€) |
|---|---|---|---|---|---|---|---|---|
| 基线 34/28/38 | 基准：均匀到达 · 确定性 | 无回写（分单冻结） | 38.8% | ±0.5% | — | — | 0.0 | 0 |
| 基线 34/28/38 | 基准：均匀到达 · 确定性 | 迟到票据跨 DC 调动 | 38.9% | ±0.5% | +0.1% | 23% / 77% / 0% | 1.1 | 14 |
| 基线 34/28/38 | 基准：均匀到达 · 确定性 | 全队列跨 DC 再平衡 | 38.9% | ±0.5% | +0.1% | 50% / 47% / 3% | 3.3 | 45 |
| 基线 34/28/38 | 基准：均匀到达 · 确定性 | 先知迟到集合（上界参考） | 38.9% | ±0.5% | +0.1% | 23% / 77% / 0% | 1.1 | 14 |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 无回写（分单冻结） | 36.7% | ±1.1% | — | — | 0.0 | 0 |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 迟到票据跨 DC 调动 | 36.8% | ±1.1% | +0.1% | 17% / 83% / 0% | 0.7 | 7 |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 全队列跨 DC 再平衡 | 36.9% | ±1.1% | +0.2% | 43% / 47% / 10% | 2.3 | 24 |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 先知迟到集合（上界参考） | 36.8% | ±1.1% | +0.0% | 10% / 90% / 0% | 0.7 | 9 |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 无回写（分单冻结） | 34.1% | ±1.4% | — | — | 0.0 | 0 |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 迟到票据跨 DC 调动 | 34.1% | ±1.4% | +0.0% | 10% / 87% / 3% | 0.7 | 6 |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 全队列跨 DC 再平衡 | 34.1% | ±1.4% | +0.1% | 33% / 60% / 7% | 2.0 | 20 |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 先知迟到集合（上界参考） | 34.1% | ±1.4% | +0.0% | 3% / 97% / 0% | 0.7 | 8 |
| 基线 34/28/38 | 加 1 名拣货员/DC | 无回写（分单冻结） | 53.0% | ±0.0% | — | — | 0.0 | 0 |
| 基线 34/28/38 | 加 1 名拣货员/DC | 迟到票据跨 DC 调动 | 53.0% | ±0.0% | +0.0% | 0% / 100% / 0% | 0.0 | 0 |
| 基线 34/28/38 | 加 1 名拣货员/DC | 全队列跨 DC 再平衡 | 53.0% | ±0.0% | +0.0% | 0% / 100% / 0% | 0.1 | 2 |
| 基线 34/28/38 | 加 1 名拣货员/DC | 先知迟到集合（上界参考） | 53.0% | ±0.0% | +0.0% | 0% / 100% / 0% | 0.0 | 0 |
| 均衡 33/33/34 | 基准：均匀到达 · 确定性 | 无回写（分单冻结） | 44.1% | ±0.5% | — | — | 0.0 | 0 |
| 均衡 33/33/34 | 基准：均匀到达 · 确定性 | 迟到票据跨 DC 调动 | 44.1% | ±0.5% | +0.0% | 0% / 100% / 0% | 0.0 | 0 |
| 均衡 33/33/34 | 基准：均匀到达 · 确定性 | 全队列跨 DC 再平衡 | 44.2% | ±0.5% | +0.1% | 7% / 93% / 0% | 0.1 | 1 |
| 均衡 33/33/34 | 基准：均匀到达 · 确定性 | 先知迟到集合（上界参考） | 44.1% | ±0.5% | +0.0% | 0% / 100% / 0% | 0.0 | 0 |
| 均衡 33/33/34 | 拣选噪声 σ=0.25 | 无回写（分单冻结） | 40.5% | ±1.4% | — | — | 0.0 | 0 |
| 均衡 33/33/34 | 拣选噪声 σ=0.25 | 迟到票据跨 DC 调动 | 40.4% | ±1.4% | -0.0% | 3% / 93% / 3% | 0.1 | 2 |
| 均衡 33/33/34 | 拣选噪声 σ=0.25 | 全队列跨 DC 再平衡 | 40.5% | ±1.5% | +0.1% | 13% / 77% / 10% | 0.4 | 8 |
| 均衡 33/33/34 | 拣选噪声 σ=0.25 | 先知迟到集合（上界参考） | 40.4% | ±1.4% | -0.0% | 7% / 90% / 3% | 0.2 | 3 |
| 均衡 33/33/34 | 重度拥堵 σ=0.40 | 无回写（分单冻结） | 37.1% | ±1.7% | — | — | 0.0 | 0 |
| 均衡 33/33/34 | 重度拥堵 σ=0.40 | 迟到票据跨 DC 调动 | 37.1% | ±1.7% | +0.0% | 3% / 97% / 0% | 0.1 | 1 |
| 均衡 33/33/34 | 重度拥堵 σ=0.40 | 全队列跨 DC 再平衡 | 37.1% | ±1.7% | -0.0% | 7% / 77% / 17% | 0.5 | 8 |
| 均衡 33/33/34 | 重度拥堵 σ=0.40 | 先知迟到集合（上界参考） | 37.2% | ±1.7% | +0.1% | 10% / 90% / 0% | 0.3 | 5 |
| 均衡 33/33/34 | 加 1 名拣货员/DC | 无回写（分单冻结） | 57.3% | ±0.0% | — | — | 0.0 | 0 |
| 均衡 33/33/34 | 加 1 名拣货员/DC | 迟到票据跨 DC 调动 | 57.3% | ±0.0% | +0.0% | 0% / 100% / 0% | 0.0 | 0 |
| 均衡 33/33/34 | 加 1 名拣货员/DC | 全队列跨 DC 再平衡 | 57.3% | ±0.0% | +0.0% | 0% / 100% / 0% | 0.0 | 0 |
| 均衡 33/33/34 | 加 1 名拣货员/DC | 先知迟到集合（上界参考） | 57.3% | ±0.0% | +0.0% | 0% / 100% / 0% | 0.0 | 0 |
| London 偏重 40/24/36 | 基准：均匀到达 · 确定性 | 无回写（分单冻结） | 35.3% | ±0.5% | — | — | 0.0 | 0 |
| London 偏重 40/24/36 | 基准：均匀到达 · 确定性 | 迟到票据跨 DC 调动 | 37.5% | ±0.5% | +2.2% | 100% / 0% / 0% | 16.7 | 257 |
| London 偏重 40/24/36 | 基准：均匀到达 · 确定性 | 全队列跨 DC 再平衡 | 38.7% | ±0.5% | +3.3% | 100% / 0% / 0% | 33.8 | 573 |
| London 偏重 40/24/36 | 基准：均匀到达 · 确定性 | 先知迟到集合（上界参考） | 37.5% | ±0.5% | +2.2% | 100% / 0% / 0% | 16.7 | 257 |
| London 偏重 40/24/36 | 拣选噪声 σ=0.25 | 无回写（分单冻结） | 33.2% | ±0.9% | — | — | 0.0 | 0 |
| London 偏重 40/24/36 | 拣选噪声 σ=0.25 | 迟到票据跨 DC 调动 | 35.2% | ±1.0% | +2.0% | 100% / 0% / 0% | 16.5 | 252 |
| London 偏重 40/24/36 | 拣选噪声 σ=0.25 | 全队列跨 DC 再平衡 | 36.0% | ±1.1% | +2.8% | 100% / 0% / 0% | 30.8 | 526 |
| London 偏重 40/24/36 | 拣选噪声 σ=0.25 | 先知迟到集合（上界参考） | 35.2% | ±1.0% | +2.0% | 100% / 0% / 0% | 16.5 | 252 |
| London 偏重 40/24/36 | 重度拥堵 σ=0.40 | 无回写（分单冻结） | 30.8% | ±1.3% | — | — | 0.0 | 0 |
| London 偏重 40/24/36 | 重度拥堵 σ=0.40 | 迟到票据跨 DC 调动 | 32.5% | ±1.3% | +1.7% | 100% / 0% / 0% | 15.7 | 246 |
| London 偏重 40/24/36 | 重度拥堵 σ=0.40 | 全队列跨 DC 再平衡 | 32.9% | ±1.4% | +2.1% | 93% / 3% / 3% | 28.3 | 489 |
| London 偏重 40/24/36 | 重度拥堵 σ=0.40 | 先知迟到集合（上界参考） | 32.5% | ±1.3% | +1.7% | 100% / 0% / 0% | 15.7 | 246 |
| London 偏重 40/24/36 | 加 1 名拣货员/DC | 无回写（分单冻结） | 54.5% | ±0.0% | — | — | 0.0 | 0 |
| London 偏重 40/24/36 | 加 1 名拣货员/DC | 迟到票据跨 DC 调动 | 54.5% | ±0.0% | +0.0% | 0% / 100% / 0% | 0.0 | 0 |
| London 偏重 40/24/36 | 加 1 名拣货员/DC | 全队列跨 DC 再平衡 | 54.5% | ±0.0% | +0.0% | 0% / 100% / 0% | 30.2 | 484 |
| London 偏重 40/24/36 | 加 1 名拣货员/DC | 先知迟到集合（上界参考） | 54.5% | ±0.0% | +0.0% | 0% / 100% / 0% | 0.0 | 0 |

`Δ vs no write-back` is the paired mean difference on shared seeds; `win / tie / loss` counts seeds where the policy beats, matches or loses to `none`.

## Execution risk

| 库存布点 | 压力格 | 回写策略 | 拣选准时 | 迟到分钟 | Makespan | 超班次概率 |
|---|---|---|---|---|---|---|
| 基线 34/28/38 | 基准：均匀到达 · 确定性 | 无回写（分单冻结） | 77.7% | 6,867 | 717 | 100.0% |
| 基线 34/28/38 | 基准：均匀到达 · 确定性 | 迟到票据跨 DC 调动 | 77.9% | 6,752 | 715 | 100.0% |
| 基线 34/28/38 | 基准：均匀到达 · 确定性 | 全队列跨 DC 再平衡 | 78.3% | 6,597 | 711 | 100.0% |
| 基线 34/28/38 | 基准：均匀到达 · 确定性 | 先知迟到集合（上界参考） | 77.9% | 6,752 | 715 | 100.0% |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 无回写（分单冻结） | 73.1% | 10,980 | 752 | 100.0% |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 迟到票据跨 DC 调动 | 73.3% | 10,834 | 750 | 100.0% |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 全队列跨 DC 再平衡 | 73.4% | 10,759 | 748 | 100.0% |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 先知迟到集合（上界参考） | 73.2% | 10,906 | 751 | 100.0% |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 无回写（分单冻结） | 68.6% | 16,196 | 791 | 100.0% |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 迟到票据跨 DC 调动 | 68.6% | 16,110 | 790 | 100.0% |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 全队列跨 DC 再平衡 | 68.7% | 16,047 | 788 | 100.0% |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 先知迟到集合（上界参考） | 68.7% | 16,117 | 790 | 100.0% |
| 基线 34/28/38 | 加 1 名拣货员/DC | 无回写（分单冻结） | 100.0% | 0 | 476 | 0.0% |
| 基线 34/28/38 | 加 1 名拣货员/DC | 迟到票据跨 DC 调动 | 100.0% | 0 | 476 | 0.0% |
| 基线 34/28/38 | 加 1 名拣货员/DC | 全队列跨 DC 再平衡 | 100.0% | 0 | 476 | 0.0% |
| 基线 34/28/38 | 加 1 名拣货员/DC | 先知迟到集合（上界参考） | 100.0% | 0 | 476 | 0.0% |
| 均衡 33/33/34 | 基准：均匀到达 · 确定性 | 无回写（分单冻结） | 81.1% | 4,289 | 692 | 100.0% |
| 均衡 33/33/34 | 基准：均匀到达 · 确定性 | 迟到票据跨 DC 调动 | 81.1% | 4,289 | 692 | 100.0% |
| 均衡 33/33/34 | 基准：均匀到达 · 确定性 | 全队列跨 DC 再平衡 | 81.2% | 4,280 | 692 | 100.0% |
| 均衡 33/33/34 | 基准：均匀到达 · 确定性 | 先知迟到集合（上界参考） | 81.1% | 4,289 | 692 | 100.0% |
| 均衡 33/33/34 | 拣选噪声 σ=0.25 | 无回写（分单冻结） | 75.2% | 7,565 | 722 | 100.0% |
| 均衡 33/33/34 | 拣选噪声 σ=0.25 | 迟到票据跨 DC 调动 | 75.2% | 7,550 | 722 | 100.0% |
| 均衡 33/33/34 | 拣选噪声 σ=0.25 | 全队列跨 DC 再平衡 | 75.3% | 7,538 | 721 | 100.0% |
| 均衡 33/33/34 | 拣选噪声 σ=0.25 | 先知迟到集合（上界参考） | 75.2% | 7,550 | 722 | 100.0% |
| 均衡 33/33/34 | 重度拥堵 σ=0.40 | 无回写（分单冻结） | 69.7% | 12,039 | 757 | 100.0% |
| 均衡 33/33/34 | 重度拥堵 σ=0.40 | 迟到票据跨 DC 调动 | 69.7% | 12,020 | 757 | 100.0% |
| 均衡 33/33/34 | 重度拥堵 σ=0.40 | 全队列跨 DC 再平衡 | 69.7% | 12,005 | 756 | 100.0% |
| 均衡 33/33/34 | 重度拥堵 σ=0.40 | 先知迟到集合（上界参考） | 69.8% | 11,995 | 756 | 100.0% |
| 均衡 33/33/34 | 加 1 名拣货员/DC | 无回写（分单冻结） | 100.0% | 0 | 476 | 0.0% |
| 均衡 33/33/34 | 加 1 名拣货员/DC | 迟到票据跨 DC 调动 | 100.0% | 0 | 476 | 0.0% |
| 均衡 33/33/34 | 加 1 名拣货员/DC | 全队列跨 DC 再平衡 | 100.0% | 0 | 476 | 0.0% |
| 均衡 33/33/34 | 加 1 名拣货员/DC | 先知迟到集合（上界参考） | 100.0% | 0 | 476 | 0.0% |
| London 偏重 40/24/36 | 基准：均匀到达 · 确定性 | 无回写（分单冻结） | 75.2% | 16,723 | 833 | 100.0% |
| London 偏重 40/24/36 | 基准：均匀到达 · 确定性 | 迟到票据跨 DC 调动 | 77.9% | 12,334 | 788 | 100.0% |
| London 偏重 40/24/36 | 基准：均匀到达 · 确定性 | 全队列跨 DC 再平衡 | 80.8% | 8,408 | 734 | 100.0% |
| London 偏重 40/24/36 | 基准：均匀到达 · 确定性 | 先知迟到集合（上界参考） | 77.9% | 12,334 | 788 | 100.0% |
| London 偏重 40/24/36 | 拣选噪声 σ=0.25 | 无回写（分单冻结） | 71.7% | 21,016 | 865 | 100.0% |
| London 偏重 40/24/36 | 拣选噪声 σ=0.25 | 迟到票据跨 DC 调动 | 74.4% | 16,207 | 818 | 100.0% |
| London 偏重 40/24/36 | 拣选噪声 σ=0.25 | 全队列跨 DC 再平衡 | 76.5% | 12,422 | 768 | 100.0% |
| London 偏重 40/24/36 | 拣选噪声 σ=0.25 | 先知迟到集合（上界参考） | 74.4% | 16,207 | 818 | 100.0% |
| London 偏重 40/24/36 | 重度拥堵 σ=0.40 | 无回写（分单冻结） | 67.9% | 26,812 | 901 | 100.0% |
| London 偏重 40/24/36 | 重度拥堵 σ=0.40 | 迟到票据跨 DC 调动 | 70.1% | 21,647 | 854 | 100.0% |
| London 偏重 40/24/36 | 重度拥堵 σ=0.40 | 全队列跨 DC 再平衡 | 71.4% | 17,992 | 811 | 100.0% |
| London 偏重 40/24/36 | 重度拥堵 σ=0.40 | 先知迟到集合（上界参考） | 70.1% | 21,649 | 854 | 100.0% |
| London 偏重 40/24/36 | 加 1 名拣货员/DC | 无回写（分单冻结） | 100.0% | 0 | 476 | 0.0% |
| London 偏重 40/24/36 | 加 1 名拣货员/DC | 迟到票据跨 DC 调动 | 100.0% | 0 | 476 | 0.0% |
| London 偏重 40/24/36 | 加 1 名拣货员/DC | 全队列跨 DC 再平衡 | 100.0% | 0 | 476 | 0.0% |
| London 偏重 40/24/36 | 加 1 名拣货员/DC | 先知迟到集合（上界参考） | 100.0% | 0 | 476 | 0.0% |

## Move behaviour

| 库存布点 | 压力格 | 回写策略 | 有调动种子 | 平均票据 | 平均件数 | 平均调拨费 (€) | 平均运输差 (€) | 救回订单 | 丢失订单 |
|---|---|---|---|---|---|---|---|---|---|
| 基线 34/28/38 | 基准：均匀到达 · 确定性 | 迟到票据跨 DC 调动 | 13/30 | 1.1 | 32 | 11 | 3 | 10 | 0 |
| 基线 34/28/38 | 基准：均匀到达 · 确定性 | 全队列跨 DC 再平衡 | 30/30 | 3.3 | 91 | 33 | 13 | 20 | 3 |
| 基线 34/28/38 | 基准：均匀到达 · 确定性 | 先知迟到集合（上界参考） | 13/30 | 1.1 | 32 | 11 | 3 | 10 | 0 |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 迟到票据跨 DC 调动 | 10/30 | 0.7 | 21 | 7 | -0 | 10 | 1 |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 全队列跨 DC 再平衡 | 23/30 | 2.3 | 66 | 23 | 1 | 28 | 6 |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 先知迟到集合（上界参考） | 9/30 | 0.7 | 18 | 7 | 2 | 7 | 1 |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 迟到票据跨 DC 调动 | 9/30 | 0.7 | 25 | 7 | -1 | 4 | 4 |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 全队列跨 DC 再平衡 | 20/30 | 2.0 | 62 | 20 | 0 | 22 | 16 |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 先知迟到集合（上界参考） | 9/30 | 0.7 | 21 | 7 | 1 | 1 | 0 |
| 基线 34/28/38 | 加 1 名拣货员/DC | 迟到票据跨 DC 调动 | 0/30 | 0.0 | 0 | 0 | 0 | 0 | 0 |
| 基线 34/28/38 | 加 1 名拣货员/DC | 全队列跨 DC 再平衡 | 2/30 | 0.1 | 4 | 1 | 1 | 0 | 0 |
| 基线 34/28/38 | 加 1 名拣货员/DC | 先知迟到集合（上界参考） | 0/30 | 0.0 | 0 | 0 | 0 | 0 | 0 |
| 均衡 33/33/34 | 基准：均匀到达 · 确定性 | 迟到票据跨 DC 调动 | 0/30 | 0.0 | 0 | 0 | 0 | 0 | 0 |
| 均衡 33/33/34 | 基准：均匀到达 · 确定性 | 全队列跨 DC 再平衡 | 2/30 | 0.1 | 2 | 1 | 1 | 6 | 0 |
| 均衡 33/33/34 | 基准：均匀到达 · 确定性 | 先知迟到集合（上界参考） | 0/30 | 0.0 | 0 | 0 | 0 | 0 | 0 |
| 均衡 33/33/34 | 拣选噪声 σ=0.25 | 迟到票据跨 DC 调动 | 3/30 | 0.1 | 3 | 1 | 1 | 1 | 4 |
| 均衡 33/33/34 | 拣选噪声 σ=0.25 | 全队列跨 DC 再平衡 | 8/30 | 0.4 | 13 | 4 | 4 | 15 | 7 |
| 均衡 33/33/34 | 拣选噪声 σ=0.25 | 先知迟到集合（上界参考） | 5/30 | 0.2 | 4 | 2 | 1 | 2 | 4 |
| 均衡 33/33/34 | 重度拥堵 σ=0.40 | 迟到票据跨 DC 调动 | 2/30 | 0.1 | 3 | 1 | 0 | 1 | 0 |
| 均衡 33/33/34 | 重度拥堵 σ=0.40 | 全队列跨 DC 再平衡 | 7/30 | 0.5 | 14 | 5 | 4 | 10 | 13 |
| 均衡 33/33/34 | 重度拥堵 σ=0.40 | 先知迟到集合（上界参考） | 5/30 | 0.3 | 6 | 3 | 2 | 10 | 2 |
| 均衡 33/33/34 | 加 1 名拣货员/DC | 迟到票据跨 DC 调动 | 0/30 | 0.0 | 0 | 0 | 0 | 0 | 0 |
| 均衡 33/33/34 | 加 1 名拣货员/DC | 全队列跨 DC 再平衡 | 0/30 | 0.0 | 0 | 0 | 0 | 0 | 0 |
| 均衡 33/33/34 | 加 1 名拣货员/DC | 先知迟到集合（上界参考） | 0/30 | 0.0 | 0 | 0 | 0 | 0 | 0 |
| London 偏重 40/24/36 | 基准：均匀到达 · 确定性 | 迟到票据跨 DC 调动 | 30/30 | 16.7 | 586 | 167 | 90 | 259 | 0 |
| London 偏重 40/24/36 | 基准：均匀到达 · 确定性 | 全队列跨 DC 再平衡 | 30/30 | 33.8 | 1,518 | 338 | 236 | 402 | 0 |
| London 偏重 40/24/36 | 基准：均匀到达 · 确定性 | 先知迟到集合（上界参考） | 30/30 | 16.7 | 586 | 167 | 90 | 259 | 0 |
| London 偏重 40/24/36 | 拣选噪声 σ=0.25 | 迟到票据跨 DC 调动 | 30/30 | 16.5 | 570 | 165 | 87 | 245 | 3 |
| London 偏重 40/24/36 | 拣选噪声 σ=0.25 | 全队列跨 DC 再平衡 | 30/30 | 30.8 | 1,400 | 308 | 218 | 345 | 7 |
| London 偏重 40/24/36 | 拣选噪声 σ=0.25 | 先知迟到集合（上界参考） | 30/30 | 16.5 | 570 | 165 | 87 | 245 | 3 |
| London 偏重 40/24/36 | 重度拥堵 σ=0.40 | 迟到票据跨 DC 调动 | 30/30 | 15.7 | 572 | 157 | 89 | 210 | 8 |
| London 偏重 40/24/36 | 重度拥堵 σ=0.40 | 全队列跨 DC 再平衡 | 30/30 | 28.3 | 1,298 | 283 | 206 | 259 | 8 |
| London 偏重 40/24/36 | 重度拥堵 σ=0.40 | 先知迟到集合（上界参考） | 30/30 | 15.7 | 572 | 157 | 89 | 210 | 8 |
| London 偏重 40/24/36 | 加 1 名拣货员/DC | 迟到票据跨 DC 调动 | 0/30 | 0.0 | 0 | 0 | 0 | 0 | 0 |
| London 偏重 40/24/36 | 加 1 名拣货员/DC | 全队列跨 DC 再平衡 | 30/30 | 30.2 | 1,157 | 302 | 182 | 0 | 0 |
| London 偏重 40/24/36 | 加 1 名拣货员/DC | 先知迟到集合（上界参考） | 0/30 | 0.0 | 0 | 0 | 0 | 0 | 0 |

### Move directions

| 库存布点 | 压力格 | 回写策略 | 方向 | 票据 |
|---|---|---|---|---|
| 均衡 33/33/34 | 基准：均匀到达 · 确定性 | 全队列跨 DC 再平衡 | London → Frankfurt | 2 |
| 均衡 33/33/34 | 拣选噪声 σ=0.25 | 先知迟到集合（上界参考） | London → Rotterdam | 5 |
| 均衡 33/33/34 | 拣选噪声 σ=0.25 | 先知迟到集合（上界参考） | Rotterdam → Frankfurt | 1 |
| 均衡 33/33/34 | 拣选噪声 σ=0.25 | 全队列跨 DC 再平衡 | London → Frankfurt | 5 |
| 均衡 33/33/34 | 拣选噪声 σ=0.25 | 全队列跨 DC 再平衡 | London → Rotterdam | 5 |
| 均衡 33/33/34 | 拣选噪声 σ=0.25 | 全队列跨 DC 再平衡 | Rotterdam → London | 1 |
| 均衡 33/33/34 | 拣选噪声 σ=0.25 | 迟到票据跨 DC 调动 | London → Frankfurt | 1 |
| 均衡 33/33/34 | 拣选噪声 σ=0.25 | 迟到票据跨 DC 调动 | London → Rotterdam | 1 |
| 均衡 33/33/34 | 拣选噪声 σ=0.25 | 迟到票据跨 DC 调动 | Rotterdam → Frankfurt | 1 |
| 均衡 33/33/34 | 重度拥堵 σ=0.40 | 先知迟到集合（上界参考） | London → Rotterdam | 5 |
| 均衡 33/33/34 | 重度拥堵 σ=0.40 | 先知迟到集合（上界参考） | London → Frankfurt | 4 |
| 均衡 33/33/34 | 重度拥堵 σ=0.40 | 全队列跨 DC 再平衡 | London → Rotterdam | 9 |
| 均衡 33/33/34 | 重度拥堵 σ=0.40 | 全队列跨 DC 再平衡 | London → Frankfurt | 2 |
| 均衡 33/33/34 | 重度拥堵 σ=0.40 | 全队列跨 DC 再平衡 | Rotterdam → Frankfurt | 2 |
| 均衡 33/33/34 | 重度拥堵 σ=0.40 | 全队列跨 DC 再平衡 | Rotterdam → London | 1 |
| 均衡 33/33/34 | 重度拥堵 σ=0.40 | 迟到票据跨 DC 调动 | London → Rotterdam | 2 |
| 基线 34/28/38 | 加 1 名拣货员/DC | 全队列跨 DC 再平衡 | London → Rotterdam | 3 |
| 基线 34/28/38 | 基准：均匀到达 · 确定性 | 先知迟到集合（上界参考） | London → Rotterdam | 30 |
| 基线 34/28/38 | 基准：均匀到达 · 确定性 | 先知迟到集合（上界参考） | Frankfurt → Rotterdam | 2 |
| 基线 34/28/38 | 基准：均匀到达 · 确定性 | 全队列跨 DC 再平衡 | London → Rotterdam | 84 |
| 基线 34/28/38 | 基准：均匀到达 · 确定性 | 全队列跨 DC 再平衡 | Rotterdam → Frankfurt | 10 |
| 基线 34/28/38 | 基准：均匀到达 · 确定性 | 全队列跨 DC 再平衡 | Frankfurt → Rotterdam | 4 |
| 基线 34/28/38 | 基准：均匀到达 · 确定性 | 迟到票据跨 DC 调动 | London → Rotterdam | 30 |
| 基线 34/28/38 | 基准：均匀到达 · 确定性 | 迟到票据跨 DC 调动 | Frankfurt → Rotterdam | 2 |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 先知迟到集合（上界参考） | London → Rotterdam | 18 |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 先知迟到集合（上界参考） | Frankfurt → Rotterdam | 2 |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 先知迟到集合（上界参考） | Rotterdam → Frankfurt | 1 |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 全队列跨 DC 再平衡 | London → Rotterdam | 45 |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 全队列跨 DC 再平衡 | Frankfurt → Rotterdam | 12 |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 全队列跨 DC 再平衡 | Rotterdam → Frankfurt | 10 |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 全队列跨 DC 再平衡 | Rotterdam → London | 1 |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 迟到票据跨 DC 调动 | London → Rotterdam | 13 |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 迟到票据跨 DC 调动 | Frankfurt → Rotterdam | 6 |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 迟到票据跨 DC 调动 | Rotterdam → Frankfurt | 1 |
| 基线 34/28/38 | 拣选噪声 σ=0.25 | 迟到票据跨 DC 调动 | Rotterdam → London | 1 |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 先知迟到集合（上界参考） | London → Rotterdam | 15 |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 先知迟到集合（上界参考） | Frankfurt → Rotterdam | 4 |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 先知迟到集合（上界参考） | Rotterdam → Frankfurt | 2 |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 全队列跨 DC 再平衡 | London → Rotterdam | 31 |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 全队列跨 DC 再平衡 | Frankfurt → Rotterdam | 18 |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 全队列跨 DC 再平衡 | Rotterdam → Frankfurt | 10 |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 全队列跨 DC 再平衡 | Rotterdam → London | 1 |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 迟到票据跨 DC 调动 | London → Rotterdam | 11 |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 迟到票据跨 DC 调动 | Frankfurt → Rotterdam | 8 |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 迟到票据跨 DC 调动 | Rotterdam → Frankfurt | 2 |
| 基线 34/28/38 | 重度拥堵 σ=0.40 | 迟到票据跨 DC 调动 | Rotterdam → London | 1 |
| London 偏重 40/24/36 | 加 1 名拣货员/DC | 全队列跨 DC 再平衡 | London → Rotterdam | 899 |
| London 偏重 40/24/36 | 加 1 名拣货员/DC | 全队列跨 DC 再平衡 | London → Frankfurt | 8 |
| London 偏重 40/24/36 | 基准：均匀到达 · 确定性 | 先知迟到集合（上界参考） | London → Rotterdam | 502 |
| London 偏重 40/24/36 | 基准：均匀到达 · 确定性 | 全队列跨 DC 再平衡 | London → Rotterdam | 1012 |
| London 偏重 40/24/36 | 基准：均匀到达 · 确定性 | 全队列跨 DC 再平衡 | London → Frankfurt | 1 |
| London 偏重 40/24/36 | 基准：均匀到达 · 确定性 | 迟到票据跨 DC 调动 | London → Rotterdam | 502 |
| London 偏重 40/24/36 | 拣选噪声 σ=0.25 | 先知迟到集合（上界参考） | London → Rotterdam | 493 |
| London 偏重 40/24/36 | 拣选噪声 σ=0.25 | 先知迟到集合（上界参考） | London → Frankfurt | 1 |
| London 偏重 40/24/36 | 拣选噪声 σ=0.25 | 全队列跨 DC 再平衡 | London → Rotterdam | 916 |
| London 偏重 40/24/36 | 拣选噪声 σ=0.25 | 全队列跨 DC 再平衡 | London → Frankfurt | 8 |
| London 偏重 40/24/36 | 拣选噪声 σ=0.25 | 迟到票据跨 DC 调动 | London → Rotterdam | 493 |
| London 偏重 40/24/36 | 拣选噪声 σ=0.25 | 迟到票据跨 DC 调动 | London → Frankfurt | 1 |
| London 偏重 40/24/36 | 重度拥堵 σ=0.40 | 先知迟到集合（上界参考） | London → Rotterdam | 464 |
| London 偏重 40/24/36 | 重度拥堵 σ=0.40 | 先知迟到集合（上界参考） | London → Frankfurt | 6 |
| London 偏重 40/24/36 | 重度拥堵 σ=0.40 | 全队列跨 DC 再平衡 | London → Rotterdam | 838 |
| London 偏重 40/24/36 | 重度拥堵 σ=0.40 | 全队列跨 DC 再平衡 | London → Frankfurt | 11 |
| London 偏重 40/24/36 | 重度拥堵 σ=0.40 | 迟到票据跨 DC 调动 | London → Rotterdam | 464 |
| London 偏重 40/24/36 | 重度拥堵 σ=0.40 | 迟到票据跨 DC 调动 | London → Frankfurt | 6 |

## Review-timing sweep

| 库存布点 | 审核时点 | 端到端 OTIF | Δ vs 默认时点 | 平均调动票据 | 救回订单 | 丢失订单 |
|---|---|---|---|---|---|---|
| 均衡 33/33/34 | 60 min | 44.1% | +0.0% | 0.0 | 0 | 0 |
| 均衡 33/33/34 | 120 min | 44.1% | +0.0% | 0.0 | 0 | 0 |
| 均衡 33/33/34 | 180 min | 44.1% | +0.0% | 0.0 | 0 | 0 |
| 均衡 33/33/34 | 240 min | 44.1% | +0.0% | 0.0 | 0 | 0 |
| 基线 34/28/38 | 60 min | 38.8% | -0.0% | 0.5 | 5 | 0 |
| 基线 34/28/38 | 120 min | 38.9% | +0.0% | 1.1 | 10 | 0 |
| 基线 34/28/38 | 180 min | 38.8% | -0.1% | 0.7 | 4 | 0 |
| 基线 34/28/38 | 240 min | 38.8% | -0.1% | 0.0 | 0 | 0 |
| London 偏重 40/24/36 | 60 min | 37.8% | +0.3% | 16.4 | 293 | 0 |
| London 偏重 40/24/36 | 120 min | 37.5% | +0.0% | 16.7 | 259 | 0 |
| London 偏重 40/24/36 | 180 min | 37.4% | -0.1% | 16.6 | 242 | 0 |
| London 偏重 40/24/36 | 240 min | 37.1% | -0.4% | 16.4 | 210 | 0 |

The sweep reruns `reroute` at each review minute on the same seeds; the default review row is shown for reference.

## Per-DC workload (seed 1, base cell)

| 库存布点 | 回写策略 | DC | 票据 | 波次 | 准时 | 迟到 | 迟到分钟 | Makespan | 调入 | 调出 |
|---|---|---|---|---|---|---|---|---|---|---|
| 基线 34/28/38 | 无回写（分单冻结） | London | 237 | 31 | 163 | 74 | 4,010 | 716 | 0 | 0 |
| 基线 34/28/38 | 无回写（分单冻结） | Rotterdam | 204 | 28 | 201 | 3 | 12 | 582 | 0 | 0 |
| 基线 34/28/38 | 无回写（分单冻结） | Frankfurt | 212 | 33 | 153 | 59 | 2,792 | 704 | 0 | 0 |
| 基线 34/28/38 | 迟到票据跨 DC 调动 | London | 237 | 31 | 163 | 74 | 4,010 | 716 | 0 | 0 |
| 基线 34/28/38 | 迟到票据跨 DC 调动 | Rotterdam | 204 | 28 | 201 | 3 | 12 | 582 | 0 | 0 |
| 基线 34/28/38 | 迟到票据跨 DC 调动 | Frankfurt | 212 | 33 | 153 | 59 | 2,792 | 704 | 0 | 0 |
| 基线 34/28/38 | 全队列跨 DC 再平衡 | London | 234 | 31 | 163 | 71 | 3,662 | 710 | 0 | 3 |
| 基线 34/28/38 | 全队列跨 DC 再平衡 | Rotterdam | 207 | 28 | 204 | 3 | 12 | 588 | 3 | 0 |
| 基线 34/28/38 | 全队列跨 DC 再平衡 | Frankfurt | 212 | 33 | 153 | 59 | 2,792 | 704 | 0 | 0 |
| 基线 34/28/38 | 先知迟到集合（上界参考） | London | 237 | 31 | 163 | 74 | 4,010 | 716 | 0 | 0 |
| 基线 34/28/38 | 先知迟到集合（上界参考） | Rotterdam | 204 | 28 | 201 | 3 | 12 | 582 | 0 | 0 |
| 基线 34/28/38 | 先知迟到集合（上界参考） | Frankfurt | 212 | 33 | 153 | 59 | 2,792 | 704 | 0 | 0 |
| 均衡 33/33/34 | 无回写（分单冻结） | London | 224 | 30 | 155 | 69 | 2,827 | 690 | 0 | 0 |
| 均衡 33/33/34 | 无回写（分单冻结） | Rotterdam | 215 | 28 | 190 | 25 | 754 | 622 | 0 | 0 |
| 均衡 33/33/34 | 无回写（分单冻结） | Frankfurt | 202 | 30 | 174 | 28 | 672 | 652 | 0 | 0 |
| 均衡 33/33/34 | 迟到票据跨 DC 调动 | London | 224 | 30 | 155 | 69 | 2,827 | 690 | 0 | 0 |
| 均衡 33/33/34 | 迟到票据跨 DC 调动 | Rotterdam | 215 | 28 | 190 | 25 | 754 | 622 | 0 | 0 |
| 均衡 33/33/34 | 迟到票据跨 DC 调动 | Frankfurt | 202 | 30 | 174 | 28 | 672 | 652 | 0 | 0 |
| 均衡 33/33/34 | 全队列跨 DC 再平衡 | London | 224 | 30 | 155 | 69 | 2,827 | 690 | 0 | 0 |
| 均衡 33/33/34 | 全队列跨 DC 再平衡 | Rotterdam | 215 | 28 | 190 | 25 | 754 | 622 | 0 | 0 |
| 均衡 33/33/34 | 全队列跨 DC 再平衡 | Frankfurt | 202 | 30 | 174 | 28 | 672 | 652 | 0 | 0 |
| 均衡 33/33/34 | 先知迟到集合（上界参考） | London | 224 | 30 | 155 | 69 | 2,827 | 690 | 0 | 0 |
| 均衡 33/33/34 | 先知迟到集合（上界参考） | Rotterdam | 215 | 28 | 190 | 25 | 754 | 622 | 0 | 0 |
| 均衡 33/33/34 | 先知迟到集合（上界参考） | Frankfurt | 202 | 30 | 174 | 28 | 672 | 652 | 0 | 0 |
| London 偏重 40/24/36 | 无回写（分单冻结） | London | 277 | 37 | 152 | 125 | 15,769 | 837 | 0 | 0 |
| London 偏重 40/24/36 | 无回写（分单冻结） | Rotterdam | 168 | 23 | 168 | 0 | 0 | 480 | 0 | 0 |
| London 偏重 40/24/36 | 无回写（分单冻结） | Frankfurt | 197 | 31 | 167 | 30 | 830 | 665 | 0 | 0 |
| London 偏重 40/24/36 | 迟到票据跨 DC 调动 | London | 263 | 35 | 152 | 111 | 11,619 | 790 | 0 | 14 |
| London 偏重 40/24/36 | 迟到票据跨 DC 调动 | Rotterdam | 182 | 24 | 182 | 0 | 0 | 523 | 14 | 0 |
| London 偏重 40/24/36 | 迟到票据跨 DC 调动 | Frankfurt | 197 | 31 | 167 | 30 | 830 | 665 | 0 | 0 |
| London 偏重 40/24/36 | 全队列跨 DC 再平衡 | London | 246 | 33 | 152 | 94 | 7,298 | 725 | 0 | 31 |
| London 偏重 40/24/36 | 全队列跨 DC 再平衡 | Rotterdam | 199 | 26 | 199 | 0 | 0 | 589 | 31 | 0 |
| London 偏重 40/24/36 | 全队列跨 DC 再平衡 | Frankfurt | 197 | 31 | 167 | 30 | 830 | 665 | 0 | 0 |
| London 偏重 40/24/36 | 先知迟到集合（上界参考） | London | 263 | 35 | 152 | 111 | 11,619 | 790 | 0 | 14 |
| London 偏重 40/24/36 | 先知迟到集合（上界参考） | Rotterdam | 182 | 24 | 182 | 0 | 0 | 523 | 14 | 0 |
| London 偏重 40/24/36 | 先知迟到集合（上界参考） | Frankfurt | 197 | 31 | 167 | 30 | 830 | 665 | 0 | 0 |

The snapshot shows how write-back redistributes tickets and tardiness across DCs; it is not averaged over seeds.

## Interpretation

1. **Mid-shift write-back recovers part of the pick-layer loss, not the allocation loss.** At the deterministic baseline cell, `London 偏重 40/24/36` runs at 35.3% end-to-end OTIF with no write-back and at 38.7% with `全队列跨 DC 再平衡` (+3.3%); the allocation bound is 54.5%, so the pick layer gives up 19.2% and `全队列跨 DC 再平衡` closes 17% of that loss. The paired win rate against no write-back is 100% across the shared seeds.
2. **Recovery needs a spare DC, so the gain depends on placement.** `均衡 33/33/34` gains only +0.1% from its best policy (全队列跨 DC 再平衡) versus +3.3% for `London 偏重 40/24/36`. A split that loads one DC leaves queue slack elsewhere for moved tickets to use; a split that congests every DC gives the planner nowhere to send work.
3. **Extra pick capacity does what write-back cannot.** With 加 1 名拣货员/DC, no-write-back already sits within 0.0% of each allocation bound and the average policy moves 30.2 tickets. Rerouting shifts work between queues; it does not add picker minutes, so it is not a capacity substitute.
4. **Knowing the realised late set adds little.** On `London 偏重 40/24/36` the oracle policy reaches 37.5% versus 37.5% for projected-late rerouting (+0.0%). The binding constraint is the queue model and the available picker minutes at the target DC, not knowledge of which ticket will actually miss its cutoff.
5. **Review timing is a real trade-off.** On `London 偏重 40/24/36`, 60 min gives the highest mean end-to-end OTIF (37.8%) and 240 min the lowest (37.1%). An early review sees fewer locked waves but decides under a longer projection horizon; a late review knows more but has fewer movable tickets left.
6. **Write-back is small and targeted.** The busiest reroute cell (`London 偏重 40/24/36` / `基准：均匀到达 · 确定性`) moves 16.7 tickets per shift on average, with €167 in transfer fees and €90 in transport delta per run. It is an operational adjustment, not a re-plan.
7. **Preemptive balancing moves much more work.** The busiest balance cell (`London 偏重 40/24/36` / `基准：均匀到达 · 确定性`) moves 33.8 tickets per shift, 402 rescues and 0 losses in total across seeds. The extra moves buy earlier queue relief, but they also raise transfer cost and the risk of moving a ticket that would have made its cutoff.
8. **Declared assumptions, not observed operations.** The review minute, transfer lead and fee, projection rule, cutoffs and pick-time model are assumptions. Moved tickets carry their stock on an internal transfer; replenishment, DC-to-DC transport scheduling, batching changes and picker rostering are outside the chain.

## Declared assumptions

- 订单/行/数量/目的国来自 Online Retail II 真实发票
- DC 库存、产能、转运天数、SLA 承诺与费率是显式假设
- 库存按 SKU 需求 stock_factor 分配并加入确定性偏斜
- 承诺天数 2/3/5 映射到拣选截单 12:00/16:00/18:00
- 班中到达占比与到达窗口是显式假设
- 三个 DC 共用同一 ABC 布局与拣选工时模型，每 DC 独立拣货员
- 审核时点前已开工的波次锁定，只有未开工波次中的票据可以调动
- 调动票据的库存随票据内部调拨到目标 DC，不要求目标 DC 有额外 SKU 库存，但受目标 DC 周产能约束
- 调动票据按调拨前置时间延后开工，并保持原截单时间与客户承诺
- 投影使用确定性 EDF 队列，不预知剩余班次的拣选时长噪声；先知策略只预知第一阶段的实际迟到集合
- 所有策略共享第二阶段同一噪声种子，差异只来自调动决策
- 跨 DC 调拨不重新求解分单，也不改变客户承诺、截单时间或总库存

## Limitations

- The projection is deterministic and the pick-time model is declared, not fitted. A queue estimator with safety buffers would change which tickets are moved.
- A moved ticket carries its stock on an internal transfer but is assumed to clear it within the declared lead time; replenishment, transfer transport capacity and handling congestion are outside the chain.
- Phase 2 is a replay, not a new allocation: the allocation bound, cutoffs and order set stay fixed, and moved tickets keep their original cutoffs.
- The review sweep reruns one policy on one cell per placement; it is a timing diagnostic, not a full cross-product of review × policy × stress.
- The normal 95% interval is an approximation, and policy comparisons are paired only within a placement and cell; placements are separate counterfactuals with different feasible allocations.
