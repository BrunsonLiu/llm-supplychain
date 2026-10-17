"""
CSV文件加载器
"""
import csv
from pathlib import Path
from typing import List, Union, Dict, Any, Iterator, Optional
from .base import BaseLoader
from ..document import Document


class CSVLoader(BaseLoader):
    """加载CSV文件"""
    
    def __init__(
        self, 
        file_path: Union[str, Path],
        content_columns: Optional[List[str]] = None,
        metadata_columns: Optional[List[str]] = None,
        csv_args: Optional[Dict[str, Any]] = None
    ):
        self.file_path = Path(file_path)
        self.content_columns = content_columns
        self.metadata_columns = metadata_columns or []
        self.csv_args = csv_args or {}
    
    def load(self) -> List[Document]:
        """加载CSV文件"""
        documents = []
        
        try:
            with open(self.file_path, 'r', encoding='utf-8', newline='') as f:
                reader = csv.DictReader(f, **self.csv_args)
                
                for i, row in enumerate(reader):
                    doc = self._create_document(row, i)
                    if doc:
                        documents.append(doc)
                        
        except Exception as e:
            print(f"Error loading CSV file {self.file_path}: {e}")
        
        return documents
    
    def _create_document(self, row: Dict[str, str], row_num: int) -> Optional[Document]:
        """从CSV行创建文档"""
        if self.content_columns:
            # 使用指定列作为内容
            content_parts = []
            for col in self.content_columns:
                if col in row:
                    content_parts.append(f"{col}: {row[col]}")
            content = "\n".join(content_parts)
        else:
            # 使用所有列作为内容
            content = "\n".join([f"{k}: {v}" for k, v in row.items()])
        
        metadata = {
            'source': str(self.file_path),
            'row': row_num
        }
        
        for col in self.metadata_columns:
            if col in row:
                metadata[col] = row[col]
        
        return Document(page_content=content, metadata=metadata)
    
    def lazy_load(self) -> Iterator[Document]:
        """惰性加载"""
        docs = self.load()
        for doc in docs:
            yield doc
