# Week 46: stock-service cost decision

The measured 100%/125%/135%/140%/150% stock frontier is turned into a decision with one declared weekly holding cost and a stockout penalty expressed as a multiple of that holding cost. This is a post-hoc decision layer, not a new demand or inventory model.

Weekly holding cost: **€0.10/unit-week**. Total cost = holding cost × stock units + stockout penalty × backlog units. The stockout penalty is `ratio × holding cost`.

## Efficient frontier

| stock | units | target | all | backlog |
|---:|---:|---:|---:|---:|
| 100% | 33,060 | 96.7% | 98.8% | 153.3 |
| 125% | 41,323 | 96.7% | 99.1% | 38.3 |
| 135% | 44,635 | 99.2% | 99.8% | 1.7 |
| 140% | 46,281 | 100.0% | 99.9% | 0.7 |

## Cheapest tested stock level by penalty/holding ratio

| penalty/holding | chosen stock | units | target | all | backlog | cost |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 100% | 33,060 | 96.7% | 98.8% | 153.3 | €3,306.00 |
| 50 | 100% | 33,060 | 96.7% | 98.8% | 153.3 | €4,072.67 |
| 75 | 125% | 41,323 | 96.7% | 99.1% | 38.3 | €4,419.80 |
| 100 | 135% | 44,635 | 99.2% | 99.8% | 1.7 | €4,480.17 |
| 200 | 135% | 44,635 | 99.2% | 99.8% | 1.7 | €4,496.83 |
| 1000 | 135% | 44,635 | 99.2% | 99.8% | 1.7 | €4,630.17 |
| 2000 | 140% | 46,281 | 100.0% | 99.9% | 0.7 | €4,761.43 |

## Break-even ratios

A step is worth taking when the stockout penalty per backlog unit is above `added stock / backlog cut` times the holding cost:

| step | added units | backlog cut | break-even penalty/holding |
|---|---:|---:|---:|
| 100% → 125% | +8,263 | 115.0 | **71.9** |
| 125% → 135% | +3,312 | 36.7 | **90.3** |
| 135% → 140% | +1,646 | 1.0 | **1,646.0** |

## Reading

- The answer is **not a universal stock level**. The cheapest tested point moves right as the stockout penalty rises, and the break-even ratios below are the decision boundaries. A tested point is dropped when another point has no more stock and no worse service; on the full Week45 grid this removed 150% in favour of 140%.
- The break-even numbers are the useful output: they translate the service frontier into a cost-penalty condition instead of an arbitrary `hold more` recommendation.
- Holding cost is applied to the whole week's stock and backlog is a proxy for shortage; there is no lost-sales, goodwill, markdown, working-capital or lead-time cost. Cost levels are illustrative, not accounting numbers.
- One target week, one layout/shift, 30 seeds × 3 repeats, fixed demand; this is a post-hoc read of the stock frontier in the same report, not a multi-week inventory policy.
