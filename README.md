# 供应链智能体（Supply Chain Agent）

一个**学习/演示用途**的供应链决策支持系统，由两个早期项目（`RAG项目` 的 RAG 管线 + `LLMandagentt` 的预测/库存工具链）合并重构而成，统一了目录结构、API 入口与技术栈。

## 诚实声明（先读这个）

这个项目**不是生产系统**，用之前请了解以下事实：

1. **数据全部是模拟生成的**——`generate_realistic_data` 合成带季节性/趋势/促销/节假日噪声的需求序列，不代表任何真实业务。导入真实数据请用 `DataImporter.import_csv` 或 `POST /data?action=import`。
2. **预测模型是教科书模型**——移动平均 + Holt 指数平滑 + 线性趋势的简单平均集成（numpy 手写，无第三方依赖）。无季节性分解、无置信区间真估计、无 ML/DL。生产环境应换 Prophet/statsmodels 或专门模型。
3. **"Agent" 是规则路由的工具编排器**——按关键词把指令分发给对应工具（数据/预测/库存/报告/RAG 检索），**不是** LLM 自主规划（无 ReAct/Function-Calling 循环）。升级路径见下文。
4. **Mock 嵌入只反映词汇重合**——无 API Key 时使用确定性词袋哈希向量（token 哈希到维度桶），检索按词汇重叠度排序，**无语义理解能力**（"库存"与"存货"不匹配）。配置 `OPENAI_API_KEY` 后自动切换真实嵌入。
5. **没有效果评估**——无预测回测（MAPE/RMSE 样本外验证）、无检索质量指标（Recall@k/MRR）。"能跑"不等于"好用"。

## 功能

| 模块 | 能力 |
|---|---|
| 数据 | 模拟数据生成 / CSV·JSON 导入 / SQLite 持久化 |
| 预测 | 三模型集成需求预测 + 简单置信区间 |
| 库存 | 安全库存（Z·σ·√LT）+ EOQ + 目标库存补货建议 |
| 报告 | 模板化决策报告 + 可选 LLM 执行摘要 |
| 知识库 | 文档加载 → 分节切分 → 嵌入 → 向量检索 → RAG 问答 |
| API | FastAPI：`/run` 决策流程、`/ask` 知识问答、`/data` 数据操作 |

## 快速开始

环境要求：Python 3.9+（开发验证用 3.13）。

```bash
pip install -r requirements.txt

# 一键演示（无需 API Key，RAG 走 Mock 模式）
PYTHONPATH=src;. python scripts/demo.py        # Windows
PYTHONPATH=src:. python scripts/demo.py        # Linux/macOS

# 测试（四件套，共 27+ 用例）
PYTHONPATH=src;. python tests/quick_test.py
PYTHONPATH=src;. python tests/test_rag.py
PYTHONPATH=src;. python tests/test_comprehensive.py
PYTHONPATH=src;. python tests/test_supply.py

# API 服务
PYTHONPATH=src;. uvicorn app.main:app --reload --port 8000
# 文档: http://localhost:8000/docs
```

### 接入真实 LLM（OpenAI 兼容端点）

设置环境变量即可，代码零改动；未设置时自动走 Mock：

```bash
# OpenAI
export OPENAI_API_KEY=sk-xxx

# DeepSeek（或任何 OpenAI 兼容服务）
export OPENAI_API_KEY=sk-xxx
export OPENAI_BASE_URL=https://api.deepseek.com
export LLM_MODEL=deepseek-chat
```

## 目录结构

```
供应链智能体/
├── src/
│   ├── rag/                  # RAG 核心（自实现，非 LangChain）
│   │   ├── loaders/          # 文本/JSON/CSV 加载
│   │   ├── splitters/        # 递归/字符/Markdown/按标题分节切分
│   │   ├── embeddings/       # OpenAI 兼容 / HuggingFace / Mock 词袋
│   │   ├── vectorstores/     # 内存 / FAISS
│   │   ├── retrievers/       # 向量 / 多查询 / 混合(BM25)
│   │   ├── llms/             # OpenAI 兼容 / Mock
│   │   ├── chains/           # RAG / 对话 / 决策 / Agentic 链
│   │   └── utils/            # 日志/缓存/重试/配置/管道构建器
│   └── supply/               # 供应链域
│       ├── agent.py          # SupplyChainAgent 统一入口（规则路由）
│       ├── tools.py          # 数据/预测/库存/报告工具
│       ├── rag_tool.py       # RAG 检索工具
│       ├── database.py       # SQLite
│       ├── data_import.py    # 数据导入与模拟生成
│       ├── forecast_models.py# 预测模型
│       └── i18n.py           # 中英文案
├── app/main.py               # FastAPI 统一入口
├── scripts/demo.py           # 一键演示
├── config/config.yaml        # 配置（默认 mock，密钥走环境变量）
├── data/documents/           # 知识库文档
└── tests/                    # 测试四件套
```

## 合并时修复的原项目缺陷

| # | 缺陷 | 修复 |
|---|---|---|
| 1 | `rag` 包循环导入（utils ↔ chains），**任何 `import rag` 必崩**，README 示例全部不可运行 | `pipeline_builder` 改为从具体子模块导入 + PEP 562 延迟加载 |
| 2 | `库存周期=N` 被预测工具截走（"周期"关键词过宽） | 预测工具增加排他条件 |
| 3 | 递归切分器 overlap 回填后超出 `chunk_size` | 三处 overlap 逻辑统一改为"放不下则放弃 overlap" |
| 4 | Mock 嵌入用整文本 MD5 随机向量，检索结果纯随机 | 改为确定性词袋哈希（中文单字+二元组），检索反映词汇重合 |
| 5 | 中文知识文档按行硬切，语义条目被切断 | 新增 `HeadingSectionSplitter` 按标题分节切分 |
| 6 | 旧 examples 会往知识库目录写文件，污染检索源 | 删除 examples，统一由 `scripts/demo.py` 演示 |
| 7 | `gpt-3.5-turbo` / `text-embedding-ada-002` 过时默认值 | `gpt-4o-mini` / `text-embedding-3-small`，且全部可配 |
| 8 | API Key 只能写死在 config.yaml | 环境变量回退（`OPENAI_API_KEY`/`DEEPSEEK_API_KEY`/`OPENAI_BASE_URL`） |

## 已知局限与升级路径

- **检索**：词袋 Mock 无语义理解；换 `OpenAIEmbeddings` 或本地 `sentence-transformers` 即有真语义检索。数据量大后把 `MemoryVectorStore` 换 `FAISSVectorStore`。
- **Agent**：规则路由换 LLM Function Calling（工具接口已就绪，改 `_route` 一处即可）。
- **预测**：加样本外回测与模型选择（按 MAPE 自动选），引入 Prophet/ARIMA。
- **评估**：补检索指标（Recall@k）与预测回测报告，用数据说话而不是"看起来能跑"。

## 技术栈

Python 3.9+ · numpy · pydantic · PyYAML · openai（兼容 SDK）· FastAPI · uvicorn · rank-bm25 · SQLite · pytest
