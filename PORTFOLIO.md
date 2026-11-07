# 供应链智能体

这个项目是我用 UCI Online Retail II 做的履约仿真。数据清洗后是 104 周、4,707 个 SKU；实验取 2011-11-28 这一周，400 张发票、3 个 DC、189 个 SKU，30 个种子各跑 3 次。

链路从预测到发车，库存和网络参数按历史或预测算，不用目标周的实际销量。

## 预测

周需求按 SKU 聚合，滚动起点回测。SKU 级 LightGBM 的 WMAPE 是 73.34%，Naive 是 89.44%，Seasonal Naive 是 86.75%。仓库总量上，Seasonal Naive 的 21.08% 比 LightGBM 的 31.93% 更好，所以两个粒度用了不同模型。

预测只覆盖 200 个主 SKU，其余用历史均值兜底。

## 库存

历史均值 ×1.4 是 44,824 单位，目标 OTIF 70.0%，积压 2,123。LightGBM ×1.6 是 55,776 单位，目标 OTIF 85.0%，积压 945。

目标服务上去了，覆盖成本和尾部服务也付出代价：覆盖率从 135.6% 升到 168.7%，全量 OTIF 从 93.9% 降到 91.6%。具体选哪一档，要看缺货惩罚和资金占用。

## 波次

400 张发票、每 DC 1 名拣货员。EDF 即时装满的端到端 OTIF 是 39.0%，迟到票据 129 张；换成节省重批后是 43.0%，迟到票据 112 张，成本基本不变。这是单个 E2E 实例，不是 30 个种子的平均。

## Agent v2

30 个任务。raw 成功 27/30，verified 27/30，adaptive 30/30。raw 有 1 个 false success，verified 为 0；adaptive 通过 3 次重规划把 recovery 类任务做到 3/3。

## 实现

库存和分单拆成两层：先按政策定 SKU 总量，再用 CP-SAT 分到 DC；分单用一个分配 MILP，目标可选服务、成本或拣选容量。拆开能分开看两层的影响，但合起来不是联合最优。分单结果落成票据，后面用事件驱动仿真跑波次、拣选、发车、门位和报价。Agent 这层是 Plan DAG + Verifier + Replan。

## 前沿层（实验）

因果、Conformal、随机联合、在线和 RL-0 已经接成最小实现：SCM + AIPW/DML 因果 benchmark、split/Mondrian conformal + ACI 在线自适应、bootstrap/copula/conformal 场景 + 成本感知 CVaR 联合、UCB/Thompson 策略选择 + receding-horizon 接口、bandit + IPS/DR。真实数据没有随机化，所以因果只报模型内效应；在线/RL 是离线回放，不是线上结论。

```bash
python scripts/run_frontier_bench.py --quick
```

最新文献和边界见 [`docs/research/FRONTIER_RESEARCH_2026.md`](docs/research/FRONTIER_RESEARCH_2026.md)。

## 运行

```bash
pip install -e ".[dev]"
python scripts/demo.py
python scripts/prepare_data.py
python scripts/run_backtest.py
python scripts/run_e2e_benchmark.py
python scripts/run_agent_v2_benchmark.py
pytest -q
```

默认流程不需要 API Key。planner 是脚本 DAG，真实 LLM 规划要另外配置。

## 说明

结果都是仿真出来的，不能当生产承诺。库存、网络、时效、门位和报价都是声明假设；单数据集、单 season，换行业或仓网前要重新校准。

README 里有更多细节：[`README.md`](README.md)。
