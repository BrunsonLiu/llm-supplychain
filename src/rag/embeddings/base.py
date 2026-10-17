"""
嵌入模型基类
"""
from abc import ABC, abstractmethod
from typing import List


class BaseEmbeddings(ABC):
    """嵌入模型基类"""
    
    @abstractmethod
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """将文档列表转换为嵌入向量"""
        pass
    
    @abstractmethod
    def embed_query(self, text: str) -> List[float]:
        """将查询文本转换为嵌入向量"""
        pass
    
    def embed_document(self, text: str) -> List[float]:
        """将单个文档转换为嵌入向量"""
        return self.embed_documents([text])[0]
