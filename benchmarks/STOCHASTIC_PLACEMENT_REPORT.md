# Uncertainty-aware stock placement (Week 14)

- Generated: `2026-10-28T06:15:22.211925+00:00`
- Orders: **400** real invoices / **2477** lines / **33060** units, week 2011-11-28
- Scenarios: **6** prior weeks (2011-10-17..2011-11-21) | stock **28115** units (85.0%) from the scenario mean
- Seeds per cell: **30** × **3** allocation replicate(s); stress cells: **4**; placements: **5**
- Picking: **1 picker(s) per DC**, shift **600.0 min**, wave cap **8 orders / 40 lines**
- Pick proxy: **0.07952 min/unit** (order route + line/unit handling + wave setup + 20% congestion), **600 min** per DC per shift

## Assumptions

| Item | Assumption | Note |
|---|---|---|
| Stock totals | scenario mean × 85% | Per-SKU totals come from the prior weeks, not the target week; only the DC location is optimized. |
| Scenario weights | equal | Each prior week is one draw; no fitted seasonality or forecast model is used. |
| Scenario volume | rescaled to the target week's units | Weekly volume is treated as known; the SKU × destination mix is not. |
| Serviceability | promise mix 30/50/20 and declared transit days | A unit is serviceable from a DC when its transit fits the promise; this is an assumption layer, not observed carrier data. |
| Pick budget | linear minutes per DC per scenario | Order route + line/unit handling + wave setup + 20% congestion; it is not a wave or cutoff simulation. |
| Risk | E[unmet] and CVaR α=0.80 | CVaR uses the Uryasev variables and empirical interpolation; the default weight is 0.50. |
| Allocation | Week-9 two-stage MILP, time-limited FEASIBLE | 30 s service + 60 s load-aware, repeated 3× per placement. |

## Methods

- **Scenario construction**: the last 6 complete weeks before the target week, restricted to the instance's SKUs and countries, aggregated by week × SKU × country, then rescaled so each week has the target week's total units.
- **Serviceable demand**: each scenario's units are split by declared promise tier; a DC can serve a unit when its declared transit fits that tier. The matrix is per scenario, SKU and DC.
- **First stage**: one integer stock placement with each SKU's total fixed to the scenario-mean level. A small tie-break rewards placing a SKU where prior weeks could serve it and lowers the global peak pick-minute load; the service coefficient is 6×10^5 times larger, so these terms only decide among service-equivalent placements.
- **Second stage**: a fluid allocation per scenario, bounded by the placement, serviceable demand, per-DC weekly throughput and the linear pick-minute budget. Unmet units close each SKU balance.
- **Risk objective**: `(1-λ)·E[unmet] + λ·CVaR_α(unmet)`, with λ swept; the reported placement uses λ=0.50 unless noted.
- **Out-of-sample evaluation**: every placement is allocated by the Week-9 capacity-aware MILP and replayed through the Week-10 Monte Carlo. Allocation is repeated to separate placement from solver noise.

## Demand scenarios

Target volume **33,060** units; each prior week is rescaled to it. `Serviceable` is the share of that week's units each DC can deliver inside the declared promise mix.

| Week | Weight | Raw units | Scale | Active SKUs | History lines | Serviceable London | Serviceable Rotterdam | Serviceable Frankfurt |
|---|---|---|---|---|---|---|---|---|
| 2011-10-17 | 16.7% | 33,080 | 0.999 | 185 | 2859 | 91.8% | 92.8% | 69.7% |
| 2011-10-24 | 16.7% | 44,799 | 0.738 | 187 | 3195 | 95.8% | 96.5% | 71.8% |
| 2011-10-31 | 16.7% | 41,726 | 0.792 | 187 | 3706 | 96.3% | 96.8% | 70.4% |
| 2011-11-07 | 16.7% | 55,345 | 0.597 | 188 | 4400 | 97.9% | 98.3% | 70.4% |
| 2011-11-14 | 16.7% | 52,602 | 0.628 | 188 | 4560 | 95.7% | 96.5% | 68.9% |
| 2011-11-21 | 16.7% | 45,550 | 0.726 | 188 | 4281 | 95.5% | 96.1% | 70.1% |

## Stock placements

