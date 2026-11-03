# End-to-end robustness benchmark (Week 10)

- Generated: `2026-10-27T21:10:58.282954+00:00`
- Orders: **400** real invoices / **2477** lines / **33060** units, week 2011-11-28
- Seeds per cell: **30**; stress cells: **8**; allocations: **3**
- Picking: **1 picker(s) per DC** at baseline, wave cap **8 orders / 40 lines**, shift **600.0 min**

## Assumptions

| Item | Assumption | Note |
|---|---|---|
| Shared instance | same orders, stock, promises, slots and allocation in every seed | Only arrivals and pick durations are resampled. |
| Arrival profile | uniform inside each tier window, or a relative-window spike | No observed intraday curve exists in Online Retail II. |
| Congestion | wave minutes × exp(σZ), clipped to [0.5, 2.0] | Median on plan, expected overrun exp(σ²/2) − 1; a declared proxy, not a fit. |
| Seeds | shared arrivals across policies | The congestion draw is not common across policies because wave structures differ. |

## Methods

- **Replay**: for each seed, redraw arrivals on the same instance, rerun the Week-8 event-driven release per DC with its own pickers, and recompute the Week-9 end-to-end OTIF (fully shipped ∩ inside promise ∩ every ticket before cutoff).
- **Stress cells**: baseline, uniform-vs-spike arrivals, zero-vs-nonzero pick-time noise, EDF-vs-savings release, and an optional extra picker.
- **Statistics**: mean with a normal 95% interval, P10/P50/P90, worst-decile mean (service metrics read the lower tail, time/cost the upper tail), and paired per-seed differences for policy and stress comparisons.
- **No re-optimisation**: the allocation is fixed per scenario; this module measures execution risk, not joint allocation-under-uncertainty.

## Allocation scenarios

| 分单方案 | 状态 | 分单 OTIF（上界） | 分单成本 (€) | 求解 (s) |
|---|---|---|---|---|
| 贪心分单（截止期优先） | HEURISTIC | 35.0% | 69,281 | 0.03 |
| MILP 服务优先 | FEASIBLE | 54.5% | 61,965 | 60.07 |
| MILP 拣选容量感知 | FEASIBLE | 55.2% | 62,002 | 60.08 |

## Stress design

| 压力格 | 在线策略 | 到达画像 | 拣选噪声 σ | 每 DC 拣货员 |
|---|---|---|---|---|
| 基准：均匀到达 · 确定性 | edf | 均匀到达 | 0.00 | 1 |
| 节省重批 · 均匀到达 | savings | 均匀到达 | 0.00 | 1 |
| 到达尖峰 · 确定性 | edf | 尖峰 60% @ 0.50±0.12 | 0.00 | 1 |
| 到达尖峰 · 节省重批 | savings | 尖峰 60% @ 0.50±0.12 | 0.00 | 1 |
| 拣选噪声 σ=0.25 | edf | 均匀到达 | 0.25 | 1 |
| 尖峰 + 噪声 σ=0.25 | edf | 尖峰 60% @ 0.50±0.12 | 0.25 | 1 |
| 重度拥堵 σ=0.40 | edf | 均匀到达 | 0.40 | 1 |
| 加 1 名拣货员/DC · 均匀到达 | edf | 均匀到达 | 0.00 | 2 |

## End-to-end OTIF distribution

