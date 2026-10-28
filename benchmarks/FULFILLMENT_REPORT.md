# Order fulfillment benchmark (multi-DC allocation)

- Generated: `2026-10-27T20:39:09.588100+00:00`
- Orders: **120** real invoices / **542** lines / **8,771** units / **155** SKUs, week 2011-11-28
- Network: **3 DCs** (London, Rotterdam, Frankfurt); stock covers **84.97%** of sampled demand; promise tiers 2d=36, 3d=60, 5d=24
- Dataset window: 2010-12-06 → 2011-11-28 (1,014,625 cleaned transactions)
- Best scenario in this run: **MILP (2 DCs, 5x late penalty)** (OTIF 30.83%)

## Assumptions

- Orders, line quantities, SKU mix, and destination countries come from real invoices; stock placement, DC capacity, transit times, shipping rates, and SLA promises are declared assumptions.
- Stock: 84.97% of demand, split by [0.34, 0.28, 0.38] with deterministic per-SKU jitter; weekly throughput caps are [0.55, 0.4, 0.35] of total units.
- Transit: 1 handling day + ceil(road km / 700) days; observed range **2–5** days.
- Cost: road km × **0.0006** per unit + DC handling; fixed **25.00** per shipment, late **0.35/unit/day**, lost sale **6.00/unit**.

## Scenario comparison

| scenario | status | unit fill | order fill | OTIF | on-time units | split orders | shipments | transport | fixed | late | unmet | total | solve (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Greedy (deadline-first) | HEURISTIC | 61.18% | 32.50% | 25.00% | 57.54% | 70.00% | 204 | 2,089 | 5,100 | 151 | 20,430 | 27,770 | 0.01 |
| MILP (max 1 DC/order) | FEASIBLE | 47.04% | 14.17% | 12.50% | 45.65% | 0.00% | 119 | 1,710 | 2,975 | 50 | 27,870 | 32,606 | 25.03 |
| MILP (max 2 DCs/order) | FEASIBLE | 67.88% | 15.00% | 15.00% | 64.96% | 79.17% | 212 | 2,726 | 5,300 | 106 | 16,902 | 25,034 | 25.01 |
| MILP (2 DCs, 5x late penalty) | FEASIBLE | 69.29% | 32.50% | 30.83% | 65.00% | 89.17% | 224 | 2,825 | 5,600 | 132 | 16,164 | 24,721 | 25.00 |

Metric definitions: unit fill = shipped / ordered units; order fill = orders with every unit shipped; OTIF = order fully shipped *and* fully on time; split orders = share of orders served by more than one DC; on-time units = shipped units that arrive within the promise.

All MILP rows share the same constraints and 25s search budget. The last row re-weights the objective only: lateness × 5.0 and a per-order OTIF bonus of 200. Reported costs always use the base penalties, so rows are directly comparable.

### Greedy (deadline-first) — DC load

| DC | units | capacity | capacity use | stock left |
|---|---|---|---|---|
| London | 2,437 | 4,825 | 50.51% | 13 |
| Rotterdam | 2,081 | 3,509 | 59.30% | 0 |
| Frankfurt | 848 | 3,070 | 27.62% | 2,074 |

### Greedy (deadline-first) — promise tiers

| promise | orders | OTIF | late units | unmet units |
|---|---|---|---|---|
| 2 days | 36 | 25.00% | 319 | 1,078 |
| 3 days | 60 | 28.33% | 0 | 1,220 |
| 5 days | 24 | 16.67% | 0 | 1,107 |

### MILP (max 1 DC/order) — DC load

| DC | units | capacity | capacity use | stock left |
|---|---|---|---|---|
| London | 1,898 | 4,825 | 39.34% | 552 |
| Rotterdam | 1,051 | 3,509 | 29.95% | 1,030 |
| Frankfurt | 1,177 | 3,070 | 38.34% | 1,745 |

### MILP (max 1 DC/order) — promise tiers

| promise | orders | OTIF | late units | unmet units |
|---|---|---|---|---|
| 2 days | 36 | 13.89% | 122 | 2,159 |
| 3 days | 60 | 13.33% | 0 | 1,512 |
| 5 days | 24 | 8.33% | 0 | 974 |

### MILP (max 2 DCs/order) — DC load

| DC | units | capacity | capacity use | stock left |
|---|---|---|---|---|
| London | 1,831 | 4,825 | 37.95% | 619 |
| Rotterdam | 1,959 | 3,509 | 55.83% | 122 |
| Frankfurt | 2,164 | 3,070 | 70.49% | 758 |

### MILP (max 2 DCs/order) — promise tiers

| promise | orders | OTIF | late units | unmet units |
|---|---|---|---|---|
| 2 days | 36 | 13.89% | 256 | 1,401 |
| 3 days | 60 | 13.33% | 0 | 856 |
| 5 days | 24 | 20.83% | 0 | 560 |

### MILP (2 DCs, 5x late penalty) — DC load

| DC | units | capacity | capacity use | stock left |
|---|---|---|---|---|
| London | 1,734 | 4,825 | 35.94% | 716 |
| Rotterdam | 2,030 | 3,509 | 57.85% | 51 |
| Frankfurt | 2,313 | 3,070 | 75.34% | 609 |

### MILP (2 DCs, 5x late penalty) — promise tiers

| promise | orders | OTIF | late units | unmet units |
|---|---|---|---|---|
| 2 days | 36 | 36.11% | 367 | 1,256 |
| 3 days | 60 | 28.33% | 9 | 895 |
| 5 days | 24 | 29.17% | 0 | 543 |

## Orders where the MILP differs from greedy

| order | destination | promise | units | greedy DCs | greedy OTIF | MILP DCs | MILP OTIF | MILP late units |
|---|---|---|---|---|---|---|---|---|
| 579176 | United Kingdom | 3d | 70 | London + Rotterdam | no | London + Frankfurt | yes | 0 |
| 579473 | United Kingdom | 3d | 50 | London + Rotterdam | no | London + Frankfurt | yes | 0 |
| 579954 | United Kingdom | 3d | 36 | London + Rotterdam | no | London + Rotterdam | yes | 0 |
| 580387 | United Kingdom | 5d | 26 | Frankfurt | no | London + Frankfurt | yes | 0 |
| 579544 | United Kingdom | 3d | 25 | London + Frankfurt | no | London | yes | 0 |
| 580386 | United Kingdom | 2d | 24 | Frankfurt | no | London | yes | 0 |

## Notes and limitations

- The instance is one trading week with a fixed stock snapshot; no replenishment, order cancellation, or multi-day promise rolling.
- Transit days and SLA tiers are assumptions. They create the cost-vs-lateness trade-off but are not validated against carrier data.
- The MILP is solved with a deterministic one-worker search and a wall-clock limit; `OPTIMAL` is not guaranteed on larger instances. Rows marked `FEASIBLE` are valid plans but not proven optimal; the JSON summary keeps the solver bound, which is loose here because of the fixed-charge and split binaries.
- The service-weighted row is a policy choice, not a free improvement: it spends objective weight on whole-order OTIF, and the chosen weights are a declared assumption rather than a tuned production setting.
- Lost sales are penalised at a flat per-unit rate, so the model does not distinguish strategic customers or backorders.
- Distances are great-circle × road factor between DC and country centroid, not real lane distances.
