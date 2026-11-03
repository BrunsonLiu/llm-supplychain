# High-value promise upgrade (Week 30)

- Generated: `2026-10-29T13:31:18.089685+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Flow: **5** weekdays | day 0: 66 | day 1: 73 | day 2: 68 | day 3: 85 | day 4: 108
- Seeds: **30** | scenarios **['atp_all', 'atp_3', 'atp_3_top10', 'atp_3_top10_up3', 'atp_3_top25', 'atp_3_top25_up3']** | daily MILP **8s/day**
- Demand revenue **170,467**; revenue coverage **100.0%**.

## Rule

This is the Week-28/29 value override plus a **promise upgrade**. A new high-value order is still accepted despite a long ATP quote, but its quote is capped at 3 days. The cap is not a capacity reservation: it only changes the order's deadline so it competes for stock/picking earlier. If the inventory or labor is not there, the earlier promise can fail. The target segment is Top10 for Top10 scenarios and Top25 for Top25 scenarios; the rest is everyone else.

## Results

| 场景 | 目标 | 接受订单 | 订单接单 | 收入接单 | 接受 OTIF | 目标接受 OTIF | 目标全量 OTIF | 非目标接受 OTIF | 原 SLA | 全量 OTIF | 流失收入 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ATP 接受全部（对照） | Top 10% | 400.0 | 100.0% | 100.0% | 74.0% | 67.5% | 67.5% | 74.7% | 66.3% | 74.0% | 0 |
| ATP 只接 ≤3 天（对照） | Top 10% | 286.0 | 71.5% | 52.8% | 100.0% | 100.0% | 20.0% | 100.0% | 98.3% | 71.5% | 80,515 |
| ATP ≤3 天 + Top10 破例 | Top 10% | 314.0 | 78.5% | 79.4% | 99.0% | 92.5% | 92.5% | 100.0% | 94.9% | 77.8% | 35,137 |
| ATP ≤3 天 + Top10 破例 + 承诺升到3天 | Top 10% | 310.0 | 77.5% | 78.2% | 98.1% | 87.5% | 87.5% | 99.6% | 93.5% | 76.0% | 37,085 |
| ATP ≤3 天 + Top25 破例 | Top 25% | 337.0 | 84.3% | 88.7% | 97.9% | 93.0% | 93.0% | 100.0% | 90.5% | 82.5% | 19,234 |
| ATP ≤3 天 + Top25 破例 + 承诺升到3天 | Top 25% | 337.0 | 84.3% | 88.8% | 96.4% | 88.0% | 88.0% | 100.0% | 89.0% | 81.2% | 19,167 |

## Findings

- **ATP ≤3 天 + Top10 破例 + 承诺升到3天:** accepts 310.0 orders (-4.0 vs no upgrade), revenue 78.2% (-1.1 pp); target accepted OTIF 87.5% (-5.0 pp), rest accepted OTIF 99.6% (-0.4 pp), all-order OTIF 76.0% (-1.7 pp).
- **ATP ≤3 天 + Top25 破例 + 承诺升到3天:** accepts 337.0 orders (+0.0 vs no upgrade), revenue 88.8% (+0.0 pp); target accepted OTIF 88.0% (-5.0 pp), rest accepted OTIF 100.0% (+0.0 pp), all-order OTIF 81.2% (-1.2 pp).
- **A promise upgrade is not a capacity reservation.** It changes the deadline and therefore the allocation/dispatch priority, but it does not create stock, pickers or dock minutes. If target OTIF rises and rest OTIF falls, the gain is redistribution; if target OTIF does not rise, the constraint was inventory/labor, not the promise date.
- **The upgrade made the target worse, not better.** Top10 target accepted OTIF 92.5% → 87.5% (-5.0 pp), while the rest is roughly flat (100.0% → 99.6%). With no added stock, pickers or doors, a 3-day promise mostly reclassifies the same later delivery as late; it does not buy service.
- **Top25 loses the same 5 pp on its target.** Target accepted OTIF 93.0% → 88.0%; rest 100.0% → 100.0%; accepted revenue is essentially unchanged. The tighter promise is a service-level accounting change, not a capacity increase.
- **Revenue is not fully insulated.** For Top25 the accepted set/revenue is essentially unchanged; for Top10 the upgrade accepts 4 fewer orders and loses 1.1 pp of revenue because earlier deadlines change stock consumption and subsequent ATP quotes. The upgrade can feed back into acceptance; it is not a pure relabeling.
- **This is deliberate over-promising.** A 3-day quote can violate ATP. The point is to measure the cost of protecting high-value service, not to claim that the upgrade is feasible in a real ATP system.
- **Read the target and rest segments together.** Accepted OTIF alone can stay flat while the target improves and everyone else pays for it.

## Limitations

- 承诺升级是故意的过度承诺（over-promise）：把高价值新订单的报价压到 3 天，可能违反 ATP；它只改截止期/优先级，不预留库存、不增加拣选/门位产能。
- 收入来自 Online Retail II 发票行 `quantity × UnitPrice`，是毛收入，不是毛利/净利；没有 COGS、退货、履约成本、门位/发车成本与客户终身价值。
- 目标客群 Top10/Top25 由本次 400 单的收入分位数定义，是样本内分层；不是真实客户价值/毛利分层。
- 被拒订单按即期流失处理：不消耗库存、不重试、不转替代品、不计收入；接受池 OTIF/原 SLA 与全量 OTIF 是两个分母。
- ATP 只按当天开始时的在库量报价，不预留在途/未来/跨订单库存；旧订单不重报价，不模拟客户接受/拒绝/取消。
- 日滚动每天只允许当天发车（max_days=0）；单周基线允许 3 天且所有订单视作周一。
- 30 个种子在本配置下 OTIF/交付日/接单率完全相同；升级后的服务差异是确定性的分配/排序效应，不是 30 个独立样本。
- 只验证 1 周、1 套库存/布局/劳动力；MILP 同配置可差约 1–1.5pp。