| 分单方案 | 压力格 | 均值 | 95% CI | P10 | P50 | P90 | 最差 10% 均值 | 最小 | 最大 | n |
|---|---|---|---|---|---|---|---|---|---|---|
| greedy | 基准：均匀到达 · 确定性 | 32.4% | ±0.2% | 31.8% | 32.2% | 33.3% | 31.5% | 31.2% | 34.0% | 30 |
| greedy | 节省重批 · 均匀到达 | 32.6% | ±0.3% | 31.5% | 32.6% | 33.3% | 31.2% | 31.0% | 33.8% | 30 |
| greedy | 到达尖峰 · 确定性 | 32.3% | ±0.2% | 31.5% | 32.2% | 33.5% | 31.5% | 31.5% | 34.0% | 30 |
| greedy | 到达尖峰 · 节省重批 | 32.6% | ±0.3% | 31.5% | 32.5% | 33.8% | 31.2% | 31.0% | 34.0% | 30 |
| greedy | 拣选噪声 σ=0.25 | 31.6% | ±0.6% | 30.2% | 31.5% | 33.6% | 28.5% | 27.0% | 34.5% | 30 |
| greedy | 尖峰 + 噪声 σ=0.25 | 31.8% | ±0.6% | 30.0% | 31.9% | 33.8% | 28.3% | 26.8% | 34.5% | 30 |
| greedy | 重度拥堵 σ=0.40 | 29.9% | ±0.9% | 27.4% | 30.2% | 32.6% | 24.6% | 23.5% | 34.0% | 30 |
| greedy | 加 1 名拣货员/DC · 均匀到达 | 35.0% | ±0.0% | 35.0% | 35.0% | 35.0% | 35.0% | 35.0% | 35.0% | 30 |
| milp_service | 基准：均匀到达 · 确定性 | 38.5% | ±0.5% | 36.7% | 38.6% | 40.0% | 35.7% | 35.0% | 41.2% | 30 |
| milp_service | 节省重批 · 均匀到达 | 38.9% | ±0.6% | 37.0% | 38.8% | 41.3% | 35.8% | 34.8% | 42.0% | 30 |
| milp_service | 到达尖峰 · 确定性 | 38.8% | ±0.5% | 37.4% | 39.0% | 40.3% | 35.8% | 34.8% | 41.2% | 30 |
| milp_service | 到达尖峰 · 节省重批 | 39.3% | ±0.7% | 36.2% | 39.6% | 41.5% | 35.1% | 34.2% | 42.8% | 30 |
| milp_service | 拣选噪声 σ=0.25 | 36.5% | ±1.0% | 33.2% | 36.5% | 40.0% | 32.5% | 31.0% | 42.5% | 30 |
| milp_service | 尖峰 + 噪声 σ=0.25 | 36.4% | ±0.9% | 33.5% | 35.9% | 40.0% | 32.9% | 32.5% | 41.5% | 30 |
| milp_service | 重度拥堵 σ=0.40 | 33.9% | ±1.3% | 30.4% | 33.6% | 38.6% | 28.0% | 24.0% | 40.2% | 30 |
| milp_service | 加 1 名拣货员/DC · 均匀到达 | 54.5% | ±0.0% | 54.5% | 54.5% | 54.5% | 54.5% | 54.5% | 54.5% | 30 |
| milp_load | 基准：均匀到达 · 确定性 | 39.1% | ±0.5% | 37.2% | 39.4% | 40.8% | 36.0% | 35.5% | 41.5% | 30 |
| milp_load | 节省重批 · 均匀到达 | 39.5% | ±0.7% | 37.2% | 39.4% | 41.8% | 36.5% | 35.8% | 44.8% | 30 |
| milp_load | 到达尖峰 · 确定性 | 39.5% | ±0.5% | 38.0% | 39.8% | 41.0% | 37.1% | 36.0% | 42.0% | 30 |
| milp_load | 到达尖峰 · 节省重批 | 40.9% | ±0.7% | 38.2% | 40.8% | 43.5% | 37.7% | 37.2% | 45.2% | 30 |
| milp_load | 拣选噪声 σ=0.25 | 36.7% | ±0.9% | 33.9% | 36.5% | 40.0% | 32.7% | 31.8% | 41.0% | 30 |
| milp_load | 尖峰 + 噪声 σ=0.25 | 37.0% | ±1.0% | 34.2% | 36.8% | 40.1% | 32.8% | 31.0% | 42.0% | 30 |
| milp_load | 重度拥堵 σ=0.40 | 34.2% | ±1.3% | 30.8% | 33.8% | 38.8% | 28.6% | 25.5% | 41.5% | 30 |
| milp_load | 加 1 名拣货员/DC · 均匀到达 | 55.2% | ±0.0% | 55.2% | 55.2% | 55.2% | 55.2% | 55.2% | 55.2% | 30 |

