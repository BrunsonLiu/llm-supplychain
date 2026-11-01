# Week 53: Forecast SKU mix does not beat history

Week52 showed SKU structure is the first-order lever. Week53 asks whether LightGBM's **predicted SKU shares** are a better structure than the historical mean, holding the total at the historical level. No target demand is used.

| policy | stock units | coverage | target OTIF | all OTIF | backlog |
|---|---:|---:|---:|---:|---:|
| actual mix @44,824 | 44,824 | 135.58% | 100.0% | 99.9% | 1.3 |
| history mix @44,824 | 44,824 | 135.58% | 70.0% | 93.9% | 2,123.0 |
| forecast mix @44,826 | 44,826 | 135.59% | 70.0% | 87.3% | 1,740.0 |
| forecast mix @51,221 | 51,221 | 154.93% | 74.2% | 90.0% | 1,261.3 |
| history mix @64,039 | 64,039 | 193.71% | 82.5% | 97.2% | 1,281.3 |
| forecast point @55,776 | 55,776 | 168.71% | 85.0% | 91.6% | 944.7 |

## Findings

- **At ~44,824 units, forecast shares do not improve target at all**: forecast mix 70.0% vs history 70.0% (same within rounding), while all-service falls from 93.9% to 87.3%. The predicted composition is not a better composition.
- **More units on the forecast mix still buy little**: forecast-160 mix at 51,221 units reaches 74.2% target, +4.2pp over 44,826 for +6,395 units; history needs +19,215 units to reach 82.5%. Neither is close to the actual mix at 44,824 (100.0%).
- **Week51's target lift is not explained by a better mix**: forecast point-160 holds 55,776 units and reaches 85.0% target, vs 74.2% for the share-160 at 51,221. The point policy also has ~4,555 more units and a different allocation, so this is not a clean level effect; it is consistent with the lift coming from more total stock, not from a better composition. All-service is still worse than history-200 (97.2% vs 91.6%).
- The forecast covers only 200 main SKUs; missing SKUs use history shares. The total is still historical, so this isolates composition, not the forecast level.
- Actual mix is still an oracle decomposition row. One target week, 400 invoices, 30 seeds × 3 repeats; no retraining, no SKU×DC model.
