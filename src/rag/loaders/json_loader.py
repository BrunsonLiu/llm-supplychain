"""
JSON文件加载器
"""
import json
from pathlib import Path
from typing import List, Union, Dict, Any, Iterator, Optional
from .base import BaseLoader
from ..document import Document


class JSONLoader(BaseLoader):
    """加载JSON文件"""
    
    def __init__(
        self, 
        file_path: Union[str, Path], 
        content_key: str = 'content',
        metadata_keys: Optional[List[str]] = None
    ):
        self.file_path = Path(file_path)
        self.content_key = content_key
        self.metadata_keys = metadata_keys or []
    
    def load(self) -> List[Document]:
        """加载JSON文件"""
        documents = []
        
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if isinstance(data, list):
                for item in data:
                    doc = self._create_document(item)
                    if doc:
                        documents.append(doc)
            elif isinstance(data, dict):
                doc = self._create_document(data)
                if doc:
                    documents.append(doc)
                    
        except Exception as e:
            print(f"Error loading JSON file {self.file_path}: {e}")
        
        return documents
    
    def _create_document(self, item: Dict[str, Any]) -> Optional[Document]:
        """从JSON项创建文档"""
        if self.content_key not in item:
            return None
        
        content = item[self.content_key]
        if isinstance(content, (list, dict)):
            content = json.dumps(content, ensure_ascii=False)
        
        metadata = {'source': str(self.file_path)}
        for key in self.metadata_keys:
            if key in item:
                metadata[key] = item[key]
        
        return Document(page_content=str(content), metadata=metadata)
    
    def lazy_load(self) -> Iterator[Document]:
        """惰性加载"""
        docs = self.load()
        for doc in docs:
            yield doc