Each row is one allocation × stress cell. `95% CI` is the normal-approximation half-width; `worst 10% mean` averages the lowest decile of seeds.

## Execution risk

| 分单方案 | 压力格 | 拣选准时均值 | 准时 95% CI | 迟到分钟均值 | 迟到分钟 P90 | Makespan 均值 | Makespan P90 | 超班次概率 |
|---|---|---|---|---|---|---|---|---|
| greedy | 基准：均匀到达 · 确定性 | 89.6% | ±0.3% | 1,333 | 1,437 | 666 | 667 | 100.0% |
| greedy | 节省重批 · 均匀到达 | 91.2% | ±0.5% | 1,171 | 1,416 | 657 | 661 | 100.0% |
| greedy | 到达尖峰 · 确定性 | 89.5% | ±0.3% | 1,326 | 1,456 | 666 | 667 | 100.0% |
| greedy | 到达尖峰 · 节省重批 | 91.2% | ±0.5% | 1,159 | 1,358 | 657 | 660 | 100.0% |
| greedy | 拣选噪声 σ=0.25 | 86.3% | ±1.7% | 2,919 | 5,507 | 682 | 721 | 100.0% |
| greedy | 尖峰 + 噪声 σ=0.25 | 86.5% | ±1.5% | 2,937 | 5,595 | 682 | 720 | 100.0% |
| greedy | 重度拥堵 σ=0.40 | 80.3% | ±2.5% | 5,633 | 10,698 | 705 | 769 | 100.0% |
| greedy | 加 1 名拣货员/DC · 均匀到达 | 100.0% | ±0.0% | 0 | 0 | 475 | 484 | 0.0% |
| milp_service | 基准：均匀到达 · 确定性 | 76.1% | ±0.4% | 8,443 | 9,142 | 726 | 729 | 100.0% |
| milp_service | 节省重批 · 均匀到达 | 77.7% | ±0.5% | 7,420 | 8,196 | 723 | 728 | 100.0% |
| milp_service | 到达尖峰 · 确定性 | 76.2% | ±0.4% | 8,409 | 9,201 | 725 | 727 | 100.0% |
| milp_service | 到达尖峰 · 节省重批 | 78.0% | ±0.6% | 7,450 | 8,079 | 724 | 727 | 100.0% |
| milp_service | 拣选噪声 σ=0.25 | 72.0% | ±1.7% | 11,544 | 16,677 | 757 | 799 | 100.0% |
| milp_service | 尖峰 + 噪声 σ=0.25 | 71.5% | ±1.3% | 11,710 | 16,699 | 758 | 797 | 100.0% |
| milp_service | 重度拥堵 σ=0.40 | 67.4% | ±2.2% | 16,242 | 25,367 | 788 | 861 | 100.0% |
| milp_service | 加 1 名拣货员/DC · 均匀到达 | 100.0% | ±0.0% | 0 | 0 | 476 | 485 | 0.0% |
| milp_load | 基准：均匀到达 · 确定性 | 76.7% | ±0.5% | 8,024 | 8,587 | 725 | 727 | 100.0% |
| milp_load | 节省重批 · 均匀到达 | 78.0% | ±0.6% | 7,000 | 7,668 | 721 | 724 | 100.0% |
| milp_load | 到达尖峰 · 确定性 | 76.9% | ±0.4% | 7,918 | 8,613 | 724 | 727 | 100.0% |
| milp_load | 到达尖峰 · 节省重批 | 79.2% | ±0.6% | 6,760 | 7,431 | 720 | 723 | 100.0% |
| milp_load | 拣选噪声 σ=0.25 | 72.2% | ±1.5% | 11,274 | 17,004 | 756 | 800 | 100.0% |
| milp_load | 尖峰 + 噪声 σ=0.25 | 72.2% | ±1.6% | 11,265 | 16,240 | 756 | 796 | 100.0% |
| milp_load | 重度拥堵 σ=0.40 | 68.1% | ±2.2% | 15,872 | 24,638 | 788 | 860 | 100.0% |
| milp_load | 加 1 名拣货员/DC · 均匀到达 | 100.0% | ±0.0% | 0 | 0 | 476 | 486 | 0.0% |

