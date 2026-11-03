# Inventory policy benchmark (Week 2)

- Generated: `2026-10-27T17:46:54.154350+00:00`
- Data: Online Retail II, 175 SKUs, evaluation `2010-12-06` → `2011-11-28` (52 weeks)
- Eligibility: excluded 25 SKUs with fewer than 13 non-zero history weeks or mean demand below 1 unit/week; parameters are estimated on the preceding 52 weeks only.
- Forecast: **lightgbm**, evaluation WMAPE 74.18%
- Parameters estimated on `2009-12-07` → `2010-11-29` (52 weeks)
- Planning assumptions: lead time 3 weeks, service level 95.00%, holding 22.00%/yr, order cost 75.0

## 1. Assumption layer

Demand, price, and calendar come from the dataset. Everything else is an explicit assumption so a reviewer can challenge it instead of discovering it buried in code.

| parameter | value | source | note |
|---|---|---|---|
| evaluation weeks | 52 | observed |  |
| SKUs (ABC top-N by revenue) | 175 | observed |  |
| weekly demand / price | panel | observed |  |
| lead time | 3 weeks | assumed | not in Online Retail II; sensitivity 2/4/6 weeks reported |
| target cycle service level | 95% | assumed | business input; cost-service frontier reported |
| holding cost | 22%/yr of unit cost | assumed |  |
| order cost | 75 per order | assumed |  |
| unit cost | 60% of price | assumed | implies a 40% gross margin |
| shortage cost | lost margin × multiplier | assumed | multiplier 1.0 |
| initial inventory | 3 weeks of demand | assumed |  |
| MOQ | 0.5 week of demand, min 1 unit | assumed |  |
| review period | 2 weeks | assumed |  |
| Monte Carlo | 300 scenarios, seed 42 | method |  |

- Annual demand of the selected basket: **1,596,630** units, list value at observed prices **4,240,726**.
- Median weekly CV **1.02**, median zero-demand share **5.77%**, median EOQ **1,504** units.

## 2. Forecast quality in the evaluation window

| forecast | WMAPE | bias | units |
|---|---|---|---|
| seasonal_naive | 85.72% | 9.20% | 1,462,072 |
| lightgbm | 74.18% | 11.77% | 1,462,072 |

WMAPE is the demand-weighted absolute error; bias is `Σ(forecast − actual) / Σ actual`, so a positive value means the forecast over-predicts. These errors are measured on the same SKU subset used by the policies.
The policy engine sees only the forecast, never the realized path. Forecast error therefore propagates directly into the inventory KPIs.

## 3. Policy replay: 52 weeks of realized demand

| policy | fill rate | SKU-week in-stock | stockout weeks | avg on-hand | turns | holding | ordering | stockout | total cost | cost / unit |
|---|---|---|---|---|---|---|---|---|---|---|
| (s, Q) 连续补货 | 93.30% | 95.50% | 96.08% | 241,424 | 5.65 | 83,577 | 56,250 | 118,937 | 258,764 | 0.190 |
| (R, S) 周期补货 | 91.57% | 94.40% | 98.04% | 141,844 | 9.44 | 55,193 | 284,250 | 141,916 | 481,359 | 0.360 |
| (s, S) 最小-最大 | 89.06% | 92.31% | 100.00% | 126,211 | 10.32 | 48,940 | 147,750 | 176,058 | 372,748 | 0.286 |

- Highest fill rate: **(s, Q) 连续补货** (93.30%); lowest total cost: **(s, Q) 连续补货** (258,764).
- Replay is a single realized path: useful for tracing orders and inventory, but it hides the tail risk that a Monte Carlo run exposes.

## 4. Monte Carlo: demand and decision risk

300 scenarios per SKU. Demand is compound: zero with the historical intermittency probability, otherwise lognormal around the forecast with the historical CV, rescaled so the scenario mean equals the forecast.

| policy | fill rate P5 | fill rate P50 | fill rate P95 | cost P5 | cost P50 | cost P95 | turns |
|---|---|---|---|---|---|---|---|
| (s, Q) 连续补货 | 89.97% | 91.74% | 93.09% | 277,845 | 307,759 | 344,685 | 6.73 |
| (R, S) 周期补货 | 88.57% | 90.23% | 91.68% | 516,942 | 546,851 | 586,616 | 12.31 |
| (s, S) 最小-最大 | 86.52% | 88.15% | 89.63% | 404,670 | 436,273 | 478,415 | 13.39 |

