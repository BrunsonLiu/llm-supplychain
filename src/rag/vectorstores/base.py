"""
向量存储基类
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from ..document import Document


class BaseVectorStore(ABC):
    """向量存储基类"""
    
    @abstractmethod
    def add_documents(self, documents: List[Document], embeddings: List[List[float]]) -> None:
        """添加文档和对应的嵌入向量"""
        pass
    
    @abstractmethod
    def similarity_search(
        self, 
        query_embedding: List[float], 
        k: int = 4,
        **kwargs
    ) -> List[Tuple[Document, float]]:
        """
        相似性搜索
        返回: [(document, score), ...]
        """
        pass
    
    @abstractmethod
    def delete(self, ids: List[str]) -> None:
        """删除文档"""
        pass
    
    @abstractmethod
    def clear(self) -> None:
        """清空存储"""
        pass
    
    def save(self, path: str) -> None:
        """保存到磁盘（可选）"""
        pass
    
    def load(self, path: str) -> None:
        """从磁盘加载（可选）"""
        pass
