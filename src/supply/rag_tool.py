"""
RAG 检索工具

把 RAG 管线（加载 -> 分割 -> 嵌入 -> 检索 -> 生成）封装为 Agent 可调用的工具。
默认使用 MockEmbeddings/MockLLM，无需 API Key 即可运行；
传入 OpenAIEmbeddings/OpenAILLM 即切换为真实模型（支持任何 OpenAI 兼容端点）。
"""
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    TitleBoostRetriever,
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
        title_boost: float = 0.3,
    ):
        from rag import OpenAIEmbeddings, OpenAILLM
        self.embeddings = embeddings or MockEmbeddings()
        self.llm = llm or MockLLM()
        self.top_k = top_k
        self.title_boost = title_boost
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

        base = VectorRetriever(store, self.embeddings)
        retriever = (
            TitleBoostRetriever(
                base, boost=self.title_boost, title_fn=self._title
            )
            if self.title_boost > 0
            else base
        )
        return RAGChain(retriever=retriever, llm=self.llm, return_source_documents=True)

    def can_handle(self, prompt: str) -> bool:
        return any(kw in prompt for kw in RAG_KEYWORDS)

    @staticmethod
    def _title(text: str) -> str:
        for line in text.splitlines():
            line = line.strip().strip("#").strip()
            if line and not set(line) <= {"=", "-"}:
                return line[:80]
        return "未命名片段"

    def _citations(self, documents, scores: List[float]) -> List[Dict[str, Any]]:
        citations = []
        for index, (doc, score) in enumerate(zip(documents, scores), start=1):
            metadata = doc.metadata or {}
            source = metadata.get("filename") or metadata.get("source") or "unknown"
            citations.append(
                {
                    "id": index,
                    "source": str(source),
                    "title": self._title(doc.page_content),
                    "score": float(score),
                    "chunk_index": metadata.get("chunk_index"),
                    "snippet": doc.page_content[:240],
                }
            )
        return citations

    def _format_citations(self, citations: List[Dict[str, Any]]) -> str:
        return "\n".join(
            f"[{item['id']}] {item['source']} · {item['title']}"
            for item in citations
        )

    def run(self, prompt: str, top_k: int = None):
        k = top_k or self.top_k
        retriever = self.chain.retriever
        # VectorRetriever 提供带相似度的检索，保留分数用于引用排序
        scored = retriever.retrieve_with_scores(prompt, k=k)
        documents = [doc for doc, _ in scored]
        citations = self._citations(documents, [score for _, score in scored])

        # Mock 模式不生成伪回答（模板字符串没有信息量），
        # 直接返回检索到的知识片段，如实演示检索效果
        if isinstance(self.llm, MockLLM):
            if not documents:
                answer = "（未检索到相关知识片段）"
            else:
                fragments = "\n\n".join(
                    f"[{item['id']}] {item['title']}\n{item['snippet']}"
                    for item in citations
                )
                answer = "【未配置 LLM，以下为检索到的知识片段】\n\n" + fragments
                answer += "\n\n参考来源：\n" + self._format_citations(citations)
            return {
                "status": "success",
                "question": prompt,
                "answer": answer,
                "citations": citations,
                "sources": [item["snippet"] for item in citations],
            }

        result = self.chain.run(prompt, k=k)
        answer = result["answer"].rstrip()
        if citations:
            answer += "\n\n参考来源：\n" + self._format_citations(citations)
        return {
            "status": "success",
            "question": result["question"],
            "answer": answer,
            "citations": citations,
            "sources": [item["snippet"] for item in citations],
        }
