"""
RAG项目 - 基础文档类
"""
from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class Document:
    """文档类，用于存储文本内容和元数据"""
    page_content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __repr__(self):
        return f"Document(content='{self.page_content[:50]}...', metadata={self.metadata})"
