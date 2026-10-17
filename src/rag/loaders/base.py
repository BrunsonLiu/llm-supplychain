"""
文档加载器基类
"""
from abc import ABC, abstractmethod
from typing import List, Iterator
from ..document import Document


class BaseLoader(ABC):
    """文档加载器基类"""
    
    @abstractmethod
    def load(self) -> List[Document]:
        """加载文档"""
        pass
    
    @abstractmethod
    def lazy_load(self) -> Iterator[Document]:
        """惰性加载文档"""
        pass
