# Week 45: stock-total service frontier

Same 400 invoices, 30 seeds, 3 repeats, fixed placement arms and end-to-end configuration; only the per-SKU stock total changes. The extra stock is a scenario, not a costed replenishment plan.

## Baseline frontier

| stock | units | units vs 100% | target OTIF | all OTIF | backlog |
|---:|---:|---:|---:|---:|---:|
| 100% | 33,060 | +0 | 96.7% | 98.8% | 153.3 |
| 125% | 41,323 | +8,263 | 96.7% | 99.1% | 38.3 |
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
| 150% | baseline | 100.0% | 99.9% | 99.9% | 0.7 | — | 0 |
| 150% | access_history | 100.0% | 99.7% | 99.8% | 4.3 | 67.3% | 14,836 |
| 150% | access_history_load_covered | 100.0% | 99.9% | 99.9% | 0.7 | 26.1% | 0 |
| 150% | access_oracle | 99.2% | 99.8% | 99.8% | 3.7 | 93.5% | 12,372 |
| 150% | access_oracle_load_covered | 100.0% | 100.0% | 100.0% | 0.0 | 37.7% | 0 |

## Findings

- **125% stock** adds 8,263 units (+25.0%); baseline all-order OTIF 98.8% -> 99.1% (+0.25pp), target 96.7% -> 96.7%, backlog 153.3 -> 38.3.
- **150% stock** adds 16,535 units (+50.0%); baseline all-order OTIF 98.8% -> 99.9% (+1.08pp), target 96.7% -> 100.0%, backlog 153.3 -> 0.7.
- At **100% stock**, best all-order arm is `access_history_load_covered` (98.9% vs baseline 98.8%); it moves 383 units.
- At **125% stock**, best all-order arm is `access_oracle` (99.8% vs baseline 99.1%); it moves 10,293 units.
- At **150% stock**, best all-order arm is `access_oracle_load_covered` (100.0% vs baseline 99.9%); it moves 0 units.
- **The stock total dominates the placement effect.** The 100% -> 125% step cuts backlog far more than any 100%-stock placement arm; the 150% step reaches the OTIF ceiling. Non-oracle placement differences at fixed stock are about 0.1-0.3pp and were not robust in Weeks 41-44.
- **Extra stock is not free.** This report does not model purchase cost, holding cost, obsolescence, markdown, or working capital; the frontier is a service diagnostic, not an optimal inventory policy.
- `access_oracle` is an upper-bound arm: it sees the current week's orders and its transfer matrix, so it is not deployable.
- One target week, one layout/shift, one picker per DC; only the stock total changes, and the fixed-total placement still assumes a pre-week transfer with no lead time or cost.
