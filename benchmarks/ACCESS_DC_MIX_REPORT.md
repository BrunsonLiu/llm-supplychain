# Week 55: Country-informed DC mix is a ~2pp trade, not a win

Week52 isolated SKU mix; Weeks53/54 tested SKU-share forecasts. Week55 uses the only observed spatial signal — destination country — to place each SKU's stock in the nearest DC, at the same 44,824 units. No target demand is used.

| policy | stock units | coverage | target OTIF | all OTIF | backlog |
|---|---:|---:|---:|---:|---:|
| actual mix @44,824 | 44,824 | 135.58% | 100.0% | 99.9% | 1.3 |
| history mean mix @44,824 | 44,824 | 135.58% | 70.0% | 93.9% | 2,123.0 |
| forecast mix @44,826 | 44,826 | 135.59% | 70.0% | 87.3% | 1,740.0 |
| last-week mix @44,833 | 44,833 | 135.61% | 49.2% | 84.6% | 4,787.3 |
| country-DC mix @44,824 | 44,824 | 135.58% | 71.7% | 92.0% | 2,151.7 |
| forecast point @55,776 | 55,776 | 168.71% | 85.0% | 91.6% | 944.7 |

## Findings

- **No win at the same total**: country-DC mix reaches 71.7% target and 92.0% all, vs history 70.0%/93.9%. Target +1.7pp, all −1.9pp, backlog +29. This is a trade near solver noise, not a robust improvement.
- **The country mix concentrates stock in one DC**: the baseline shares become roughly 90% / 7% / 2% because most historical demand maps to London. That helps some target orders and hurts the tail; it does not change the SKU composition that Week52 identified.
- **All simple structure signals now fail**: history 70.0%, LightGBM 70.0%, last week 49.2%, country-DC 71.7%; only actual target mix reaches 100.0%. The missing input is a real SKU×DC demand signal, not another placement heuristic.
- The forecast point at 55,776 units reaches 85.0% target but only 91.6% all; more total stock still does not repair the structure.
- Country→nearest-DC is a proxy, not observed DC demand: the actual DC demand is endogenous to the allocation MILP. One target week, 400 invoices, 30 seeds × 3 repeats.
