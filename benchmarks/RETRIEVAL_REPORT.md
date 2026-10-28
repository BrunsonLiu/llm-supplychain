# Retrieval evaluation

- Generated: `2026-10-27T17:59:33.685364+00:00`
- Embeddings: `mock` (deterministic word-bag hashing, no API key)
- Corpus: **2** documents / **34** heading-level chunks; **15** labeled Chinese queries
- Retrievers: vector-only baseline vs title-boosted re-ranking (boost=0.3)

## Comparison

| retriever | Recall@1 | Recall@3 | Recall@5 | MRR@5 | Hit@3 |
|---|---|---|---|---|---|
| vector | 86.7% | 90.0% | 100.0% | 0.917 | 93.3% |
| title-boost | 96.7% | 96.7% | 100.0% | 1.000 | 100.0% |

## Per-query results (k=3)

| query | labeled relevant chunk(s) | vector rank | boosted rank | boosted top-3 | recall | RR |
|---|---|---|---|---|---|---|
| 安全库存怎么计算 | 1. 安全库存（Safety Stock） | — | 1 | 1. 安全库存（Safety Stock） · 4. 服务水平（Service Level） · 2. 再订货点（Reorder Point） | 1.000 | 1.000 |
| 什么时候该补货 | 2. 再订货点（Reorder Point） | 1 | 1 | 2. 再订货点（Reorder Point） · 3. 经济订货批量（EOQ） · 2. 订货提前期（Lead Time） | 1.000 | 1.000 |
| 经济订货批量的公式 | 3. 经济订货批量（EOQ） | 1 | 1 | 3. 经济订货批量（EOQ） · 2. 大批量订货可降低单位订货成本，但推高持有成本和滞销风险；小批量多 · 2. 再订货点（Reorder Point） | 1.000 | 1.000 |
| 提高服务水平会怎样 | 4. 服务水平（Service Level） | 1 | 1 | 4. 服务水平（Service Level） · 2. 服务质量：评估供应商的服务水平 · 2. 指数平滑法（Exponential Smoothing） | 1.000 | 1.000 |
| ABC 分类法怎么用 | 5. ABC 分类法 | 1 | 1 | 5. ABC 分类法 · 2. 分散投资：不要把所有鸡蛋放在一个篮子里 · 一、需求预测方法 | 1.000 | 1.000 |
| 牛鞭效应是什么 | 1. 牛鞭效应（Bullwhip Effect） | 1 | 1 | 1. 牛鞭效应（Bullwhip Effect） · 3. 促销期需求激增具有前置透支效应（需求前移），促销后的预测应剔除 · 3. 交付能力：考察供应商的交付记录 | 1.000 | 1.000 |
| 提前期对库存的影响 | 2. 订货提前期（Lead Time） | 1 | 1 | 2. 订货提前期（Lead Time） · 2. 再订货点（Reorder Point） · 1. 安全库存（Safety Stock） | 1.000 | 1.000 |
| 库存周转率低意味着什么 | 3. 库存周转率 | 1 | 1 | 3. 库存周转率 · 二、库存管理 · 2. 再订货点（Reorder Point） | 1.000 | 1.000 |
| 如何评估预测误差 | 5. 预测误差评估 | 1 | 1 | 5. 预测误差评估 · 1. 风险评估：投资前必须评估风险承受能力 · 一、需求预测方法 | 1.000 | 1.000 |
| 移动平均法适合什么场景 | 1. 移动平均法（Moving Average） | 1 | 1 | 1. 移动平均法（Moving Average） · 3. 长期投资：股票投资适合长期持有 · 4. 集成预测（Ensemble） | 1.000 | 1.000 |
| Holt 双参数法怎么用 | 2. 指数平滑法（Exponential Smoothing） | 1 | 1 | 2. 指数平滑法（Exponential Smoothing） · 5. ABC 分类法 · 供应链管理基础知识库 | 1.000 | 1.000 |
| 多个预测模型怎么组合 | 4. 集成预测（Ensemble） | 1 | 1 | 4. 集成预测（Ensemble） · 一、需求预测方法 · 4. 定期评估：定期评估投资组合表现 | 1.000 | 1.000 |
| 供应商选择要看哪些指标 | 1. 供应商选择应综合评估 / 1. 价格因素：比较不同供应商的报价 | 2 | 1 | 1. 供应商选择应综合评估：价格、质量合格率、交付准时率、财务稳定性、 · 4. 可维护性：考虑长期维护成本 · 2. 服务质量：评估供应商的服务水平 | 0.500 | 1.000 |
| 促销后预测要注意什么 | 3. 促销期需求激增 | 1 | 1 | 3. 促销期需求激增具有前置透支效应（需求前移），促销后的预测应剔除 · 一、需求预测方法 · 4. 集成预测（Ensemble） | 1.000 | 1.000 |
| 大批量订货的利弊 | 2. 大批量订货 | 1 | 1 | 2. 大批量订货可降低单位订货成本，但推高持有成本和滞销风险；小批量多 · 3. 经济订货批量（EOQ） · 2. 再订货点（Reorder Point） | 1.000 | 1.000 |

## Notes and limitations

- Title boost is a lexical re-ranker: it adds `boost × (query terms shared with the first heading / query terms)` to the base retrieval score. It helps when the title contains the question's words, not when the question is a paraphrase.
- `boost=0.3` is a fixed heuristic, not tuned on a held-out set; the 15 queries are a small regression suite, so treat the delta as directional rather than a general benchmark.
- Labels mark the minimal chunk(s) needed to answer each query; they are not an exhaustive relevance judgment over all chunks.
- `mock` embeddings only capture lexical overlap (Chinese single characters plus bigrams), so the vector-only baseline is intentionally weak. Run `--embeddings openai` for a model-backed comparison.