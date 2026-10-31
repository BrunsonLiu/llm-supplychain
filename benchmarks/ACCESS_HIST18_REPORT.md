# Week 49: demand-weighted stock placement

- Orders: **400** | units: **33,060** | week: **2011-11-28** | stock factor: **180%**
- Seeds: **30** | repeats: **3** | MILP time: **10.0 s** | history lookback: **6 weeks** | pickers/DC: **1** | DC share bounds: **10%–60%**

## Design

Week 48 compared hand-picked DC stock splits and found only a directional, non-robust difference. This run keeps the same fixed total stock, 400 invoices, 30 seeds, 2x DC capacity and transit -1, but replaces the hand-picked shares with a small integer program:

```
max  sum_{d,s} z[d,s]
s.t. sum_d y[d,s] = stock_total[s]
     z[d,s] <= y[d,s]
     z[d,s] <= demand[d,s]
     min_share * total <= sum_s y[d,s] <= max_share * total
     y, z integer >= 0
```

`demand[d,s]` is a partition of demand: each line is assigned to one best on-time DC. `access_oracle` uses the current week's realised lines; `access_history` uses the prior six weeks' country x SKU quantities and the current week's destination/transit matrix. The 10%/60% share bounds stop the coverage objective from parking almost all stock in one DC.

The `_load` arms use a **covered demand** pick-minute cap. With `c=0.052` minutes per unit and per-DC capacity `600` minutes:

```
L[d] = sum_s z[d,s] * c
L[d] <= capacity[d] + overload[d]
max coverage - penalty * sum_d overload[d] - moves
```

This is a placement proxy, not a queue simulation: it penalises load where the pick layer would have to work it, but it does not know arrival order or wave release.

## Results

| policy | target OTIF | rest OTIF | all OTIF | backlog | fill | avg day | coverage | peak pick | moved units | MILP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| baseline | 79.2% | 98.7% | 96.7% | 1,448 | 95.6% | 3.42 | — | — | 0 | — |
| access_history | 80.0% | 96.4% | 94.7% | 1,596 | 95.2% | 3.40 | 78.2% | — | 14,530 | OPTIMAL |
| access_history_load_covered | 81.7% | 98.5% | 96.8% | 1,454 | 95.6% | 3.41 | 26.1% | 600 min | 0 | OPTIMAL |
| access_oracle | 76.7% | 96.9% | 94.8% | 1,597 | 95.2% | 3.35 | 90.0% | — | 10,384 | OPTIMAL |
| access_oracle_load_covered | 82.5% | 98.7% | 97.1% | 1,447 | 95.6% | 3.42 | 37.7% | 600 min | 0 | OPTIMAL |

## Paired differences vs baseline

Same `(repeat, seed)` pairs; a normal 95% interval on the paired mean is shown. This is a noise diagnostic, not a causal estimate.

| policy | pairs | Δ target | Δ all | Δ backlog | all wins/ties/losses |
|---|---:|---:|---:|---:|---:|
| access_history | 90 | +0.83pp ±0.24 | -2.00pp ±0.07 | +148.3 ±10.5 | 0/0/90 |
| access_history_load_covered | 90 | +2.50pp ±0.42 | +0.08pp ±0.05 | +5.7 ±7.6 | 60/0/30 |
| access_oracle | 90 | -2.50pp ±0.42 | -1.92pp ±0.21 | +148.7 ±8.2 | 0/0/90 |
| access_oracle_load_covered | 90 | +3.33pp ±0.24 | +0.33pp ±0.06 | -0.7 ±10.7 | 60/30/0 |

## Findings

