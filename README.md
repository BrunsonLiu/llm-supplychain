# 供应链智能体

这个仓库是我用 UCI Online Retail II 做的一个供应链履约仿真。数据是 2009 到 2011 年一家英国在线零售商的真实发票，清洗后 1,014,625 行、4,707 个 SKU、104 周。

履约实验取 2011-11-28 这一周，这是面板里最后一个完整周；400 张发票、3 个 DC、189 个 SKU，30 个种子各跑 3 次。库存、DC 产能、运输时效、承诺和拣选工时都是代码里的假设，原数据没有这些字段。

链路从 SKU 周需求预测开始，往下接库存和 DC 布点、订单分单、波次拣选和发车。做这个项目，主要是想用同一套 OTIF 和成本口径，比较库存、布点和仓内执行各自的影响。

跑默认流程不需要 API Key。Agent 用确定性 planner，重点在工具调用、校验和失败重规划；接真实 LLM 是另一个配置，也需要单独报告方差和成本。

## 流程

```text
UCI Online Retail II
        │
        ▼
  需求预测
        │
        ▼
  库存政策 → DC 布点
        │
        ▼
  订单分单
        │
        ▼
  波次拣选 → 发车
        │
        ▼
  OTIF / 成本 / 积压
        │
        └──► 指标与诊断工具 → Agent v2
```

## 预测

周需求面板按 SKU 聚合，滚动起点回测。LightGBM 是全局模型，另外还有 6 个基线：ma8、ma4、croston_sba、seasonal_naive、naive、holt。

| 模型 | SKU WMAPE | 偏差 |
|---|---:|---:|
| LightGBM | 73.34% | +8.53% |
| Seasonal Naive | 86.75% | +2.13% |
| Naive | 89.44% | +0.30% |

SKU 级 LightGBM 最好。仓库总量是另一回事，Seasonal Naive 的 21.08% 反而优于 LightGBM 的 31.93%，所以系统里两个粒度用了不同模型。

表里只是 200 个主 SKU 的误差；其余 SKU 用历史均值兜底，没算进这个数。

## 库存和布点

每个 SKU 先按历史均值、安全库存或 LightGBM 预测定总量，再用 CP-SAT 分到 DC。布点约束有 10%–60% 的 DC 份额、DC 产能和拣选分钟负荷。分单用一个分配 MILP，目标可选服务、成本或拣选容量。

库存和分单没有合成一个大 MILP：先定 SKU 总量，再分单到 DC。拆开的好处是能分别看两层的影响，代价是合起来不是联合最优。

| 政策 | 库存 | 覆盖 | 目标 OTIF | 全量 OTIF | 积压 |
|---|---:|---:|---:|---:|---:|
| 历史均值 ×1.4 | 44,824 | 135.6% | 70.0% | 93.9% | 2,123 |
| LightGBM ×1.6 | 55,776 | 168.7% | 85.0% | 91.6% | 945 |

换成预测后，目标 OTIF 高 15 个百分点，积压少 1,178 单位；代价是覆盖率多 33.1 个百分点，全量 OTIF 低 2.3 个百分点。30 个种子只改到达和拣选噪声，需求不变。

## 分单、波次和发车

分单之后，订单行会变成按发票和 DC 拆分的票据。每个 DC 用事件驱动仿真处理到达、波次、拣选和发车；释放策略可以选 EDF、节省重批或等待凑波，发车侧还有承运商截止、月台门位和装车资源。端到端 400 单的 CP-SAT 有时间上限，这里的分单是可行解，不是证明最优。

同一分单下只改释放策略，400 张发票、每 DC 1 名拣货员：

| 释放策略 | 波次 | 拣选准时 | 迟到票据 | 端到端 OTIF | 总成本 |
|---|---:|---:|---:|---:|---:|
| EDF 即时装满 | 84 | 79.1% | 129 | 39.0% | 62,194 |
| 节省重批 | 92 | 81.8% | 112 | 43.0% | 62,189 |

节省重批把端到端 OTIF 从 39.0% 提到 43.0%，迟到票据少 17 张，成本几乎不变。波次只跑了单个 E2E 实例，不是 30 个种子的平均；库存那组才是 30 种子 × 3 次。

## Agent v2

Agent 只暴露一个 `submit_plan` 工具，只接受带 `id`、`tool`、`args`、`depends_on` 的 DAG。执行前会检查工具白名单、参数 Schema、依赖和环；失败时带结构化错误重规划。

30 个任务、三种策略：

| 策略 | 成功 | 验证通过 | False success | Abstain | 重规划 |
|---|---:|---:|---:|---:|---:|
| raw | 27/30 | 100.0% | 1 | 0 | 0 |
| verified | 27/30 | 76.7% | 0 | 7 | 0 |
| adaptive | 30/30 | 86.7% | 0 | 4 | 3 |

raw 会有一个任务在工具返回错误数字时仍然报成功，Verifier 能把它拦下来。adaptive 多了重规划，把 recovery 类任务从 0/3 做到 3/3。

## 怎么跑

先装依赖。`demo.py` 用的是合成需求，直接能跑；后面的真实数据基准要先执行一次 `prepare_data.py`，已有 `data/raw` 和 `data/processed` 时可以跳过。测试是 46 个 `test_*.py` 加 `quick_test.py`，当前 345 个通过。

```bash
pip install -e ".[dev]"
python scripts/demo.py           # 用合成需求，不需要数据
python scripts/prepare_data.py   # 跑真实数据基准前执行一次，下载约 45 MB
python scripts/run_backtest.py
python scripts/run_e2e_benchmark.py
python scripts/run_agent_v2_benchmark.py
python scripts/run_retrieval_eval.py
pytest -q
```

## 代码入口

主要代码在 `src/supply/` 下：

- 端到端流水线：`src/supply/e2e/pipeline.py`
- Agent v2：`src/supply/agent_v2/`
- 预测：`src/supply/forecasting/`
- 分单、波次和发车：`src/supply/fulfillment/`、`src/supply/wave/`
- RAG：`src/rag/`
- 基准脚本：`scripts/`

测试在 `tests/`；脚本默认读的 JSON 在 `benchmarks/`，早期报告在 `docs/archive/benchmarks/`。

## 边界

这些数字来自仿真，不能当生产指标。库存、网络、时效、门位和报价都是假设；库存和波次也只取一个目标周，换行业或仓网要重新校准。

Agent 默认用脚本 planner；真实模型规划还没放进这份报告。

一页版在 [`PORTFOLIO.md`](PORTFOLIO.md)。