`over shift` is the share of seeds whose picking makespan exceeds the declared shift length.

## Savings vs EDF (same allocation)

| 分单方案 | 对比 | 指标 | 差值均值 | 95% CI | 胜率 | 负率 | 平率 | n |
|---|---|---|---|---|---|---|---|---|
| greedy | 均匀到达：节省 − EDF | 端到端 OTIF | +0.2% | ±0.3% | 60.0% | 36.7% | 3.3% | 30 |
| milp_service | 均匀到达：节省 − EDF | 端到端 OTIF | +0.3% | ±0.7% | 53.3% | 46.7% | 0.0% | 30 |
| milp_load | 均匀到达：节省 − EDF | 端到端 OTIF | +0.4% | ±0.8% | 56.7% | 36.7% | 6.7% | 30 |
| greedy | 尖峰到达：节省 − EDF | 端到端 OTIF | +0.2% | ±0.3% | 50.0% | 43.3% | 6.7% | 30 |
| milp_service | 尖峰到达：节省 − EDF | 端到端 OTIF | +0.5% | ±0.8% | 60.0% | 33.3% | 6.7% | 30 |
| milp_load | 尖峰到达：节省 − EDF | 端到端 OTIF | +1.4% | ±0.7% | 70.0% | 30.0% | 0.0% | 30 |

| 分单方案 | 对比 | 指标 | 差值均值 | 95% CI | 胜率 | 负率 | 平率 | n |
|---|---|---|---|---|---|---|---|---|
| greedy | 均匀到达：节省 − EDF | 迟到票据分钟 | -161.8 | ±76.9 | 20.0% | 80.0% | 0.0% | 30 |
| milp_service | 均匀到达：节省 − EDF | 迟到票据分钟 | -1,023.1 | ±229.8 | 10.0% | 90.0% | 0.0% | 30 |
| milp_load | 均匀到达：节省 − EDF | 迟到票据分钟 | -1,024.2 | ±212.6 | 3.3% | 96.7% | 0.0% | 30 |
| greedy | 尖峰到达：节省 − EDF | 迟到票据分钟 | -167.3 | ±72.2 | 23.3% | 76.7% | 0.0% | 30 |
| milp_service | 尖峰到达：节省 − EDF | 迟到票据分钟 | -959.4 | ±240.7 | 13.3% | 86.7% | 0.0% | 30 |
| milp_load | 尖峰到达：节省 − EDF | 迟到票据分钟 | -1,157.4 | ±232.9 | 3.3% | 96.7% | 0.0% | 30 |

## Arrival spike vs uniform

| 分单方案 | 对比 | 指标 | 差值均值 | 95% CI | 胜率 | 负率 | 平率 | n |
|---|---|---|---|---|---|---|---|---|
| greedy | 尖峰 − 均匀 | 端到端 OTIF | -0.0% | ±0.2% | 33.3% | 46.7% | 20.0% | 30 |
| milp_service | 尖峰 − 均匀 | 端到端 OTIF | +0.3% | ±0.3% | 60.0% | 23.3% | 16.7% | 30 |
| milp_load | 尖峰 − 均匀 | 端到端 OTIF | +0.4% | ±0.4% | 60.0% | 20.0% | 20.0% | 30 |

| 分单方案 | 对比 | 指标 | 差值均值 | 95% CI | 胜率 | 负率 | 平率 | n |
|---|---|---|---|---|---|---|---|---|
| greedy | 尖峰 − 均匀 | 迟到票据分钟 | -7.2 | ±22.7 | 46.7% | 53.3% | 0.0% | 30 |
| milp_service | 尖峰 − 均匀 | 迟到票据分钟 | -34.1 | ±139.5 | 46.7% | 53.3% | 0.0% | 30 |
| milp_load | 尖峰 − 均匀 | 迟到票据分钟 | -106.7 | ±136.8 | 40.0% | 60.0% | 0.0% | 30 |

## Pick-time noise vs deterministic