| Placement | DC mix | Stock units | Peak pick (min) | Peak / shift | Predicted E[unmet] | Predicted CVaR | Note |
|---|---|---|---|---|---|---|---|
| Week-5 基线 34/28/38 | London 35% / Rotterdam 28% / Frankfurt 37% | 9,781 / 7,916 / 10,418 | 828 | 138.1% | 32.0% | 32.1% | Week-5 占比与确定性 SKU 抖动，应用到场景均值总量 |
| 目的地历史布点 | London 83% / Rotterdam 8% / Frankfurt 9% | 23,370 / 2,129 / 2,616 | 1,858 | 309.7% | 63.6% | 64.8% | 前 6 周目的地占比；产能盲区 |
| 目的地历史 + 产能封顶 | London 62% / Rotterdam 19% / Frankfurt 19% | 17,404 / 5,368 / 5,343 | 1,384 | 230.7% | 45.7% | 46.9% | 目的地历史按 DC 周产能封顶，超额按剩余产能再分配 |
| 场景均值最优 (λ=0) | London 34% / Rotterdam 30% / Frankfurt 36% | 9,620 / 8,324 / 10,171 | 809 | 134.8% | 32.0% | 32.0% | 场景期望未满足最小；覆盖与峰值拣选分钟平局决胜 |
| 场景 CVaR (λ=0.5) | London 31% / Rotterdam 35% / Frankfurt 34% | 8,722 / 9,818 / 9,575 | 781 | 130.1% | 32.0% | 32.0% | 期望 + CVaR(α=0.80) 风险权重 |

`Peak pick` is the stock units in the busiest DC times the linear pick-minute coefficient; `Peak / shift` above 100% means that DC holds more work than one picker can start inside the shift.

## Predicted service

| Placement | E[unmet] | CVaR | Worst scenario | Best scenario | Status |
|---|---|---|---|---|---|
| Week-5 基线 34/28/38 | 32.0% | 32.1% | 32.1% | 31.9% | OPTIMAL |
| 目的地历史布点 | 63.6% | 64.8% | 65.1% | 63.1% | OPTIMAL |
| 目的地历史 + 产能封顶 | 45.7% | 46.9% | 47.2% | 45.2% | OPTIMAL |
| 场景均值最优 (λ=0) | 32.0% | 32.0% | 32.0% | 31.9% | OPTIMAL |
| 场景 CVaR (λ=0.5) | 32.0% | 32.0% | 32.0% | 31.9% | OPTIMAL |

Scenario-to-scenario spread of unserved units: Week-5 基线 34/28/38 0.1% / 目的地历史布点 2.0% / 目的地历史 + 产能封顶 2.0% / 场景均值最优 (λ=0) 0.1% / 场景 CVaR (λ=0.5) 0.1%.

These are fluid unit-service scores over the prior-week scenarios, not end-to-end OTIF forecasts; the allocation and execution sections below evaluate each placement separately.

## CVaR weight sweep

| λ | DC mix | E[unmet] | CVaR | Peak pick (min) | Status | Solve (s) |
|---|---|---|---|---|---|---|
| 0.00 | 34% / 30% / 36% | 32.0% | 32.0% | 809 | OPTIMAL | 11.7 |
| 0.25 | 33% / 33% / 35% | 32.0% | 32.0% | 779 | OPTIMAL | 15.5 |
| 0.50 | 31% / 35% / 34% | 32.0% | 32.0% | 781 | OPTIMAL | 17.6 |
| 0.75 | 33% / 33% / 33% | 32.0% | 32.0% | 747 | OPTIMAL | 30.7 |
| 1.00 | 33% / 32% / 35% | 32.0% | 32.0% | 783 | OPTIMAL | 16.4 |

## Allocation outcomes

