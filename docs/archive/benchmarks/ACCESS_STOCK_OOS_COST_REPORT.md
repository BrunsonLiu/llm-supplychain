# Week 47: stock-service cost decision

The measured 100%/125%/140% stock frontier is turned into a decision with one declared weekly holding cost and a stockout penalty expressed as a multiple of that holding cost. This is a post-hoc decision layer, not a new demand or inventory model.

Weekly holding cost: **€0.10/unit-week**. Total cost = holding cost × stock units + stockout penalty × backlog units. The stockout penalty is `ratio × holding cost`.

## Efficient frontier

| stock | units | target | all | backlog |
|---:|---:|---:|---:|---:|
| 100% | 32,609 | 96.7% | 98.8% | 172.0 |
| 125% | 40,757 | 97.5% | 99.5% | 28.3 |
| 140% | 45,652 | 100.0% | 99.9% | 0.7 |

## Cheapest tested stock level by penalty/holding ratio

| penalty/holding | chosen stock | units | target | all | backlog | cost |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 100% | 32,609 | 96.7% | 98.8% | 172.0 | €3,260.90 |
| 50 | 100% | 32,609 | 96.7% | 98.8% | 172.0 | €4,120.90 |
| 75 | 125% | 40,757 | 97.5% | 99.5% | 28.3 | €4,288.20 |
| 100 | 125% | 40,757 | 97.5% | 99.5% | 28.3 | €4,359.03 |
| 200 | 140% | 45,652 | 100.0% | 99.9% | 0.7 | €4,578.53 |
| 1000 | 140% | 45,652 | 100.0% | 99.9% | 0.7 | €4,631.87 |
| 2000 | 140% | 45,652 | 100.0% | 99.9% | 0.7 | €4,698.53 |

## Break-even ratios

A step is worth taking when the stockout penalty per backlog unit is above `added stock / backlog cut` times the holding cost:

| step | added units | backlog cut | break-even penalty/holding |
|---|---:|---:|---:|
| 100% → 125% | +8,148 | 143.7 | **56.7** |
| 125% → 140% | +4,895 | 27.7 | **176.9** |

## Reading

- The answer is **not a universal stock level**. The cheapest tested point moves right as the stockout penalty rises, and the break-even ratios below are the decision boundaries. A tested point is dropped when another point has no more stock and no worse service; on the full Week45 grid this removed 150% in favour of 140%.
- The break-even numbers are the useful output: they translate the service frontier into a cost-penalty condition instead of an arbitrary `hold more` recommendation.
- Holding cost is applied to the whole week's stock and backlog is a proxy for shortage; there is no lost-sales, goodwill, markdown, working-capital or lead-time cost. Cost levels are illustrative, not accounting numbers.
- One target week, one layout/shift, 30 seeds × 3 repeats, fixed demand; this is a post-hoc read of the stock frontier in the same report, not a multi-week inventory policy.
