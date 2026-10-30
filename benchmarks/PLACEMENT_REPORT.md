# Fixed-total stock rebalance (Week 40)

- Generated: `2026-10-30T06:39:50.611175+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Flow: **5** weekdays | day 0: 66 | day 1: 73 | day 2: 68 | day 3: 85 | day 4: 108
- Seeds: **30** | placements **['baseline', 'balanced', 'rotterdam', 'london']** | daily MILP **8s/day**
- Conditions: **100% total stock**, **2× DC capacity**, **transit −1**, ATP accept-all. Only the DC stock shares change; every SKU's total units are held fixed.

## Rule

Week 39 could only close the target gap with 150% total stock, which confounds placement with more units. Week 40 fixes each SKU's total stock at 100% of demand and varies only the split across London / Rotterdam / Frankfurt. If target OTIF moves, local placement matters at fixed total; if it does not, the Week-39 gain came from the extra units, not from rebalancing.

## Results

| 布点 | DC 占比 | 库存单位 | 接受订单 | 接受 OTIF | 目标 OTIF | 非目标 OTIF | 全量 OTIF | 满足率 | 积压单位 | 平均交付日 |
|---|---|---|---|---|---|---|---|---|---|---|
| 基线 34/28/38 | 34%/28%/38% | 33,060 | 400.0 | 98.5% | 95.0% | 98.9% | 98.5% | 99.5% | 170 | 3.52 |
| 均衡 33/33/34 | 33%/33%/34% | 33,060 | 400.0 | 99.0% | 97.5% | 99.2% | 99.0% | 99.6% | 127 | 3.51 |
| Rotterdam 偏重 30/40/30 | 30%/40%/30% | 33,060 | 400.0 | 98.5% | 95.0% | 98.9% | 98.5% | 99.6% | 145 | 3.46 |
| London 偏重 40/24/36 | 40%/24%/36% | 33,060 | 400.0 | 98.8% | 97.5% | 98.9% | 98.8% | 99.5% | 176 | 3.53 |

## Findings

- **Baseline 34/28/38:** target OTIF 95.0%, rest 98.9%, all 98.5%, backlog 170 units.
- **Best fixed-total rebalance: 均衡 33/33/34** target 97.5% (+2.5 pp vs baseline), backlog 127 units.
- **Directional, but not robust.** The best arm is +2.5 pp, which is smaller than the 5.0 pp baseline spread across repeated runs; the arm ranking also flips between runs. Treat this as inconclusive, not as evidence that rebalancing closes the gap.
- **Baseline repeats matter:** the same 34/28/38 arm produced 92.5% / 95.0% / 97.5% target OTIF across repeated 400×30 runs. A 2–3 pp arm gap is inside that spread; only a gap larger than the spread should be read as a placement effect.
- **Total stock is held fixed per SKU.** The shares are applied to each SKU's total with a deterministic 0.75–1.25 jitter, so the arms differ in placement, not in the amount purchased.
- **All arms accept 400 orders** at 2× capacity and transit −1; this is not an acceptance-mix, throughput or carrier effect.
- **Four shares are not an optimizer.** The set (34/28/38, 33/33/34, 30/40/30, 40/24/36) is a small design, not a search over all feasible placements; a null does not prove every rebalance is useless.

## Limitations

- 只改 DC 库存占比，每个 SKU 的总库存固定在 100% 需求；不建模采购、在途、仓储成本、COGS、持有成本、过期/跌价。
- 库存占比只扫 4 个声明布点（34/28/38、33/33/34、30/40/30、40/24/36），不是全可行域上的优化；null 不等于所有重摆位都无效。
- 库存按 SKU 总量加确定性 0.75–1.25 jitter 分配，jitter 随 seed 固定；不同布点的总库存相同但 SKU×DC 分布仍受 jitter 影响。
- 所有臂 2× DC 产能、transit −1、ATP accept-all，接受集/需求分母相同；仍只有 1 个目标周、1 套布局/班次。
- 目标是样本内收入 Top10，不是外推客户价值；毛收入无退货/履约成本。
- 日滚动只允许当天发车（max_days=0），与单周基线的发车自由度不同；不跨周比较绝对 OTIF。
- CP-SAT 8s/day 时间受限：同一 34/28/38 baseline 的 400×30 重复运行得到 92.5/95.0/97.5 目标 OTIF（5pp 跨度），臂间 2–3pp 差异落在该波动内，不能当因果效应。
- 库存布点只做 4 个声明的 DC 占比，不是全可行域优化；排名在两次运行间翻转（Rotterdam 97.5→95.0），固定总量重摆位没有稳健收益。
