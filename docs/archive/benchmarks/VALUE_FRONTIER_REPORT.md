# Value-threshold frontier (Week 29)

- Generated: `2026-10-29T12:53:39.304706+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Flow: **5** weekdays | day 0: 66 | day 1: 73 | day 2: 68 | day 3: 85 | day 4: 108
- Seeds: **30** | thresholds **[5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 40.0]** | daily MILP **8s/day**
- Demand revenue **170,467**; revenue coverage **100.0%**.

## Rule

Every point uses the same ATP ≤3-day cutoff. A long-promise order is kept only when its invoice revenue is at least the threshold quantile; the scan moves that bar from the top 5% down to accept-all. This is a threshold frontier, not a tuned optimum: all thresholds are in-sample quantiles on the same 400 orders, and no out-of-sample calibration is done.

## Results

| 阈值 | 价值门槛 | 接受订单 | 订单接单率 | 收入接单率 | 接受 OTIF | 原 SLA | 全量 OTIF | 流失收入 |
|---|---|---|---|---|---|---|---|---|
| 单周快照 | — | 400.0 | 100.0% | 100.0% | 54.0% | 54.0% | 54.0% | 0 |
| Top 0% | — | 279.0 | 69.8% | 50.6% | 100.0% | 98.6% | 69.8% | 84,127 |
| Top 5% | Top 5% (≥1,131) | 298.0 | 74.5% | 71.1% | 99.3% | 94.6% | 74.0% | 49,330 |
| Top 10% | Top 10% (≥791) | 309.0 | 77.3% | 77.9% | 99.0% | 93.9% | 76.5% | 37,595 |
| Top 15% | Top 15% (≥630) | 318.0 | 79.5% | 82.6% | 98.4% | 93.7% | 78.2% | 29,663 |
| Top 20% | Top 20% (≥546) | 333.0 | 83.2% | 87.3% | 97.9% | 91.9% | 81.5% | 21,650 |
| Top 25% | Top 25% (≥478) | 336.0 | 84.0% | 88.5% | 97.6% | 90.2% | 82.0% | 19,656 |
| Top 30% | Top 30% (≥435) | 344.0 | 86.0% | 90.4% | 96.2% | 89.0% | 82.8% | 16,388 |
| Top 40% | Top 40% (≥360) | 351.0 | 87.8% | 92.6% | 96.6% | 88.9% | 84.8% | 12,692 |
| 接受全部 | — | 400.0 | 100.0% | 100.0% | 94.5% | 83.7% | 94.5% | 0 |

## Findings

- **No override (Top 0%):** accepts 279.0 orders (69.8%), revenue 86,340 (50.6%), accepted OTIF 100.0%; lost revenue 84,127.
- **Top 0% → Top 5%:** revenue +20.4 pp, accepted OTIF -0.7 pp, all-order OTIF +4.2 pp.
- **Top 5% → Top 10%:** revenue +6.9 pp, accepted OTIF -0.3 pp, all-order OTIF +2.5 pp.
- **Top 10% → Top 15%:** revenue +4.7 pp, accepted OTIF -0.6 pp, all-order OTIF +1.7 pp.
- **Top 15% → Top 20%:** revenue +4.7 pp, accepted OTIF -0.5 pp, all-order OTIF +3.3 pp.
- **Top 20% → Top 25%:** revenue +1.2 pp, accepted OTIF -0.3 pp, all-order OTIF +0.5 pp.
- **Top 25% → Top 30%:** revenue +1.9 pp, accepted OTIF -1.4 pp, all-order OTIF +0.8 pp.
- **Top 30% → Top 40%:** revenue +2.2 pp, accepted OTIF +0.4 pp, all-order OTIF +2.0 pp.
- **Top 40% → 接受全部:** revenue +7.4 pp, accepted OTIF -2.1 pp, all-order OTIF +9.8 pp.
- **Best marginal trade-off:** Top 0% → Top 5% gains +20.4 pp revenue for -0.7 pp accepted OTIF (30.4 revenue points per OTIF point). Other segments can be better on absolute revenue or service, so this is a marginal reading, not a global optimum.
- **Accepted-OTIF frontier:** 8 of 10 points are non-dominated in (revenue, accepted OTIF): Top 0%, Top 5%, Top 10%, Top 15%, Top 20%, Top 25%, Top 40%, 接受全部.
- **Top 30% is dominated by Top 40% in this run.** Top 40% has 92.6% vs 90.4% revenue and 96.6% vs 96.2% accepted OTIF. The accepted-OTIF difference is only +0.4 pp, inside the usual solver spread, so the curve is not cleanly monotone; do not over-read a single threshold.
- **All-order OTIF is a coverage check, not a policy frontier.** It rises monotonically as fewer orders are rejected, so accept-all is the endpoint by construction. That is why the accepted-OTIF and original-SLA columns carry the trade-off; all-order OTIF tells you how much demand is served at all.
- **Marginal returns are not monotone.** The segment with the best revenue-per-OTIF ratio need not be the segment with the most absolute revenue, and accept-all can have the same accepted OTIF as a threshold while serving more orders. Read the table rather than assuming a single stylized knee; the threshold is a business choice, not a universal optimum.
- **Two service lenses disagree.** A threshold that looks good on accepted OTIF can look different on all-order OTIF, because a higher threshold rejects more orders. Read both, plus the original-SLA column, before choosing.
- **Accept-all is not on the same frontier dimension.** It has 100% revenue but a lower original SLA; a value threshold can buy original-SLA service by giving up some revenue. Neither is strictly better without a cost for lateness.
- **Thresholds are in-sample.** The scan is a sensitivity check on Week 28, not an out-of-sample policy. A live threshold would need historical revenue quantiles, drift monitoring, COGS/margin, capacity and customer value.

## Limitations

- 所有阈值都是本次 400 单的样本内收入分位数；前沿是敏感性检查，不是外推最优，也没有 train/test 切分。
- 收入来自 Online Retail II 发票行 `quantity × UnitPrice`，是毛收入，不是毛利/净利；没有 COGS、退货、履约成本、门位/发车成本与客户终身价值。
- 高价值破例只改“是否接受”，不预留库存、不提高分单/拣选/发车优先级；接受后的长承诺高价值订单仍可能迟到。
- 被拒订单按即期流失处理：不消耗库存、不重试、不转替代品、不计收入；接受池 OTIF/原 SLA 与全量 OTIF 是两个分母。
- ATP 只按当天开始时的在库量报价，不预留在途/未来/跨订单库存；旧订单不重报价，不模拟客户接受/拒绝/取消。
- 日滚动每天只允许当天发车（max_days=0）；单周基线允许 3 天且所有订单视作周一。
- 30 个种子在本配置下 OTIF/交付日/接单率完全相同，收入也是确定性的；不是 30 个独立需求样本。
- 只验证 1 周、1 套库存/布局/劳动力；MILP 同配置可差约 1–1.5pp。
