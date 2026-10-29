# High-value pick priority (Week 33)

- Generated: `2026-10-29T15:20:02.704243+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Flow: **5** weekdays | day 0: 66 | day 1: 73 | day 2: 68 | day 3: 85 | day 4: 108
- Seeds: **30** | scenarios **['atp_all', 'atp_3_top10_edf', 'atp_3_top10_pick', 'atp_3_top25_edf', 'atp_3_top25_pick']** | daily MILP **8s/day**
- Demand revenue **170,467**; revenue coverage **100.0%**.

## Rule

This is the Week-28/29 value override plus a **pick-wave priority**. When a picker is free, high-value invoices that have already arrived are released before lower-value invoices; EDF still orders the rest and still fills the wave by promise tier. It is not a promise relabel, an objective weight, or a dock sort: it changes the upstream pick sequence. It does not add a picker, a shift minute, or a unit of stock. EDF and priority replay the **same prepared flow**, so acceptance/allocation are held fixed.

## Results

| 场景 | 目标 | 接受订单 | 收入接单 | 接受 OTIF | 目标 OTIF | 非目标 OTIF | 原 SLA | 全量 OTIF | 发车 | 平均等车 |
|---|---|---|---|---|---|---|---|---|---|---|
| ATP 接受全部（对照） | Top 10% | 400.0 | 100.0% | 95.5% | 85.0% | 96.7% | 85.2% | 95.5% | 72.8 | 220 |
| Top10 破例 · EDF 拣选 | Top 10% | 310.0 | 78.3% | 98.7% | 90.0% | 100.0% | 93.9% | 76.5% | 51.1 | 222 |
| Top10 破例 · 高价值优先拣选 | Top 10% | 310.0 | 78.3% | 98.7% | 90.0% | 100.0% | 93.9% | 76.5% | 51.2 | 218 |
| Top25 破例 · EDF 拣选 | Top 25% | 335.0 | 88.3% | 97.6% | 92.0% | 100.0% | 90.7% | 81.7% | 58.5 | 223 |
| Top25 破例 · 高价值优先拣选 | Top 25% | 335.0 | 88.3% | 97.6% | 92.0% | 100.0% | 90.7% | 81.7% | 58.5 | 220 |

## Findings

- **Top 10% pick priority:** target OTIF 90.0% → 90.0% (+0.0 pp), rest 100.0% → 100.0% (+0.0 pp), all-order +0.0 pp; accepted +0 orders; mean wait 222 → 218 min.
- **Top 25% pick priority:** target OTIF 92.0% → 92.0% (+0.0 pp), rest 100.0% → 100.0% (+0.0 pp), all-order +0.0 pp; accepted +0 orders; mean wait 223 → 220 min.
- **Pick priority did not move target OTIF in this instance.** Mean dock wait fell 3–4 minutes, so the sequence really changed, but target/rest/all OTIF did not: the movable high-value tickets were already completing before their cutoffs, while the late target tickets were not in the available set that priority could pull forward (not yet arrived or still behind the same cutoff). Re-ordering available work changes the sequence, not the delivery day. This is a null result for this capacity, not evidence that pick priority never matters.
- **Pick priority is upstream of the levers already rejected.** Week 30 changed the promise label, Week 31 changed the allocation objective, and Week 32 changed dock loading. This week changes which available invoice gets the next pick minute. If target still does not move, the remaining constraint is physical pick/arrival capacity, not ordering.
- **It is still not extra capacity.** One picker and one shift are fixed; priority can only move pick minutes between orders. A real service fix would add a picker, extend the shift, reserve a dedicated high-value window, or expedite inbound stock.

## Limitations

- 拣选优先级只改“下一个空闲拣货员先拿哪张已到票据”，不增加拣货员、班次分钟或库存；它可以把拣选分钟从非目标转给目标，也可以反向。
- 收入来自 Online Retail II 发票行 `quantity × UnitPrice`，是毛收入，不是毛利/净利；没有 COGS、退货、履约成本、门位/发车成本与客户终身价值。
- 目标客群 Top10/Top25 由本次 400 单的收入分位数定义，是样本内分层；不是真实客户价值/毛利分层。
- 被拒订单按即期流失处理：不消耗库存、不重试、不转替代品、不计收入；接受池 OTIF/原 SLA 与全量 OTIF 是两个分母；同一 flow 下接单/收入按构造不变。
- ATP 只按当天开始时的在库量报价，不预留在途/未来/跨订单库存；旧订单不重报价，不模拟客户接受/拒绝/取消。
- 日滚动每天只允许当天发车（max_days=0）；单周基线允许 3 天且所有订单视作周一。
- 30 个种子在本配置下 OTIF/交付日/接单率完全相同；拣选优先级差异是确定性的排序效应，不是 30 个独立样本。
- 只验证 1 周、1 套库存/布局/劳动力；MILP/发车同配置可差约 1–1.5pp，小差异可能落在求解器噪声内。
