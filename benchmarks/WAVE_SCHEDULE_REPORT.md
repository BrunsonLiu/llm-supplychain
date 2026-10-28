# Wave release scheduling benchmark (Week 7)

- Generated: `2026-10-27T19:09:48.830416+00:00`
- Orders: **200** real invoices / **1,269** lines / **18,748** units, week 2011-11-28
- Batching basis: Week-6 partition, wave cap **8 orders / 40 lines**; labor minutes include travel, picking and per-wave setup.
- Promise mix: express **20.0%** (cutoff 240 min), standard **50.0%** (480 min), economy **30.0%** (600 min), assigned by seeded shuffle.
- Shift: start 08:00, length **600 min**, **2 pickers**; overtime is allowed and reported, not constrained.
- Best scenario in this run: **承诺分层合并 + CP-SAT** (on-time 100.0%)

## Assumptions

| Item | Assumption | Note |
|---|---|---|
| Promise tier mix | 20% / 50% / 30% | No customer-promise data in Online Retail II; tiers are assigned by seeded shuffle. |
| Cutoffs | 12:00 / 16:00 / 18:00 | Minutes 240 / 480 / 600 after the 08:00 shift start. |
| Pickers | 2 identical workers | No skills, zones, breaks, or absenteeism. |
| Shift | 08:00–18:00 (600 min) | Waves may finish after 18:00; overtime is a reported metric, not a hard constraint. |
| Scheduling objective | tardiness × 100 + makespan × 1 | A policy weight: one late order-minute is worth 100 minutes of shift length. |
| Wave labor | Week-6 model | Travel at 72.0 m/min, 0.35 min/line + 0.02 min/unit, 3.0 min setup/wave. |

## Methods

- **Week-6 batching**: the CP-SAT set-partitioning partition (36 waves in the main run) is reused unchanged, so travel and picking labor match the Week-6 report.
- **Tier-aware batching**: the same Clarke-Wright savings merge, but pairs are only scored inside a promise tier; orders with different cutoffs are never merged.
- **EDF scheduling**: waves are released earliest-deadline-first onto identical pickers, where a wave's deadline is the earliest cutoff among its orders.
- **CP-SAT scheduling**: optional intervals on parallel pickers, no overlap per picker, and an objective of per-order tardiness minutes plus makespan. The EDF plan is injected as an integer-consistent hint, so the solver starts from EDF and returns the best plan it finds; when it cannot improve, differences are rounding-level.

## Scenario comparison

