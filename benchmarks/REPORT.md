# Demand forecasting benchmark (Online Retail II)

- Generated: `2026-10-27T17:44:00.867725+00:00`
- Dataset: `online_retail_ii` (104 weeks, 200 SKUs)
- Period: `2009-12-07` to `2011-11-28`
- Backtest: 4 rolling folds x horizon 13, min train 52 weeks
- Best model by WMAPE: **lightgbm** (73.34%)

## Overall metrics

| rank | model | n | wmape | bias | mae | rmse | rmsse |
|---|---|---|---|---|---|---|---|
| 1 | lightgbm | 9685 | 73.34% | 8.53% | 120.65 | 249.61 | 1.53 |
| 2 | ma8 | 9685 | 80.68% | 8.27% | 132.72 | 280.04 | 1.66 |
| 3 | croston_sba | 9685 | 83.02% | 11.73% | 136.58 | 422.00 | 1.75 |
| 4 | ma4 | 9685 | 85.22% | 15.10% | 140.20 | 294.91 | 1.69 |
| 5 | seasonal_naive | 9685 | 86.75% | 2.13% | 142.71 | 313.63 | 2.02 |
| 6 | naive | 9685 | 89.44% | 0.30% | 147.13 | 318.45 | 1.77 |
| 7 | holt | 9685 | 97.10% | 30.84% | 159.73 | 343.58 | 1.84 |

## Aggregate volume (planning-level)

Weekly demand summed across the selected SKUs. This is the volume view used for warehouse capacity and labor planning; SKU-level errors partially cancel.

| model | weeks | wmape | bias |
|---|---|---|---|
| seasonal_naive | 52 | 21.08% | 2.13% |
| croston_sba | 52 | 29.66% | 11.73% |
| lightgbm | 52 | 31.93% | 8.53% |
| ma8 | 52 | 39.51% | 8.27% |
| ma4 | 52 | 45.09% | 15.10% |
| holt | 52 | 50.05% | 30.84% |
| naive | 52 | 53.27% | 0.30% |

## WMAPE by horizon bucket

| model | 1-4 | 5-8 | 9-13 |
|---|---|---|---|
| croston_sba | 83.26% | 85.69% | 80.96% |
| holt | 88.98% | 100.26% | 100.69% |
| lightgbm | 74.21% | 75.15% | 71.42% |
| ma4 | 83.80% | 87.75% | 84.45% |
| ma8 | 79.68% | 82.78% | 79.90% |
| naive | 89.63% | 90.25% | 88.73% |
| seasonal_naive | 83.19% | 92.48% | 85.24% |

## WMAPE by fold

| model | fold | wmape | bias | rmsse |
|---|---|---|---|---|
| croston_sba | 0 | 120.63% | 76.75% | 2.195 |
| croston_sba | 1 | 71.84% | -0.38% | 1.432 |
| croston_sba | 2 | 65.04% | 4.94% | 1.365 |
| croston_sba | 3 | 81.47% | -10.31% | 1.882 |
| holt | 0 | 216.53% | 182.96% | 2.877 |
| holt | 1 | 75.16% | -0.41% | 1.149 |
| holt | 2 | 70.43% | 12.97% | 1.005 |
| holt | 3 | 65.03% | -17.66% | 1.799 |
| lightgbm | 0 | 124.19% | 87.89% | 2.196 |
| lightgbm | 1 | 67.42% | -12.82% | 1.166 |
| lightgbm | 2 | 63.85% | 2.15% | 0.937 |
| lightgbm | 3 | 56.37% | -15.36% | 1.545 |
| ma4 | 0 | 172.99% | 140.01% | 2.418 |
| ma4 | 1 | 65.29% | -19.77% | 1.109 |
| ma4 | 2 | 68.19% | 12.86% | 0.983 |
| ma4 | 3 | 62.54% | -26.40% | 1.857 |
| ma8 | 0 | 150.95% | 112.69% | 2.283 |
| ma8 | 1 | 64.75% | -15.21% | 1.127 |
| ma8 | 2 | 68.85% | 3.68% | 0.978 |
| ma8 | 3 | 61.39% | -28.40% | 1.910 |
| naive | 0 | 180.29% | 140.03% | 2.598 |
| naive | 1 | 68.62% | -24.78% | 1.187 |
| naive | 2 | 67.55% | -27.23% | 1.062 |
| naive | 3 | 68.65% | -39.80% | 1.863 |
| seasonal_naive | 0 | 92.13% | -11.25% | 2.318 |
| seasonal_naive | 1 | 84.32% | -5.77% | 1.596 |
| seasonal_naive | 2 | 91.92% | 14.82% | 1.396 |
| seasonal_naive | 3 | 82.35% | 6.44% | 2.511 |

## LightGBM feature importance (latest fold, top 15)

| feature | gain |
|---|---|
| price | 19673432.576 |
| roll_mean_4 | 13108395.916 |
| sku_mean | 9137949.977 |
| target_week_of_year | 8475334.902 |
| roll_mean_8 | 6056261.813 |
| zero_streak | 5851420.414 |
| price_lag_4 | 4628298.800 |
| seasonal_lag_53 | 2295449.404 |
| sku_nonzero_rate | 1855445.141 |
| sku_cv | 1696954.029 |
| target_cos_woy | 1645553.801 |
| lag_1 | 1641544.733 |
| target_sin_woy | 1606571.280 |
| seasonal_lag_52 | 1369164.733 |
| seasonal_lag_51 | 1356743.952 |

## Training time

| model | mean_seconds | total_seconds |
|---|---|---|
| croston_sba | 0.030 | 0.110 |
| holt | 4.070 | 16.270 |
| lightgbm | 11.140 | 44.570 |
| ma4 | 0.020 | 0.090 |
| ma8 | 0.020 | 0.090 |
| naive | 0.020 | 0.080 |
| seasonal_naive | 0.020 | 0.080 |

## Notes

- WMAPE and bias are demand-weighted; RMSSE uses the M5 seasonal-naive scale.
- Baselines include naive, seasonal-naive, moving averages, Croston-SBA (intermittent), and Holt. Holt-Winters needs two full seasonal cycles, which this two-year dataset cannot provide at every fold, so it is not in the default lineup.
- LightGBM is a single global direct multi-horizon model; lag and rolling features are shifted by one week to prevent leakage.
- Same-week-last-year anchors are added as features only when they have training coverage in that fold, so trees never split on untrained missing values.
- SKUs with fewer than 13 non-zero weeks in a fold's training window are excluded from that fold; new-product launches need a separate process.
- A fold whose test window crosses a holiday or level shift is dominated by that shift; read the by-fold table before comparing models.
- Online Retail II contains demand, price, and calendar only. Inventory, lead time, and warehouse cost are introduced later as an explicit assumption layer.
