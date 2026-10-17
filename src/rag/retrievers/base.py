"""
检索器基类
"""
from abc import ABC, abstractmethod
from typing import List, Tuple
from .. import Document


class BaseRetriever(ABC):
    """检索器基类"""
    
    @abstractmethod
    def retrieve(self, query: str, k: int = 4) -> List[Document]:
        """检索相关文档"""
        pass
    
    @abstractmethod
    def retrieve_with_scores(self, query: str, k: int = 4) -> List[Tuple[Document, float]]:
        """检索相关文档并返回相似度分数"""
        pass
