# High-value allocation priority (Week 31)

- Generated: `2026-10-29T14:05:44.664967+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Flow: **5** weekdays | day 0: 66 | day 1: 73 | day 2: 68 | day 3: 85 | day 4: 108
- Seeds: **30** | scenarios **['atp_all', 'atp_3', 'atp_3_top10_p1', 'atp_3_top10_p3', 'atp_3_top10_p10', 'atp_3_top25_p1', 'atp_3_top25_p3', 'atp_3_top25_p10']** | daily MILP **8s/day**
- Demand revenue **170,467**; revenue coverage **100.0%**.

## Rule

The accepted set is the Week-28/29 value override: long-promise orders are kept only when their invoice revenue clears the top-quantile bar. The new lever is the **daily allocation objective**: high-value orders get an `order_priority` multiplier on unmet and late penalties, so the CP-SAT solver gives them scarce stock first. The multiplier does not reserve stock, add capacity, or change the quoted promise. The target segment is Top10 for Top10 scenarios and Top25 for Top25 scenarios; the rest is everyone else.

## Results

| 场景 | 权重 | 目标 | 接受订单 | 收入接单 | 接受 OTIF | 目标 OTIF | 非目标 OTIF | 原 SLA | 全量 OTIF | 流失收入 |
|---|---|---|---|---|---|---|---|---|---|---|
| ATP 接受全部（对照） | 1× | Top 10% | 400.0 | 100.0% | 95.3% | 85.0% | 96.4% | 82.3% | 95.3% | 0 |
| ATP 只接 ≤3 天（对照） | 1× | Top 10% | 279.0 | 51.4% | 100.0% | 100.0% | 100.0% | 96.1% | 69.8% | 82,787 |
| Top10 破例 · 优先级 1× | 1× | Top 10% | 313.0 | 79.0% | 99.0% | 92.5% | 100.0% | 93.6% | 77.5% | 35,765 |
| Top10 破例 · 优先级 3× | 3× | Top 10% | 309.0 | 78.2% | 98.7% | 92.5% | 99.6% | 92.2% | 76.2% | 37,138 |
| Top10 破例 · 优先级 10× | 10× | Top 10% | 312.0 | 78.6% | 99.0% | 92.5% | 100.0% | 91.3% | 77.3% | 36,416 |
| Top25 破例 · 优先级 1× | 1× | Top 25% | 338.0 | 88.8% | 97.9% | 93.0% | 100.0% | 90.5% | 82.8% | 19,028 |
| Top25 破例 · 优先级 3× | 3× | Top 25% | 335.0 | 88.4% | 97.6% | 92.0% | 100.0% | 90.4% | 81.7% | 19,712 |
| Top25 破例 · 优先级 10× | 10× | Top 25% | 336.0 | 88.6% | 97.6% | 93.0% | 99.6% | 91.1% | 82.0% | 19,515 |

## Findings

- **Top 10% no-priority baseline:** accepts 313.0 orders, revenue 79.0%, target OTIF 92.5%, rest 100.0%, all-order 77.5%.
- **Top10 破例 · 优先级 3×:** target OTIF 92.5% → 92.5% (+0.0 pp), rest 100.0% → 99.6% (-0.4 pp), all-order -1.3 pp, revenue -0.8 pp, accepted -4.0 orders.
- **Top10 破例 · 优先级 10×:** target OTIF 92.5% → 92.5% (+0.0 pp), rest 100.0% → 100.0% (+0.0 pp), all-order -0.2 pp, revenue -0.4 pp, accepted -1.0 orders.
- **Top 25% no-priority baseline:** accepts 338.0 orders, revenue 88.8%, target OTIF 93.0%, rest 100.0%, all-order 82.8%.
- **Top25 破例 · 优先级 3×:** target OTIF 93.0% → 92.0% (-1.0 pp), rest 100.0% → 100.0% (+0.0 pp), all-order -1.0 pp, revenue -0.4 pp, accepted -3.0 orders.
- **Top25 破例 · 优先级 10×:** target OTIF 93.0% → 93.0% (+0.0 pp), rest 100.0% → 99.6% (-0.4 pp), all-order -0.8 pp, revenue -0.3 pp, accepted -2.0 orders.
- **Priority did not buy service in this instance.** Top10 target OTIF stayed at 92.5% under 3× and 10×, while accepted orders fell and revenue dropped 0.4–0.8 pp; Top25 stayed at 92–93%. The binding constraint is not who gets allocatable stock: the target orders that missed were not waiting on a stock-allocation choice, or their lateness is arrival/picking/dispatch timing. A higher penalty cannot fix a non-stock constraint.
- **Priority can only redistribute, not create, service.** If target OTIF rises and rest OTIF falls, the high-value gain is paid for by other orders. If both rise, the solver found a better allocation; if target does not rise, the binding constraint was not stock ordering.
- **The price of protection is visible in the rest column.** A team can choose a weight, but it should read the target/rest pair and the revenue/acceptance feedback rather than a single aggregate OTIF.
- **Weights are objective units, not promises.** A 3× weight says a high-value order's unmet/late penalty is three times as costly; it does not guarantee stock, and it does not change the customer-facing quote.
- **Prioritisation can feed back into acceptance.** Earlier/high-priority stock use changes later ATP quotes, so the accepted set and revenue can move; do not assume revenue is fixed.

## Limitations

- 优先级只改分单 MILP 的缺货/迟到权重，不预留库存、不增加拣选/门位产能；它能重分配稀缺库存，不能创造服务。
- 收入来自 Online Retail II 发票行 `quantity × UnitPrice`，是毛收入，不是毛利/净利；没有 COGS、退货、履约成本、门位/发车成本与客户终身价值。
- 目标客群 Top10/Top25 由本次 400 单的收入分位数定义，是样本内分层；不是真实客户价值/毛利分层。
- 被拒订单按即期流失处理：不消耗库存、不重试、不转替代品、不计收入；接受池 OTIF/原 SLA 与全量 OTIF 是两个分母。
- ATP 只按当天开始时的在库量报价，不预留在途/未来/跨订单库存；旧订单不重报价，不模拟客户接受/拒绝/取消。
- 日滚动每天只允许当天发车（max_days=0）；单周基线允许 3 天且所有订单视作周一。
- 30 个种子在本配置下 OTIF/交付日/接单率完全相同；优先级差异是确定性的分配效应，不是 30 个独立样本。
- 只验证 1 周、1 套库存/布局/劳动力；MILP 同配置可差约 1–1.5pp，优先级权重的小差异可能落在求解器噪声内。
