# 供应链智能体

> 在真实电商交易数据上，把**需求预测 → 库存政策 → 仓网布点 → 订单分单 → 波次拣选 → 发车**串成一条可复现的履约链路，并用 **Agent v2** 把预测、优化和诊断工具组织成可校验的决策流程。

一页版：[`PORTFOLIO.md`](PORTFOLIO.md)　·　5 分钟演示：`python scripts/demo.py`

## 30 秒了解

- **真实数据**：UCI Online Retail II，1,067,371 行原始交易，清洗后 1,014,625 行、4,707 个 SKU、104 周面板。
- **端到端**：400 张真实发票、3 个 DC、189 个 SKU、30 个种子 × 3 次重复；分单、库存、波次、拣选、发车在同一实例里联动。
- **可复现**：所有指标由仓库脚本生成，固定 seed；345 个测试通过。
- **不依赖 API Key**：默认 Agent 使用确定性 planner + 工具运行时；真实模型可切换。

## 架构

```text
UCI Online Retail II
        │
        ▼
  需求预测（LightGBM / 基线）
        │  SKU 周需求
        ▼
  库存政策（历史均值 / 安全库存 / 预测）
        │  SKU × DC 库存
        ▼
  布点 MILP（CP-SAT：份额、产能、拣选负荷）
        │  DC 初始库存
        ▼
  分单 MILP（订单 → DC → 履约承诺）
        │  运单 / 票据
        ▼
  波次 + 拣选 + 发车（EDF / CP-SAT / 集批）
        │
        ▼
  OTIF · 成本 · 积压 · 尾部风险
        │
        └──► 指标 / 报告 / 诊断工具
                    │
                    ▼
        Agent v2（Plan DAG + Verifier + Replan）
```

## 核心模块

### 1. 需求预测

- SKU 周需求面板，滚动起点回测；LightGBM 全局模型 + 6 个基线。
- 特征：滞后、滚动均值/方差、价格、季节、SKU/国家统计。
- 两个口径都评估：
  - **SKU 级**：LightGBM WMAPE **73.34%**，Naive **89.44%**。
  - **仓库总量**：Seasonal Naive **21.08%**，LightGBM **31.93%**。
- 结论：SKU 级用 LightGBM，仓库总量用季节基线；不强行一个模型打所有粒度。

### 2. 库存与布点

- 库存基准：历史均值、安全库存 `mean + z×std`、LightGBM 预测、预测结构。
- 布点：CP-SAT 固定总量 MILP，10%–60% DC 份额，DC 产能，拣选分钟负荷。
- 分单：逐 DC 分配 MILP，服务/成本/拣选容量三种目标。
- 评价：400 发票 × 30 种子 × 3 重复，报告 target/rest/all OTIF、积压、调拨量。

### 3. 履约执行

- 波次拣选、订单合并、截单时间、班中插单、在线释放。
- 承运商发车截止、月台门位、装车资源、同日集批。
- 承诺报价与 ATP、订单接受、价值分层、滚动补货。
- 统一用事件驱动仿真执行，优化结果落到票据/波次/发车。

### 4. Agent v2

- **Plan DAG**：`submit_plan` 只接受带 `id/tool/args/depends_on` 的 DAG。
- **Verifier**：执行前校验 allowlist、JSON Schema、依赖、环、预算。
- **Replan**：工具失败或验证不通过时，带结构化错误重规划。
- **工具层**：预测、库存、布点、分单、诊断、报告、RAG 检索。
- 30 个任务、3 种策略：raw / verified / adaptive；adaptive **30/30**，raw 有 1 个 false success，verified 为 0。

### 5. 工程

- Python 3.9+，`from __future__ import annotations`。
- OR-Tools CP-SAT、LightGBM、pandas/numpy、FastAPI、Streamlit。
- 46 个 `test_*.py` + quick_test，**345 passed**；CI 覆盖核心 smoke。
- 输出同时写 Markdown + JSON，报告中的每个数字都可回溯到脚本。

## 最终基准

