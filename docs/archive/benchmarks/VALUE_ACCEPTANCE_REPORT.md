# Value-tiered order acceptance (Week 28)

- Generated: `2026-10-29T12:16:16.115142+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Flow: **5** weekdays | day 0: 66 | day 1: 73 | day 2: 68 | day 3: 85 | day 4: 108
- Seeds: **30** | scenarios **['atp_all', 'atp_3', 'atp_3_top10', 'atp_3_top25', 'static_3', 'static_3_top10', 'static_3_top25']** | daily MILP **8s/day**
- Demand revenue **170,467**; revenue coverage **100.0%**.

## Rule

This extends Week 27 from measurement to policy. The base rule rejects a new order when its quoted promise exceeds the cutoff. The **value override** keeps a long-promise order when its invoice revenue is in the top X% of all sampled orders: `reject iff promised > cutoff AND revenue < threshold`. The threshold is computed once on the full order set, not per day, so the same revenue bar applies throughout the week. Rejected orders consume no stock, do not enter picking/dispatch, and remain in the all-order denominator. Revenue is gross invoice revenue, not margin.

## Results

| 场景 | 报价 | 上限 | 价值门槛 | 接受订单 | 订单接单率 | 收入接单率 | 接受 OTIF | 原 SLA | 全量 OTIF | 接受收入 | 流失收入 | 拒单均值 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 单周快照 · 固定承诺 | static | 全部 | — | 400.0 | 100.0% | 100.0% | 54.5% | 54.5% | 54.5% | 170,467 | 0 | 0 |
| ATP 接受全部 | atp | 全部 | — | 400.0 | 100.0% | 100.0% | 95.7% | 84.0% | 95.7% | 170,467 | 0 | 0 |
| ATP 只接 ≤3 天 | atp | 3 | — | 282.0 | 70.5% | 51.9% | 100.0% | 97.5% | 70.5% | 88,432 | 82,035 | 695 |
| ATP ≤3 天 + 收入 Top 10% 破例 | atp | 3 | Top 10% (≥791) | 309.0 | 77.3% | 78.2% | 99.0% | 94.2% | 76.5% | 133,323 | 37,144 | 408 |
| ATP ≤3 天 + 收入 Top 25% 破例 | atp | 3 | Top 25% (≥478) | 334.0 | 83.5% | 88.3% | 97.6% | 90.4% | 81.5% | 150,445 | 20,022 | 303 |
| static 只接 ≤3 天 | static | 3 | — | 320.0 | 80.0% | 82.0% | 87.5% | 87.5% | 70.0% | 139,740 | 30,727 | 384 |
| static ≤3 天 + 收入 Top 10% 破例 | static | 3 | Top 10% (≥791) | 326.0 | 81.5% | 85.7% | 88.3% | 88.3% | 72.0% | 146,168 | 24,299 | 328 |
| static ≤3 天 + 收入 Top 25% 破例 | static | 3 | Top 25% (≥478) | 340.0 | 85.0% | 90.7% | 87.1% | 87.1% | 74.0% | 154,627 | 15,841 | 264 |

## Findings

- **Base ATP ≤3 days:** accepts 282.0 orders (70.5%), revenue 88,432 (51.9%), accepted OTIF 100.0%; lost revenue 82,035.
- **ATP ≤3 天 + 收入 Top 10% 破例:** accepts 309.0 orders (+27.0 vs base), revenue 133,323 (+44,890), accepted OTIF 99.0% (-1.0 pp), all-order OTIF 76.5% (+6.0 pp).
- **ATP ≤3 天 + 收入 Top 25% 破例:** accepts 334.0 orders (+52.0 vs base), revenue 150,445 (+62,013), accepted OTIF 97.6% (-2.4 pp), all-order OTIF 81.5% (+11.0 pp).
- **static ≤3 天 + 收入 Top 10% 破例:** accepts 326.0 orders (+6.0 vs base), revenue 146,168 (+3.8 pp), accepted OTIF 88.3% (+0.8 pp), all-order OTIF 72.0% (+2.0 pp).
- **static ≤3 天 + 收入 Top 25% 破例:** accepts 340.0 orders (+20.0 vs base), revenue 154,627 (+8.7 pp), accepted OTIF 87.1% (-0.4 pp), all-order OTIF 74.0% (+4.0 pp).
- **Top 10% is the efficient point in this run.** It recovers +26.3 pp of revenue for -1.0 pp of accepted OTIF; all-order OTIF rises +6.0 pp because fewer orders are rejected. Top 25% recovers +36.4 pp but gives up -2.4 pp of accepted OTIF; the two bars trade revenue for accepted service, neither dominates.
- **Accepted OTIF and all-order OTIF move in opposite directions here.** Adding high-value long-promise orders raises coverage (fewer rejected, so all-order OTIF rises) while making the accepted pool harder to serve on time (accepted OTIF falls). A single OTIF number cannot describe this policy; quote both denominators.
- **The override is a trade, not a free lunch.** It buys back high-value orders that the cutoff would reject, but those orders have long promises; compare the revenue recovered with the accepted service lost, not just the headline revenue. In this run the all-order OTIF still improves because more orders are served at all.
- **A value bar is not a profit bar.** Invoice revenue has no COGS, returns, fulfillment cost or customer lifetime value; a high-revenue order can still be a low-margin order. This is a revenue-protection stress test, not an optimal policy.
- **The threshold is an in-sample quantile.** It is computed on the same 400 orders used for evaluation; a live policy would estimate it from history and would face drift. Top 10%/25% are scenario labels, not a tuned optimum.

## Limitations

- 价值阈值用本次 400 单的收入分位数（Top 10%/25%）计算，是样本内门槛，不是从历史外推的最优阈值；真实上线会面对收入漂移。
- 收入来自 Online Retail II 发票行 `quantity × UnitPrice`，是毛收入，不是毛利/净利；没有 COGS、退货、履约成本、门位/发车成本与客户终身价值。
- 高价值破例只改“是否接受”，不预留库存、不提高优先级；接受后的高价值长承诺订单仍与所有订单竞争分单/拣选/发车，可能迟到。
- 被拒订单按即期流失处理：不消耗库存、不重试、不转替代品、不计收入；接受池 OTIF/原 SLA 与全量 OTIF 是两个分母。
- ATP 只按当天开始时的在库量报价，不预留在途/未来/跨订单库存；旧订单不重报价，不模拟客户接受/拒绝/取消。
- 日滚动每天只允许当天发车（max_days=0）；单周基线允许 3 天且所有订单视作周一。
- 分单后不接收拣选/发车/门位失败的回写；补货是声明 order-up-to，1/2 天前置期。
- 30 个种子在本配置下 OTIF/交付日/接单率完全相同，收入也是确定性的；不是 30 个独立需求样本。
- 只验证 1 周、1 套库存/布局/劳动力；MILP 同配置可差约 1–1.5pp。
