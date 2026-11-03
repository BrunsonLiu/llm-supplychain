# Week 47: stock-total service frontier

Same 400 invoices, 30 seeds, 3 repeats, fixed placement arms and end-to-end configuration; only the per-SKU stock total changes. Target week: **2011-11-21**. The extra stock is a scenario, not a costed replenishment plan.

## Baseline frontier

| stock | units | units vs 100% | target OTIF | all OTIF | backlog |
|---:|---:|---:|---:|---:|---:|
| 100% | 32,609 | +0 | 96.7% | 98.8% | 172.0 |
| 125% | 40,757 | +8,148 | 97.5% | 99.5% | 28.3 |
| 140% | 45,652 | +13,043 | 100.0% | 99.9% | 0.7 |

## All arms

| stock | policy | target | rest | all | backlog | coverage | moved |
|---:|---|---:|---:|---:|---:|---:|---:|
| 100% | baseline | 96.7% | 99.1% | 98.8% | 172.0 | — | 0 |
| 100% | access_history | 97.5% | 99.3% | 99.1% | 144.0 | 45.1% | 9,029 |
| 100% | access_history_load_covered | 97.5% | 99.3% | 99.1% | 69.3 | 26.1% | 509 |
| 100% | access_oracle | 100.0% | 98.8% | 98.9% | 21.3 | 71.6% | 9,996 |
| 100% | access_oracle_load_covered | 97.5% | 98.9% | 98.8% | 154.3 | 46.3% | 1,751 |
| 125% | baseline | 97.5% | 99.7% | 99.5% | 28.3 | — | 0 |
| 125% | access_history | 97.5% | 99.8% | 99.6% | 31.7 | 56.3% | 11,538 |
| 125% | access_history_load_covered | 97.5% | 99.9% | 99.7% | 58.0 | 26.1% | 0 |
| 125% | access_oracle | 100.0% | 99.7% | 99.8% | 11.0 | 86.6% | 12,013 |
| 125% | access_oracle_load_covered | 97.5% | 99.8% | 99.6% | 51.3 | 46.3% | 1,068 |
| 140% | baseline | 100.0% | 99.9% | 99.9% | 0.7 | — | 0 |
| 140% | access_history | 100.0% | 99.7% | 99.8% | 6.3 | 63.1% | 13,165 |
| 140% | access_history_load_covered | 100.0% | 100.0% | 100.0% | 0.0 | 26.1% | 0 |
| 140% | access_oracle | 100.0% | 99.9% | 99.9% | 0.3 | 95.7% | 13,280 |
| 140% | access_oracle_load_covered | 100.0% | 99.9% | 99.9% | 0.7 | 46.3% | 894 |

## Findings

- **125% stock** adds 8,148 units (+25.0%); baseline all-order OTIF 98.8% -> 99.5% (+0.67pp), target 96.7% -> 97.5%, backlog 172.0 -> 28.3.
- **140% stock** adds 13,043 units (+40.0%); baseline all-order OTIF 98.8% -> 99.9% (+1.08pp), target 96.7% -> 100.0%, backlog 172.0 -> 0.7.
- **100% -> 125% stock**: +8,148 units cuts backlog 172.0 -> 28.3 (57 units of stock per backlog unit); all-order 98.8% -> 99.5%, target 96.7% -> 97.5%.
- **125% -> 140% stock**: +4,895 units cuts backlog 28.3 -> 0.7 (177 units of stock per backlog unit); all-order 99.5% -> 99.9%, target 97.5% -> 100.0%.
- **First tested point reaching ~100% target on baseline is 140% stock** (previous tested point 125% = 97.5%); this is a grid boundary, not an interpolated minimum.
- At **100% stock**, best all-order arm is `access_history` (99.1% vs baseline 98.8%); it moves 9,029 units.
- At **125% stock**, best all-order arm is `access_oracle` (99.8% vs baseline 99.5%); it moves 12,013 units.
- At **140% stock**, best all-order arm is `access_history_load_covered` (100.0% vs baseline 99.9%); it moves 0 units.
- **The stock total dominates the placement effect.** The first stock step cuts backlog far more than any 100%-stock placement arm; the highest tested step (140%) is at or near the OTIF ceiling. Non-oracle placement differences at fixed stock are about 0.1-0.3pp and were not robust in Weeks 41-44.
- **Extra stock is not free.** This report does not model purchase cost, holding cost, obsolescence, markdown, or working capital; the frontier is a service diagnostic, not an optimal inventory policy.
- `access_oracle` is an upper-bound arm: it sees the current week's orders and its transfer matrix, so it is not deployable.
- One target week, one layout/shift, one picker per DC; only the stock total changes, and the fixed-total placement still assumes a pre-week transfer with no lead time or cost.