完整报告：[`benchmarks/FINAL_SUMMARY.md`](benchmarks/FINAL_SUMMARY.md)

### 需求预测（UCI Online Retail II，52 周滚动回测）

| 模型 | SKU WMAPE | 偏差 | 周数 |
|---|---:|---:|---:|
| **LightGBM** | **73.34%** | +8.53% | 52 |
| Seasonal Naive | 86.75% | +2.13% | 52 |
| Naive | 89.44% | +0.30% | 52 |

仓库总量口径：Seasonal Naive **21.08%**，LightGBM **31.93%**。

### 库存政策（400 发票、3 DC、30 种子 × 3 重复）

| 政策 | 库存单位 | 覆盖率 | 目标 OTIF | 全量 OTIF | 积压 |
|---|---:|---:|---:|---:|---:|
| 历史均值 ×1.4 | 44,824 | 135.6% | 70.0% | 93.9% | 2,123 |
| **LightGBM 预测 ×1.6** | **55,776** | **168.7%** | **85.0%** | **91.6%** | **945** |

预测库存把目标 OTIF 从 **70.0% → 85.0%**，积压从 **2,123 → 945**；代价是覆盖率从 135.6% 升到 168.7%，全量 OTIF 从 93.9% 降到 91.6%。

### 波次释放（400 发票、3 DC、1 拣货员/DC）

| 释放策略 | 波次 | 拣选准时 | 迟到票据 | 端到端 OTIF | 总成本 |
|---|---:|---:|---:|---:|---:|
| EDF 即时装满 | 84 | 79.1% | 129 | 39.0% | 62,194 |
| **节省重批** | 92 | **81.8%** | **112** | **43.0%** | **62,189** |

同一分单下，只改释放策略：端到端 OTIF **+4.0pp**，迟到票据 **−17**，成本基本不变。

### Agent v2（30 任务）

| 策略 | 成功 | 验证通过 | False success | Abstain | 重规划 |
|---|---:|---:|---:|---:|---:|
| raw | 27/30 | 100.0% | 1 | 0 | 0 |
| verified | 27/30 | 76.7% | 0 | 7 | 0 |
| **adaptive** | **30/30** | **86.7%** | **0** | 4 | 3 |

完整报告：[`benchmarks/FINAL_SUMMARY.md`](benchmarks/FINAL_SUMMARY.md)。

## 快速开始

```bash
# 1) 安装
pip install -e ".[dev]"

# 2) 5 分钟演示：数据 → 预测 → 库存 → 报告 → RAG → Function Calling
python scripts/demo.py

# 3) 预测回测
python scripts/run_backtest.py

# 4) 端到端履约基准
python scripts/run_e2e_benchmark.py

# 5) Agent v2 评测
python scripts/run_agent_v2_benchmark.py

# 6) 检索评测
python scripts/run_retrieval_eval.py

# 7) 测试
pytest -q
```

Windows 设置 `PYTHONPATH`：

```powershell
$env:PYTHONPATH='src;.'
```

## 目录

```text
src/
  supply/
    forecasting/     需求预测、回测
    inventory/       库存政策、补货
    network/         仓网、路径
    fulfillment/     分单、波次、拣选、发车、门位
    e2e/             端到端实例、流水线、报告
  agent/             Plan DAG、Verifier、Replan、工具
  rag/               文档、嵌入、检索、RAG
scripts/             基准与演示入口
tests/               46 个 test_*.py + quick_test
benchmarks/          最终报告 + JSON
docs/model_cards/    模型卡
```

## 范围与边界

- 这是**仿真基准**，不是生产系统：库存、网络、时效、门位、报价参数是显式声明假设。
- 默认 Agent planner 是确定性 DAG，用来验证运行时、护栏和工具边界；真实 LLM 规划需单独配置 API Key 并报告方差/成本。
- 单数据集、单 season；跨行业、跨仓网推广前需要重新校准。
- 所有结果可由本仓库脚本复现；报告中的绝对值不应直接当作业务承诺。

## License

MIT，见 [`LICENSE`](LICENSE)。
