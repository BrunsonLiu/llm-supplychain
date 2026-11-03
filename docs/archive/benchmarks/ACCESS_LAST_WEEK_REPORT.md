# Week 54: Last-week SKU mix is worse than the mean

Week53 showed LightGBM's predicted SKU shares do not beat the historical mean. Week54 tests the simplest deployable alternative: use **last week's actual SKU shares**, at the same historical total. No target demand is used.

| policy | stock units | coverage | target OTIF | all OTIF | backlog |
|---|---:|---:|---:|---:|---:|
| actual mix @44,824 | 44,824 | 135.58% | 100.0% | 99.9% | 1.3 |
| history mean mix @44,824 | 44,824 | 135.58% | 70.0% | 93.9% | 2,123.0 |
| forecast mix @44,826 | 44,826 | 135.59% | 70.0% | 87.3% | 1,740.0 |
| last-week mix @44,833 | 44,833 | 135.61% | 49.2% | 84.6% | 4,787.3 |
| forecast point @55,776 | 55,776 | 168.71% | 85.0% | 91.6% | 944.7 |

## Findings

- **Naive persistence fails badly**: at ~44,824 units, last-week mix reaches 49.2% target and 84.6% all, vs history mean 70.0%/93.9%. Backlog rises from 2,123 to 4,787.
- **Only actual demand shares reach 100.0%**; forecast shares reach 70.0% and last-week shares 49.2%. Neither simple signal is a usable substitute for the target-week composition.
- **More total stock does not repair the bad mix**: the forecast point policy at 55,776 units reaches 85.0% target, but its all-service (91.6%) is still below history. The structure problem is not a level problem.
- Last week is a single adjacent week and the target week is a seasonal transition; the negative result is a stress case, not a general claim that persistence never works.
- Actual mix is an oracle decomposition row. One target week, 400 invoices, 30 seeds × 3 repeats; no promotion/new-product signal.
