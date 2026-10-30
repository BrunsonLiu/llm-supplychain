# Model card: capacity-aware allocation MILP

## 1. Problem

Given a set of order lines, DCs, stock by SKU, DC throughput capacity and per-DC
transit days, choose how many units of every line ship from every DC. The model
is a mixed-integer program because a line can only ship from a DC if the order
"touches" that DC, and the number of DCs per order is capped (`max_splits`).

This is the allocation core behind the Week 32–39 experiments. The same model is
also exposed to Agent v2 as `solve_allocation_milp`, but that tool uses a small
synthetic 3 DC × 4 order instance so the benchmark is cheap and reproducible.

## 2. Formulation

Sets and indices:

- `L`: order lines, `l ∈ L`; each line belongs to one order `o(l)` and one SKU `s(l)`.
- `D`: distribution centers, `d ∈ D`.

Parameters:

- `q_l`: units on line `l`.
- `stock_s`: total units available for SKU `s`.
- `cap_d`: DC throughput capacity in units.
- `ship_{d,o}`: per-unit shipping cost from DC `d` to order `o`.
- `transit_{d,o}`: transit days; `promise_o`: promised days.
- `late_penalty`: cost per unit-day late.
- `fixed_ship_cost`: fixed cost per (order, DC) shipment.
- `unmet_penalty_per_unit`: penalty for unfulfilled units.
- `max_splits`: maximum DCs per order.
- `otif_bonus`: reward for an order that is complete and on time.

Decision variables:

- `x_{l,d} ∈ Z≥0`: units of line `l` shipped from DC `d`.
- `u_l ∈ Z≥0`: unmet units of line `l`.
- `y_{o,d} ∈ {0,1}`: order `o` uses DC `d`.
- `touch_{l,d} ∈ {0,1}`: line `l` ships from DC `d` (used for pick-time).
- `f_o ∈ {0,1}`: order `o` is OTIF (optional bonus).
- `slack_{d,k} ≥ 0`: pick-overload slack at DC `d` by deadline `k`.

Constraints:

1. Demand balance: `Σ_d x_{l,d} + u_l = q_l` for every line.
2. Touch linking: `x_{l,d} ≤ q_l · touch_{l,d}`.
3. Shipment linking: `x_{l,d} ≤ q_l · y_{o(l),d}`.
4. Split cap: `Σ_d y_{o,d} ≤ max_splits` for every order.
5. DC capacity: `Σ_l x_{l,d} ≤ cap_d` for every DC.
6. SKU stock: `Σ_{l: s(l)=s} Σ_d x_{l,d} ≤ stock_s`.
7. Pick deadline: `Σ_{l: day(l)≤k} (line_coef·touch_{l,d} + unit_coef·x_{l,d}) + ship_coef·Σ_{o: day(o)≤k} y_{o,d} ≤ deadline_{d,k} + slack_{d,k}`.
8. OTIF flag: `Σ_{l∈o} u_l + q_o·f_o ≤ q_o` and `late_units_o + q_o·f_o ≤ q_o`; `f_o=1` only if the order has no unmet and no late units.

Objective (minimize):

```
Σ_{l,d} (ship_{d,o(l)} + late_days_{d,o(l)}·late_penalty) · x_{l,d}
+ Σ_{o,d} fixed_ship_cost · y_{o,d}
+ Σ_l unmet_penalty_per_unit · u_l
+ pick_overload_penalty · Σ slack
- otif_bonus · Σ_o f_o
```

`late_days_{d,o} = max(0, transit_{d,o} - promise_o)`.

## 3. Solver and complexity

- Formulation: MILP; solved with OR-Tools CP-SAT (`cp_model`), 8 s/day budget in
  the rolling experiments, `num_search_workers` configurable.
- The problem is NP-hard (capacitated facility/assignment structure). The model
  is small in lines (hundreds) but the integer variables and the split/OTIF
  logic make the LP relaxation weak.
- CP-SAT reports `OPTIMAL`, `FEASIBLE` or `UNKNOWN`; the rolling runner keeps the
  best feasible solution and records the objective and best bound.
- Time-limited runs can differ by roughly 1–1.5pp OTIF between identical
  configurations, which is why the experiments use 30 deterministic seeds and
  same-flow counterfactuals rather than cross-week absolute comparisons.

## 4. Baseline and evidence

- Greedy baseline: each order takes the cheapest DC with remaining supply. It
  ignores capacity, split limits, stock by SKU and late penalties, so it can be
  infeasible or materially worse.
- In the Agent v2 tool's 3 DC × 4 order instance: MILP optimum **880.0**,
  greedy **930.0**, gap **5.68%**. This is a unit test of the OR path, not a
  production estimate.
- In the 400-invoice rolling flow, allocation is only one component: Week 30–35
  show that allocation/pick/dispatch changes alone do not move target OTIF when
  stock, DC capacity and transit are binding.

## 5. Limitations

- Single-week, 3-DC, 1-picker/DC baseline; no COGS, holding cost, returns or
  door capacity in the objective.
- `otif_bonus` is a modeling device to trade cost against service; it is not a
  calibrated economic value.
- The MILP is deterministic given the same instance, but CP-SAT time limits make
  the *reported* solution sensitive to the budget.
- The small Agent v2 instance is synthetic; it validates the tool contract and
  solver wiring, not the quality of the real allocation policy.