- Tightest fill-rate distribution: **(R, S) 周期补货** (P5–P95 spread 3.11%).

### 4b. Forecast source effect

| forecast | policy | fill rate | avg on-hand | turns | total cost |
|---|---|---|---|---|---|
| seasonal_naive | (s, S) 最小-最大 | 86.48% | 124,565 | 10.15 | 437,082 |
| lightgbm | (s, S) 最小-最大 | 89.06% | 126,211 | 10.32 | 372,748 |

## 5. Service-level trade-off

The same policy is re-run across target cycle service levels, using the same Monte Carlo demand paths. This separates the service decision from the policy choice.

| target SL | z | fill rate | SKU-week in-stock | stockout weeks | avg on-hand | turns | holding | ordering | stockout | total cost |
|---|---|---|---|---|---|---|---|---|---|---|
| 80.00% | 0.84 | 89.77% | 93.24% | 98.97% | 197,198 | 7.43 | 67,553 | 59,873 | 207,446 | 334,872 |
| 85.00% | 1.04 | 90.30% | 93.76% | 98.90% | 202,802 | 7.27 | 69,746 | 60,498 | 197,414 | 327,658 |
| 90.00% | 1.28 | 90.91% | 94.37% | 97.79% | 210,330 | 7.06 | 72,705 | 61,330 | 185,197 | 319,233 |
| 95.00% | 1.64 | 91.65% | 95.07% | 97.19% | 222,206 | 6.73 | 77,337 | 62,397 | 170,098 | 309,832 |
| 97.50% | 1.96 | 92.18% | 95.56% | 96.69% | 232,609 | 6.47 | 81,415 | 63,287 | 159,276 | 303,978 |
| 99.00% | 2.33 | 92.69% | 96.01% | 95.65% | 245,027 | 6.18 | 86,299 | 64,251 | 148,823 | 299,373 |

- Cost-minimising target in this sweep: **99.00%** at total cost 299,373; the 95% target is a business input, not an optimisation result.

## 6. Lead-time sensitivity

Lead time is not observable in the public dataset. Instead of hiding it, the benchmark re-runs every policy at several coverage horizons.

| lead time (weeks) | policy | fill rate | SKU-week in-stock | avg on-hand | turns | total cost |
|---|---|---|---|---|---|---|
| 2 | (s, Q) 连续补货 | 94.01% | 95.91% | 227,770 | 6.03 | 240,020 |
| 2 | (R, S) 周期补货 | 91.37% | 93.70% | 124,266 | 10.75 | 483,113 |
| 2 | (s, S) 最小-最大 | 88.29% | 91.56% | 106,585 | 12.11 | 371,081 |
| 3 | (s, Q) 连续补货 | 93.30% | 95.50% | 241,424 | 5.65 | 258,764 |
| 3 | (R, S) 周期补货 | 91.57% | 94.40% | 141,844 | 9.44 | 481,359 |
| 3 | (s, S) 最小-最大 | 89.06% | 92.31% | 126,211 | 10.32 | 372,748 |
| 4 | (s, Q) 连续补货 | 92.96% | 95.41% | 246,832 | 5.51 | 270,530 |
| 4 | (R, S) 周期补货 | 91.23% | 93.88% | 153,629 | 8.68 | 486,871 |
| 4 | (s, S) 最小-最大 | 89.07% | 92.39% | 141,219 | 9.22 | 381,395 |
| 6 | (s, Q) 连续补货 | 92.00% | 95.06% | 261,782 | 5.14 | 296,953 |
| 6 | (R, S) 周期补货 | 90.57% | 93.44% | 177,787 | 7.45 | 501,639 |
| 6 | (s, S) 最小-最大 | 88.95% | 92.14% | 166,455 | 7.81 | 397,584 |

## 7. Multi-period replenishment MILP

- Solver: OR-Tools CP-SAT; 20 SKUs (top by historical mean demand) × 13 weeks; lead time 3 weeks; shared storage 55,687 units and inbound throughput 33,412 units/week.
- Rolling horizon re-plans weekly with the forecast and executes only the current-week order; perfect foresight uses realized demand and is the best achievable plan, not an implementable policy.
- The point-forecast rolling model is deterministic and holds no buffer against forecast error: it plans to the mean path, so it inherits the forecast's bias. This is the single largest driver of the rolling/perfect-foresight gap.