| Placement | Status | Unit fill | Fill range | Tickets | Allocation OTIF | OTIF range | Cost (€) | Solve (s) | reps |
|---|---|---|---|---|---|---|---|---|---|
| Week-5 基线 34/28/38 | FEASIBLE | 70.8% | 70%–71% | 647 | 54.6% | 52%–56% | 83,876 | 60.8 | 3 |
| 目的地历史布点 | FEASIBLE | 67.2% | 67%–67% | 566 | 46.6% | 42%–51% | 85,010 | 60.2 | 3 |
| 目的地历史 + 产能封顶 | FEASIBLE | 70.3% | 70%–71% | 621 | 46.6% | 44%–48% | 82,706 | 60.5 | 3 |
| 场景均值最优 (λ=0) | FEASIBLE | 70.8% | 71%–71% | 638 | 54.0% | 53%–55% | 83,843 | 60.1 | 3 |
| 场景 CVaR (λ=0.5) | FEASIBLE | 69.8% | 70%–70% | 641 | 47.3% | 45%–49% | 86,896 | 60.2 | 3 |

`OTIF range` is the spread across allocation replicates on the same placement; `Cost` is the mean reported fulfillment cost. Allocation OTIF covers shipping inside the promise but not pick-cutoff risk; the end-to-end table adds wave batching and cutoff timing.

## End-to-end OTIF distribution

| Placement | Stress cell | Mean | 95% CI | P10 | P50 | P90 | Worst 10% mean | n |
|---|---|---|---|---|---|---|---|---|
| Week-5 基线 34/28/38 | 基准：均匀到达 · 确定性 | 39.2% | ±0.4% | 37.0% | 38.5% | 42.3% | 36.5% | 90 |
| Week-5 基线 34/28/38 | 拣选噪声 σ=0.25 | 37.6% | ±0.6% | 34.2% | 37.5% | 41.8% | 32.4% | 90 |
| Week-5 基线 34/28/38 | 重度拥堵 σ=0.40 | 35.5% | ±0.9% | 29.7% | 35.5% | 40.0% | 28.5% | 90 |
| Week-5 基线 34/28/38 | 加 1 名拣货员/DC | 54.6% | ±0.4% | 52.0% | 55.2% | 56.5% | 52.0% | 90 |
| 目的地历史布点 | 基准：均匀到达 · 确定性 | 16.3% | ±0.3% | 14.4% | 16.5% | 17.8% | 13.6% | 90 |
| 目的地历史布点 | 拣选噪声 σ=0.25 | 15.3% | ±0.4% | 12.5% | 15.5% | 17.8% | 11.9% | 90 |
| 目的地历史布点 | 重度拥堵 σ=0.40 | 14.1% | ±0.5% | 11.0% | 14.0% | 17.5% | 10.2% | 90 |
| 目的地历史布点 | 加 1 名拣货员/DC | 46.6% | ±0.8% | 42.0% | 46.5% | 51.2% | 42.0% | 90 |
| 目的地历史 + 产能封顶 | 基准：均匀到达 · 确定性 | 20.0% | ±0.2% | 18.5% | 20.0% | 21.5% | 18.1% | 90 |
| 目的地历史 + 产能封顶 | 拣选噪声 σ=0.25 | 19.2% | ±0.4% | 16.7% | 19.1% | 22.0% | 15.6% | 90 |
| 目的地历史 + 产能封顶 | 重度拥堵 σ=0.40 | 18.1% | ±0.5% | 14.8% | 18.2% | 21.5% | 13.8% | 90 |
| 目的地历史 + 产能封顶 | 加 1 名拣货员/DC | 46.6% | ±0.3% | 44.5% | 47.0% | 48.2% | 44.5% | 90 |
| 场景均值最优 (λ=0) | 基准：均匀到达 · 确定性 | 40.6% | ±0.2% | 39.5% | 40.5% | 41.8% | 39.0% | 90 |
| 场景均值最优 (λ=0) | 拣选噪声 σ=0.25 | 38.6% | ±0.5% | 35.2% | 38.8% | 41.0% | 34.4% | 90 |
| 场景均值最优 (λ=0) | 重度拥堵 σ=0.40 | 35.9% | ±0.7% | 31.0% | 36.5% | 39.8% | 29.5% | 90 |
| 场景均值最优 (λ=0) | 加 1 名拣货员/DC | 54.0% | ±0.2% | 53.0% | 54.0% | 55.0% | 53.0% | 90 |
| 场景 CVaR (λ=0.5) | 基准：均匀到达 · 确定性 | 43.1% | ±0.4% | 40.5% | 43.5% | 45.0% | 39.9% | 90 |
| 场景 CVaR (λ=0.5) | 拣选噪声 σ=0.25 | 41.1% | ±0.6% | 36.5% | 40.9% | 45.0% | 35.8% | 90 |
| 场景 CVaR (λ=0.5) | 重度拥堵 σ=0.40 | 37.8% | ±0.9% | 32.7% | 37.6% | 42.4% | 30.7% | 90 |
| 场景 CVaR (λ=0.5) | 加 1 名拣货员/DC | 47.3% | ±0.4% | 44.8% | 48.0% | 49.2% | 44.8% | 90 |

