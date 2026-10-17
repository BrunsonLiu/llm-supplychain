"""
内存向量存储
使用FAISS或简单余弦相似度
"""
import json
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import numpy as np
from .base import BaseVectorStore
from ..document import Document


class MemoryVectorStore(BaseVectorStore):
    """内存向量存储"""
    
    def __init__(self):
        self.documents: List[Document] = []
        self.embeddings: np.ndarray = None
        self.ids: List[str] = []
    
    def add_documents(self, documents: List[Document], embeddings: List[List[float]]) -> None:
        """添加文档和嵌入向量"""
        if len(documents) != len(embeddings):
            raise ValueError("文档数量和嵌入向量数量不匹配")
        
        # 归一化嵌入向量
        embeddings_array = np.array(embeddings, dtype=np.float32)
        norms = np.linalg.norm(embeddings_array, axis=1, keepdims=True)
        norms[norms == 0] = 1  # 避免除零
        embeddings_array = embeddings_array / norms
        
        if self.embeddings is None:
            self.embeddings = embeddings_array
            self.documents = list(documents)
        else:
            self.embeddings = np.vstack([self.embeddings, embeddings_array])
            self.documents.extend(documents)
        
        # 生成ID
        start_idx = len(self.ids)
        for i in range(len(documents)):
            self.ids.append(f"doc_{start_idx + i}")
    
    def similarity_search(
        self, 
        query_embedding: List[float], 
        k: int = 4,
        **kwargs
    ) -> List[Tuple[Document, float]]:
        """相似性搜索（余弦相似度）"""
        if self.embeddings is None or len(self.documents) == 0:
            return []
        
        # 归一化查询向量
        query_array = np.array(query_embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query_array)
        if query_norm > 0:
            query_array = query_array / query_norm
        
        # 计算余弦相似度
        similarities = np.dot(self.embeddings, query_array)
        
        # 获取top k
        top_k_indices = np.argsort(similarities)[::-1][:k]
        
        results = []
        for idx in top_k_indices:
            results.append((self.documents[idx], float(similarities[idx])))
        
        return results
    
    def delete(self, ids: List[str]) -> None:
        """删除文档"""
        indices_to_delete = []
        for doc_id in ids:
            if doc_id in self.ids:
                indices_to_delete.append(self.ids.index(doc_id))
        
        # 从后往前删除，避免索引变化
        for idx in sorted(indices_to_delete, reverse=True):
            del self.documents[idx]
            del self.ids[idx]
        
        if indices_to_delete and self.embeddings is not None:
            mask = np.ones(len(self.embeddings), dtype=bool)
            mask[indices_to_delete] = False
            self.embeddings = self.embeddings[mask]
    
    def clear(self) -> None:
        """清空存储"""
        self.documents = []
        self.embeddings = None
        self.ids = []
    
    def save(self, path: str) -> None:
        """保存到磁盘"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            'documents': [
                {
                    'page_content': doc.page_content,
                    'metadata': doc.metadata
                }
                for doc in self.documents
            ],
            'ids': self.ids
        }
        
        # 保存文档和元数据
        with open(path.with_suffix('.json'), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 保存嵌入向量
        if self.embeddings is not None:
            np.save(path.with_suffix('.npy'), self.embeddings)
    
    def load(self, path: str) -> None:
        """从磁盘加载"""
        path = Path(path)
        
        # 加载文档和元数据
        with open(path.with_suffix('.json'), 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        self.documents = [
            Document(page_content=doc['page_content'], metadata=doc['metadata'])
            for doc in data['documents']
        ]
        self.ids = data['ids']
        
        # 加载嵌入向量
        embeddings_path = path.with_suffix('.npy')
        if embeddings_path.exists():
            self.embeddings = np.load(embeddings_path)
        else:
            self.embeddings = None


class FAISSVectorStore(BaseVectorStore):
    """基于FAISS的向量存储"""
    
    def __init__(self, dimension: int = 1536):
        try:
            import faiss
            self.faiss = faiss
        except ImportError:
            raise ImportError("Please install faiss: pip install faiss-cpu 或 pip install faiss-gpu")
        
        self.dimension = dimension
        self.index = None
        self.documents: List[Document] = []
        self.ids: List[str] = []
    
    def add_documents(self, documents: List[Document], embeddings: List[List[float]]) -> None:
        """添加文档和嵌入向量"""
        if len(documents) != len(embeddings):
            raise ValueError("文档数量和嵌入向量数量不匹配")
        
        embeddings_array = np.array(embeddings, dtype=np.float32)
        
        if self.index is None:
            # 创建索引
            self.index = self.faiss.IndexFlatIP(self.dimension)  # 内积（对于归一化向量等于余弦相似度）
        
        # 归一化
        norms = np.linalg.norm(embeddings_array, axis=1, keepdims=True)
        norms[norms == 0] = 1
        embeddings_array = embeddings_array / norms
        
        # 添加到索引
        self.index.add(embeddings_array)
        self.documents.extend(documents)
        
        # 生成ID
        start_idx = len(self.ids)
        for i in range(len(documents)):
            self.ids.append(f"doc_{start_idx + i}")
    
    def similarity_search(
        self, 
        query_embedding: List[float], 
        k: int = 4,
        **kwargs
    ) -> List[Tuple[Document, float]]:
        """相似性搜索"""
        if self.index is None or self.index.ntotal == 0:
            return []
        
        # 归一化查询向量
        query_array = np.array([query_embedding], dtype=np.float32)
        query_norm = np.linalg.norm(query_array)
        if query_norm > 0:
            query_array = query_array / query_norm
        
        # 搜索
        k = min(k, self.index.ntotal)
        distances, indices = self.index.search(query_array, k)
        
        results = []
        for i, idx in enumerate(indices[0]):
            if idx >= 0 and idx < len(self.documents):
                results.append((self.documents[idx], float(distances[0][i])))
        
        return results
    
    def delete(self, ids: List[str]) -> None:
        """删除文档（FAISS不支持直接删除，这里简单地重新构建索引）"""
        indices_to_delete = []
        for doc_id in ids:
            if doc_id in self.ids:
                indices_to_delete.append(self.ids.index(doc_id))
        
        if not indices_to_delete:
            return
        
        # 从后往前删除文档
        for idx in sorted(indices_to_delete, reverse=True):
            del self.documents[idx]
            del self.ids[idx]
        
        # 重新构建索引
        if self.documents:
            # 这里需要重新计算所有嵌入向量
            # 由于我们没有保存原始嵌入向量，这里只能清空索引
            self.index = None
            print("Warning: Index cleared, please re-add documents with embeddings")
        else:
            self.index = None
    
    def clear(self) -> None:
        """清空存储"""
        self.index = None
        self.documents = []
        self.ids = []
    
    def save(self, path: str) -> None:
        """保存到磁盘"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # 保存FAISS索引
        if self.index is not None:
            self.faiss.write_index(self.index, str(path.with_suffix('.faiss')))
        
        # 保存文档
        data = {
            'documents': [
                {
                    'page_content': doc.page_content,
                    'metadata': doc.metadata
                }
                for doc in self.documents
            ],
            'ids': self.ids
        }
        
        with open(path.with_suffix('.json'), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def load(self, path: str) -> None:
        """从磁盘加载"""
        path = Path(path)
        
        # 加载FAISS索引
        index_path = path.with_suffix('.faiss')
        if index_path.exists():
            self.index = self.faiss.read_index(str(index_path))
        
        # 加载文档
        with open(path.with_suffix('.json'), 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        self.documents = [
            Document(page_content=doc['page_content'], metadata=doc['metadata'])
            for doc in data['documents']
        ]
        self.ids = data['ids']
