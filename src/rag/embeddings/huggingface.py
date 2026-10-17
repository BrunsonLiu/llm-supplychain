"""
HuggingFace嵌入模型
"""
from typing import List
from .base import BaseEmbeddings


class HuggingFaceEmbeddings(BaseEmbeddings):
    """HuggingFace嵌入模型"""
    
    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        device: str = None,
        **kwargs
    ):
        try:
            from sentence_transformers import SentenceTransformer
            self.SentenceTransformer = SentenceTransformer
        except ImportError:
            raise ImportError("Please install sentence-transformers: pip install sentence-transformers")
        
        self.model_name = model_name
        self.device = device
        self.kwargs = kwargs
        
        # 加载模型
        self.model = SentenceTransformer(model_name, device=device, **kwargs)
    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """批量嵌入文档"""
        embeddings = self.model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()
    
    def embed_query(self, text: str) -> List[float]:
        """嵌入查询文本"""
        embedding = self.model.encode([text], convert_to_numpy=True)
        return embedding[0].tolist()
