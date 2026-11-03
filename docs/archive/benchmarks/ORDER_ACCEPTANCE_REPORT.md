# Order acceptance under daily replenishment (Week 24)

- Generated: `2026-10-28T19:08:13.069548+00:00`
- Orders: **400** real invoices / **2477** lines / **33,060** units, week 2011-11-28
- Flow: **5** weekdays | day 0: 66 | day 1: 73 | day 2: 68 | day 3: 85 | day 4: 108
- Seeds: **30** | scenario **['static_all', 'atp_all', 'atp_3', 'atp_2', 'static_3']** | daily MILP **8s/day**

## Rule

A new order is **accepted** only when its quoted promise at arrival is within the cutoff; otherwise it is rejected immediately. Rejected orders consume no stock and do not enter the dispatch queue, but they remain in the all-order denominator (`全量 OTIF`). Accepted-order metrics use only the accepted orders; `接单率` is accepted orders / all orders.

## Results

| 场景 | 报价 | 接单上限 | 接受订单 | 接单率 | 接单 quoted OTIF | 接单原 SLA | 接单 fill | 接单 backlog | 流失订单 | 流失单位 | 平均承诺 | 全量 OTIF |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 单周快照 · 固定承诺 | static | 全部 | 400.0 | 100.0% | 53.3% | 53.3% | 83.0% | 5,633 | 0.0 | 0 | 3.10 | 53.3% |
| 每日补货 · 接受全部 | static | 全部 | 400.0 | 100.0% | 87.5% | 87.5% | 96.2% | 1,256 | 0.0 | 0 | 3.10 | 87.5% |
| 每日补货 · ATP 接受全部 | atp | 全部 | 400.0 | 100.0% | 95.0% | 83.7% | 98.3% | 559 | 0.0 | 0 | 3.64 | 95.0% |
| 每日补货 · ATP 只接 ≤3 天 | atp | 3 | 283.0 | 70.7% | 100.0% | 97.9% | 100.0% | 0 | 117.0 | 19,191 | 3.00 | 70.7% |
| 每日补货 · ATP 只接 ≤2 天 | atp | 2 | 0.0 | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 400.0 | 33,060 | 0.00 | 0.0% |
| 每日补货 · 固定承诺只接 ≤3 天 | static | 3 | 320.0 | 80.0% | 87.5% | 87.5% | 96.1% | 1,060 | 80.0 | 5,640 | 2.62 | 70.0% |

## Findings

- **Accept-all is the reference.** With daily replenishment and `atp` quoting, accepted OTIF is 95.0% and the original SLA is 83.7% at 3.64 average quoted days; 0.0 orders are lost. The all-order OTIF is 95.0%.
- **ATP accept-all still has the Week-22 split.** vs fixed 2/3/5, ATP raises accepted quoted OTIF by +7.5 pp and fill by +2.1 pp, but lowers the original SLA by -3.8 pp and lengthens the average quote. Acceptance cannot repair that gap by itself; it only changes who stays in the denominator.
- **Cutoff 3 days with `atp`:** accepts 70.7% of orders; accepted OTIF 100.0% (+5.0 pp vs its accept-all reference), original SLA 97.9% (+14.1 pp). The service gain is bought with lost demand, not free: 117.0 more orders (19,191 units) are rejected.
- **Cutoff 2 days with `atp` rejects every order.** `每日补货 · ATP 只接 ≤2 天` accepts 0 orders and loses 33,060 units; its 0% accepted OTIF is an empty denominator, not a service success. A cutoff must be compatible with the quote policy's feasible tiers.
- **Cutoff 3 days with `static`:** accepts 80.0% of orders; accepted OTIF 87.5% (+0.0 pp vs its accept-all reference), original SLA 87.5% (+0.0 pp). Accepted service does **not** improve (+0.0 pp quoted, +0.0 pp original SLA); rejection only removes 80.0 orders (5,640 units). This cutoff is not a service lever for this quote policy.
- **Read the loss column with the service column.** A higher accepted OTIF is not a better policy if the denominator shrank; `全量 OTIF` and `流失订单/单位` are shown for exactly this reason.
- **Acceptance is not a second inventory lever.** It can protect the accepted pool, but it cannot serve the rejected demand; the inventory and replenishment decision still sets the feasible frontier.
- **Solver variation is visible.** The time-limited MILP is not bit-for-bit reproducible; treat differences below ~1 pp as solver noise.

## Limitations

- 被拒订单按即期流失处理：不消耗库存、不进入分单/拣选/发车，不重试、不转替代品、不计收入损失；接受率是订单数口径。
- 接受订单的 OTIF/原 SLA 只对接受池计算；全量 OTIF 把被拒订单当作未履约，两个分母必须一起看。
- ATP 只按当天开始时的在库量报价，不预留在途/未来/跨订单库存；同一天多张订单可能同时报 2 天再竞争。
- 旧订单保留到达时的绝对承诺日，不改单/不重报价；不模拟客户接受/拒绝/取消。
- 日滚动每天只允许当天发车（max_days=0）；单周基线允许 3 天且所有订单视作周一。
- 分单后不接收拣选/发车/门位失败的回写；补货是声明 order-up-to，1/2 天前置期，不做预测/MOQ/供应商产能/DC 调拨。
- 30 个种子在本配置下 OTIF/交付日完全相同，接受率与流失量也是确定性的；不是 30 个独立需求样本。
- 原 SLA 用 Week-20 固定 2/3/5 承诺，不是客户真实容忍度；只验证 1 周、1 套库存/布局/劳动力。
