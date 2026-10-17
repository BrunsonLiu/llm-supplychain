"""
RAG 检索工具

把 RAG 管线（加载 -> 分割 -> 嵌入 -> 检索 -> 生成）封装为 Agent 可调用的工具。
默认使用 MockEmbeddings/MockLLM，无需 API Key 即可运行；
传入 OpenAIEmbeddings/OpenAILLM 即切换为真实模型（支持任何 OpenAI 兼容端点）。
"""
import sys
from pathlib import Path
from typing import Optional

from .tools import Tool

# 保证 src 在路径中（兼容 `python scripts/demo.py` 直接运行）
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from rag import (
    TextLoader,
    HeadingSectionSplitter,
    MemoryVectorStore,
    VectorRetriever,
    RAGChain,
    MockEmbeddings,
    MockLLM,
)

# 触发检索的关键词（与预测/库存/报告工具的关键词不重叠）
RAG_KEYWORDS = ("知识", "文档", "资料", "手册", "什么是", "如何", "为什么", "怎么",
                "什么", "？", "?", "了解", "介绍", "解释")


class RAGTool(Tool):
    """供应链知识库检索问答工具"""

    name = "rag"

    def __init__(
        self,
        documents_dir: str = None,
        embeddings=None,
        llm=None,
        chunk_size: int = 500,
        chunk_overlap: int = 100,
        top_k: int = 3,
    ):
        from rag import OpenAIEmbeddings, OpenAILLM
        self.embeddings = embeddings or MockEmbeddings()
        self.llm = llm or MockLLM()
        self.top_k = top_k
        self._openai_cls = (OpenAIEmbeddings, OpenAILLM)

        # 文档目录：默认 <项目根>/data/documents
        if documents_dir is None:
            documents_dir = _SRC.parent / "data" / "documents"
        self.documents_dir = Path(documents_dir)

        # 构建 RAG 链（无文档时也能构造，检索返回空结果）
        self.chain = self._build_chain(chunk_size, chunk_overlap)

    def _build_chain(self, chunk_size: int, chunk_overlap: int) -> RAGChain:
        docs = []
        if self.documents_dir.is_dir():
            loader = TextLoader(self.documents_dir)
            docs = loader.load()

        # 默认按标题分节切分，保证每个知识条目（标题+正文）语义完整；
        # chunk_size 参数保留兼容，作为分节后的上限
        splitter = HeadingSectionSplitter(max_chunk_size=max(chunk_size, 300))
        chunks = splitter.split_documents(docs) if docs else []

        store = MemoryVectorStore()
        if chunks:
            store.add_documents(
                chunks,
                self.embeddings.embed_documents([c.page_content for c in chunks]),
            )

        retriever = VectorRetriever(store, self.embeddings)
        return RAGChain(retriever=retriever, llm=self.llm, return_source_documents=True)

    def can_handle(self, prompt: str) -> bool:
        return any(kw in prompt for kw in RAG_KEYWORDS)

    def run(self, prompt: str, top_k: int = None):
        k = top_k or self.top_k
        # Mock 模式不生成伪回答（模板字符串没有信息量），
        # 直接返回检索到的知识片段，如实演示检索效果
        if isinstance(self.llm, MockLLM):
            docs = self.chain.retriever.retrieve(prompt, k=k)
            if not docs:
                answer = "（未检索到相关知识片段）"
            else:
                answer = "【未配置 LLM，以下为检索到的知识片段】\n\n" + \
                    "\n\n---\n\n".join(d.page_content[:300] for d in docs)
            return {
                "status": "success",
                "question": prompt,
                "answer": answer,
                "sources": [d.page_content[:120] for d in docs],
            }

        result = self.chain.run(prompt, k=k)
        return {
            "status": "success",
            "question": result["question"],
            "answer": result["answer"],
            "sources": [
                d.page_content[:120] for d in result.get("source_documents", [])
            ],
        }
