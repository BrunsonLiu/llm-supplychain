"""
文本分割器基类
"""
from abc import ABC, abstractmethod
from typing import List
from ..document import Document


class BaseSplitter(ABC):
    """文本分割器基类"""
    
    @abstractmethod
    def split_text(self, text: str) -> List[str]:
        """将文本分割成多个片段"""
        pass
    
    def split_documents(self, documents: List[Document]) -> List[Document]:
        """将文档分割成多个片段"""
        split_docs = []
        for doc in documents:
            chunks = self.split_text(doc.page_content)
            for i, chunk in enumerate(chunks):
                metadata = doc.metadata.copy()
                metadata['chunk_index'] = i
                metadata['chunk_count'] = len(chunks)
                split_docs.append(Document(page_content=chunk, metadata=metadata))
        return split_docs