## Execution risk

| Placement | Stress cell | Pick on-time | Pick on-time CI | Tardy minutes | Tardy P90 | Makespan | Makespan P90 | Over-shift |
|---|---|---|---|---|---|---|---|---|
| Week-5 基线 34/28/38 | 基准：均匀到达 · 确定性 | 83.2% | ±0.2% | 7,445 | 8,673 | 747 | 757 | 100.0% |
| Week-5 基线 34/28/38 | 拣选噪声 σ=0.25 | 81.5% | ±0.6% | 9,451 | 14,054 | 763 | 804 | 100.0% |
| Week-5 基线 34/28/38 | 重度拥堵 σ=0.40 | 78.3% | ±0.9% | 12,544 | 20,185 | 788 | 862 | 100.0% |
| Week-5 基线 34/28/38 | 加 1 名拣货员/DC | 100.0% | ±0.0% | 0 | 0 | 476 | 486 | 0.0% |
| 目的地历史布点 | 基准：均匀到达 · 确定性 | 56.5% | ±0.5% | 61,733 | 63,673 | 1,169 | 1,174 | 100.0% |
| 目的地历史布点 | 拣选噪声 σ=0.25 | 55.3% | ±0.6% | 66,497 | 78,059 | 1,195 | 1,256 | 100.0% |
| 目的地历史布点 | 重度拥堵 σ=0.40 | 53.7% | ±0.8% | 73,382 | 89,556 | 1,236 | 1,340 | 100.0% |
| 目的地历史布点 | 加 1 名拣货员/DC | 100.0% | ±0.0% | 0 | 0 | 590 | 595 | 0.0% |
| 目的地历史 + 产能封顶 | 基准：均匀到达 · 确定性 | 65.3% | ±0.2% | 48,198 | 51,637 | 1,075 | 1,086 | 100.0% |
| 目的地历史 + 产能封顶 | 拣选噪声 σ=0.25 | 64.2% | ±0.5% | 52,250 | 62,545 | 1,098 | 1,155 | 100.0% |
| 目的地历史 + 产能封顶 | 重度拥堵 σ=0.40 | 62.9% | ±0.7% | 58,314 | 74,217 | 1,136 | 1,221 | 100.0% |
| 目的地历史 + 产能封顶 | 加 1 名拣货员/DC | 100.0% | ±0.0% | 0 | 0 | 542 | 548 | 0.0% |
| 场景均值最优 (λ=0) | 基准：均匀到达 · 确定性 | 84.5% | ±0.3% | 5,893 | 6,718 | 729 | 736 | 100.0% |
| 场景均值最优 (λ=0) | 拣选噪声 σ=0.25 | 81.4% | ±0.7% | 8,020 | 12,176 | 747 | 790 | 100.0% |
| 场景均值最优 (λ=0) | 重度拥堵 σ=0.40 | 76.9% | ±1.0% | 11,330 | 18,060 | 774 | 841 | 100.0% |
| 场景均值最优 (λ=0) | 加 1 名拣货员/DC | 100.0% | ±0.0% | 0 | 0 | 475 | 485 | 0.0% |
| 场景 CVaR (λ=0.5) | 基准：均匀到达 · 确定性 | 95.0% | ±0.1% | 819 | 937 | 653 | 657 | 100.0% |
| 场景 CVaR (λ=0.5) | 拣选噪声 σ=0.25 | 92.2% | ±0.7% | 1,781 | 3,504 | 668 | 706 | 96.7% |
| 场景 CVaR (λ=0.5) | 重度拥堵 σ=0.40 | 87.5% | ±1.1% | 3,632 | 6,580 | 694 | 741 | 95.6% |
| 场景 CVaR (λ=0.5) | 加 1 名拣货员/DC | 100.0% | ±0.0% | 0 | 0 | 475 | 485 | 0.0% |

