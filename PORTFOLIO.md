# 供应链智能体

这是一个基于真实电商交易的供应链履约项目。数据来自 UCI Online Retail II，清洗后是 104 周、4,707 个 SKU。端到端实验取 2011-11-28 这一周，400 张发票、3 个 DC、189 个 SKU，30 个种子，每个种子重复 3 次。

项目把预测、库存、布点、分单、波次和发车放在同一个实例里跑，库存和网络参数都写在代码里，没有用目标周的真实需求。

## 结果

**预测。** SKU 周需求上，LightGBM 的 WMAPE 是 73.34%，Naive 是 89.44%，Seasonal Naive 是 86.75%。仓库总量上，Seasonal Naive 的 21.08% 比 LightGBM 的 31.93% 更好，所以两个粒度用了不同模型。

**库存。** 历史均值 ×1.4 是 44,824 单位，目标 OTIF 70.0%，积压 2,123。LightGBM ×1.6 是 55,776 单位，目标 OTIF 85.0%，积压 945。预测把目标服务拉高 15 个百分点，代价是覆盖率从 135.6% 升到 168.7%，全量 OTIF 从 93.9% 降到 91.6%。

**波次释放。** 400 张发票、每 DC 1 名拣货员，EDF 即时装满的端到端 OTIF 是 39.0%，迟到票据 129 张；换成节省重批后是 43.0%，迟到票据 112 张，成本基本不变。

**Agent v2。** 30 个任务，raw 成功 27/30，verified 27/30，adaptive 30/30。raw 有 1 个 false success，verified 为 0；adaptive 通过 3 次重规划把 recovery 类任务做到 3/3。

## 做法

- 预测用滚动起点回测，LightGBM 之外还有 6 个基线。
- 库存先定 SKU 总量，再用 CP-SAT 分到 DC，约束包括 10%–60% 份额、DC 产能和拣选负荷。
- 分单用逐 DC 的 MILP，目标可选服务、成本或拣选容量。
- 分单结果落成票据，再用事件驱动仿真跑波次、拣选、发车、门位和报价。
- Agent 用 Plan DAG + Verifier + Replan，工具覆盖预测、库存、布点、分单、诊断和检索。

## 运行

```bash
pip install -e ".[dev]"
python scripts/demo.py
python scripts/run_backtest.py
python scripts/run_e2e_benchmark.py
python scripts/run_agent_v2_benchmark.py
pytest -q
```

不需要 API Key。默认 planner 是脚本 DAG，真实 LLM 规划要另外配置。

## 说明

这是仿真基准，不是生产系统。库存、网络、时效、门位和报价都是声明假设；单数据集、单 season，换行业或仓网前要重新校准。

更完整的说明在 [`README.md`](README.md)，结果汇总在 [`benchmarks/FINAL_SUMMARY.md`](benchmarks/FINAL_SUMMARY.md)。
