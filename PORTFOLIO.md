# 供应链智能体 · 一页版

> 真实电商数据上的履约算法作品：预测、库存、布点、分单、波次、发车，以及可校验的 Agent v2。

## 我做了什么

把 UCI Online Retail II 的 **1,014,625 行真实交易、4,707 个 SKU、52 周**，做成一条端到端可复现链路：

**需求预测 → 库存政策 → DC 布点 → 订单分单 → 波次拣选 → 发车 → OTIF/成本**

所有优化和仿真参数显式声明，所有数字由仓库脚本生成。

## 三个最终结果

| 模块 | 设置 | 结果 |
|---|---|---|
| **需求预测** | 9,685 个 SKU-周，52 周滚动回测 | LightGBM WMAPE **73.34%**，Naive **89.44%**；仓库总量口径 Seasonal Naive **21.08%** 更优 |
| **库存政策** | 400 发票、3 DC、30 种子 × 3 重复 | 历史均值 ×1.4：target **70.0%**；LightGBM ×1.6：target **85.0%**、积压 **945**（历史 2,123） |
| **波次释放** | 400 发票、3 DC、1 拣货员/DC | EDF → 节省重批：端到端 OTIF **39.0% → 43.0%**，迟到票据 **129 → 112**，成本基本不变 |

## Agent v2

- **Plan DAG** + **Verifier** + **Replan**：工具调用先校验 allowlist、Schema、依赖、环、预算。
- 30 个任务、3 种策略：raw 27/30，verified 27/30，**adaptive 30/30**。
- raw 有 1 个 false success；adaptive 通过重规划把 recovery 类任务做到 3/3，验证通过率 86.7%。
- 工具层覆盖预测、库存、布点、分单、诊断、报告、RAG。

## 工程

- Python 3.9+；OR-Tools CP-SAT、LightGBM、pandas/numpy、FastAPI、Streamlit。
- **46 个 `test_*.py` + quick_test，345 passed**。
- Markdown + JSON 双输出；固定 seed；CI 覆盖核心 smoke。
- 5 分钟演示：`python scripts/demo.py`，无需 API Key。

## 复现

```bash
pip install -e ".[dev]"
python scripts/demo.py
python scripts/run_backtest.py
python scripts/run_e2e_benchmark.py
python scripts/run_agent_v2_benchmark.py
pytest -q
```

完整说明：[`README.md`](README.md)

基准摘要：[`benchmarks/FINAL_SUMMARY.md`](benchmarks/FINAL_SUMMARY.md)

## 边界

- 仿真基准，不是生产系统；库存、时效、门位、报价是显式假设。
- 默认 Agent planner 是确定性 DAG；真实 LLM 规划需单独配置并报告方差/成本。
- 单数据集、单 season；推广前需重新校准。
