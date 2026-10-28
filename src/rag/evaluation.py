"""检索质量评估：Recall@k、MRR@k 与命中率。

评估对象是任意 ``retrieve(query, k) -> Sequence[id]`` 的可调用对象。id 通常
取检索结果的标题或 ``来源::标题``；标签用子串匹配，因此一个标签可以覆盖
同一主题的多个片段（例如两篇文档都讲“供应商选择”）。

用法::

    cases = [RetrievalCase("安全库存怎么计算", ("安全库存（Safety Stock）",))]
    report = evaluate_queries(cases, retrieve=my_retriever, k=3)
    report.mean_recall, report.mean_mrr, report.hit_rate
"""
from dataclasses import asdict, dataclass
from typing import Callable, Dict, Optional, Sequence, Tuple


@dataclass(frozen=True)
class RetrievalCase:
    """一条带标注的检索查询。

    ``relevant`` 中的每个标签是一个子串：只要某个检索结果的 id 包含它，
    就认为该标签被命中。多标签用于“同一问题有多个正确片段”的情况。
    """

    query: str
    relevant: Tuple[str, ...]
    note: str = ""


@dataclass(frozen=True)
class RetrievalCaseResult:
    query: str
    relevant: Tuple[str, ...]
    retrieved: Tuple[str, ...]
    matched: Tuple[str, ...]
    first_rank: Optional[int]
    recall: float
    reciprocal_rank: float


@dataclass(frozen=True)
class RetrievalReport:
    k: int
    results: Tuple[RetrievalCaseResult, ...]

    @property
    def mean_recall(self) -> float:
        return sum(r.recall for r in self.results) / len(self.results)

    @property
    def mean_mrr(self) -> float:
        return sum(r.reciprocal_rank for r in self.results) / len(self.results)

    @property
    def hit_rate(self) -> float:
        hits = sum(1 for r in self.results if r.first_rank is not None)
        return hits / len(self.results)

    def to_dict(self) -> Dict[str, object]:
        return {
            "k": self.k,
            "cases": len(self.results),
            "recall_at_k": self.mean_recall,
            "mrr_at_k": self.mean_mrr,
            "hit_rate": self.hit_rate,
            "results": [asdict(r) for r in self.results],
        }


def _validate_labels(relevant: Sequence[str]) -> Tuple[str, ...]:
    labels = tuple(dict.fromkeys(label for label in relevant if label))
    if not labels:
        raise ValueError("relevant 至少需要一个非空标签")
    return labels


def _matches(doc_id: str, labels: Sequence[str]) -> bool:
    return any(label in doc_id for label in labels)


def first_relevant_rank(
    ranked_ids: Sequence[str],
    relevant: Sequence[str],
    k: Optional[int] = None,
) -> Optional[int]:
    """返回第一个命中标签的 1-based 排名；没有命中返回 ``None``。"""
    labels = _validate_labels(relevant)
    if k is not None and k <= 0:
        raise ValueError("k 必须为正整数")
    top = list(ranked_ids)
    if k is not None:
        top = top[:k]
    for rank, doc_id in enumerate(top, start=1):
        if _matches(str(doc_id), labels):
            return rank
    return None


def recall_at_k(ranked_ids: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """前 k 个结果命中的标签数 / 标注标签总数。"""
    labels = _validate_labels(relevant)
    if k <= 0:
        raise ValueError("k 必须为正整数")
    top = [str(doc_id) for doc_id in list(ranked_ids)[:k]]
    matched = sum(1 for label in labels if any(label in doc_id for doc_id in top))
    return matched / len(labels)


def mrr_at_k(ranked_ids: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """前 k 个结果中第一个命中标签的倒数排名；未命中为 0。"""
    if k <= 0:
        raise ValueError("k 必须为正整数")
    rank = first_relevant_rank(ranked_ids, relevant, k=k)
    return 0.0 if rank is None else 1.0 / rank


def evaluate_queries(
    cases: Sequence[RetrievalCase],
    retrieve: Callable[[str, int], Sequence[str]],
    k: int = 3,
) -> RetrievalReport:
    """对标注查询集计算 Recall@k、MRR@k 与命中率。

    Args:
        cases: 标注查询列表。
        retrieve: ``(query, k) -> ranked ids``，返回按相关度降序排列的结果。
        k: 截断排名。
    """
    if k <= 0:
        raise ValueError("k 必须为正整数")
    case_list = list(cases)
    if not case_list:
        raise ValueError("cases 不能为空")

    results = []
    for case in case_list:
        labels = _validate_labels(case.relevant)
        retrieved = tuple(str(doc_id) for doc_id in retrieve(case.query, k))[:k]
        results.append(
            RetrievalCaseResult(
                query=case.query,
                relevant=labels,
                retrieved=retrieved,
                matched=tuple(
                    label
                    for label in labels
                    if any(label in doc_id for doc_id in retrieved)
                ),
                first_rank=first_relevant_rank(retrieved, labels, k=k),
                recall=recall_at_k(retrieved, labels, k=k),
                reciprocal_rank=mrr_at_k(retrieved, labels, k=k),
            )
        )

    return RetrievalReport(k=k, results=tuple(results))
