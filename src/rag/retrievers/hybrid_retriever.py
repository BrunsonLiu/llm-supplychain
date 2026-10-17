"""
混合检索器
结合 BM25 关键词检索和向量检索
"""
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict
from rank_bm25 import BM25Okapi
import numpy as np
from .base import BaseRetriever
from ..document import Document
from ..embeddings.base import BaseEmbeddings
from ..vectorstores.base import BaseVectorStore
from ..utils import get_logger, PerformanceLogger

logger = get_logger(__name__)


class BM25Retriever:
    """BM25 关键词检索器"""
    
    def __init__(self):
        self.bm25 = None
        self.documents: List[Document] = []
        self.tokenized_docs: List[List[str]] = []
    
    def add_documents(self, documents: List[Document]) -> None:
        """
        添加文档到 BM25 索引
        
        Args:
            documents: 文档列表
        """
        self.documents = documents
        
        # 简单分词（按空格和标点）
        self.tokenized_docs = [
            self._tokenize(doc.page_content)
            for doc in documents
        ]
        
        # 创建 BM25 索引
        self.bm25 = BM25Okapi(self.tokenized_docs)
        logger.info(f"BM25 索引创建完成，包含 {len(documents)} 个文档")
    
    def search(self, query: str, k: int = 4) -> List[Tuple[Document, float]]:
        """
        BM25 搜索
        
        Args:
            query: 查询文本
            k: 返回结果数量
            
        Returns:
            文档和分数列表
        """
        if self.bm25 is None:
            return []
        
        # 分词
        tokenized_query = self._tokenize(query)
        
        # 获取 BM25 分数
        scores = self.bm25.get_scores(tokenized_query)
        
        # 获取 top-k
        top_indices = np.argsort(scores)[::-1][:k]
        
        results = []
        for idx in top_indices:
            if scores[idx] > 0:
                results.append((self.documents[idx], float(scores[idx])))
        
        return results
    
    def _tokenize(self, text: str) -> List[str]:
        """
        简单分词
        
        Args:
            text: 输入文本
            
        Returns:
            分词结果
        """
        # 简单实现：按空格分割，去除标点
        import re
        # 保留中文、英文、数字
        tokens = re.findall(r'[\u4e00-\u9fa5a-zA-Z0-9]+', text)
        return tokens


class HybridRetriever(BaseRetriever):
    """
    混合检索器
    结合向量检索和 BM25 关键词检索
    """
    
    def __init__(
        self,
        vector_store: BaseVectorStore,
        embeddings: BaseEmbeddings,
        bm25_weight: float = 0.3,
        vector_weight: float = 0.7,
        use_hybrid: bool = True
    ):
        """
        初始化混合检索器
        
        Args:
            vector_store: 向量存储
            embeddings: 嵌入模型
            bm25_weight: BM25 权重
            vector_weight: 向量检索权重
            use_hybrid: 是否使用混合检索
        """
        self.vector_store = vector_store
        self.embeddings = embeddings
        self.bm25_weight = bm25_weight
        self.vector_weight = vector_weight
        self.use_hybrid = use_hybrid
        
        # 创建 BM25 检索器
        self.bm25_retriever = BM25Retriever()
        
        logger.info(
            f"HybridRetriever 初始化 - "
            f"BM25权重: {bm25_weight}, 向量权重: {vector_weight}, "
            f"混合模式: {use_hybrid}"
        )
    
    def add_documents(self, documents: List[Document]) -> None:
        """
        添加文档
        
        Args:
            documents: 文档列表
        """
        # 添加到 BM25
        self.bm25_retriever.add_documents(documents)
        
        # 向量存储由外部添加
        logger.info(f"添加了 {len(documents)} 个文档到混合检索器")
    
    def retrieve(self, query: str, k: int = 4, **kwargs) -> List[Document]:
        """
        检索相关文档
        
        Args:
            query: 查询文本
            k: 返回结果数量
            **kwargs: 其他参数
            
        Returns:
            相关文档列表
        """
        with PerformanceLogger(logger, f"HybridRetriever.retrieve: {query[:30]}"):
            if not self.use_hybrid:
                # 仅使用向量检索
                return self._vector_search(query, k)
            
            # 混合检索
            bm25_results = self.bm25_retriever.search(query, k=k * 2)
            vector_results = self._vector_search_with_scores(query, k=k * 2)
            
            # 融合结果
            merged_results = self._merge_results(
                bm25_results,
                vector_results,
                k=k
            )
            
            # 返回文档
            return [doc for doc, _ in merged_results]
    
    def _vector_search(self, query: str, k: int = 4) -> List[Document]:
        """向量检索"""
        query_embedding = self.embeddings.embed_query(query)
        results = self.vector_store.similarity_search(query_embedding, k=k)
        return [doc for doc, _ in results]
    
    def _vector_search_with_scores(
        self,
        query: str,
        k: int = 4
    ) -> List[Tuple[Document, float]]:
        """带分数的向量检索"""
        query_embedding = self.embeddings.embed_query(query)
        return self.vector_store.similarity_search(query_embedding, k=k)
    
    def _merge_results(
        self,
        bm25_results: List[Tuple[Document, float]],
        vector_results: List[Tuple[Document, float]],
        k: int = 4
    ) -> List[Tuple[Document, float]]:
        """
        融合 BM25 和向量检索结果
        
        Args:
            bm25_results: BM25 结果
            vector_results: 向量检索结果
            k: 返回结果数量
            
        Returns:
            融合后的结果
        """
        # 归一化分数
        bm25_scores = [score for _, score in bm25_results]
        vector_scores = [score for _, score in vector_results]
        
        bm25_normalized = self._normalize_scores(bm25_scores)
        vector_normalized = self._normalize_scores(vector_scores)
        
        # 合并分数
        doc_scores = defaultdict(float)
        doc_map = {}
        
        for i, (doc, _) in enumerate(bm25_results):
            doc_id = id(doc)
            doc_scores[doc_id] += bm25_normalized[i] * self.bm25_weight
            doc_map[doc_id] = doc
        
        for i, (doc, _) in enumerate(vector_results):
            doc_id = id(doc)
            doc_scores[doc_id] += vector_normalized[i] * self.vector_weight
            doc_map[doc_id] = doc
        
        # 排序
        sorted_docs = sorted(
            doc_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )[:k]
        
        results = [(doc_map[doc_id], score) for doc_id, score in sorted_docs]
        
        logger.info(
            f"混合检索完成 - BM25结果: {len(bm25_results)}, "
            f"向量结果: {len(vector_results)}, "
            f"融合结果: {len(results)}"
        )
        
        return results
    
    def _normalize_scores(self, scores: List[float]) -> List[float]:
        """
        归一化分数到 0-1 范围
        
        Args:
            scores: 原始分数
            
        Returns:
            归一化后的分数
        """
        if not scores:
            return []
        
        min_score = min(scores)
        max_score = max(scores)
        
        if max_score == min_score:
            return [1.0 if s > 0 else 0.0 for s in scores]
        
        return [(s - min_score) / (max_score - min_score) for s in scores]
