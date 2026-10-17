"""
OpenAI 兼容嵌入模型

默认模型为 text-embedding-3-small（ada-002 的继任者，更便宜、效果更好）。
支持任何 OpenAI 兼容端点，api_key / base_url 可从环境变量回退读取。
"""
import os
from typing import List, Optional
import numpy as np
from .base import BaseEmbeddings


class OpenAIEmbeddings(BaseEmbeddings):
    """OpenAI 兼容嵌入模型实现"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "text-embedding-3-small",
        **kwargs
    ):
        try:
            import openai
            self.openai = openai
        except ImportError:
            raise ImportError("Please install openai: pip install openai")
        
        # 环境变量回退，便于接入 OpenAI 兼容服务
        api_key = api_key or os.environ.get("OPENAI_API_KEY")
        base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.client_kwargs = kwargs
        
        # 创建客户端（OpenAI 兼容端点均可）
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url, **kwargs)
    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """批量嵌入文档"""
        # OpenAI API有批处理限制，这里分段处理
        batch_size = 100
        all_embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            response = self.client.embeddings.create(
                model=self.model,
                input=batch
            )
            embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(embeddings)
        
        return all_embeddings
    
    def embed_query(self, text: str) -> List[float]:
        """嵌入查询文本"""
        response = self.client.embeddings.create(
            model=self.model,
            input=[text]
        )
        return response.data[0].embedding


class MockEmbeddings(BaseEmbeddings):
    """模拟嵌入模型（确定性词袋哈希向量）

    原版用"整文本 MD5 随机向量"——语义无关的文本也得到无关随机向量，
    相似度检索退化为随机排序（问"安全库存"可能返回任何文档）。
    本版改为词袋哈希：token 经稳定哈希（crc32）映射到固定维度桶计数，
    余弦相似度反映词汇重合度。中文按 单字+二元组 切分，免分词器。

    局限：只捕捉词汇重合，无语义理解（"库存"与"存货"不匹配）。
    仅用于测试和无 API Key 演示；真实场景请用 OpenAIEmbeddings /
    HuggingFaceEmbeddings。
    """

    def __init__(self, dimension: int = 1536):
        self.dimension = dimension

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        import re
        text = text.lower()
        tokens = re.findall(r"[a-z0-9]+", text)
        for seg in re.findall(r"[\u4e00-\u9fff]+", text):
            tokens.extend(seg)  # 中文单字
            tokens.extend(seg[i:i + 2] for i in range(len(seg) - 1))  # 二元组
        return tokens

    def _embed_one(self, text: str) -> List[float]:
        import zlib
        vec = np.zeros(self.dimension, dtype=np.float32)
        for tok in self._tokenize(text):
            idx = zlib.crc32(tok.encode("utf-8")) % self.dimension
            vec[idx] += 1.0
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """生成确定性词袋嵌入向量"""
        return [self._embed_one(t) for t in texts]

    def embed_query(self, text: str) -> List[float]:
        """嵌入查询文本"""
        return self._embed_one(text)
