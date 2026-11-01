"""
RAG系统测试
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import unittest
from rag import (
    BaseRetriever,
    Document,
    MockEmbeddings,
    MockLLM,
    RetrievalCase,
    TitleBoostRetriever,
    evaluate_queries,
    first_relevant_rank,
    recall_at_k,
    mrr_at_k,
)


class TestDocument(unittest.TestCase):
    """测试Document类"""
    
    def test_document_creation(self):
        doc = Document(page_content="测试内容", metadata={"source": "test.txt"})
        self.assertEqual(doc.page_content, "测试内容")
        self.assertEqual(doc.metadata["source"], "test.txt")
    
    def test_document_default_metadata(self):
        doc = Document(page_content="测试")
        self.assertEqual(doc.metadata, {})


class TestMockEmbeddings(unittest.TestCase):
    """测试MockEmbeddings"""
    
    def setUp(self):
        self.embeddings = MockEmbeddings(dimension=10)
    
    def test_embed_query(self):
        embedding = self.embeddings.embed_query("测试")
        self.assertEqual(len(embedding), 10)
    
    def test_embed_documents(self):
        texts = ["文本1", "文本2", "文本3"]
        embeddings = self.embeddings.embed_documents(texts)
        self.assertEqual(len(embeddings), 3)
        self.assertEqual(len(embeddings[0]), 10)


class TestMockLLM(unittest.TestCase):
    """测试MockLLM"""
    
    def setUp(self):
        self.llm = MockLLM()
    
    def test_generate(self):
        response = self.llm.generate("测试问题")
        self.assertIsInstance(response, str)
        self.assertIn("测试", response)
    
    def test_generate_with_response(self):
        response = self.llm.generate_with_response("测试")
        self.assertIsNotNone(response.content)
        self.assertIn("prompt_tokens", response.usage)


class TestMemoryVectorStore(unittest.TestCase):
    """测试内存向量存储"""
    
    def setUp(self):
        from rag import MemoryVectorStore
        self.store = MemoryVectorStore()
        self.embeddings = MockEmbeddings()
    
    def test_add_and_search(self):
        docs = [
            Document(page_content="机器学习"),
            Document(page_content="深度学习"),
        ]
        embeddings = self.embeddings.embed_documents([d.page_content for d in docs])
        
        self.store.add_documents(docs, embeddings)
        
        # 搜索
        query_emb = self.embeddings.embed_query("机器学习")
        results = self.store.similarity_search(query_emb, k=2)
        
        self.assertEqual(len(results), 2)
        self.assertGreater(results[0][1], 0)  # 分数应该大于0


class TestTextSplitter(unittest.TestCase):
    """测试文本分割器"""
    
    def test_recursive_splitter(self):
        from rag import RecursiveCharacterTextSplitter
        
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=50,
            chunk_overlap=10
        )
        
        text = "这是一个很长的文本。" * 20
        chunks = splitter.split_text(text)
        
        self.assertGreater(len(chunks), 1)
        # 每个块应该小于等于chunk_size
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 50 + 10)  # 允许一些余量


class TestRetrievalMetrics(unittest.TestCase):
    """测试检索质量指标"""

    def test_first_relevant_rank(self):
        ranked = ["a", "b", "c"]
        self.assertEqual(first_relevant_rank(ranked, ["b"]), 2)
        self.assertIsNone(first_relevant_rank(ranked, ["missing"]))
        self.assertIsNone(first_relevant_rank(ranked, ["c"], k=2))
        self.assertEqual(first_relevant_rank(ranked, ["c"], k=3), 3)

    def test_recall_at_k_with_multiple_labels(self):
        ranked = ["安全库存", "服务水平", "EOQ"]
        self.assertEqual(recall_at_k(ranked, ["安全库存"], 1), 1.0)
        self.assertEqual(recall_at_k(ranked, ["安全库存", "EOQ"], 2), 0.5)
        self.assertEqual(recall_at_k(ranked, ["安全库存", "EOQ"], 3), 1.0)
        self.assertEqual(recall_at_k(ranked, ["ABC"], 3), 0.0)

    def test_mrr_at_k(self):
        ranked = ["x", "安全库存", "y"]
        self.assertEqual(mrr_at_k(ranked, ["安全库存"], 1), 0.0)
        self.assertAlmostEqual(mrr_at_k(ranked, ["安全库存"], 3), 0.5)
        self.assertAlmostEqual(mrr_at_k(ranked, ["x"], 3), 1.0)

    def test_evaluate_queries(self):
        cases = [
            RetrievalCase("q1", ("安全库存",)),
            RetrievalCase("q2", ("EOQ",)),
        ]

        def retrieve(query, k):
            return {
                "q1": ["安全库存", "x"],
                "q2": ["x", "y", "EOQ"],
            }[query][:k]

        report = evaluate_queries(cases, retrieve, k=2)
        self.assertEqual(report.results[0].first_rank, 1)
        self.assertIsNone(report.results[1].first_rank)
        self.assertAlmostEqual(report.mean_recall, 0.5)
        self.assertAlmostEqual(report.mean_mrr, 0.5)
        self.assertAlmostEqual(report.hit_rate, 0.5)

        payload = report.to_dict()
        self.assertEqual(payload["k"], 2)
        self.assertEqual(payload["cases"], 2)
        self.assertEqual(len(payload["results"]), 2)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            recall_at_k(["a"], ["a"], k=0)
        with self.assertRaises(ValueError):
            first_relevant_rank(["a"], [])
        with self.assertRaises(ValueError):
            evaluate_queries([], lambda query, k: [], k=3)


class _StaticRetriever(BaseRetriever):
    def __init__(self, scored):
        self.scored = list(scored)
        self.requested_k = None

    def retrieve(self, query, k=4):
        return [doc for doc, _ in self.scored[:k]]

    def retrieve_with_scores(self, query, k=4):
        self.requested_k = k
        return self.scored[:k]


class TestTitleBoostRetriever(unittest.TestCase):
    """测试标题加权重排"""

    def setUp(self):
        self.service = Document(
            "4. 服务水平（Service Level）\n提高服务水平会推高安全库存。"
        )
        self.safety = Document(
            "1. 安全库存（Safety Stock）\n安全库存 = Z × σ_d × √(LT)。"
        )

    def test_title_match_promotes_candidate_beyond_top_k(self):
        base = _StaticRetriever([(self.service, 0.40), (self.safety, 0.30)])
        retriever = TitleBoostRetriever(base, boost=0.3)
        results = retriever.retrieve_with_scores("安全库存怎么计算", k=1)
        self.assertIs(results[0][0], self.safety)
        self.assertEqual(base.requested_k, 4)

    def test_zero_boost_keeps_base_order(self):
        base = _StaticRetriever([(self.service, 0.40), (self.safety, 0.30)])
        retriever = TitleBoostRetriever(base, boost=0)
        results = retriever.retrieve_with_scores("安全库存怎么计算", k=2)
        self.assertIs(results[0][0], self.service)

    def test_invalid_boost_rejected(self):
        with self.assertRaises(ValueError):
            TitleBoostRetriever(_StaticRetriever([]), boost=-0.1)


class TestRAGToolRetrieval(unittest.TestCase):
    """端到端验证 Agent 实际使用的检索配置"""

    def test_safety_stock_question_hits_safety_chunk(self):
        from supply.rag_tool import RAGTool

        result = RAGTool(top_k=3).run("什么是安全库存？")
        self.assertEqual(result["status"], "success")
        self.assertIn("安全库存", result["citations"][0]["title"])


class TestRetrievalDataset(unittest.TestCase):
    """校验标注查询与知识库片段一致"""

    @classmethod
    def setUpClass(cls):
        from rag import HeadingSectionSplitter, TextLoader
        from supply.rag_tool import RAGTool
        from run_retrieval_eval import CASES

        cls.cases = CASES
        docs = TextLoader(ROOT / "data" / "documents").load()
        chunks = HeadingSectionSplitter(max_chunk_size=500).split_documents(docs)
        cls.titles = [RAGTool._title(chunk.page_content) for chunk in chunks]

    def test_queries_are_unique(self):
        queries = [case.query for case in self.cases]
        self.assertEqual(len(queries), len(set(queries)))

    def test_chunk_titles_are_unique(self):
        self.assertEqual(len(self.titles), len(set(self.titles)))

    def test_every_label_matches_a_chunk(self):
        for case in self.cases:
            for label in case.relevant:
                self.assertTrue(
                    any(label in title for title in self.titles),
                    f"label {label!r} for {case.query!r} matches no chunk",
                )


class TestConfigValidation(unittest.TestCase):
    """Pydantic v2 field validators keep the old config contract."""

    def test_openai_requires_key(self):
        import os
        from unittest.mock import patch
        from rag.utils.config import LLMConfig
        from rag.utils.exceptions import ConfigurationError

        with patch.dict(
            os.environ, {"OPENAI_API_KEY": "", "DEEPSEEK_API_KEY": ""}, clear=False
        ):
            with self.assertRaises(ConfigurationError):
                LLMConfig(provider="openai", api_key="")

    def test_openai_accepts_env_key(self):
        import os
        from unittest.mock import patch
        from rag.utils.config import LLMConfig

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
            config = LLMConfig(provider="openai", api_key="")
        self.assertEqual(config.provider, "openai")

    def test_chunk_overlap_must_be_smaller(self):
        from rag.utils.config import TextSplitterConfig
        from rag.utils.exceptions import ConfigurationError

        with self.assertRaises(ConfigurationError):
            TextSplitterConfig(chunk_size=100, chunk_overlap=200)
        self.assertEqual(
            TextSplitterConfig(chunk_size=100, chunk_overlap=99).chunk_overlap, 99
        )


if __name__ == "__main__":
    unittest.main()
