"""
向量检索器
"""
from typing import List, Tuple
from .base import BaseRetriever
from .. import Document
from ..embeddings.base import BaseEmbeddings
from ..vectorstores.base import BaseVectorStore


class VectorRetriever(BaseRetriever):
    """基于向量的检索器"""
    
    def __init__(
        self,
        vector_store: BaseVectorStore,
        embeddings: BaseEmbeddings,
        search_kwargs: dict = None
    ):
        self.vector_store = vector_store
        self.embeddings = embeddings
        self.search_kwargs = search_kwargs or {}
    
    def retrieve(self, query: str, k: int = 4) -> List[Document]:
        """检索相关文档"""
        # 将查询转换为嵌入向量
        query_embedding = self.embeddings.embed_query(query)
        
        # 在向量存储中搜索
        results = self.vector_store.similarity_search(
            query_embedding, 
            k=k,
            **self.search_kwargs
        )
        
        # 返回文档列表
        return [doc for doc, _ in results]
    
    def retrieve_with_scores(self, query: str, k: int = 4) -> List[Tuple[Document, float]]:
        """检索相关文档并返回分数"""
        # 将查询转换为嵌入向量
        query_embedding = self.embeddings.embed_query(query)
        
        # 在向量存储中搜索
        return self.vector_store.similarity_search(
            query_embedding, 
            k=k,
            **self.search_kwargs
        )


class MultiQueryRetriever(BaseRetriever):
    """多查询检索器 - 生成多个查询变体来提高检索效果"""
    
    def __init__(
        self,
        base_retriever: BaseRetriever,
        llm = None,  # 用于生成查询变体
        num_queries: int = 3
    ):
        self.base_retriever = base_retriever
        self.llm = llm
        self.num_queries = num_queries
    
    def _generate_queries(self, query: str) -> List[str]:
        """生成查询变体"""
        if self.llm is None:
            # 如果没有LLM，使用简单的变体
            return [query]
        
        # 使用LLM生成查询变体
        prompt = f"""请基于以下问题生成{self.num_queries}个不同的表述方式，用于搜索相关信息。
问题：{query}

请只返回查询列表，每行一个："""
        
        try:
            response = self.llm.generate(prompt)
            queries = [q.strip() for q in response.strip().split('\n') if q.strip()]
            # 确保原始查询也在列表中
            if query not in queries:
                queries.insert(0, query)
            return queries[:self.num_queries]
        except:
            return [query]
    
    def retrieve(self, query: str, k: int = 4) -> List[Document]:
        """检索相关文档"""
        queries = self._generate_queries(query)
        
        all_results = []
        seen_contents = set()
        
        for q in queries:
            results = self.base_retriever.retrieve(q, k=k)
            for doc in results:
                if doc.page_content not in seen_contents:
                    all_results.append(doc)
                    seen_contents.add(doc.page_content)
        
        return all_results[:k]
    
    def retrieve_with_scores(self, query: str, k: int = 4) -> List[Tuple[Document, float]]:
        """检索相关文档并返回分数"""
        queries = self._generate_queries(query)
        
        all_results = []
        seen_contents = set()
        
        for q in queries:
            results = self.base_retriever.retrieve_with_scores(q, k=k)
            for doc, score in results:
                if doc.page_content not in seen_contents:
                    all_results.append((doc, score))
                    seen_contents.add(doc.page_content)
        
        # 按分数排序
        all_results.sort(key=lambda x: x[1], reverse=True)
        return all_results[:k]