| 分单方案 | 对比 | 指标 | 差值均值 | 95% CI | 胜率 | 负率 | 平率 | n |
|---|---|---|---|---|---|---|---|---|
| greedy | 含噪声 − 确定性 | 端到端 OTIF | -0.8% | ±0.7% | 26.7% | 66.7% | 6.7% | 30 |
| milp_service | 含噪声 − 确定性 | 端到端 OTIF | -2.0% | ±0.9% | 30.0% | 66.7% | 3.3% | 30 |
| milp_load | 含噪声 − 确定性 | 端到端 OTIF | -2.4% | ±0.9% | 23.3% | 76.7% | 0.0% | 30 |

| 分单方案 | 对比 | 指标 | 差值均值 | 95% CI | 胜率 | 负率 | 平率 | n |
|---|---|---|---|---|---|---|---|---|
| greedy | 含噪声 − 确定性 | 迟到票据分钟 | 1,585.7 | ±619.2 | 86.7% | 13.3% | 0.0% | 30 |
| milp_service | 含噪声 − 确定性 | 迟到票据分钟 | 3,101.0 | ±1,289.2 | 76.7% | 23.3% | 0.0% | 30 |
| milp_load | 含噪声 − 确定性 | 迟到票据分钟 | 3,249.4 | ±1,289.8 | 80.0% | 20.0% | 0.0% | 30 |

## Severe congestion vs deterministic

| 分单方案 | 对比 | 指标 | 差值均值 | 95% CI | 胜率 | 负率 | 平率 | n |
|---|---|---|---|---|---|---|---|---|
| greedy | 重度拥堵 − 确定性 | 端到端 OTIF | -2.4% | ±1.0% | 10.0% | 80.0% | 10.0% | 30 |
| milp_service | 重度拥堵 − 确定性 | 端到端 OTIF | -4.6% | ±1.2% | 10.0% | 86.7% | 3.3% | 30 |
| milp_load | 重度拥堵 − 确定性 | 端到端 OTIF | -5.0% | ±1.3% | 10.0% | 90.0% | 0.0% | 30 |

| 分单方案 | 对比 | 指标 | 差值均值 | 95% CI | 胜率 | 负率 | 平率 | n |
|---|---|---|---|---|---|---|---|---|
| greedy | 重度拥堵 − 确定性 | 迟到票据分钟 | 4,300.2 | ±1,308.5 | 93.3% | 6.7% | 0.0% | 30 |
| milp_service | 重度拥堵 − 确定性 | 迟到票据分钟 | 7,798.8 | ±2,287.7 | 93.3% | 6.7% | 0.0% | 30 |
| milp_load | 重度拥堵 − 确定性 | 迟到票据分钟 | 7,847.4 | ±2,227.4 | 90.0% | 10.0% | 0.0% | 30 |

## Extra picker vs baseline

| 分单方案 | 对比 | 指标 | 差值均值 | 95% CI | 胜率 | 负率 | 平率 | n |
|---|---|---|---|---|---|---|---|---|
| greedy | 2 名 − 1 名 | 端到端 OTIF | +2.6% | ±0.2% | 100.0% | 0.0% | 0.0% | 30 |
| milp_service | 2 名 − 1 名 | 端到端 OTIF | +16.0% | ±0.5% | 100.0% | 0.0% | 0.0% | 30 |
| milp_load | 2 名 − 1 名 | 端到端 OTIF | +16.1% | ±0.5% | 100.0% | 0.0% | 0.0% | 30 |

| 分单方案 | 对比 | 指标 | 差值均值 | 95% CI | 胜率 | 负率 | 平率 | n |
|---|---|---|---|---|---|---|---|---|
| greedy | 2 名 − 1 名 | 迟到票据分钟 | -1,333.0 | ±33.9 | 0.0% | 100.0% | 0.0% | 30 |
| milp_service | 2 名 − 1 名 | 迟到票据分钟 | -8,443.2 | ±167.0 | 0.0% | 100.0% | 0.0% | 30 |
| milp_load | 2 名 − 1 名 | 迟到票据分钟 | -8,024.3 | ±163.7 | 0.0% | 100.0% | 0.0% | 30 |