| method | fill rate | total cost | cost / unit | turns | fixed orders | solve (s) |
|---|---|---|---|---|---|---|
| policy: (s, Q) 连续补货 | 85.16% | 15,350 | 0.124 | 8.10 | 35 | 0.00 |
| policy: (R, S) 周期补货 | 85.69% | 21,125 | 0.170 | 17.36 | 140 | 0.00 |
| policy: (s, S) 最小-最大 | 82.87% | 18,961 | 0.158 | 18.38 | 82 | 0.00 |
| MILP: rolling horizon | 76.97% | 21,083 | 0.189 | 17.98 | 45 | 52.90 |
| MILP: perfect foresight | 93.17% | 7,887 | 0.058 | 21.46 | 33 | 43.62 |

- Peak shared-capacity utilisation: rolling storage 84.27%, throughput 97.04%; perfect foresight storage 84.91%, throughput 99.66%.
- Rolling solver statuses: `{'FEASIBLE': 1, 'OPTIMAL': 12}`. When the plan is infeasible (on-hand and pipeline already exceed the shared storage limit), that week executes zero orders rather than adding to an already violated capacity. One worker, a fixed seed, and a CP-SAT deterministic-time budget 10 per solve make re-runs reproduce the same plan.
- The gap between rolling and perfect foresight is the value of forecast accuracy; the gap between the policies and perfect foresight is the value of reactivity (rule policies see realized demand every week and can reorder immediately).

## 8. DC → store allocation

One representative week, 8 stores, 2 DCs, DC stock covers 90.00% of store demand; store receiving capacity is an explicit space constraint.

| scenario | fill rate | unmet units | transport | shortage | total | cost / unit | solve (s) |
|---|---|---|---|---|---|---|---|
| unconstrained | 100.00% | 0 | 2,889 | 0 | 2,889 | 0.103 | 0.018 |
| capacity | 90.00% | 2,812 | 3,238 | 22,493 | 25,732 | 1.017 | 0.029 |
| priority | 90.00% | 2,812 | 3,277 | 20,767 | 24,044 | 0.950 | 0.029 |

Priority scenario, store level:

| store | demand | shipped | unmet | fill rate | DC1 share |
|---|---|---|---|---|---|
| S1 | 7,892 | 7,497 | 395 | 95.00% | 100.00% |
| S2 | 5,777 | 5,488 | 289 | 95.00% | 92.58% |
| S3 | 4,118 | 3,912 | 206 | 95.00% | 0.00% |
| S4 | 2,742 | 2,605 | 137 | 95.00% | 100.00% |
| S5 | 2,298 | 2,183 | 115 | 95.00% | 0.00% |
| S6 | 2,115 | 2,009 | 106 | 95.00% | 0.00% |
| S7 | 1,388 | 0 | 1,388 | 0.00% | 0.00% |
| S8 | 1,787 | 1,611 | 177 | 90.12% | 0.00% |

With equal penalties the LP is indifferent to *who* absorbs a shortage; priority weights change the allocation, not the total physical capacity.

## 9. Limitations

- Lead time, costs, MOQ, store shares, and the DC cost matrix are assumptions, not observations. They are configurable in one dataclass and one network builder.
- Point forecasts are used without a predictive distribution; the Monte Carlo layer is a scenario generator around the point forecast, not a calibrated probabilistic forecast.
- The MILP is a single-echelon model on a Top-N SKU subset. It does not model multi-echelon inventory, case-pack rounding, truckload consolidation, or stochastic demand. A `z·σ`-buffered rolling variant exists as an API option (`rolling_horizon(..., safety_stock=...)`), but it is not reported here: under hard shared-capacity limits the buffered plan is often infeasible and the reported numbers move with the solver time limit.
- Rule-based policies ignore shared storage and inbound throughput, while the MILP enforces them. The comparison therefore mixes policy quality with constraint feasibility and should be read as indicative, not as a controlled A/B test.
- The rolling MILP is deterministic and plans to the point forecast, so it inherits forecast bias and has no mechanism to stock against forecast error. That is why its fill rate trails the rule policies even though its cost objective is better specified.
- The reported MILP plan is the best incumbent found within the deterministic-time budget, not a proven optimum; a larger budget can change the plan.
- MILP inventory turns are annualised from the 13-week window and are not comparable to full-year turns. Shared capacity is sized from the same window (storage = 5× mean weekly demand, inbound throughput = 3× mean weekly demand), so the throughput limit binds in peak weeks by construction.
- No service-level optimisation is performed end-to-end: the sweep shows the cost-service frontier, while the target remains a business input.
