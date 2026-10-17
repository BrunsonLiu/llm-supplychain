"""
RAG系统测试
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import unittest
from rag import Document, MockEmbeddings, MockLLM


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


if __name__ == "__main__":
    unittest.main()
