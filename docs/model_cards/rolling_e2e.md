# Model card: rolling end-to-end fulfillment simulation

## 1. What is simulated

A five-day order week from UCI Online Retail II (400 invoices, 2,477 lines,
33,060 units, 3 DCs). Each day is a rolling decision episode:

1. **Arrivals**: orders become visible/on-site according to an arrival curve.
2. **Quote / acceptance**: ATP or promise logic accepts, rejects or upgrades.
3. **Allocation**: capacity-aware MILP assigns lines to DCs (8 s/day).
4. **Picking**: lines are released to waves; EDF or priority order; one picker
   per DC by default, 600-minute shift.
5. **Dispatch**: orders are consolidated into departures at 13:00/19:00; door
   and lane constraints can block a departure.
6. **Delivery**: transit days by DC/order; an order is OTIF if it is complete
   and delivered by its promise date.

The simulation is the environment used by Weeks 30–39. It is not a production
WMS: it is a deterministic, inspectable testbed for controlled experiments.

## 2. State and determinism

- Global random seed per run; the 30 "seeds" in the reports are deterministic
  replications, not 30 independent weeks.
- All inputs are fixed: invoice set, order days, DC/SKU stock, arrival curves,
  shift length, door/lane settings, MILP time limit.
- Same config can still vary by ~1–1.5pp OTIF because CP-SAT is time-limited.
- Metrics are computed over the **accepted** set, so a policy that rejects orders
  cannot improve OTIF by shrinking the denominator without also reporting
  acceptance and revenue.

## 3. Metrics

- `accepted_orders`, `accepted_rate`, `accepted_units`.
- `target_accepted_otif`: OTIF over accepted orders in the in-sample revenue
  Top10 (the "target" segment).
- `rest_accepted_otif`: all other accepted orders.
- `all_otif`: all accepted orders.
- `accepted_backlog_units`: units still unshipped at the end of the week.
- `avg_delivery_day`, `pickers_per_dc`, `labor_minutes`,
  `pick_makespan_minutes`.
- Revenue is gross invoice revenue (`quantity × UnitPrice`), not margin.

## 4. Why this design

- **Same prepared flow**: treatment and control share the instance, arrival
  curve and accepted set where possible. This removes composition effects that
  would otherwise masquerade as policy effects.
- **Same accepted set**: for resource experiments (stock/capacity/transit) the
  ATP accept-all policy accepts all 400 orders, so the denominator is fixed.
- **Counterfactual lever**: each week changes one physical lever (stock, DC
  capacity, transit, local buffer) and keeps the rest fixed.
- **Null results are reported**: six scheduling/priority/promise/arrival levers
  did not move target OTIF; the reports keep those nulls instead of hiding them.

## 5. Known limitations

- One week, one layout, one shift pattern, 3 DCs. Absolute OTIF is not
  transferable to another week or company.
- No COGS, holding cost, expedite freight, overtime, door cost or returns.
- Target segment is the in-sample revenue Top10; it is a fixed cohort, not a
  causal segmentation.
- 30 seeds are deterministic; confidence intervals would overstate independence.
- The MILP is time-limited; small differences should not be over-interpreted.
- `dock_cost` is not comparable across door levels because blocked departures do
  not run.

## 6. Reproduction

```bash
PYTHONPATH=src;. python scripts/run_e2e_rolling_e2e.py
PYTHONPATH=src;. python scripts/run_e2e_stock.py
PYTHONPATH=src;. python scripts/run_e2e_dc_capacity.py
PYTHONPATH=src;. python scripts/run_e2e_transit.py
PYTHONPATH=src;. python scripts/run_e2e_local_stock.py
```

Each script writes a Markdown report and a JSON summary under `benchmarks/`.