## Placement differences

| Comparison | Δ OTIF | 95% CI | Win | Loss | Tie | n |
|---|---|---|---|---|---|---|
| 目的地历史布点 − Week-5 基线 34/28/38 | -22.82% | ±0.4% | 0.0% | 100.0% | 0.0% | 90 |
| 目的地历史 + 产能封顶 − Week-5 基线 34/28/38 | -19.21% | ±0.4% | 0.0% | 100.0% | 0.0% | 90 |
| 场景均值最优 (λ=0) − Week-5 基线 34/28/38 | +1.41% | ±0.5% | 66.7% | 32.2% | 1.1% | 90 |
| 场景 CVaR (λ=0.5) − Week-5 基线 34/28/38 | +3.89% | ±0.4% | 98.9% | 0.0% | 1.1% | 90 |
| 场景 CVaR (λ=0.5) − 场景均值最优 (λ=0) | +2.48% | ±0.4% | 84.4% | 10.0% | 5.6% | 90 |

Differences are `right − left` on shared arrival seeds and replicate indices; the interval is the normal approximation over pooled runs.

## Per-DC workload (replicate 1, seed 1)

| Placement | DC | Tickets | Waves | Labor (min) | On-time tickets | Tardy tickets | Tardy minutes | Makespan |
|---|---|---|---|---|---|---|---|---|
| Week-5 基线 34/28/38 | London | 261 | 34 | 753.8 | 150 | 111 | 8,431.8 | 753.8 |
| Week-5 基线 34/28/38 | Rotterdam | 195 | 25 | 554.4 | 195 | 0 | 0.0 | 554.4 |
| Week-5 基线 34/28/38 | Frankfurt | 191 | 28 | 546.1 | 191 | 0 | 0.0 | 546.1 |
| 目的地历史布点 | London | 336 | 46 | 1,171.2 | 117 | 219 | 60,039.1 | 1,171.2 |
| 目的地历史布点 | Rotterdam | 128 | 33 | 304.2 | 128 | 0 | 0.0 | 466.7 |
| 目的地历史布点 | Frankfurt | 102 | 36 | 311.8 | 102 | 0 | 0.0 | 449.9 |
| 目的地历史 + 产能封顶 | London | 325 | 43 | 1,067.9 | 117 | 208 | 45,984.7 | 1,067.9 |
| 目的地历史 + 产能封顶 | Rotterdam | 168 | 26 | 401.9 | 168 | 0 | 0.0 | 417.7 |
| 目的地历史 + 产能封顶 | Frankfurt | 128 | 35 | 385.2 | 128 | 0 | 0.0 | 452.5 |
| 场景均值最优 (λ=0) | London | 238 | 33 | 728.1 | 146 | 92 | 5,173.6 | 728.1 |
| 场景均值最优 (λ=0) | Rotterdam | 216 | 29 | 590.2 | 216 | 0 | 0.0 | 590.2 |
| 场景均值最优 (λ=0) | Frankfurt | 184 | 28 | 547.8 | 184 | 0 | 0.0 | 547.8 |
| 场景 CVaR (λ=0.5) | London | 239 | 32 | 657.5 | 211 | 28 | 845.6 | 657.5 |
| 场景 CVaR (λ=0.5) | Rotterdam | 227 | 30 | 568.9 | 227 | 0 | 0.0 | 568.9 |
| 场景 CVaR (λ=0.5) | Frankfurt | 175 | 26 | 501.1 | 175 | 0 | 0.0 | 501.1 |

## Interpretation

