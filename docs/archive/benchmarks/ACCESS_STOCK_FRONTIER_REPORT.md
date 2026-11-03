# Week 45: stock-total service frontier

Same 400 invoices, 30 seeds, 3 repeats, fixed placement arms and end-to-end configuration; only the per-SKU stock total changes. Target week: **2011-11-28**. The extra stock is a scenario, not a costed replenishment plan.

## Baseline frontier

| stock | units | units vs 100% | target OTIF | all OTIF | backlog |
|---:|---:|---:|---:|---:|---:|
| 100% | 33,060 | +0 | 96.7% | 98.8% | 153.3 |
| 125% | 41,323 | +8,263 | 96.7% | 99.1% | 38.3 |
| 135% | 44,635 | +11,575 | 99.2% | 99.8% | 1.7 |
| 140% | 46,281 | +13,221 | 100.0% | 99.9% | 0.7 |
| 150% | 49,595 | +16,535 | 100.0% | 99.9% | 0.7 |

## All arms

| stock | policy | target | rest | all | backlog | coverage | moved |
|---:|---|---:|---:|---:|---:|---:|---:|
| 100% | baseline | 96.7% | 99.1% | 98.8% | 153.3 | — | 0 |
| 100% | access_history | 97.5% | 99.0% | 98.8% | 307.0 | 44.9% | 9,212 |
| 100% | access_history_load_covered | 96.7% | 99.2% | 98.9% | 148.0 | 26.1% | 383 |
| 100% | access_oracle | 96.7% | 97.4% | 97.3% | 180.3 | 63.1% | 8,222 |
| 100% | access_oracle_load_covered | 97.5% | 98.9% | 98.7% | 130.7 | 37.7% | 0 |
| 125% | baseline | 96.7% | 99.4% | 99.1% | 38.3 | — | 0 |
| 125% | access_history | 97.5% | 99.5% | 99.3% | 62.3 | 56.1% | 11,853 |
| 125% | access_history_load_covered | 96.7% | 99.5% | 99.2% | 41.7 | 26.1% | 0 |
| 125% | access_oracle | 99.2% | 99.9% | 99.8% | 2.7 | 78.3% | 10,293 |
| 125% | access_oracle_load_covered | 97.5% | 99.4% | 99.2% | 79.0 | 37.7% | 0 |
| 135% | baseline | 99.2% | 99.9% | 99.8% | 1.7 | — | 0 |
| 135% | access_history | 96.7% | 98.6% | 98.4% | 90.7 | 60.6% | 12,984 |
| 135% | access_history_load_covered | 100.0% | 99.5% | 99.6% | 5.0 | 26.1% | 0 |
| 135% | access_oracle | 99.2% | 99.9% | 99.8% | 8.3 | 84.4% | 11,116 |
| 135% | access_oracle_load_covered | 99.2% | 99.6% | 99.6% | 6.3 | 37.7% | 0 |
| 140% | baseline | 100.0% | 99.9% | 99.9% | 0.7 | — | 0 |
| 140% | access_history | 99.2% | 99.7% | 99.7% | 6.3 | 62.8% | 13,564 |
| 140% | access_history_load_covered | 100.0% | 99.9% | 99.9% | 0.3 | 26.1% | 0 |
| 140% | access_oracle | 99.2% | 99.9% | 99.8% | 0.7 | 87.4% | 11,532 |
| 140% | access_oracle_load_covered | 100.0% | 100.0% | 100.0% | 0.0 | 37.7% | 0 |
| 150% | baseline | 100.0% | 99.9% | 99.9% | 0.7 | — | 0 |
| 150% | access_history | 100.0% | 99.7% | 99.8% | 4.3 | 67.3% | 14,836 |
| 150% | access_history_load_covered | 100.0% | 99.9% | 99.9% | 0.7 | 26.1% | 0 |
| 150% | access_oracle | 99.2% | 99.8% | 99.8% | 3.7 | 93.5% | 12,372 |
| 150% | access_oracle_load_covered | 100.0% | 100.0% | 100.0% | 0.0 | 37.7% | 0 |

## Findings

- **125% stock** adds 8,263 units (+25.0%); baseline all-order OTIF 98.8% -> 99.1% (+0.25pp), target 96.7% -> 96.7%, backlog 153.3 -> 38.3.
- **135% stock** adds 11,575 units (+35.0%); baseline all-order OTIF 98.8% -> 99.8% (+1.00pp), target 96.7% -> 99.2%, backlog 153.3 -> 1.7.
- **140% stock** adds 13,221 units (+40.0%); baseline all-order OTIF 98.8% -> 99.9% (+1.08pp), target 96.7% -> 100.0%, backlog 153.3 -> 0.7.
- **150% stock** adds 16,535 units (+50.0%); baseline all-order OTIF 98.8% -> 99.9% (+1.08pp), target 96.7% -> 100.0%, backlog 153.3 -> 0.7.
- **100% -> 125% stock**: +8,263 units cuts backlog 153.3 -> 38.3 (72 units of stock per backlog unit); all-order 98.8% -> 99.1%, target 96.7% -> 96.7%.
- **125% -> 135% stock**: +3,312 units cuts backlog 38.3 -> 1.7 (90 units of stock per backlog unit); all-order 99.1% -> 99.8%, target 96.7% -> 99.2%.
- **135% -> 140% stock**: +1,646 units cuts backlog 1.7 -> 0.7 (1,646 units of stock per backlog unit); all-order 99.8% -> 99.9%, target 99.2% -> 100.0%.
- **140% -> 150% stock**: +3,314 units buys no further backlog reduction; all-order 99.9% -> 99.9%, target 100.0% -> 100.0%.
- **First tested point reaching ~100% target on baseline is 140% stock** (previous tested point 135% = 99.2%); this is a grid boundary, not an interpolated minimum.
- At **100% stock**, best all-order arm is `access_history_load_covered` (98.9% vs baseline 98.8%); it moves 383 units.
- At **125% stock**, best all-order arm is `access_oracle` (99.8% vs baseline 99.1%); it moves 10,293 units.
- At **135% stock**, best all-order arm is `baseline` (99.8% vs baseline 99.8%); it moves 0 units.
- At **140% stock**, best all-order arm is `access_oracle_load_covered` (100.0% vs baseline 99.9%); it moves 0 units.
- At **150% stock**, best all-order arm is `access_oracle_load_covered` (100.0% vs baseline 99.9%); it moves 0 units.
- **The stock total dominates the placement effect.** The first stock step cuts backlog far more than any 100%-stock placement arm; the highest tested step (150%) is at or near the OTIF ceiling. Non-oracle placement differences at fixed stock are about 0.1-0.3pp and were not robust in Weeks 41-44.
- **Extra stock is not free.** This report does not model purchase cost, holding cost, obsolescence, markdown, or working capital; the frontier is a service diagnostic, not an optimal inventory policy.
- `access_oracle` is an upper-bound arm: it sees the current week's orders and its transfer matrix, so it is not deployable.
- One target week, one layout/shift, one picker per DC; only the stock total changes, and the fixed-total placement still assumes a pre-week transfer with no lead time or cost.
