# Revenue-weighted order acceptance (Week 27)

- Generated: `2026-10-29T11:40:54.570947+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Flow: **5** weekdays | day 0: 66 | day 1: 73 | day 2: 68 | day 3: 85 | day 4: 108
- Seeds: **30** | scenario **['static_all', 'atp_all', 'atp_3', 'atp_2', 'static_3']** | daily MILP **8s/day**
- Revenue coverage: **100.0%** of orders matched to a positive invoice revenue; total demand revenue **170,467**.

## Rule

This is the Week-24 acceptance rule with a third denominator. A new order whose quoted promise exceeds the cutoff is rejected; rejected orders consume no stock, do not enter picking/dispatch, and remain in the all-order denominator. Revenue is the real invoice line revenue (`quantity × unit price`) sampled from Online Retail II. `收入接单率` is accepted revenue / all-demand revenue; it is **not** profit, because COGS, returns and fulfillment cost are not modeled.

## Results

| 场景 | 报价 | 上限 | 接受订单 | 订单接单率 | 接受单位 | 流失单位 | 接受收入 | 流失收入 | 收入接单率 | 接单 OTIF | 原 SLA | 全量 OTIF |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 单周快照 · 固定承诺 | static | 全部 | 400.0 | 100.0% | 33,060 | 0 | 170,467 | 0 | 100.0% | 49.5% | 49.5% | 49.5% |
| 每日补货 · 接受全部 | static | 全部 | 400.0 | 100.0% | 33,060 | 0 | 170,467 | 0 | 100.0% | 87.5% | 87.5% | 87.5% |
| 每日补货 · ATP 接受全部 | atp | 全部 | 400.0 | 100.0% | 33,060 | 0 | 170,467 | 0 | 100.0% | 95.3% | 85.2% | 95.3% |
| 每日补货 · ATP 只接 ≤3 天 | atp | 3 | 285.0 | 71.2% | 14,345 | 18,715 | 89,441 | 81,026 | 52.5% | 100.0% | 98.2% | 71.2% |
| 每日补货 · ATP 只接 ≤2 天 | atp | 2 | 0.0 | 0.0% | 0 | 33,060 | 0 | 170,467 | 0.0% | 0.0% | 0.0% | 0.0% |
| 每日补货 · 固定承诺只接 ≤3 天 | static | 3 | 320.0 | 80.0% | 27,420 | 5,640 | 139,740 | 30,727 | 82.0% | 87.5% | 87.5% | 70.0% |

## Findings

- **每日补货 · ATP 只接 ≤3 天:** order acceptance 71.2%, unit acceptance 43.4%, revenue acceptance 52.5% (-18.8 pp vs order rate). Accepted revenue 89,441; lost revenue 81,026. Average revenue per accepted order 314 vs lost order 705.
- **每日补货 · ATP 只接 ≤2 天 accepts nothing.** Revenue acceptance 0.0%, lost revenue 170,467; this is an empty denominator, not a service success.
- **每日补货 · 固定承诺只接 ≤3 天:** order acceptance 80.0%, unit acceptance 82.9%, revenue acceptance 82.0% (+2.0 pp vs order rate). Accepted revenue 139,740; lost revenue 30,727. Average revenue per accepted order 437 vs lost order 384.
- **ATP accept-all is the revenue benchmark.** It accepts all 400 orders, revenue 170,467, accepted OTIF 95.3% and original SLA 85.2%. Any cutoff below must be judged against the revenue it removes, not only the accepted OTIF.
- **ATP ≤3 days: order acceptance overstates revenue retention.** Orders 71.2% but revenue only 52.5%; average accepted order 314 vs rejected 705. The cutoff keeps small high-price-per-unit orders and drops large high-revenue baskets. The 100% accepted OTIF is bought with 47.5% of demand revenue, not 29% of orders.
- **Static ≤3 days: the opposite selection.** Orders 80.0%, units 82.9%, revenue 82.0%: rejected orders are lower-value on average, so revenue is retained better than order count suggests. But accepted OTIF is still 87.5%—the same as accept-all—so this is revenue loss without a service gain.
- **Order, unit and revenue acceptance can diverge.** If revenue acceptance is lower than order acceptance, the rejected tail is high-value; if higher, the policy keeps high-value orders. Neither direction is “free” — the lost revenue column is the price of the smaller accepted pool.
- **Revenue is not margin.** The data has no COGS, slotting cost or fulfillment cost per order, so a high-revenue order is not necessarily a high-profit order; this is a revenue-at-risk lens, not an NPV/profit claim.

## Limitations

- 收入来自 Online Retail II 发票行 `quantity × UnitPrice`，是毛收入，不是毛利/净利；没有 COGS、退货、履约成本、门位/发车成本与客户终身价值。
- 被拒订单按即期流失处理：不消耗库存、不重试、不转替代品、不计收入；收入接单率以全部需求收入为分母。
- 接受池 OTIF/原 SLA 只对接受池计算；全量 OTIF 把被拒订单当未履约；订单/单位/收入三个接单率必须一起看。
- ATP 只按当天开始时的在库量报价，不预留在途/未来/跨订单库存；旧订单不重报价，不模拟客户接受/拒绝/取消。
- 日滚动每天只允许当天发车（max_days=0）；单周基线允许 3 天且所有订单视作周一。
- 分单后不接收拣选/发车/门位失败的回写；补货是声明 order-up-to，1/2 天前置期，不做预测/MOQ/供应商产能/DC 调拨。
- 30 个种子在本配置下 OTIF/交付日完全相同，接受率与收入也是确定性的；不是 30 个独立需求样本。
- 收入覆盖按订单发票匹配，未匹配的行按 0 收入；只验证 1 周、1 套库存/布局/劳动力。
