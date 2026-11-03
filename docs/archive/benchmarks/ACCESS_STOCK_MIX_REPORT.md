# Week 52: SKU mix dominates total stock

Week49-51 changed the stock basis and total together, so they could not say whether the service loss came from **less total stock** or from **the wrong SKU mix**. Week52 holds one factor fixed at a time, using the same 400 orders, seeds and DC shares.

| policy | stock units | coverage | target OTIF | all OTIF | backlog |
|---|---:|---:|---:|---:|---:|
| actual mix @ 46,281 | 46,281 | 139.99% | 100.0% | 99.9% | 0.7 |
| actual mix @ 44,824 | 44,824 | 135.58% | 100.0% | 99.9% | 1.3 |
| history mix @ 44,824 | 44,824 | 135.58% | 70.0% | 93.9% | 2,123.0 |
| history mix @ 46,288 | 46,288 | 140.01% | 72.5% | 95.2% | 1,980.0 |
| history mix @ 64,039 | 64,039 | 193.71% | 82.5% | 97.2% | 1,281.3 |

## Findings

- **At the same 44,824 units, SKU mix moves target by +30.0pp**: actual mix 100.0%/99.9% vs history mix 70.0%/93.9%; backlog 1.3 vs 2,123.0. This is the cleanest mix-only comparison.
- **At the actual 46,288 units, history mix still only reaches 72.5% target** vs actual mix 100.0% at 46,281. Adding 1,464 units to the wrong mix (44,824→46,288) buys +2.5pp target, +1.3pp all and cuts backlog 143; the total effect is second-order next to the ~28pp mix gap.
- **Even 64,039 units with the wrong mix is only 82.5% target**: history-200 has 19,215 more units than history-140 and buys +12.5pp, while the actual mix at 44,824 buys +30.0pp with no extra stock. SKU mix is the first-order lever.
- The actual-mix row is still an **oracle counterfactual**: it uses the target week's per-SKU demand. It is a decomposition tool, not a deployable policy. The deployable question is how to forecast the SKU mix; Week51 shows a 200-SKU LightGBM forecast is not enough.
- Stock shares and per-SKU jitter are unchanged; this isolates the per-SKU total, not DC placement. One target week, 400 invoices, 30 seeds × 3 repeats.
