# Stock availability (Week 36)

- Generated: `2026-10-29T16:32:07.832704+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Flow: **5** weekdays | day 0: 66 | day 1: 73 | day 2: 68 | day 3: 85 | day 4: 108
- Seeds: **30** | scenarios **['atp_all_85', 'atp_all_100']** | daily MILP **8s/day**
- Demand revenue **170,467**; revenue coverage **100.0%**.

## Rule

This is the ATP accept-all arm at the same 400 real invoices, replayed with a **stock snapshot** of 85% vs 100% of demand. All orders are accepted in both arms, so the accepted set and demand denominator are identical; only the initial inventory changes. Pricing, promises, pickers, dock policy, and the value override are not involved. 100% is an upper bound, not a purchase plan; stock holding cost and COGS are not modeled.

## Results

| 库存因子 | 接受订单 | 接受率 | 收入接单 | 接受 OTIF | 目标 OTIF | 非目标 OTIF | 原 SLA | 全量 OTIF | 接受满足率 | 积压单位 | 发车 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 85% | 400.0 | 100.0% | 100.0% | 94.8% | 85.0% | 95.8% | 83.0% | 94.8% | 98.5% | 509 | 73.4 |
| 100% | 400.0 | 100.0% | 100.0% | 98.5% | 95.0% | 98.9% | 87.5% | 98.5% | 99.5% | 157 | 71.0 |

## Findings

- **Stock 85% → 100%:** target OTIF 85.0% → 95.0% (+10.0 pp), rest 95.8% → 98.9% (+3.1 pp), all-order +3.7 pp; accepted fill 98.5% → 99.5% (+1.1 pp), backlog 509 → 157 units.
- **Stock is the binding constraint for the target gap.** Adding inventory raises target OTIF; the earlier ordering, labor, and arrival levers could not, because they could not create units. This is the positive counterpart to Weeks 30–35.
- **Both arms accept all 400 orders**, so the comparison is not driven by a different accepted mix: accepted revenue is 100.0% in both. The change is confined to physical availability.
- **100% stock is an upper bound.** It removes the 15% shortage but keeps the same per-DC split, DC capacity, transit days and promises. If target still misses, the residual is placement/ATP, not total units.
- **Inventory is not free.** This report does not price holding cost, working capital, obsolescence or COGS; a 100% fill policy would have to earn its keep against those costs.

## Limitations

- 85%→100% 只改库存快照，不建模采购/在途/仓储成本、COGS、持有成本、过期/跌价；100% 是上界，不是补货计划。
- 两个库存因子共用同一 400 单样本与 ATP accept-all（接受集/需求分母相同），但库存变化会改变日滚动分配/补货路径，仍属于情景比较。
- 收入来自 Online Retail II 发票行 `quantity × UnitPrice`，是毛收入，不是毛利/净利；没有退货、履约成本、门位/发车成本与客户终身价值。
- 目标客群 Top10 由本次 400 单收入分位数定义，是样本内分层；不是真实客户价值/毛利分层。
- 被拒订单按即期流失处理；本实验 ATP 接受全部，因此 lost_orders=0，接受池=全量。
- ATP 只按当天开始时在库量报价，不预留在途/未来/跨订单库存；旧订单不重报价。
- 日滚动每天只允许当天发车（max_days=0）；单周基线允许 3 天且所有订单视作周一。
- 30 个种子在本配置下 OTIF/交付日完全相同；库存差异是确定性的可用量效应，不是 30 个独立样本。
- 只验证 1 周、1 套库存布局/班次；100% 仍受 DC 分布、DC 产能、transit/promise 约束；MILP 8s/day 可差约 1–1.5pp。
