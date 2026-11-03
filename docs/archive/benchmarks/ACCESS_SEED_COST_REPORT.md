# Week 48: seed-level stock-cost stability

The cost decision in Weeks 46-47 uses one mean frontier. This layer recomputes the cheapest tested stock level for every `(repeat, seed)` cell, so the decision is reported as a distribution rather than a single point. It reuses the existing runs; no new simulation.

Weekly holding cost: **€0.10/unit-week**; stockout penalty = `ratio × holding cost`; 90 repeat/seed cells per dataset.

## In-sample Week45 (100%/125%/135%/140%/150%)

| penalty/holding | n | seed choices | modal | mean factor | mean-data choice |
|---:|---:|---|---:|---:|---:|
| 0 | 90 | 100%:100% | 100% | 100.00% | 100% |
| 50 | 90 | 100%:100% | 100% | 100.00% | 100% |
| 75 | 90 | 100%:33% / 125%:67% | 125% | 116.67% | 125% |
| 100 | 90 | 125%:67% / 135%:33% | 125% | 128.33% | 135% |
| 200 | 90 | 135%:100% | 135% | 135.00% | 135% |
| 1000 | 90 | 135%:67% / 140%:33% | 135% | 136.67% | 135% |
| 2000 | 90 | 135%:67% / 140%:33% | 135% | 136.67% | 140% |

## Out-of-sample Week47 (100%/125%/140%)

| penalty/holding | n | seed choices | modal | mean factor | mean-data choice |
|---:|---:|---|---:|---:|---:|
| 0 | 90 | 100%:100% | 100% | 100.00% | 100% |
| 50 | 90 | 100%:67% / 125%:33% | 100% | 108.33% | 100% |
| 75 | 90 | 125%:100% | 125% | 125.00% | 125% |
| 100 | 90 | 125%:100% | 125% | 125.00% | 125% |
| 200 | 90 | 140%:100% | 140% | 140.00% | 140% |
| 1000 | 90 | 140%:100% | 140% | 140.00% | 140% |
| 2000 | 90 | 140%:100% | 140% | 140.00% | 140% |

## Findings

- **in-sample at p/h=100**: modal 125% (mean factor 128.33%); distribution 125%:67% / 135%:33%; unanimous=False.
- **out-of-sample at p/h=100**: modal 125% (mean factor 125.00%); distribution 125%:100%; unanimous=True.
- The mean-data decision is the Week46/47 table; the seed distribution shows whether that decision is a sharp boundary or a near-tie. Disagreement means the threshold should be read as a region, not a single percentage.
- The 90 cells vary arrival/pick noise, not demand: demand, stock shares, layout and promises are fixed. This is decision uncertainty, not out-of-sample demand evidence.
- Holding cost is illustrative and backlog is a shortage proxy; no lost-sales, goodwill, markdown, working-capital or lead-time cost.
