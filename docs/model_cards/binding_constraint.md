# Model card: binding-constraint diagnosis (Weeks 30–39)

## 1. Question

Why does the high-value (revenue Top10) accepted OTIF stay below the rest of the
book, and which physical constraint is binding? The diagnosis is a sequence of
controlled experiments, not a single regression.

## 2. Estimand

For a lever `L` with baseline `L0` and treatment `L1`:

```
Δ_target = OTIF_target(L1) - OTIF_target(L0)
```

estimated on the **same prepared flow** and, for resource levers, the **same
accepted set (400 orders)**. The unit is percentage points (pp).

This is a within-instance counterfactual, not an average treatment effect over
weeks or companies.

## 3. Experiment sequence

| Week | Lever | Target Δ | Verdict |
|---|---|---:|---|
| 30 | promise upgrade for Top10/25 | negative | rejected |
| 31 | allocation weight 3×/10× | ~0 | rejected |
| 32 | same-lane dispatch priority | 0 | null (batches fit) |
| 33 | high-value pick priority | 0 | null (OTIF unchanged) |
| 34 | second picker/DC | 0 | null (labor not binding) |
| 35 | arrival expedite | 0 | null (departures fall, OTIF same) |
| 36 | stock 85%→100% | **+10.0** | binding |
| 37 | DC capacity 1×→2×/10× | **+2.5** | binding, saturates at 2× |
| 38 | transit 0→−1/−2 days | **+5.0** | binding, saturates at −1 |
| 39 | local stock 100%/120%/150% | **+2.5** | only at 150%, non-monotonic |

## 4. Why the nulls matter

- **Promise upgrade** changed the promise, not the physical delivery; it lowered
  OTIF because more orders were labeled late.
- **Allocation/pick/dispatch priority** changed sequence and wait times but not
  the delivery day; the bottleneck was upstream or physical.
- **Second picker** added capacity that was not used: labor was ~3,160 of 9,000
  available minutes; daily pick makespan stayed below 600 minutes.
- **Arrival expedite** cut departures from 49.1 to 34.5 but target OTIF stayed at
  92.5%; the orders were already able to make the promise.

These nulls are evidence for the final claim: scheduling is not the binding
constraint in this instance.

## 5. Residual and upper bounds

After stock 100%, DC 2× and transit −1, target OTIF is about 97.5% vs 98.6% for
the rest (~1.1pp). Week 39 shows that only 150% local stock reaches 100%, but:

- 150% is 1.5× weekly demand, an overstock upper bound, not a replenishment plan;
- 120% is worse than 100% on target (95.0% vs 97.5%), so the path is not
  monotonic;
- the experiment cannot separate "local placement" from "more total units".

Therefore the honest conclusion is **resource-constrained**, not "the optimizer
should rebalance inventory". The next clean test is a fixed-total reallocation.

## 6. Threats to validity

- Single week, single layout, 3 DCs; external validity is limited.
- 30 deterministic seeds; run-to-run CP-SAT spread ~1–1.5pp.
- Gross revenue, no COGS/holding/expedite/returns; "target" is in-sample Top10.
- Multiple levers are upper bounds (100% stock, 10× capacity, 150% stock); they
  identify constraints, not optimal policies.
- Absolute OTIF is not comparable across weeks; only within-week deltas are used.

## 7. Reproduction

The reports and JSON are in `benchmarks/`:

- `STOCK_REPORT.md`, `DC_CAPACITY_REPORT.md`, `TRANSIT_REPORT.md`,
  `LOCAL_STOCK_REPORT.md`;
- `DISPATCH_PRIORITY_REPORT.md`, `PICK_PRIORITY_REPORT.md`,
  `CAPACITY_REPORT.md`, `ARRIVAL_REPORT.md`.

Agent v2 exposes the summary as `diagnose_service_gap` and `compare_arms`, so the
same numbers can be queried programmatically with a verified trace.
