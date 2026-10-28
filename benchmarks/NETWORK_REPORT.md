# Network & warehouse benchmark (Week 3)

- Generated: `2026-10-27T18:30:41.524548+00:00`
- Data: Online Retail II transaction lines (full span `2009-12-01` → `2011-12-09`); 200 SKUs, demand window `2010-12-06` → `2011-11-28`.
- Observed: unit demand by country, order lines, SKU popularity. Assumed: country centroids, hub candidates/costs, fleet, store coordinates, warehouse layout and travel speed.

## 1. Capacitated facility location (CFLP)

- Demand coverage: **97.44%** of selected units (1,717,478 of 1,762,688); countries without a mapped coordinate are excluded.
- Transport: 0.00018 currency/unit/road-km, road factor 1.25; fixed costs are per year.
- Model: CP-SAT with integer unit flows. The baseline opens every hub and assigns each country to the cheapest hub with remaining capacity.

| method | status | hubs | fixed cost | transport cost | total cost | avg road km | solve (s) |
|---|---|---|---|---|---|---|---|
| all hubs open, nearest | HEURISTIC | 8 | 2,220,000 | 84,311 | 2,304,311 | 273 | 0.00 |
| CFLP optimum | OPTIMAL | 2 | 710,000 | 150,315 | 860,315 | 486 | 0.11 |

- CFLP opens **2** hubs and cuts annual cost by **62.66%** versus all-open nearest assignment.

| hub | units | capacity use | fixed cost |
|---|---|---|---|
| London | 1,000,000 | 100.00% | 380,000 |
| Rotterdam | 717,478 | 89.68% | 330,000 |

### 1b. Demand geography

| country | units | share |
|---|---|---|
| United Kingdom | 1,488,693 | 86.68% |
| Netherlands | 70,044 | 4.08% |
| EIRE | 38,687 | 2.25% |
| France | 35,471 | 2.07% |
| Germany | 29,559 | 1.72% |
| Sweden | 12,510 | 0.73% |
| Spain | 9,500 | 0.55% |
| Switzerland | 8,160 | 0.48% |
| Belgium | 6,571 | 0.38% |
| Portugal | 4,763 | 0.28% |
| Norway | 3,997 | 0.23% |
| Channel Islands | 3,406 | 0.20% |
| Denmark | 3,060 | 0.18% |
| Finland | 3,057 | 0.18% |

### 1c. Fixed-cost sensitivity

Fixed costs are assumptions, so the open/close decision is re-solved across multipliers. This is the honest way to show how sensitive the network is.

| fixed-cost multiplier | status | hubs | fixed cost | transport | total | hubs opened |
|---|---|---|---|---|---|---|
| 0.25x | OPTIMAL | 3 | 207,500 | 110,668 | 318,168 | London, Manchester, Warsaw |
| 0.5x | OPTIMAL | 2 | 355,000 | 150,315 | 505,315 | London, Rotterdam |
| 1x | OPTIMAL | 2 | 710,000 | 150,315 | 860,315 | London, Rotterdam |
| 2x | OPTIMAL | 2 | 1,420,000 | 150,315 | 1,570,315 | London, Rotterdam |
| 4x | OPTIMAL | 2 | 2,840,000 | 150,315 | 2,990,315 | London, Rotterdam |

## 2. Vehicle routing (CVRP / VRPTW)

- One depot, **8** stores, **4** vehicles, capacity 10,950 units, speed 40 km/h, service 20 min, horizon 480 min.
- Store demand comes from the real weekly basket; store shares and coordinates are the same assumed network as the allocation LP. Distances are Euclidean km on that grid.

| method | distance km | vehicles | max load | route minutes | feasible | solve (s) |
|---|---|---|---|---|---|---|
| one route per store | 544.8 | 8 | 9,491 | 977 | no | 0.000 |
| Clarke-Wright savings | 365.3 | 4 | 9,491 | 708 | yes | 0.000 |
| exact subset DP | 365.3 | 4 | 9,491 | 708 | yes | 0.011 |
| OR-Tools CVRP | 365.3 | 4 | 9,491 | 708 | yes | 2.038 |
| OR-Tools CVRP + time windows | 413.4 | 4 | 10,508 | 780 | yes | 2.004 |

OR-Tools CVRP routes, store level:

| vehicle | stores | load | distance km | visits (minutes) |
|---|---|---|---|---|
| V1 | S2 | 6,441 | 72.8 | S2 54-74min |
| V2 | S4 → S3 → S8 | 10,508 | 167.2 | S4 120-140min; S3 170-190min; S8 360-380min |
| V3 | S1 | 9,491 | 56.9 | S1 42-62min |
| V4 | S6 → S5 → S7 | 7,458 | 116.6 | S6 240-260min; S5 306-326min; S7 360-380min |

- The exact subset DP is a proven optimum for this small instance and is used to validate the OR-Tools result, not as a production solver. Clarke-Wright is a fast constructive baseline; the gap between it and the solver is the value of local search on this instance.

## 3. Warehouse slotting and picking

- Layout: 8 aisles × 16 bays × 2 sides = **256** slots; front and back cross-aisles; bay 1.2 m, aisle gap 2.5 m.
- Orders: 200 sampled invoices from the week of `2011-11-28`, 5 median lines/order, 179 unique SKUs.
- ``abc`` places SKUs by 52-week velocity, closest to dispatch first; ``random`` is the control. Savings are relative to the random-slotting distance under the same routing policy.

| slotting | orders | avg lines | return m | S-shape m | optimal m | return saving | optimal saving |
|---|---|---|---|---|---|---|---|
| random | 200 | 6.3 | 122.7 | 120.4 | 90.6 | 0.00% | 0.00% |
| abc | 200 | 6.3 | 87.4 | 116.5 | 79.7 | 28.75% | 12.02% |

Highest-velocity SKUs under ABC slotting:

| SKU | ABC class | slot (aisle, bay) | distance to dispatch (m) |
|---|---|---|---|
| 23166 | A | (4, 1) | 2.5 |
| 22197 | A | (4, 1) | 2.5 |
| 84077 | A | (5, 1) | 2.5 |
| 85099B | A | (5, 1) | 2.5 |
| 85123A | A | (4, 2) | 3.6 |

- ``return`` walks into an aisle and back to the front cross-aisle; ``S-shape`` traverses the full aisle and alternates ends; ``optimal`` solves the picker TSP (Held-Karp at ≤12 picks, 2-opt above). S-shape only wins when picks are dense: with ~6 lines spread over 256 slots it adds empty aisle travel, which is why it trails the return policy here.

## 4. Limitations

- Country centroids, hub fixed costs/capacities, store coordinates, fleet size, and warehouse layout are assumptions. They are declared in one module and configurable; none of them come from the dataset.
- CFLP uses annualised units from the last 52 weeks as a steady-state demand; seasonality and demand growth are not modelled.
- The CVRP instance has eight stores. Exact DP validates the solver only at this scale; large instances would need the OR-Tools model and a longer search budget.
- VRPTW uses four coarse two-hour receiving blocks and no driver shift rules, loading time, or stochastic travel times.
- Warehouse distances are grid metrics with constant travel speed; pick time, congestion, and replenishment are out of scope here. Order batching and picker labor are covered in the Week-6 wave benchmark.
- Routing search uses a fixed wall-clock limit, so a heavily loaded machine can return a slightly different plan. The CFLP uses a deterministic budget.