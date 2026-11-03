# Week 50: safety stock does not close the oracle gap

Week49 showed that target-demand stock is an oracle upper bound. Week50 tests whether a standard order-up-to safety-stock rule closes the gap: per SKU, stock = `mean + z × std` of the prior 6 weekly demands, scaled to the sampled order count. No target demand is used.

| policy | parameter | stock units | coverage | target OTIF | all OTIF | backlog |
|---|---:|---:|---:|---:|---:|---:|
| oracle target-demand | 140% | 46,281 | 139.99% | 100.0% | 99.9% | 0.7 |
| history mean | 140% | 44,824 | 135.58% | 70.0% | 93.9% | 2,123.0 |
| history mean | 200% | 64,039 | 193.71% | 82.5% | 97.2% | 1,281.3 |
| mean + zσ safety | z=1.645 | 61,537 | 186.14% | 77.5% | 96.6% | 1,081.7 |
| mean + zσ safety | z=2.326 | 73,748 | 223.07% | 79.2% | 97.1% | 879.7 |

## Findings

- **Even a 99% safety factor is far below oracle service**: 73,748 units (223% of target demand) reaches only 79.2% target/97.1% all with 879.7 backlog. The oracle 140% policy holds 46,281 units (140%) and reaches 100.0%/99.9%.
- **Safety stock is not a free substitute for the right SKU mix**: z=1.645 holds 61,537 units and reaches 77.5% target, while the simpler history-200% policy holds 64,039 units and reaches 82.5%. Safety allocates stock by demand volatility, not by the target week's SKU ranking.
- **More safety stock improves backlog more than target OTIF**: z=2.326 holds 73,748 units vs history-200% 64,039, cuts backlog 1,281.3→879.7, but target OTIF moves 82.5%→79.2% (slightly down) and all OTIF 97.2%→97.1% (slightly down). Aggregate safety stock buys tail coverage, not the specific high-demand SKUs that drive target OTIF.
- **The binding constraint is per-SKU/DC demand location, not total units.** A deployable policy needs a forecast of the target-week SKU mix, not a larger buffer on the historical mix.
- Safety stock uses a normal approximation on 6 weekly observations; it has no seasonality, promotion, lead time, replenishment, substitution or DC-level forecast. It is a negative result about this simple policy, not a claim that all safety stock is useless.
- One target week, 400 invoices, 30 seeds × 3 repeats, fixed layout/shift; the oracle row is still not executable.
