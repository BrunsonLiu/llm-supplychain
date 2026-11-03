# Inbound arrival expedite (Week 35)

- Generated: `2026-10-29T16:09:02.471889+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Flow: **5** weekdays | day 0: 66 | day 1: 73 | day 2: 68 | day 3: 85 | day 4: 108
- Seeds: **30** | scenarios **['atp_all_base', 'atp_3_top10_base', 'atp_3_top10_target_early', 'atp_3_top10_all_early', 'atp_3_top25_base', 'atp_3_top25_target_early', 'atp_3_top25_all_early']** | daily MILP **8s/day**
- Demand revenue **170,467**; revenue coverage **100.0%**.

## Rule

This is the Week-28/29 value override replayed with an **inbound arrival expedite** on the same prepared flow. In the target arm, every high-value order is marked onsite at minute zero instead of its sampled arrival; in the all-early arm, every open order is onsite at zero. Stock, promises, picker count, pick order and dock policy are unchanged, so only the arrival timestamp moves. It does not add inventory, labor, or a departure; an expedite cost is not modeled.

## Results

| 场景 | 目标 | 接受订单 | 收入接单 | 接受 OTIF | 目标 OTIF | 非目标 OTIF | 原 SLA | 全量 OTIF | 发车 | 平均等车 |
|---|---|---|---|---|---|---|---|---|---|---|
| ATP 接受全部 · 基准到达 | Top 10% | 400.0 | 100.0% | 95.0% | 82.5% | 96.4% | 84.5% | 95.0% | 72.9 | 221 |
| Top10 破例 · 基准到达 | Top 10% | 310.0 | 78.5% | 99.0% | 92.5% | 100.0% | 93.5% | 76.7% | 49.1 | 223 |
| Top10 破例 · 目标订单提前到达 | Top 10% | 310.0 | 78.5% | 99.0% | 92.5% | 100.0% | 93.5% | 76.7% | 46.0 | 218 |
| Top10 破例 · 全部订单提前到达 | Top 10% | 310.0 | 78.5% | 99.0% | 92.5% | 100.0% | 93.5% | 76.7% | 34.5 | 218 |
| Top25 破例 · 基准到达 | Top 25% | 335.0 | 88.3% | 97.9% | 93.0% | 100.0% | 90.7% | 82.0% | 59.5 | 223 |
| Top25 破例 · 目标订单提前到达 | Top 25% | 335.0 | 88.3% | 97.9% | 93.0% | 100.0% | 90.7% | 82.0% | 54.3 | 218 |
| Top25 破例 · 全部订单提前到达 | Top 25% | 335.0 | 88.3% | 97.9% | 93.0% | 100.0% | 90.7% | 82.0% | 44.6 | 215 |

## Findings

- **Top 10% target arrivals at 0:** target 92.5% → 92.5% (+0.0 pp), rest 100.0% → 100.0% (+0.0 pp), all-order +0.0 pp.
- **Top 10% all arrivals at 0:** target +0.0 pp, rest +0.0 pp, all-order +0.0 pp; departures 49.1 → 34.5. **The arrival manipulation was real:** departures fell from 49.1 to 34.5 (more consolidated waves), yet OTIF did not move; earlier freight changed batching, not service. The late orders are blocked by stock/allocation, not by their arrival clock.
- **Top 25% target arrivals at 0:** target 93.0% → 93.0% (+0.0 pp), rest 100.0% → 100.0% (+0.0 pp), all-order +0.0 pp.
- **Top 25% all arrivals at 0:** target +0.0 pp, rest +0.0 pp, all-order +0.0 pp; departures 59.5 → 44.6. **The arrival manipulation was real:** departures fell from 59.5 to 44.6 (more consolidated waves), yet OTIF did not move; earlier freight changed batching, not service. The late orders are blocked by stock/allocation, not by their arrival clock.
- **Arrival timing alone does not close the gap.** Even with every open order onsite at minute zero, aggregate/target OTIF does not improve materially; the remaining constraint is stock or the value/ATP rule, not the arrival clock.
- **Target-only expedite is a sharper test than all-early.** If target rises while rest is unchanged, the target's late orders were genuinely waiting for inbound; if target does not rise, the late target orders were already onsite or blocked by stock, not by their arrival stamp.
- **This is not free.** Expediting inbound has a freight/premium cost that this report does not model; it also assumes the warehouse can receive the order at minute zero.

## Limitations

- 提前到达只改入库时间戳（目标/全部订单在班次开始即 onsite），不增加库存、拣货员、门位或发车；不模拟加急运费/入库装卸能力/供应商配合。
- 收入来自 Online Retail II 发票行 `quantity × UnitPrice`，是毛收入，不是毛利/净利；没有 COGS、退货、履约成本、门位/发车成本与客户终身价值。
- 目标客群 Top10/Top25 由本次 400 单收入分位数定义，是样本内分层；不是真实客户价值/毛利分层。
- 被拒订单按即期流失处理：不消耗库存、不重试、不转替代品、不计收入；同一 flow 下接单/收入按构造不变。
- ATP 只按当天开始时在库量报价，不预留在途/未来/跨订单库存；旧订单不重报价，不模拟客户接受/拒绝/取消。
- 日滚动每天只允许当天发车（max_days=0）；单周基线允许 3 天且所有订单视作周一。
- 30 个种子在本配置下 OTIF/交付日/接单率完全相同；提前到达差异是确定性的到达效应，不是 30 个独立样本。
- 只验证 1 周、1 套库存/布局/班次；全部提前是上界式反事实，真实加急不可能让所有订单同时到仓；MILP/发车同配置可差约 1–1.5pp。
