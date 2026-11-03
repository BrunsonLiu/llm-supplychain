# Week 51: LightGBM forecast stock — target gain within noise, tail loss

Week49/50 showed that oracle and naive history/safety policies do not transfer. Week51 uses the existing rolling-origin LightGBM predictions (`benchmarks/backtest_predictions.csv`) for the target week, calibrated only on the prior weeks' actual/predicted totals. No target demand is used.

| policy | parameter | stock units | coverage | target OTIF | all OTIF | backlog |
|---|---:|---:|---:|---:|---:|---:|
| oracle target-demand | 140% | 46,281 | 139.99% | 100.0% | 99.9% | 0.7 |
| history mean | 140% | 44,824 | 135.58% | 70.0% | 93.9% | 2,123.0 |
| history mean | 200% | 64,039 | 193.71% | 82.5% | 97.2% | 1,281.3 |
| mean + zσ safety | z=2.326 | 73,748 | 223.07% | 79.2% | 97.1% | 879.7 |
| forecast-140 | 140% | 48,806 | 147.63% | 75.0% | 88.3% | 1,407.3 |
| forecast-160 | 160% | 55,776 | 168.71% | 85.0% | 91.6% | 944.7 |
| forecast-160-replicate | 160% | 55,776 | 168.71% | 81.7% | 91.1% | 1,004.3 |

## Findings

- **Forecast shifts stock toward predicted demand, at the cost of tail service**: forecast-140 holds 48,806 units and reaches 75.0% target/88.3% all; forecast-160 holds 55,776 units and reaches 85.0%/91.6%. Relative to history 200% (64,039 units, 82.5%/97.2%), forecast-160 changes target by +2.5pp and all-service by -5.7pp.
- **The target gain is within same-stock rerun noise**: the forecast-160 replicate holds the same 55,776 units but reaches 81.7% target vs 85.0% (3.3pp). The nominal +2.5pp target advantage over history-200 is therefore not robust; the all-service loss (−5.7pp) is larger and consistent.
- **The 200-SKU forecast and its allocation error still cost tail service**: the forecast only covers 200 main SKUs, and the missing-SKU fill did not add units in this sample (same stock total). Even without missing SKUs, forecast allocation lowers all-service by ~5.7pp vs history-200.
- **Still far from oracle**: forecast-160 reaches 85.0% target, while oracle 140% with 46,281 units reaches 100.0%. The binding gap is per-SKU/DC demand location, not the choice of a slightly better aggregate forecast.
- The forecast is not retrained or tuned here; it is the existing rolling-origin LightGBM artifact. It uses prior weeks only, but the prediction is a full-week total scaled to the sampled order count, and the calibration is a single aggregate ratio rather than a per-SKU bias correction.
- One target week, 400 invoices, 30 seeds × 3 repeats, fixed layout/shift; oracle remains non-executable. The forecast result does not establish a multi-week policy.
