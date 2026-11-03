# 供应链智能体

项目用的是 UCI Online Retail II 的真实交易数据。整个流程从 SKU 周需求预测开始，往下是库存和 DC 布点、订单分单、波次拣选和发车，最后落到 OTIF、成本和积压。

数据覆盖 2009 到 2011 年一家英国在线零售商的发票。清洗后是 1,014,625 行、4,707 个 SKU、104 周。端到端实验取 2011-11-28 这一周，400 张发票、3 个 DC、189 个 SKU，跑 30 个种子，每个种子重复 3 次。库存、DC 产能、运输时效、承诺和拣选工时都是代码里写明的假设，数据里没有这些字段。

跑默认流程不需要 API Key。Agent 用确定性 planner，重点在工具调用、校验和失败重规划；接真实 LLM 是另一个配置，也需要单独报告方差和成本。

## 结构

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

## 需求预测

周需求面板按 SKU 聚合，滚动起点回测。LightGBM 是全局模型，另外还有 6 个基线：ma8、ma4、croston_sba、seasonal_naive、naive、holt。

| 模型 | SKU WMAPE | 偏差 |
|---|---:|---:|
| LightGBM | 73.34% | +8.53% |
| Seasonal Naive | 86.75% | +2.13% |
| Naive | 89.44% | +0.30% |

SKU 级 LightGBM 最好。仓库总量是另一回事，Seasonal Naive 的 21.08% 反而优于 LightGBM 的 31.93%，所以系统里两个粒度用了不同模型。

## 库存与布点

库存政策有三种：历史均值、`mean + z×std` 安全库存、LightGBM 预测。每个 SKU 先定总库存，再用 CP-SAT 布点 MILP 分到 DC。布点约束包括 10%–60% 的 DC 份额、DC 产能和拣选分钟负荷。

分单是逐 DC 的 MILP，目标可以选服务、成本或拣选容量。400 张发票、30 个种子、3 次重复，结果取平均。

库存对比里，历史均值 ×1.4 是 44,824 单位，覆盖 135.6%，目标 OTIF 70.0%，全量 93.9%，积压 2,123。LightGBM ×1.6 是 55,776 单位，覆盖 168.7%，目标 OTIF 85.0%，全量 91.6%，积压 945。预测把目标服务拉高了 15 个百分点，积压少了约 1,200 单位，但覆盖率多了 33 个百分点，全量服务略降。

## 分单与履约

分单之后，订单行会变成按发票和 DC 拆分的票据。每个 DC 用事件驱动仿真处理到达、波次、拣选和发车；释放策略可以选 EDF、节省重批或等待凑波，发车侧还有承运商截止、月台门位和装车资源。

同一分单下只改释放策略，400 张发票、每 DC 1 名拣货员：

| 释放策略 | 波次 | 拣选准时 | 迟到票据 | 端到端 OTIF | 总成本 |
|---|---:|---:|---:|---:|---:|
| EDF 即时装满 | 84 | 79.1% | 129 | 39.0% | 62,194 |
| 节省重批 | 92 | 81.8% | 112 | 43.0% | 62,189 |

节省重批把端到端 OTIF 从 39.0% 提到 43.0%，迟到票据少 17 张，成本几乎不变。

## Agent v2

Agent 的入口是一个 `submit_plan` 工具，只接受带 `id`、`tool`、`args`、`depends_on` 的 DAG。执行前会检查工具白名单、参数 Schema、依赖和环；失败时带结构化错误重规划。

30 个任务、三种策略：

| 策略 | 成功 | 验证通过 | False success | Abstain | 重规划 |
|---|---:|---:|---:|---:|---:|
| raw | 27/30 | 100.0% | 1 | 0 | 0 |
| verified | 27/30 | 76.7% | 0 | 7 | 0 |
| adaptive | 30/30 | 86.7% | 0 | 4 | 3 |

raw 会有一个任务在工具返回错误数字时仍然报成功，Verifier 能把它拦下来。adaptive 多了重规划，把 recovery 类任务从 0/3 做到 3/3。

## 运行

```bash
pip install -e ".[dev]"
python scripts/demo.py
python scripts/run_backtest.py
python scripts/run_e2e_benchmark.py
python scripts/run_agent_v2_benchmark.py
python scripts/run_retrieval_eval.py
pytest -q
```

Windows 下先设：

```powershell
$env:PYTHONPATH='src;.'
```

测试是 46 个 `test_*.py` 加 `quick_test.py`，当前 345 个通过。

## 代码结构

```text
src/supply/       预测、库存、网络、履约、端到端仿真
src/agent/        Plan DAG、Verifier、Replan、工具
src/rag/          文档、嵌入、检索
scripts/          基准和演示入口
tests/            测试
benchmarks/       结果和 JSON
docs/             模型卡、归档
```

## 说明

下面这些数字是仿真出来的，不是生产指标。库存、网络、时效、门位和报价参数都是假设；单数据集、单 season，换行业或换仓网需要重新校准。默认 Agent 的 planner 是脚本 DAG，真实模型规划还没有纳入这份报告。

一页版在 [`PORTFOLIO.md`](PORTFOLIO.md)。
