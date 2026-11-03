# Week 49: stock basis — target demand vs prior history

The earlier stock frontier (Weeks 45-48) sets each SKU's stock to a percentage of the **target week's sampled demand**. That is an oracle-stock upper bound. Week49 uses the same 400 orders but sets stock from the mean of the **prior 6 weeks** by SKU, scaled by the sampled-order/historical-invoice ratio. No target demand is used.

| stock basis | factor | stock units | coverage | target OTIF | all OTIF | backlog |
|---|---:|---:|---:|---:|---:|---:|
| actual-demand | 140% | 46,281 | 139.99% | 100.0% | 99.9% | 0.7 |
| history-mean | 140% | 44,824 | 135.58% | 70.0% | 93.9% | 2,123.0 |
| history-mean | 180% | 57,626 | 174.31% | 79.2% | 96.7% | 1,448.0 |
| history-mean | 200% | 64,039 | 193.71% | 82.5% | 97.2% | 1,281.3 |

## Findings

- **Same 140% factor, very different service**: actual-demand 46,281 units delivers 100.0%/99.9%/0.7; prior-history 44,824 units delivers 70.0%/93.9%/2,123.0. The stock totals are close, but the SKU mix is not: the target week's demand is concentrated in different SKUs.
- **More aggregate history stock does not close the gap**: history 200% holds 64,039 units (194% of target demand) but reaches only 82.5%/97.2% with 1,281.3 backlog. Aggregate overstock cannot fix per-SKU mix error.
- **The Weeks 45-48 frontier is an oracle-stock upper bound.** Those results answer what happens if stock is already in the right SKU proportions; they overstate deployable service. The cost decision and seed-stability layers inherit that caveat.
- The history policy is a **naive 6-week mean**, not a forecast model: no seasonality, promotion, lead time, replenishment or substitution. It is a lower bound on what a real forecast could do, and a useful warning against treating the frontier as deployable.
- One target week, 400 invoices, 30 seeds × 3 repeats, fixed layout/shift; stock shares and jitter are unchanged.
