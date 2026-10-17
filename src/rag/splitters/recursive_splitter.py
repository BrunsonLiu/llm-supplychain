"""
递归字符文本分割器
"""
from typing import List, Optional
from .base import BaseSplitter


class RecursiveCharacterTextSplitter(BaseSplitter):
    """
    递归字符文本分割器
    按照优先级顺序尝试不同的分隔符进行分割
    """
    
    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        separators: Optional[List[str]] = None,
        keep_separator: bool = True
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or ["\n\n", "\n", "。", "；", " ", ""]
        self.keep_separator = keep_separator
    
    def split_text(self, text: str) -> List[str]:
        """递归分割文本"""
        return self._recursive_split(text, self.separators)
    
    def _recursive_split(self, text: str, separators: List[str]) -> List[str]:
        """递归分割"""
        final_chunks = []
        
        # 获取当前分隔符
        separator = separators[0] if separators else ""
        remaining_separators = separators[1:] if len(separators) > 1 else []
        
        # 使用当前分隔符分割
        if separator:
            splits = text.split(separator)
        else:
            # 没有分隔符时按字符分割
            splits = list(text)
        
        # 合并小的片段
        current_chunk = []
        current_length = 0
        
        for split in splits:
            # 计算这个分割后的长度
            split_length = len(split)
            if separator and self.keep_separator and current_chunk:
                split_length += len(separator)
            
            # 如果这个分割本身超过chunk_size，需要进一步分割
            if split_length > self.chunk_size:
                # 如果有更多分隔符，递归分割
                if remaining_separators:
                    sub_chunks = self._recursive_split(split, remaining_separators)
                    for sub_chunk in sub_chunks:
                        if current_length + len(sub_chunk) + (len(separator) if separator and self.keep_separator else 0) <= self.chunk_size:
                            if current_chunk and separator and self.keep_separator:
                                current_chunk.append(separator)
                            current_chunk.append(sub_chunk)
                            current_length += len(sub_chunk) + (len(separator) if separator and self.keep_separator else 0)
                        else:
                            if current_chunk:
                                final_chunks.append("".join(current_chunk))
                                # 修复：overlap 与下一段放不下则放弃 overlap，保证不超 chunk_size
                                overlap_text = self._get_overlap(current_chunk)
                                if len(overlap_text) + len(sub_chunk) <= self.chunk_size:
                                    current_chunk = [overlap_text] if overlap_text else []
                                else:
                                    current_chunk = []
                                current_length = len("".join(current_chunk))
                            
                            if separator and self.keep_separator:
                                current_chunk.append(separator)
                            current_chunk.append(sub_chunk)
                            current_length += len(sub_chunk) + (len(separator) if separator and self.keep_separator else 0)
                else:
                    # 强制分割
                    for i in range(0, len(split), self.chunk_size - self.chunk_overlap):
                        chunk = split[i:i + self.chunk_size]
                        if current_length + len(chunk) <= self.chunk_size:
                            current_chunk.append(chunk)
                            current_length += len(chunk)
                        else:
                            if current_chunk:
                                final_chunks.append("".join(current_chunk))
                                # 修复：overlap 与新 chunk 拼接可能超出 chunk_size，放不下则放弃 overlap
                                overlap_text = self._get_overlap(current_chunk)
                                if len(overlap_text) + len(chunk) <= self.chunk_size:
                                    current_chunk = [overlap_text] if overlap_text else []
                                else:
                                    current_chunk = []
                                current_length = len("".join(current_chunk))
                            current_chunk.append(chunk)
                            current_length += len(chunk)
            else:
                # 正常处理
                if current_length + split_length <= self.chunk_size:
                    if current_chunk and separator and self.keep_separator:
                        current_chunk.append(separator)
                    current_chunk.append(split)
                    current_length += split_length
                else:
                    # 保存当前块
                    if current_chunk:
                        final_chunks.append("".join(current_chunk))
                        # 修复：overlap 与下一段放不下则放弃 overlap，保证不超 chunk_size
                        overlap_text = self._get_overlap(current_chunk)
                        if len(overlap_text) + split_length <= self.chunk_size:
                            current_chunk = [overlap_text] if overlap_text else []
                        else:
                            current_chunk = []
                        current_length = len("".join(current_chunk))
                    
                    # 开始新块
                    if separator and self.keep_separator:
                        current_chunk.append(separator)
                    current_chunk.append(split)
                    current_length += split_length
        
        # 添加最后一个块
        if current_chunk:
            final_chunks.append("".join(current_chunk))
        
        return final_chunks
    
    def _get_overlap(self, chunks: List[str]) -> str:
        """获取重叠文本"""
        overlap_text = ""
        total_length = 0
        
        # 从后往前取文本，直到达到overlap大小
        for chunk in reversed(chunks):
            if total_length + len(chunk) <= self.chunk_overlap:
                overlap_text = chunk + overlap_text
                total_length += len(chunk)
            else:
                remaining = self.chunk_overlap - total_length
                if remaining > 0:
                    overlap_text = chunk[-remaining:] + overlap_text
                break
        
        return overlap_text
