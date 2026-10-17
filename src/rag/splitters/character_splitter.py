"""
字符文本分割器
简单的基于字符数量的分割
"""
from typing import List
from .base import BaseSplitter


class CharacterTextSplitter(BaseSplitter):
    """字符文本分割器"""
    
    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        separator: str = "\n\n"
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separator = separator
    
    def split_text(self, text: str) -> List[str]:
        """分割文本"""
        # 首先用分隔符分割
        if self.separator:
            splits = text.split(self.separator)
        else:
            splits = [text]
        
        chunks = []
        current_chunk = []
        current_length = 0
        
        for split in splits:
            split_length = len(split)
            
            # 如果单个split超过chunk_size，需要强制分割
            if split_length > self.chunk_size:
                # 先保存当前块
                if current_chunk:
                    chunks.append(self.separator.join(current_chunk))
                    # 获取重叠部分
                    overlap_text = self._get_overlap_text(current_chunk)
                    current_chunk = [overlap_text] if overlap_text else []
                    current_length = len(overlap_text)
                
                # 强制分割大文本
                for i in range(0, split_length, self.chunk_size - self.chunk_overlap):
                    chunk = split[i:i + self.chunk_size]
                    chunks.append(chunk)
            else:
                # 检查是否可以加入当前块
                separator_length = len(self.separator) if current_chunk else 0
                if current_length + separator_length + split_length <= self.chunk_size:
                    current_chunk.append(split)
                    current_length += separator_length + split_length
                else:
                    # 保存当前块
                    if current_chunk:
                        chunks.append(self.separator.join(current_chunk))
                        # 获取重叠部分
                        overlap_text = self._get_overlap_text(current_chunk)
                        current_chunk = [overlap_text] if overlap_text else []
                        current_length = len(overlap_text)
                    
                    # 开始新块
                    current_chunk.append(split)
                    current_length = split_length
        
        # 添加最后一个块
        if current_chunk:
            chunks.append(self.separator.join(current_chunk))
        
        return chunks
    
    def _get_overlap_text(self, chunks: List[str]) -> str:
        """获取重叠文本"""
        overlap_text = ""
        total_length = 0
        
        for chunk in reversed(chunks):
            chunk_with_sep = chunk + self.separator if overlap_text else chunk
            if total_length + len(chunk_with_sep) <= self.chunk_overlap:
                overlap_text = chunk_with_sep + overlap_text
                total_length += len(chunk_with_sep)
            else:
                remaining = self.chunk_overlap - total_length
                if remaining > 0:
                    overlap_text = chunk[-remaining:] + overlap_text
                break
        
        return overlap_text
