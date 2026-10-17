"""
按标题分节的文本分割器

专为中文知识文档设计：以标题行为边界切分，每个"标题 + 其下正文"
为一个 chunk，保证语义完整。标题模式覆盖：
- Markdown ATX 标题：# / ## / ###
- 中文序号标题：一、 二、 十、
- 数字序号标题：1. 2. 3.（后跟非空内容）
- 章节标题：第一章 / 第2章

超长章节再交给 RecursiveCharacterTextSplitter 二次切分，避免无限长 chunk。
"""
import re
from typing import List
from .base import BaseSplitter
from .recursive_splitter import RecursiveCharacterTextSplitter

# 标题行正则
_HEADING_PATTERNS = [
    re.compile(r"^#{1,6}\s+\S"),            # markdown ATX
    re.compile(r"^[一二三四五六七八九十百]+、"),  # 中文序号
    re.compile(r"^第[一二三四五六七八九十百\d]+[章节部篇]\s*\S"),  # 第X章
    re.compile(r"^\d+\.\s+\S"),             # 数字序号
]


class HeadingSectionSplitter(BaseSplitter):
    """按标题分节切分"""

    def __init__(self, max_chunk_size: int = 800, chunk_overlap: int = 50):
        self.max_chunk_size = max_chunk_size
        self.chunk_overlap = chunk_overlap
        self._fallback = RecursiveCharacterTextSplitter(
            chunk_size=max_chunk_size, chunk_overlap=chunk_overlap
        )

    @classmethod
    def _is_heading(cls, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        return any(p.match(stripped) for p in _HEADING_PATTERNS)

    def split_text(self, text: str) -> List[str]:
        lines = text.split("\n")
        sections: List[str] = []
        current: List[str] = []

        for line in lines:
            if self._is_heading(line) and current:
                sections.append("\n".join(current).strip())
                current = [line]
            else:
                current.append(line)
        if current:
            sections.append("\n".join(current).strip())

        # 过滤空节；超长节二次切分
        chunks: List[str] = []
        for section in sections:
            if not section:
                continue
            if len(section) > self.max_chunk_size:
                chunks.extend(self._fallback.split_text(section))
            else:
                chunks.append(section)
        return chunks
