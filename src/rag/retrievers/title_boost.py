"""标题加权检索器：用查询与片段标题的词重合度重排候选。

向量检索只看整段文本的相似度，标题里的关键词容易被正文中的高频词稀释。
例如“什么是安全库存？”会先召回同样反复提到“安全库存”的“服务水平”片段。
本检索器先取一批候选，再用 ``score + boost * title_overlap`` 重排，让标题
直接命中查询的片段排到前面。

这是轻量的词法重排，不是语义模型：它只改善“标题词与问题词重合”的情况，
同义词/改写仍需真实嵌入模型。
"""
import re
from typing import Callable, List, Optional, Set, Tuple

from ..document import Document
from .base import BaseRetriever


def first_heading(text: str, max_length: int = 80) -> str:
    """取正文第一行非分隔线作为标题。"""
    for line in text.splitlines():
        line = line.strip().strip("#").strip()
        if line and not set(line) <= {"=", "-"}:
            return line[:max_length]
    return ""


def lexical_terms(text: str) -> Set[str]:
    """英文/数字按词、中文按单字+二元组切分，与 MockEmbeddings 一致。"""
    text = text.lower()
    terms = set(re.findall(r"[a-z0-9]+", text))
    for segment in re.findall(r"[\u4e00-\u9fff]+", text):
        terms.update(segment)
        terms.update(segment[i:i + 2] for i in range(len(segment) - 1))
    return terms


class TitleBoostRetriever(BaseRetriever):
    """在基础检索器之上，按标题词重合度重排。

    Args:
        base_retriever: 任意 ``BaseRetriever``。
        boost: 标题重合度的权重；0 表示保持基础检索排序。
        candidate_k: 参与重排的候选数；默认 ``max(k * 4, k)``。
        title_fn: 从片段正文提取标题的函数。
    """

    def __init__(
        self,
        base_retriever: BaseRetriever,
        boost: float = 0.3,
        candidate_k: Optional[int] = None,
        title_fn: Callable[[str], str] = first_heading,
    ):
        if boost < 0:
            raise ValueError("boost 必须 >= 0")
        if candidate_k is not None and candidate_k < 1:
            raise ValueError("candidate_k 必须 >= 1")
        self.base_retriever = base_retriever
        self.boost = boost
        self.candidate_k = candidate_k
        self.title_fn = title_fn

    def retrieve(self, query: str, k: int = 4) -> List[Document]:
        return [doc for doc, _ in self.retrieve_with_scores(query, k=k)]

    def retrieve_with_scores(
        self, query: str, k: int = 4
    ) -> List[Tuple[Document, float]]:
        if k <= 0:
            return []
        candidate_k = self.candidate_k or max(k * 4, k)
        candidates = self.base_retriever.retrieve_with_scores(
            query, k=max(k, candidate_k)
        )
        if self.boost == 0 or not candidates:
            return candidates[:k]

        query_terms = lexical_terms(query)
        if not query_terms:
            return candidates[:k]

        reranked = []
        for doc, score in candidates:
            title_terms = lexical_terms(self.title_fn(doc.page_content))
            overlap = len(query_terms & title_terms) / len(query_terms)
            reranked.append((doc, score + self.boost * overlap))
        reranked.sort(key=lambda item: item[1], reverse=True)
        return reranked[:k]