## Interpretation

1. **A single seed understates the variance.** For `MILP 拣选容量感知` the baseline end-to-end OTIF is 39.1% ± 0.5% (95% CI) across 30 seeds, ranging from 35.5% to 41.5% with a worst-decile mean of 36.0%. The worst-decile mean is 65% of the 55.2% allocation bound, so execution risk does not erase the allocation ranking. The Week-9 point estimate sits inside this band, so one run is an illustration, not a forecast.
2. **Savings beats EDF only when the queue actually spikes.** At uniform arrivals it changes end-to-end OTIF by +0.4% (±0.8%, win rate 57%); the interval includes zero, so this sample cannot separate it from noise. Under a mid-shift spike the same policy is +1.4% (±0.7%, win rate 70%) and the interval excludes zero. Pairing fixes the arrival draw but not the congestion draw, so this is a policy comparison at fixed allocation, not a common-random-number experiment.
3. **Arrival timing is second-order at one picker per DC.** A mid-shift spike changes end-to-end OTIF by +0.4% (±0.4%); the interval excludes zero, so the spike is a real but small effect. With the picker continuously backlogged, cutoff misses come from total capacity, not from when the queue fills.
4. **Congestion risk shows up in tails, not only in the mean.** Right-skewed pick-time noise (σ=0.25) changes end-to-end OTIF by -2.4% (±0.9%); late-ticket minutes move +3,249 and makespan +30 min, while the allocation upper bound caps the upside. At σ=0.40 the loss grows to -5.0% (±1.3%).
5. **Staffing is still the strongest lever.** Adding a picker per DC changes end-to-end OTIF by +16.1% (±0.5%) and wins 100% of paired seeds; that closes the gap to the allocation upper bound, so the residual loss is upstream allocation and stock. One picker also overruns the declared shift in every seed, so the service level above is bought with overtime that the model does not price.
6. **These are declared stress distributions, not calibrated ones.** Arrival spikes are relative-window samples, congestion is a lognormal multiplier with no fitted parameters, and every seed reuses one allocation, one stock snapshot and one warehouse layout. The intervals describe sensitivity to the declared randomness, not field uncertainty.

## Declared assumptions

- 订单/行/数量/目的国来自 Online Retail II 真实发票
- DC 库存、产能、转运天数、SLA 承诺与费率是显式假设
- 库存按 SKU 需求 stock_factor 分配并加入确定性偏斜
- 承诺天数 2/3/5 映射到拣选截单 12:00/16:00/18:00
- 班中到达占比与到达窗口是显式假设
- 尖峰画像按层内相对窗口抽样，不是观测到的日内曲线
- 三个 DC 共用同一 ABC 布局与拣选工时模型，每 DC 独立拣货员
- 随机性只来自到达重抽样与拣选时长乘子，订单、库存、槽位与分单固定
- 拥堵乘子 exp(σZ) 截断在 [0.5, 2.0]，σ 为声明值而非拟合值
- 配对种子共享到达抽样；不同策略的拥堵抽样因波次结构不同而不同

## Limitations

- The resampled randomness is declared, not estimated: arrival windows, spike shape and congestion variance are assumptions, and no confidence interval covers model misspecification.
- The allocation is fixed across seeds. A planner that re-optimises after early waves run late could perform better, but that closed loop is not modelled.
- Seeds share the order set and stock snapshot; demand uncertainty and replenishment are outside the chain.
- The normal 95% interval is an approximation and the worst-decile mean is noisy with 30 seeds; tail statements should be read as indicative.
- The MILP allocations are time-limited `FEASIBLE` solutions and are re-solved for this benchmark, so their costs and OTIF differ slightly from Week 9; the allocation ranking is indicative, not a proven optimum ordering.
- Congestion is a single multiplier per wave with no zones, breaks, skills or queue-dependent slowdown, and it is applied to total wave minutes.
- One trading week, one layout, one arrival profile family and one warehouse labor model; absolute OTIF levels are not transferable.
