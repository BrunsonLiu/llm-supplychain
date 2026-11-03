# Extra pick capacity (Week 34)

- Generated: `2026-10-29T15:46:34.991682+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Flow: **5** weekdays | day 0: 66 | day 1: 73 | day 2: 68 | day 3: 85 | day 4: 108
- Seeds: **30** | scenarios **['atp_all_1p', 'atp_all_2p', 'atp_3_top10_1p', 'atp_3_top10_2p', 'atp_3_top10_2p_pick', 'atp_3_top25_1p', 'atp_3_top25_2p', 'atp_3_top25_2p_pick']** | daily MILP **8s/day**
- Demand revenue **170,467**; revenue coverage **100.0%**.

## Rule

This is the Week-28/29 value override replayed with **one vs two pickers per DC** on the same prepared flow. Acceptance and stock allocation are held fixed; only the labor resource changes. In the third arm, the second picker is combined with the Week-33 high-value pick priority, so the test separates 'more capacity' from 'same capacity, different order'. It does not add a door, stock, or a departure, and it does not model a picker wage.

## Results

| 场景 | 目标 | 拣货员/DC | 接单率 | 收入接单 | 接受 OTIF | 目标 OTIF | 非目标 OTIF | 原 SLA | 全量 OTIF | 发车 | 拣选分钟 | 拣选跨度合计 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ATP 接受全部 · 1 拣货员 | Top 10% | 1 | 100.0% | 100.0% | 93.8% | 80.0% | 95.3% | 80.8% | 93.8% | 77.0 | 3,160 | 2208 |
| ATP 接受全部 · 2 拣货员 | Top 10% | 2 | 100.0% | 100.0% | 93.8% | 80.0% | 95.3% | 80.8% | 93.8% | 76.7 | 3,363 | 2202 |
| Top10 破例 · 1 拣货员 EDF | Top 10% | 1 | 77.3% | 78.1% | 99.0% | 92.5% | 100.0% | 91.6% | 76.5% | 48.2 | 2,266 | 2024 |
| Top10 破例 · 2 拣货员 EDF | Top 10% | 2 | 77.3% | 78.1% | 99.0% | 92.5% | 100.0% | 91.6% | 76.5% | 48.2 | 2,379 | 2015 |
| Top10 破例 · 2 拣货员 + 优先拣选 | Top 10% | 2 | 77.3% | 78.1% | 99.0% | 92.5% | 100.0% | 91.6% | 76.5% | 48.2 | 2,375 | 2015 |
| Top25 破例 · 1 拣货员 EDF | Top 25% | 1 | 84.3% | 88.6% | 97.6% | 93.0% | 99.6% | 88.1% | 82.3% | 58.5 | 2,625 | 2137 |
| Top25 破例 · 2 拣货员 EDF | Top 25% | 2 | 84.3% | 88.6% | 97.6% | 93.0% | 99.6% | 88.1% | 82.3% | 58.3 | 2,775 | 2132 |
| Top25 破例 · 2 拣货员 + 优先拣选 | Top 25% | 2 | 84.3% | 88.6% | 97.6% | 93.0% | 99.6% | 88.1% | 82.3% | 58.3 | 2,767 | 2132 |

## Findings

- **Accept-all 1 → 2 pickers:** accepted OTIF 93.8% → 93.8% (+0.0 pp), target 80.0% → 80.0%, rest 95.3% → 95.3%; pick makespan 2208 → 2202 min.
- **Top 10% 1 → 2 pickers:** target 92.5% → 92.5% (+0.0 pp), rest 100.0% → 100.0% (+0.0 pp), all-order +0.0 pp; pick makespan 2024 → 2015 min, labor 2,266 → 2,379 min.
- **Top 10% 2 pickers, EDF → priority:** target +0.0 pp, rest +0.0 pp. This asks whether priority only works once there is spare pick capacity.
- **Top 25% 1 → 2 pickers:** target 93.0% → 93.0% (+0.0 pp), rest 99.6% → 99.6% (+0.0 pp), all-order +0.0 pp; pick makespan 2137 → 2132 min, labor 2,625 → 2,775 min.
- **Top 25% 2 pickers, EDF → priority:** target +0.0 pp, rest +0.0 pp. This asks whether priority only works once there is spare pick capacity.
- **More pick capacity alone does not move aggregate OTIF materially.** If target also stays flat, the remaining constraint is upstream arrival or stock, not pick minutes; if target moves while aggregate does not, capacity is being reallocated rather than created for the target.
- **The first picker was not saturated.** Average daily pick span under 1 picker is **442 min of a 600-min shift**, and total labor is 3,160 min against 3 DCs × 5 days × 600 min. A second picker therefore adds slack, not throughput at the bottleneck. That is why 2-picker target/rest/all OTIF are identical to 1-picker and only makespan/labor move.
- **Priority with extra capacity is the cleaner test of the earlier nulls.** Week 33 gave priority no spare minute. Here the second picker creates slack; if priority still does nothing, ordering is not the mechanism even with slack. If it now helps target, the earlier null was a capacity interaction, not a wrong priority rule.
- **Read target and rest together.** A second picker can raise target OTIF by taking minutes from rest, or raise both by reducing queueing. The table separates those cases; aggregate OTIF alone cannot.

## Limitations

- 1/2 拣货员共用同一 prepared flow（接受/库存分配固定），只改拣选劳动力；不模拟第二拣货员工资、招聘/培训、工位/设备约束。
- 收入来自 Online Retail II 发票行 `quantity × UnitPrice`，是毛收入，不是毛利/净利；没有 COGS、退货、履约成本、门位/发车成本与客户终身价值。
- 目标客群 Top10/Top25 由本次 400 单收入分位数定义，是样本内分层；不是真实客户价值/毛利分层。
- 被拒订单按即期流失处理：不消耗库存、不重试、不转替代品、不计收入；同一 flow 下接单/收入按构造不变。
- ATP 只按当天开始时在库量报价，不预留在途/未来/跨订单库存；旧订单不重报价，不模拟客户接受/拒绝/取消。
- 日滚动每天只允许当天发车（max_days=0）；单周基线允许 3 天且所有订单视作周一。
- 30 个种子在本配置下 OTIF/交付日/接单率完全相同；差异是确定性的资源效应，不是 30 个独立样本。
- 只验证 1 周、1 套库存/布局/班次；2 拣货员共用 600 分钟班次；MILP/发车同配置可差约 1–1.5pp，小差异可能落在求解器噪声内。
