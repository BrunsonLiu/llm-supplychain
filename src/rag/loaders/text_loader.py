"""
文本文件加载器
"""
import os
from pathlib import Path
from typing import List, Union, Iterator
from .base import BaseLoader
from ..document import Document


class TextLoader(BaseLoader):
    """加载文本文件"""
    
    def __init__(self, file_path: Union[str, Path], encoding: str = 'utf-8'):
        self.file_path = Path(file_path)
        self.encoding = encoding
    
    def load(self) -> List[Document]:
        """加载文本文件"""
        documents = []
        
        if self.file_path.is_dir():
            # 如果是目录，递归加载所有文本文件
            for file_path in self.file_path.rglob('*.txt'):
                documents.extend(self._load_file(file_path))
        else:
            documents = self._load_file(self.file_path)
        
        return documents
    
    def _load_file(self, file_path: Path) -> List[Document]:
        """加载单个文件"""
        try:
            with open(file_path, 'r', encoding=self.encoding, errors='ignore') as f:
                text = f.read()
            
            metadata = {
                'source': str(file_path),
                'filename': file_path.name,
                'file_type': 'text',
                'size': os.path.getsize(file_path)
            }
            
            return [Document(page_content=text, metadata=metadata)]
        except Exception as e:
            print(f"Error loading file {file_path}: {e}")
            return []
    
    def lazy_load(self) -> Iterator[Document]:
        """惰性加载"""
        if self.file_path.is_dir():
            for file_path in self.file_path.rglob('*.txt'):
                docs = self._load_file(file_path)
                for doc in docs:
                    yield doc
        else:
            docs = self._load_file(self.file_path)
            for doc in docs:
                yield doc
