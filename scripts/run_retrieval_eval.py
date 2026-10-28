"""Retrieval evaluation: vector baseline vs title-boosted re-ranking.

The default run uses MockEmbeddings (deterministic word-bag hashing), so the
numbers are reproducible without an API key. ``--embeddings openai`` switches
to an OpenAI-compatible embedding endpoint and produces a model-dependent run.

Usage:
    PYTHONPATH=src;. python scripts/run_retrieval_eval.py
    PYTHONPATH=src;. python scripts/run_retrieval_eval.py --embeddings openai --k 5
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rag import (  # noqa: E402
    HeadingSectionSplitter,
    MemoryVectorStore,
    RetrievalCase,
    TextLoader,
    TitleBoostRetriever,
    VectorRetriever,
    evaluate_queries,
)
from supply.rag_tool import RAGTool  # noqa: E402

DOCS_DIR = ROOT / "data" / "documents"
KS = (1, 3, 5)

# 每条查询标注“回答该问题所必需的最少片段”，标签按标题子串匹配。
CASES: List[RetrievalCase] = [
    RetrievalCase("安全库存怎么计算", ("1. 安全库存（Safety Stock）",)),
    RetrievalCase("什么时候该补货", ("2. 再订货点（Reorder Point）",)),
    RetrievalCase("经济订货批量的公式", ("3. 经济订货批量（EOQ）",)),
    RetrievalCase("提高服务水平会怎样", ("4. 服务水平（Service Level）",)),
    RetrievalCase("ABC 分类法怎么用", ("5. ABC 分类法",)),
    RetrievalCase("牛鞭效应是什么", ("1. 牛鞭效应（Bullwhip Effect）",)),
    RetrievalCase("提前期对库存的影响", ("2. 订货提前期（Lead Time）",)),
    RetrievalCase("库存周转率低意味着什么", ("3. 库存周转率",)),
    RetrievalCase("如何评估预测误差", ("5. 预测误差评估",)),
    RetrievalCase("移动平均法适合什么场景", ("1. 移动平均法（Moving Average）",)),
    RetrievalCase(
        "Holt 双参数法怎么用", ("2. 指数平滑法（Exponential Smoothing）",)
    ),
    RetrievalCase("多个预测模型怎么组合", ("4. 集成预测（Ensemble）",)),
    RetrievalCase(
        "供应商选择要看哪些指标",
        ("1. 供应商选择应综合评估", "1. 价格因素：比较不同供应商的报价"),
    ),
    RetrievalCase("促销后预测要注意什么", ("3. 促销期需求激增",)),
    RetrievalCase("大批量订货的利弊", ("2. 大批量订货",)),
]


def _load_embeddings(name: str):
    if name == "openai":
        from rag import OpenAIEmbeddings

        return OpenAIEmbeddings()
    from rag import MockEmbeddings

    return MockEmbeddings()


def _as_retrieve(retriever):
    def retrieve(query: str, k: int) -> Sequence[str]:
        hits = retriever.retrieve_with_scores(query, k=k)
        return [RAGTool._title(doc.page_content) for doc, _ in hits]

    return retrieve


def build_retrievers(
    embeddings, title_boost: float = 0.3, max_chunk_size: int = 500
):
    # 与 RAGTool 默认 chunk_size=500 对齐，评估的就是 Agent 实际检索的语料
    documents = TextLoader(DOCS_DIR).load()
    chunks = HeadingSectionSplitter(max_chunk_size=max_chunk_size).split_documents(
        documents
    )
    store = MemoryVectorStore()
    if chunks:
        store.add_documents(
            chunks,
            embeddings.embed_documents([chunk.page_content for chunk in chunks]),
        )
    base = VectorRetriever(store, embeddings)
    boosted = TitleBoostRetriever(
        base, boost=title_boost, title_fn=RAGTool._title
    )
    return (
        {"vector": _as_retrieve(base), "title-boost": _as_retrieve(boosted)},
        documents,
        chunks,
    )


def _short(text: str, limit: int = 46) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _table(rows: List[Dict[str, Any]], columns: List[tuple[str, str]]) -> str:
    lines = [
        "| " + " | ".join(label for _, label in columns) + " |",
        "|" + "|".join("---" for _ in columns) + "|",
    ]
    for row in rows:
        cells = []
        for key, _ in columns:
            value = row.get(key, "")
            if isinstance(value, float):
                cells.append(f"{value:.3f}")
            elif value is None:
                cells.append("—")
            else:
                cells.append(str(value).replace("|", "/"))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _metrics(
    reports: Dict[int, Any], max_k: int, table_k: int
) -> Dict[str, float]:
    metrics = {f"recall@{k}": reports[k].mean_recall for k in KS}
    metrics[f"mrr@{max_k}"] = reports[max_k].mean_mrr
    metrics[f"hit_rate@{table_k}"] = reports[table_k].hit_rate
    return metrics


def _case_rows(report: Any) -> List[Dict[str, Any]]:
    return [
        {
            "query": result.query,
            "relevant": list(result.relevant),
            "retrieved": list(result.retrieved),
            "matched": list(result.matched),
            "first_rank": result.first_rank,
            "recall": result.recall,
            "reciprocal_rank": result.reciprocal_rank,
        }
        for result in report.results
    ]


def build_report(
    reports: Dict[str, Dict[int, Any]],
    documents: int,
    chunks: int,
    embedding_name: str,
    title_boost: float,
    table_k: int,
) -> tuple[Dict[str, Any], str]:
    max_k = max(KS)
    vector_by_query = {
        result.query: result
        for result in reports["vector"][table_k].results
    }
    rows = []
    for result in reports["title-boost"][table_k].results:
        baseline = vector_by_query[result.query]
        rows.append(
            {
                "query": result.query,
                "relevant": " / ".join(result.relevant),
                "vector_rank": baseline.first_rank,
                "boosted_rank": result.first_rank,
                "boosted_top": " · ".join(
                    _short(title) for title in result.retrieved
                ),
                "recall": result.recall,
                "reciprocal_rank": result.reciprocal_rank,
            }
        )

    metrics = {
        name: _metrics(reports[name], max_k, table_k)
        for name in reports
    }
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "embedding": embedding_name,
        "title_boost": title_boost,
        "documents": documents,
        "chunks": chunks,
        "queries": len(reports["title-boost"][table_k].results),
        "k_values": list(KS),
        "table_k": table_k,
        "retrievers": {
            name: {
                "metrics": metrics[name],
                "cases": _case_rows(reports[name][max_k]),
            }
            for name in reports
        },
    }

    lines = ["# Retrieval evaluation", ""]
    lines.append(f"- Generated: `{summary['generated_at']}`")
    lines.append(
        f"- Embeddings: `{embedding_name}` "
        f"({'deterministic word-bag hashing, no API key' if embedding_name == 'mock' else 'OpenAI-compatible endpoint, model-dependent'})"
    )
    lines.append(
        f"- Corpus: **{documents}** documents / **{chunks}** heading-level chunks; "
        f"**{summary['queries']}** labeled Chinese queries"
    )
    lines.append(
        f"- Retrievers: vector-only baseline vs title-boosted re-ranking "
        f"(boost={title_boost:g})"
    )
    lines.append("")
    lines.append("## Comparison")
    lines.append("")
    comparison = []
    for name in ("vector", "title-boost"):
        item = {
            "retriever": name,
            "recall@1": f"{metrics[name]['recall@1']:.1%}",
            "recall@3": f"{metrics[name]['recall@3']:.1%}",
            "recall@5": f"{metrics[name]['recall@5']:.1%}",
            f"mrr@{max_k}": f"{metrics[name][f'mrr@{max_k}']:.3f}",
            f"hit_rate@{table_k}": f"{metrics[name][f'hit_rate@{table_k}']:.1%}",
        }
        comparison.append(item)
    lines.append(
        _table(
            comparison,
            [
                ("retriever", "retriever"),
                ("recall@1", "Recall@1"),
                ("recall@3", "Recall@3"),
                ("recall@5", "Recall@5"),
                (f"mrr@{max_k}", f"MRR@{max_k}"),
                (f"hit_rate@{table_k}", f"Hit@{table_k}"),
            ],
        )
    )
    lines.append("")
    lines.append(f"## Per-query results (k={table_k})")
    lines.append("")
    lines.append(
        _table(
            rows,
            [
                ("query", "query"),
                ("relevant", "labeled relevant chunk(s)"),
                ("vector_rank", "vector rank"),
                ("boosted_rank", "boosted rank"),
                ("boosted_top", f"boosted top-{table_k}"),
                ("recall", "recall"),
                ("reciprocal_rank", "RR"),
            ],
        )
    )
    lines.append("")
    lines.append("## Notes and limitations")
    lines.append("")
    lines.append(
        "- Title boost is a lexical re-ranker: it adds `boost × (query terms "
        "shared with the first heading / query terms)` to the base retrieval score. "
        "It helps when the title contains the question's words, not when the question "
        "is a paraphrase."
    )
    lines.append(
        f"- `boost={title_boost:g}` is a fixed heuristic, not tuned on a held-out "
        "set; the 15 queries are a small regression suite, so treat the delta as "
        "directional rather than a general benchmark."
    )
    lines.append(
        "- Labels mark the minimal chunk(s) needed to answer each query; they are "
        "not an exhaustive relevance judgment over all chunks."
    )
    lines.append(
        "- `mock` embeddings only capture lexical overlap (Chinese single characters "
        "plus bigrams), so the vector-only baseline is intentionally weak. Run "
        "`--embeddings openai` for a model-backed comparison."
    )
    return summary, "\n".join(lines)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Retrieval quality evaluation")
    parser.add_argument(
        "--embeddings",
        choices=["mock", "openai"],
        default="mock",
        help="mock = offline word-bag embeddings; openai = API embeddings",
    )
    parser.add_argument("--k", type=int, default=3, help="k for the per-query table")
    parser.add_argument(
        "--title-boost",
        type=float,
        default=0.3,
        help="weight of the title-overlap bonus (0 disables re-ranking)",
    )
    parser.add_argument("--out-dir", default=str(ROOT / "benchmarks"))
    args = parser.parse_args()

    if args.k not in KS:
        raise SystemExit(f"--k 必须是 {', '.join(map(str, KS))} 之一")
    if args.title_boost < 0:
        raise SystemExit("--title-boost 必须 >= 0")

    embeddings = _load_embeddings(args.embeddings)
    retrievers, documents, chunks = build_retrievers(
        embeddings, title_boost=args.title_boost
    )
    reports = {
        name: {
            k: evaluate_queries(CASES, retrieve, k=k) for k in KS
        }
        for name, retrieve in retrievers.items()
    }

    print("=" * 72)
    print("Retrieval evaluation")
    print("=" * 72)
    for name in ("vector", "title-boost"):
        print(
            f"{name:12s} Recall@1 {reports[name][1].mean_recall:.1%}, "
            f"Recall@3 {reports[name][3].mean_recall:.1%}, "
            f"Recall@5 {reports[name][5].mean_recall:.1%}, "
            f"MRR@5 {reports[name][5].mean_mrr:.3f}"
        )
    for result in reports["title-boost"][args.k].results:
        rank = result.first_rank if result.first_rank is not None else "—"
        print(
            f"{result.query:22s} rank={str(rank):2s} "
            f"recall={result.recall:.2f} "
            f"top1={_short(result.retrieved[0] if result.retrieved else '—', 40)}"
        )

    summary, markdown = build_report(
        reports,
        len(documents),
        len(chunks),
        args.embeddings,
        args.title_boost,
        args.k,
    )
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "RETRIEVAL_REPORT.md"
    summary_path = out_dir / "retrieval_summary.json"
    report_path.write_text(markdown, encoding="utf-8")
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nWrote: {report_path}")
    print(f"Wrote: {summary_path}")


if __name__ == "__main__":
    main()
