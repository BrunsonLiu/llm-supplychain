"""
Markdown文本分割器
专门为Markdown格式设计的分割器
"""
import re
from typing import List
from .recursive_splitter import RecursiveCharacterTextSplitter


class MarkdownTextSplitter(RecursiveCharacterTextSplitter):
    """Markdown文本分割器"""
    
    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ):
        # Markdown特定的分隔符
        separators = [
            "\n#{1,6} ",      # 标题
            "\n\n",          # 段落
            "\n",            # 换行
            "```\n",         # 代码块结束
            "\n```",         # 代码块开始
            " ",             # 空格
            "",              # 字符
        ]
        super().__init__(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=separators,
            keep_separator=True
        )