| 方案 | 状态 | 波次 | 单均工时 | 准时率 | 迟到单 | 迟到订单分钟 | 最大迟到 (min) | Makespan | 加班 (min) | 拣货员利用率 | 求解 (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 按单拣选 + EDF | HEURISTIC | 200 | 8.31 | 50.0% | 100 | 10,950 | 233 | 833 | 233 | 99.7% | 0.00 |
| 全量合并 + EDF | HEURISTIC | 36 | 5.03 | 86.5% | 27 | 1,707 | 127 | 504 | 0 | 100.0% | 0.00 |
| 全量合并 + CP-SAT | FEASIBLE | 36 | 5.03 | 86.5% | 27 | 1,707 | 127 | 504 | 0 | 100.0% | 10.01 |
| 承诺分层合并 + EDF | HEURISTIC | 36 | 5.05 | 100.0% | 0 | 0 | 0 | 509 | 0 | 99.4% | 0.00 |
| 承诺分层合并 + CP-SAT | FEASIBLE | 36 | 5.05 | 100.0% | 0 | 0 | 0 | 505 | 0 | 100.0% | 10.00 |

On-time is counted per order against its own cutoff; a wave that finishes early for an express order but late for an economy order splits the credit accordingly. Tardiness is in order-minutes.

### Promise tiers — Full batching + EDF

| 承诺层 | 截单 | 订单 | 准时 | 准时率 | 迟到 | 迟到分钟 | 最大迟到 (min) |
|---|---|---|---|---|---|---|---|
| 特快 | 12:00 | 40 | 19 | 47.5% | 21 | 1,589 | 127 |
| 标准 | 16:00 | 100 | 94 | 94.0% | 6 | 118 | 24 |
| 经济 | 18:00 | 60 | 60 | 100.0% | 0 | 0 | 0 |

### Promise tiers — Tier-aware batching + EDF

| 承诺层 | 截单 | 订单 | 准时 | 准时率 | 迟到 | 迟到分钟 | 最大迟到 (min) |
|---|---|---|---|---|---|---|---|
| 特快 | 12:00 | 40 | 40 | 100.0% | 0 | 0 | 0 |
| 标准 | 16:00 | 100 | 100 | 100.0% | 0 | 0 | 0 |
| 经济 | 18:00 | 60 | 60 | 100.0% | 0 | 0 | 0 |

## Picker-count sensitivity

Same tier-aware partition and cutoffs, re-scheduled with 1/2/3 pickers. This isolates scheduling freedom from batching: with enough pickers both rules meet every cutoff, while a single picker forces a choice.

| 拣货员 | EDF 准时率 | EDF 迟到分钟 | EDF makespan | CP-SAT 状态 | CP-SAT 准时率 | CP-SAT 迟到分钟 | CP-SAT makespan | 求解 (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | 41.5% | 24,794 | 1,011 | FEASIBLE | 53.0% | 22,129 | 1,011 | 8.01 |
| 2 | 100.0% | 0 | 509 | FEASIBLE | 100.0% | 0 | 505 | 10.00 |
| 3 | 100.0% | 0 | 345 | FEASIBLE | 100.0% | 0 | 342 | 8.01 |

## Schedule detail — tier-aware batching + CP-SAT

| 波次 | 拣货员 | 开始 | 结束 | 工时 (min) | 订单 | 最紧截单 | 迟到单 | 最大迟到 (min) |
|---|---|---|---|---|---|---|---|---|
| W1 | P1 | 08:00 | 08:28 | 28.4 | 8 | 18:00 | 0 | 0 |
| W2 | P2 | 08:00 | 08:28 | 28.3 | 4 | 18:00 | 0 | 0 |
| W3 | P2 | 08:28 | 08:45 | 16.2 | 7 | 12:00 | 0 | 0 |
| W4 | P1 | 08:28 | 08:53 | 24.9 | 8 | 18:00 | 0 | 0 |
| W5 | P2 | 08:45 | 09:21 | 36.3 | 4 | 16:00 | 0 | 0 |
| W6 | P1 | 08:53 | 09:16 | 22.3 | 8 | 18:00 | 0 | 0 |
| W7 | P1 | 09:16 | 09:38 | 22.4 | 3 | 18:00 | 0 | 0 |
| W8 | P2 | 09:21 | 09:55 | 33.9 | 5 | 12:00 | 0 | 0 |
| W9 | P1 | 09:38 | 09:52 | 13.8 | 2 | 16:00 | 0 | 0 |
| W10 | P1 | 09:52 | 10:22 | 29.9 | 4 | 16:00 | 0 | 0 |

## Interpretation

1. **Batching saves labor, but couples deadlines.** Pick-by-order needs 8.31 min/order; full batching drops it to 5.03 min/order. The same merge, however, puts express and economy orders in one wave, so the wave finishes when its slowest line is picked and the express promise inherits the whole wave.
2. **Full batching + EDF misses 27 orders** (13.5%), with 1,707 order-minutes of tardiness. Tier-aware batching keeps the wave count unchanged (36 vs 36) and raises on-time to 100.0% at 5.05 min/order — the deadline is protected by not merging across cutoffs, not by adding pickers.
3. **EDF already meets every cutoff at 2 pickers**, so CP-SAT mainly reshuffles the same work: makespan 509 → 505 min, status `FEASIBLE`. Scheduling freedom has little value when capacity is ample.
4. **Scheduling matters when pickers are scarce.** With 1 picker, EDF leaves 24,794 order-minutes late; CP-SAT returns 22,129. With enough capacity the gap closes, which is the honest boundary of the optimisation: fix the batching policy first, then schedule.
5. **The result is a policy statement, not a universal rule.** The on-time gain comes from refusing to merge across cutoffs. If the promise mix or cutoffs are wrong, the partition is wrong; a production system must feed real promise and cutoff data into this layer instead of a fixed 20/50/30 mix.

## Limitations

- Promise tiers, cutoffs, picker count, shift length and the objective weights are declared assumptions; the dataset contains no customer promises, picker roster, or labor rules.
- The order pool is one static trading week. Orders do not arrive during the shift, and there is no re-optimisation when a wave finishes early or a picker is pulled away.
- Pickers are identical and never blocked: no zones, skills, breaks, congestion, replenishment delays, or handover time between waves.
- Batching is fixed before scheduling. The benchmark does not jointly optimise batching and release times, and the tier-aware partition only forbids cross-tier merges; it does not search for the best deadline-aware partition.
- CP-SAT runs with a wall-clock budget and a fixed weight ratio. `OPTIMAL` is not guaranteed on a larger order pool, and the weights are a policy choice rather than a tuned production setting.
- The reported CP-SAT status is `FEASIBLE`, not `OPTIMAL`. Its bound is weak because the objective mixes order-minutes with makespan; `FEASIBLE` only means the EDF-seeded incumbent was not improved within the budget, not that a better schedule does not exist.
- Overtime is reported, not constrained: the model can finish after 18:00, so the makespan and overtime columns are consequences of the plan rather than a legal shift limit.