- **oracle**: target 79.2% -> 76.7% (-2.5pp, lower), moved 10,384 units; directional, inside the 5pp solver-noise band.
- **history**: target 79.2% -> 80.0% (+0.8pp, higher), moved 14,530 units; not material on this run.
- **Repeated runs**: target OTIF ranges baseline 77.5%–80.0%; access_history 80.0%–80.0%; access_oracle 75.0%–77.5%. Treat differences smaller than this range as solver/arrival noise, not a treatment effect.
- **No arm is a Pareto improvement.** Each non-baseline arm loses at least one of target, rest or all-order OTIF.
- **oracle - history gap**: -3.3pp. A gap of this size suggests forecast quality matters, but even the oracle does not turn better demand information into a Pareto gain at this fixed total.
- **The oracle does not buy target service.** Its target moves -2.5pp while rest moves -1.9pp and all-order OTIF -1.9pp versus baseline: this is reallocation, not a Pareto gain.
- **No arm dominates the hand-picked baseline.** The coverage MILP improves its own proxy (`coverage`) but not all three end-to-end metrics. A likely reason is that the objective ignores pick load/queue and arrival timing; concentrating stock in the demand-accessible DC can create a pick bottleneck that the static proxy never sees.
- **access_history_load_covered vs access_history**: target 80.0% -> 81.7% (+1.7pp); all-order 94.7% -> 96.8%; backlog 1,596 -> 1,454; peak covered-demand pick 600 min/DC, overload 0 min. The load cap is a placement proxy, so this tests whether avoiding concentration helps, not whether the real queue is optimised.
- **access_oracle_load_covered vs access_oracle**: target 76.7% -> 82.5% (+5.8pp); all-order 94.8% -> 97.1%; backlog 1,597 -> 1,447; peak covered-demand pick 600 min/DC, overload 0 min. The load cap is a placement proxy, so this tests whether avoiding concentration helps, not whether the real queue is optimised.
- **This is not a production policy.** `access_oracle` sees the week's orders; `access_history` still uses the current week's destination/transit matrix and assumes the transfer is available before the week starts. Both are declared experiment arms.

## Limitations

- 固定总量：每个 SKU 的总库存 = 180% × 前 6 周 SKU 均值，只允许 DC→DC 重摆位；增加总库存的臂是情景外推，不建模采购、在途、仓储成本、COGS、持有成本、过期/跌价。
- access_oracle 使用本周实际订单，是可达需求上界，不是可在周前执行的生产策略。
- access_history 使用前 6 周 country×SKU 数量，但仍使用本周 destination/transit 矩阵来判定可达性；它是半可部署估计，不是完整因果策略。
- 库存按 SKU 总量加确定性 jitter 分配；不同 target 的总量相同，但 SKU×DC 分布受 jitter 影响。
- 所有臂 2× DC 产能、transit −1、ATP accept-all，接受集/需求分母相同；仍只有 1 个目标周、1 套布局/班次。
- 调拨假设在周前完成且无运输时间/费用；真实 DC 调拨需要提前期、批次和成本。
- 布点 MILP 是单线程固定 seed；端到端分单 MILP 仍是 2 workers/时间受限，跨臂重解会带来 1–3pp 差异。
- history 库存基准只用目标周之前的 SKU 周需求均值，不使用目标周实际需求；它仍是周前可部署近似，不是需求预测模型，且只回看固定周数。
- 负荷臂是 covered（只按该 DC 实际覆盖的需求乘单位分钟） 代理，不是波次/到达仿真的真实队列；cap 是 600 分钟/DC 的布点约束，与运行时 1 名拣货员独立，软超载惩罚，所以它约束的是“库存/覆盖需求停在哪”，不是“实际先拣谁”。
- 负荷臂用同一份 demand，但目标里 coverage 与 overload 的权重是声明值；cap、basis 与惩罚变化会改变 target，不能把单点结果当全局最优。
- Week 40 同一 baseline 的 400×30 重复运行得到 92.5/95.0/97.5 目标 OTIF（5pp 跨度）；本周臂间差异必须和这个波动一起读。
- oracle/history 的 target 只由当前实例的订单结构决定，不随 arrival seed 变化；种子只改变到达/拣选噪声。
- 本次每个策略重复 3 次；报告同时给出 target 的 min–max，单次 2.5pp 不能当效应。
