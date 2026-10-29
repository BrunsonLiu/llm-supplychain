# Transit speed (Week 38)

- Generated: `2026-10-29T16:59:41.733748+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Flow: **5** weekdays | day 0: 66 | day 1: 73 | day 2: 68 | day 3: 85 | day 4: 108
- Seeds: **30** | scenarios **['atp_all_100_cap2_t0', 'atp_all_100_cap2_t1', 'atp_all_100_cap2_t2']** | daily MILP **8s/day**
- Demand revenue **170,467**; revenue coverage **100.0%**.

## Rule

This is the Week-37 100%-stock, DC-capacity-2×, ATP accept-all arm replayed with the **road transit** shortened by 0/1/2 days (floor 1 day). All arms accept all 400 orders, stock and DC capacity are fixed, so the accepted set, demand denominator and allocation inputs are the same; only the carrier time changes. It is an upper-bound speed-up, not a carrier contract; expedited freight cost is not modeled.

## Results

| 库存 | DC 产能 | transit 缩短 | 接受订单 | 接受 OTIF | 目标 OTIF | 非目标 OTIF | 原 SLA | 全量 OTIF | 平均交付日 | 积压单位 | 发车 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 100% | 2× | 0 天 | 400.0 | 98.5% | 92.5% | 99.2% | 89.2% | 98.5% | 4.52 | 177 | 69.7 |
| 100% | 2× | 1 天 | 400.0 | 99.0% | 97.5% | 99.2% | 97.5% | 99.0% | 3.55 | 147 | 64.0 |
| 100% | 2× | 2 天 | 400.0 | 99.2% | 97.5% | 99.4% | 98.5% | 99.2% | 3.28 | 131 | 61.6 |

## Findings

- **Transit −1 day:** target 92.5% → 97.5% (+5.0 pp), rest 99.2% → 99.2% (+0.0 pp), all-order +0.5 pp; average delivery day 4.52 → 3.55.
- **Transit −2 day:** target 92.5% → 97.5% (+5.0 pp), rest 99.2% → 99.4% (+0.3 pp), all-order +0.8 pp; average delivery day 4.52 → 3.28.
- **Transit is a real part of the residual.** Shorter road transit raises target OTIF at fixed stock and DC capacity; the remaining 4 pp was not only placement/promise. Faster freight has to be paid for.
- **The speed-up saturates.** −1 and −2 days give the same target OTIF, so the last day is not where the misses come from; extra speed beyond −1 has no service value.
- **The residual falls to ~1.9 pp.** At −2 days target is 97.5% vs rest 99.4%; what is left is placement/promise/static-deadline, not stock, DC throughput or carrier time.
- **The 0-day baseline is not cross-week comparable.** Its target 92.5% differs from Week-37 2× (95.0%) because CP-SAT time limits/configuration differ by ~1–1.5pp; only the three arms in this report are compared.
- **Every arm accepts all 400 orders at 100% stock and 2× capacity**, so this is not an acceptance-mix or resource effect. The comparison isolates carrier time.
- **−2 days is an upper bound, not a rate card.** It ignores expedited freight premium, carrier capacity, cut-off changes and emissions; a real carrier cannot remove two days from every lane.

## Limitations

- transit −1/−2 天只是承运商时效上界，不建模加急运费、承运商容量、截单变化、排放或线路可达性；−2 天不代表可签约。
- 所有臂库存 100%、DC 产能 2×、ATP accept-all，接受集/需求分母相同；transit 变化会改变分单/分配路径，仍属于情景比较。
- 收入来自 Online Retail II 发票行 `quantity × UnitPrice`，是毛收入，不是毛利/净利；没有 COGS、退货、履约成本、门位/发车成本与客户终身价值。
- 目标客群 Top10 由本次 400 单收入分位数定义，是样本内分层；不是真实客户价值/毛利分层。
- ATP 只按当天开始时在库量报价，不预留在途/未来/跨订单库存；旧订单不重报价。
- 日滚动每天只允许当天发车（max_days=0）；单周基线允许 3 天且所有订单视作周一。
- 30 个种子在本配置下 OTIF/交付日完全相同；transit 差异是确定性的时效效应，不是 30 个独立样本。
- 只验证 1 周、1 套库存布局/班次；transit 缩短仍受拣选/门位/发车/DC 分布约束；MILP 8s/day 可差约 1–1.5pp。