- **The fluid model cannot separate the declared split from the scenario plan.** Predicted unmet is 32.0% for `declared` and 32.0% for λ=0 (-0.0%). The stock-based peak also exceeds one shift: the busiest DC holds 138% of a shift's pick minutes if all of its stock ships, so part of the shortfall is execution, not only stock. With per-SKU totals fixed, most of the shortfall is common to every placement; the placement is then chosen by the cover and peak-minute tie-break, not by the service objective.
- **Capacity-blind demand history strands pick capacity.** The uncapped destination mix predicts 63.6% unmet; clipping it to DC throughput improves that to 45.7%, still +13.7% worse than the declared split (32.0%). History says where demand was, not where one shift can pick it.
- **CVaR weight is not identified on this scenario set.** Across λ∈[0.00, 1.00], predicted E[unmet] and CVaR vary by at most 0.01%, yet the selected DC mix changes; the objective is nearly flat, so the solver's cover and peak-minute tie-break decides the placement.
- **Demand history ignores pick capacity.** The uncapped destination mix puts 310% of one shift's pick minutes in the busiest DC; capping it to throughput reduces that to 231%, while the declared split is at 138% and the scenario plan at 135%. Stock that exceeds a DC's shift cannot be picked before the cutoff, so a capacity-blind history is not a deployable plan.
- **The scenario placement wins the out-of-sample week.** At the deterministic baseline cell it reaches 40.6% end-to-end OTIF versus 39.2% for the declared split (+1.4%); the paired 95% interval excludes zero. The fluid objective called the two placements equal, so the scenario plan also lowers the busiest DC from 138% to 135% of a shift, consistent with a gain from execution balance. Pick on-time moves from 83.2% to 84.5%.
- **The CVaR placement improves realized OTIF.** λ=0.5 reaches 43.1% versus 40.6% for λ=0 (+2.5%); the paired interval excludes zero. The predicted objective was flat, so this reflects how the risk weight redistributes SKUs across DCs, not a better forecast.
- **The fluid score tracks unit fill, not end-to-end OTIF.** For `declared`, predicted service is 68.0%, the Week-9 MILP fills 70.8% of units and 54.6% of orders meet the allocation OTIF, but only 39.2% reach end-to-end OTIF once wave batching and cutoff timing are simulated. Read the placement model as a unit-service proxy, not as an OTIF forecast.
- **Allocation solver noise is material.** Across 3 replicates the allocation-OTIF range is widest for `场景 CVaR (λ=0.5)` at 4.5%. The capacity-blind destination baseline is noisier still at 9.2%. Placement comparisons use the pooled mean over replicates; a single solve is not a stable estimate.
- **This is one target week, not a forecast evaluation.** The scenario set uses only prior weeks and the stock totals are deployable, but the out-of-sample result is a single draw. The 6-week set is too short to estimate tail probabilities precisely.

## Declared assumptions

- 订单/行/数量/目的国来自 Online Retail II 真实发票
- DC 库存、产能、转运天数、SLA 承诺与费率是显式假设
- 库存按 SKU 需求 stock_factor 分配并加入确定性偏斜
- 承诺天数 2/3/5 映射到拣选截单 12:00/16:00/18:00
- 班中到达占比与到达窗口是显式假设
- 三个 DC 共用同一 ABC 布局与拣选工时模型，每 DC 独立拣货员
- 每个 SKU 的库存总量取前 6 周场景均值 × 85%，不使用目标周自身的 SKU 结构
- 场景周按目标周总量缩放：周总量已知，SKU 与目的国结构不确定
- 可服务需求按声明承诺 30/50/20 与各 DC 转运天数计算，不是观测值
- 拣选分钟是订单路程 + 行/件工时 + 每波 setup + 20% 拥堵余量，不是波次仿真
- 分单为时间受限 FEASIBLE，每个布点重复 3 次以区分求解器噪声

## Limitations

- The scenario set has 6 weeks. CVaR and the upper tail are estimated from that many observations; the interpolation is coarse.
- The second stage is fluid: it has no order identity, wave batching, cutoff timing, or travel sequence. The pick-minute budget is a linear proxy calibrated to the Week-9 labor model, not a simulation.
- The objective is unserved units only. Transport cost, handling cost and the fixed cost of opening a DC are not in the placement model, so the result is a service frontier, not a profit-maximizing plan.
- Serviceability uses declared transit days and the 30/50/20 promise mix. A different carrier network or premium promise share can change which DC is valuable.
- Allocation is time-limited and solver-dependent. The replicate spread is reported, but it is not a formal confidence interval for the MILP optimum.
- One target week is one draw. The report separates predicted scenario service from realized OTIF, but does not claim a forecast improvement over Week-13 hindsight.
