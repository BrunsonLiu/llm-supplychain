# DC capacity upper bound (Week 37)

- Generated: `2026-10-29T16:46:13.396560+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Flow: **5** weekdays | day 0: 66 | day 1: 73 | day 2: 68 | day 3: 85 | day 4: 108
- Seeds: **30** | scenarios **['atp_all_100_cap1', 'atp_all_100_cap2', 'atp_all_100_cap10']** | daily MILP **8s/day**
- Demand revenue **170,467**; revenue coverage **100.0%**.

## Rule

This is the Week-36 100%-stock ATP accept-all arm replayed with **DC weekly capacity** multiplied by 1×, 2× and 10×. All orders are accepted in every arm and stock is 100%, so the accepted set, demand denominator and inventory are identical; only the per-DC weekly throughput limit changes. It is an upper-bound stress test, not a capacity plan; the cost of extra DC capacity is not modeled.

## Results

| 库存 | DC 产能 | 接受订单 | 接受 OTIF | 目标 OTIF | 非目标 OTIF | 原 SLA | 全量 OTIF | 接受满足率 | 积压单位 | 发车 |
|---|---|---|---|---|---|---|---|---|---|---|
| 100% | 1× | 400.0 | 98.3% | 92.5% | 98.9% | 87.8% | 98.3% | 99.6% | 144 | 68.3 |
| 100% | 2× | 400.0 | 99.0% | 95.0% | 99.4% | 88.5% | 99.0% | 99.6% | 132 | 69.1 |
| 100% | 10× | 400.0 | 99.0% | 95.0% | 99.4% | 89.5% | 99.0% | 99.6% | 145 | 70.8 |

## Findings

- **DC capacity 2×:** target 92.5% → 95.0% (+2.5 pp), rest 98.9% → 99.4% (+0.6 pp), all-order +0.7 pp; backlog 144 → 132.
- **DC capacity 10×:** target 92.5% → 95.0% (+2.5 pp), rest 98.9% → 99.4% (+0.6 pp), all-order +0.7 pp; backlog 144 → 145.
- **DC weekly capacity is part of the residual.** Raising the per-DC throughput limit improves target OTIF at fixed stock; the Week-36 residual was not only transit/promise. Capacity still has to be paid for.
- **Capacity saturates before 10×.** The 2× and 10× arms both reach target 95.0%; extra weekly throughput beyond 2× adds no target service. The remaining gap to the 99%+ rest is therefore transit/promise/placement, not the weekly capacity cap.
- **Every arm accepts all 400 orders at 100% stock**, so this is not an acceptance-mix effect. The comparison isolates the capacity constraint.
- **10× is an upper bound, not a recommendation.** It ignores the cost of space, labor, equipment and the fact that a real DC cannot scale weekly capacity tenfold without capex/lead time.

## Limitations

- DC 周产能 1×/2×/10× 只是上界压力测试，不建模扩产 capex、租约、设备、人力招聘或提前期；10× 不代表可执行方案。
- 所有臂库存 100%、ATP accept-all，接受集/需求分母相同；但产能变化会改变日滚动分配路径，仍属于情景比较。
- 收入来自 Online Retail II 发票行 `quantity × UnitPrice`，是毛收入，不是毛利/净利；没有 COGS、退货、履约成本、门位/发车成本与客户终身价值。
- 目标客群 Top10 由本次 400 单收入分位数定义，是样本内分层；不是真实客户价值/毛利分层。
- ATP 只按当天开始时在库量报价，不预留在途/未来/跨订单库存；旧订单不重报价。
- 日滚动每天只允许当天发车（max_days=0）；单周基线允许 3 天且所有订单视作周一。
- 30 个种子在本配置下 OTIF/交付日完全相同；产能差异是确定性的容量效应，不是 30 个独立样本。
- 只验证 1 周、1 套库存布局/班次；DC 产能放大仍受 transit/promise/门位/拣选约束；MILP 8s/day 可差约 1–1.5pp。
