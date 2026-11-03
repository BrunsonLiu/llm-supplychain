# Local stock distribution (Week 39)

- Generated: `2026-10-29T17:14:45.843812+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Flow: **5** weekdays | day 0: 66 | day 1: 73 | day 2: 68 | day 3: 85 | day 4: 108
- Seeds: **30** | scenarios **['atp_all_s100_cap2_t1', 'atp_all_s120_cap2_t1', 'atp_all_s150_cap2_t1']** | daily MILP **8s/day**
- Demand revenue **170,467**; revenue coverage **100.0%**.

## Rule

This is the Week-38 transit −1 arm replayed with **initial stock** at 100%, 120% and 150% of demand, keeping DC capacity 2× and ATP accept-all. All arms accept all 400 orders, so the accepted set and demand denominator are identical; only the local stock buffer changes. 120%/150% is not a purchase plan: it is an upper bound that removes DC×SKU local shortages, not just the total-unit shortage. Holding cost and COGS are not modeled.

## Results

| 库存 | DC 产能 | transit 缩短 | 接受订单 | 接受 OTIF | 目标 OTIF | 非目标 OTIF | 原 SLA | 全量 OTIF | 平均交付日 | 积压单位 |
|---|---|---|---|---|---|---|---|---|---|---|
| 100% | 2× | 1 天 | 400.0 | 98.5% | 97.5% | 98.6% | 97.0% | 98.5% | 3.54 | 138 |
| 120% | 2× | 1 天 | 400.0 | 98.8% | 95.0% | 99.2% | 97.5% | 98.8% | 3.46 | 56 |
| 150% | 2× | 1 天 | 400.0 | 99.7% | 100.0% | 99.7% | 98.5% | 99.7% | 3.39 | 4 |

## Findings

- **Stock 120%:** target 97.5% → 95.0% (-2.5 pp), rest 98.6% → 99.2% (+0.6 pp), all-order +0.3 pp; backlog 138 → 56.
- **Stock 150%:** target 97.5% → 100.0% (+2.5 pp), rest 98.6% → 99.7% (+1.1 pp), all-order +1.2 pp; backlog 138 → 4.
- **Only the 150% overstock arm closes the residual, and the path is not monotonic.** The 120% arm is *lower* than 100% on target, so this is not a clean “more local stock, more service” effect; allocation/replenishment path and solver variation dominate at 120%. 150% removes local shortages and reaches 100%, but it is also 1.5× demand, so it cannot separate local placement from extra total units.
- **Every arm accepts all 400 orders at 2× capacity and transit −1**, so this is not an acceptance-mix, throughput or carrier effect.
- **150% is an upper bound, not a recommendation.** It ignores holding cost, working capital, obsolescence and the fact that a real buyer would not hold 1.5× weekly demand at every DC. It also cannot prove that a fixed-total rebalance would work; the 120% dip argues against a simple buffer story.

## Limitations

- 120%/150% 只改初始库存快照，不建模采购/在途/仓储成本、COGS、持有成本、过期/跌价；150% 是上界，不是补货计划。
- 所有臂 DC 产能 2×、transit −1、ATP accept-all，接受集/需求分母相同；库存变化会改变日滚动分配路径，仍属于情景比较。
- 收入来自 Online Retail II 发票行 `quantity × UnitPrice`，是毛收入，不是毛利/净利；没有退货、履约成本、门位/发车成本与客户终身价值。
- 目标客群 Top10 由本次 400 单收入分位数定义，是样本内分层；不是真实客户价值/毛利分层。
- ATP 只按当天开始时在库量报价，不预留在途/未来/跨订单库存；旧订单不重报价。
- 日滚动每天只允许当天发车（max_days=0）；单周基线允许 3 天且所有订单视作周一。
- 30 个种子在本配置下 OTIF/交付日完全相同；库存差异是确定性的可用量效应，不是 30 个独立样本。
- 只验证 1 周、1 套库存布局/班次；150% 仍受 DC 分布/承诺/发车约束；MILP 8s/day 可差约 1–1.5pp。
