# Wave picking benchmark (Week 6)

- Generated: `2026-10-27T18:37:53.441462+00:00`
- Orders: **200** real invoices / **1,269** lines / **18,748** units / **179** SKUs, week 2011-11-28
- Warehouse: **8 aisles × 16 bays**, ABC slotting; wave caps **8 orders / 40 lines**.
- Best scenario in this run: **集合划分 CP-SAT** (1,007 labor-minutes, 39.43% below pick-by-order).

## Assumptions

Orders, line quantities, and SKU mix come from real invoices. The warehouse layout, ABC slot assignment, wave capacity, walking speed, pick time, setup time, and labor rate are declared assumptions; none of them come from the dataset.

| parameter | value | source |
|---|---|---|
| orders | 200 | real invoices from one trading week |
| lines | 1,269 | invoice × SKU, duplicates removed |
| SKUs | 179 | mapped to ABC slots |
| slots | 256 | 8 aisles × 16 bays × 2 sides |
| max orders/wave | 8 | declared cart/tote capacity |
| max lines/wave | 40 | declared pick capacity |
| walking speed | 72 m/min | 1.2 m/s with a cart; assumed |
| pick time | 0.35 min/line + 0.02 min/unit | assumed |
| wave setup | 3.0 min/wave | release, tote induction; assumed |
| labor cost | 0.45 /min | fully loaded picker cost; assumed |

## Methods

- **Pick-by-order (baseline)**: one wave per invoice; each order pays its own setup and dispatch trip.
- **FCFS waves**: orders arrive in a seeded random sequence and fill a wave until the next order would exceed the order or line cap.
- **Savings waves**: Clarke-Wright-style order savings. A pair is merged when the combined `return` route is shorter than the two separate routes, subject to wave capacity; randomized jitter gives the candidate pool several local variants.
- **Set-partitioning CP-SAT**: candidate waves are singles, high-saving pairs, and waves from the savings runs. The model chooses one wave for every order and minimises travel minutes plus wave setup. `OPTIMAL` is optimal **for the candidate pool**, not over all subsets.

## Scenario comparison

| scenario | status | waves | orders/wave | lines/wave | travel m/order | travel saving | labor min/order | labor saving | orders/hour | labor cost | solve (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 按单拣选 | BASELINE | 200 | 1.0 | 6.3 | 87.4 | 0.00% | 8.31 | 0.00% | 7.2 | 748 | 0.00 |
| FCFS 波次 | HEURISTIC | 37 | 5.4 | 34.3 | 36.5 | 58.28% | 5.16 | 37.94% | 11.6 | 464 | 0.00 |
| 节省算法波次 | HEURISTIC | 36 | 5.6 | 35.2 | 28.6 | 67.27% | 5.03 | 39.43% | 11.9 | 453 | 0.00 |
| 集合划分 CP-SAT | OPTIMAL | 36 | 5.6 | 35.2 | 28.6 | 67.27% | 5.03 | 39.43% | 11.9 | 453 | 2.30 |

Travel is measured with the Week-3 `return` picker route over the union of wave slots. Labor = travel + line/unit pick time + wave setup; pick time is identical across scenarios, so the differences come from travel and setup.

| scenario | waves | max lines/wave | max units/wave | candidate pool |
|---|---|---|---|---|
| 按单拣选 | 200 | 19 | 1,456 | 0 |
| FCFS 波次 | 37 | 40 | 2,243 | 0 |
| 节省算法波次 | 36 | 40 | 2,310 | 0 |
| 集合划分 CP-SAT | 36 | 40 | 2,310 | 2516 |

## 4. Wave-cap sensitivity

The same orders are re-batched under tighter caps. This shows when the savings heuristic is already sufficient and when the solver earns its keep by repacking capacity.

| capacity (orders/lines) | savings waves | MIP waves | wave delta | savings min/order | MIP min/order | labor delta | MIP status | pool |
|---|---|---|---|---|---|---|---|---|
| 8/25 | 53 | 53 | 0 | 5.420 | 5.420 | 0.00% | FEASIBLE | 2080 |
| 4/19 | 74 | 71 | -3 | 5.872 | 5.822 | -0.86% | FEASIBLE | 1274 |
| 3/19 | 81 | 75 | -6 | 6.000 | 5.903 | -1.62% | FEASIBLE | 1311 |

### Largest waves — 集合划分 CP-SAT

| wave | orders | lines | units | travel m | invoices |
|---|---|---|---|---|---|
| W1 | 8 | 32 | 296 | 162.0 | 579069, 579158, 579274, 579623, 579749, 580135, 580277, 580375 |
| W2 | 8 | 21 | 597 | 89.8 | 579089, 579159, 579403, 579449, 579531, 580158, 580395, 580517 |
| W3 | 8 | 27 | 262 | 130.4 | 579095, 579145, 579153, 579285, 579445, 579711, 580393, 580438 |
| W4 | 8 | 19 | 824 | 94.6 | 579098, 579249, 579279, 579513, 579921, 580051, 580070, 580506 |
| W5 | 8 | 36 | 418 | 142.4 | 579103, 579136, 579391, 579548, 579689, 579690, 580118, 580309 |
| W6 | 8 | 38 | 680 | 128.4 | 579131, 579514, 579840, 580096, 580258, 580281, 580516, 580534 |
| W7 | 8 | 19 | 383 | 128.0 | 579163, 579358, 579406, 579740, 579868, 579954, 580166, 580490 |
| W8 | 8 | 40 | 383 | 142.6 | 579171, 579507, 579600, 579675, 579693, 579747, 579943, 580098 |

## How to read the result

1. Pick-by-order needs **200** waves and **87.4 m** of travel per order. Savings batching cuts travel by **67.27%** and labor by **39.43%** with **36** waves.
2. The CP-SAT row uses **36** waves and reaches **67.27%** travel savings / **39.43%** labor savings versus pick-by-order. It matches the savings heuristic and, with `OPTIMAL` status, proves that this partition is optimal for the 2,516-wave candidate pool.
3. With a tighter **3/19** cap the line limit binds: savings needs 81 waves, CP-SAT packs it into 75 (delta -6), and labor per order moves from 6.000 to 5.903 minutes.
4. The gap between FCFS and batching is the value of grouping by slot proximity instead of arrival order. FCFS is intentionally a weak baseline; it shows why wave release needs a batching rule.

## Notes and limitations

- One trading week and one static order pool; no cut-off times, picker shifts, wave sequencing, or carrier departure deadlines.
- Wave capacity is modelled as order and line caps. Tote volume, weight, and cart cube are not modelled.
- Pick time is linear in lines and units; congestion, replenishment, and picker learning are out of scope.
- The CP-SAT model is a restricted set-partitioning model. Its `OPTIMAL` status is relative to the generated pool, and the pool is biased toward savings-style waves.
- Solver runs use a wall-clock budget. On a different machine the sensitivity scenarios can switch between `OPTIMAL` and `FEASIBLE` and shift the packed waves slightly.
- `return` routing is one policy; the Week-3 report shows that `optimal` routing changes absolute distances but not the slot layout ranking.
