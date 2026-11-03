# High-value dispatch priority (Week 32)

- Generated: `2026-10-29T14:54:59.844848+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Flow: **5** weekdays | day 0: 66 | day 1: 73 | day 2: 68 | day 3: 85 | day 4: 108
- Seeds: **30** | scenarios **['atp_all', 'atp_3_top10_edf', 'atp_3_top10_priority', 'atp_3_top25_edf', 'atp_3_top25_priority']** | daily MILP **8s/day**
- Demand revenue **170,467**; revenue coverage **100.0%**.

## Rule

This is the Week-28/29 value override plus a **dispatch priority**. Within a lane, tickets of the target high-value orders are loaded before lower-priority tickets; ties still use EDF. This is an actual loading-sequence change, not a promise relabel or an objective weight. It does not add a door, a picker, or a departure. EDF and priority replay the **same prepared flow**, so acceptance/allocation are held fixed and only the loading order changes. The target is Top10 for Top10 scenarios and Top25 for Top25 scenarios; the rest is everyone else.

## Results

| 场景 | 目标 | 接受订单 | 收入接单 | 接受 OTIF | 目标 OTIF | 非目标 OTIF | 原 SLA | 全量 OTIF | 发车 | 平均等车 |
|---|---|---|---|---|---|---|---|---|---|---|
| ATP 接受全部（对照） | Top 10% | 400.0 | 100.0% | 93.8% | 85.0% | 94.7% | 82.3% | 93.8% | 72.3 | 221 |
| Top10 破例 · EDF 发车 | Top 10% | 311.0 | 78.6% | 99.0% | 92.5% | 100.0% | 91.3% | 77.0% | 52.1 | 222 |
| Top10 破例 · 高价值发车插队 | Top 10% | 311.0 | 78.6% | 99.0% | 92.5% | 100.0% | 91.3% | 77.0% | 52.1 | 222 |
| Top25 破例 · EDF 发车 | Top 25% | 336.0 | 88.8% | 97.3% | 91.0% | 100.0% | 89.9% | 81.7% | 57.6 | 221 |
| Top25 破例 · 高价值发车插队 | Top 25% | 336.0 | 88.8% | 97.3% | 91.0% | 100.0% | 89.9% | 81.7% | 57.6 | 221 |

## Findings

- **Top 10% priority:** target OTIF 92.5% → 92.5% (+0.0 pp), rest 100.0% → 100.0% (+0.0 pp), all-order +0.0 pp, revenue +0.0 pp, accepted +0.0 orders; departures 52.1 → 52.1, mean wait 222 → 222 min.
- **Top 25% priority:** target OTIF 91.0% → 91.0% (+0.0 pp), rest 100.0% → 100.0% (+0.0 pp), all-order +0.0 pp, revenue +0.0 pp, accepted +0.0 orders; departures 57.6 → 57.6, mean wait 221 → 221 min.
- **The priority was a no-op in this instance.** EDF and priority produced identical accepted orders, target/rest/all OTIF, and departure counts. Every lane batch fits the departure capacity, so reordering tickets changes only the sequence **inside** the same batch, not which tickets leave or on which day. This is a valid null result: dispatch priority can only matter when a batch/door constraint actually selects a subset. It says nothing about a capacity-constrained dock, where the same manipulation could help target and hurt rest.
- **Dispatch priority can only reorder existing capacity.** If target OTIF rises and rest falls, the gain is zero-sum: the high-value parcel took an earlier departure from a low-value parcel. If both rise, the priority also improved lane packing; if target does not rise, dock ordering was not the binding constraint.
- **A real loading priority is not free.** Moving a target ticket ahead can push another order past its promise even though every parcel was picked. Read target and rest together, not just aggregate OTIF.
- **It is still not extra capacity.** The priority changes who gets the next departure slot; it does not create another slot, door, picker, or unit of stock.

## Limitations

- 发车插队只改同一车道内的装车顺序（高价值优先，其次 EDF），不增加发车、门位、拣选或库存；它可以把迟到从非目标转移到目标，也可以反向。
- 收入来自 Online Retail II 发票行 `quantity × UnitPrice`，是毛收入，不是毛利/净利；没有 COGS、退货、履约成本、门位/发车成本与客户终身价值。
- 目标客群 Top10/Top25 由本次 400 单的收入分位数定义，是样本内分层；不是真实客户价值/毛利分层。
- 被拒订单按即期流失处理：不消耗库存、不重试、不转替代品、不计收入；接受池 OTIF/原 SLA 与全量 OTIF 是两个分母。
- ATP 只按当天开始时的在库量报价，不预留在途/未来/跨订单库存；旧订单不重报价，不模拟客户接受/拒绝/取消。
- 日滚动每天只允许当天发车（max_days=0）；单周基线允许 3 天且所有订单视作周一。
- 30 个种子在本配置下 OTIF/交付日/接单率完全相同；插队差异是确定性的排序效应，不是 30 个独立样本。
- 只验证 1 周、1 套库存/布局/劳动力；MILP/发车同配置可差约 1–1.5pp，小差异可能落在求解器噪声内。
