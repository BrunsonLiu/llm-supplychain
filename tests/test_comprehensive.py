"""
综合测试 - 测试新增功能
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import unittest
import time
import tempfile
import json
from rag import (
    Document, 
    MockEmbeddings, 
    MockLLM,
    MemoryVectorStore,
    VectorRetriever,
    RAGChain,
    ConversationalRAGChain,
    DecisionRAGChain,
    AgenticRAGChain,
    get_logger,
    LoggerConfig,
    SimpleCache,
    FileCache,
    CacheManager,
    generate_cache_key,
    retry,
    RetryManager,
    RAGException,
    ConfigurationError,
)
# RAGConfig 等配置类位于 rag.utils（原文件从 rag 顶层导入，属原项目的导出遗漏）
from rag.utils import RAGConfig, LLMConfig, EmbeddingsConfig
from rag.utils.exceptions import RetryableError


class TestLogging(unittest.TestCase):
    """测试日志系统"""
    
    def test_logger_initialization(self):
        """测试日志初始化"""
        LoggerConfig.setup(
            log_level="DEBUG",
            console_output=False,
            file_output=False
        )
        logger = get_logger("test")
        self.assertIsNotNone(logger)
        logger.debug("测试日志消息")


class TestCache(unittest.TestCase):
    """测试缓存系统"""
    
    def test_simple_cache(self):
        """测试简单缓存"""
        cache = SimpleCache(max_size=100, default_ttl=60)
        
        # 设置和获取
        cache.set("key1", "value1")
        self.assertEqual(cache.get("key1"), "value1")
        
        # 不存在的键
        self.assertIsNone(cache.get("nonexistent"))
        
        # 删除
        self.assertTrue(cache.delete("key1"))
        self.assertIsNone(cache.get("key1"))
        
        # 清空
        cache.set("key2", "value2")
        cache.clear()
        self.assertIsNone(cache.get("key2"))
    
    def test_cache_ttl(self):
        """测试缓存过期"""
        cache = SimpleCache(max_size=100, default_ttl=1)
        cache.set("key", "value")
        self.assertEqual(cache.get("key"), "value")
        
        # 等待过期
        time.sleep(1.1)
        self.assertIsNone(cache.get("key"))
    
    def test_cache_max_size(self):
        """测试缓存大小限制"""
        cache = SimpleCache(max_size=5, default_ttl=60)
        
        for i in range(10):
            cache.set(f"key{i}", f"value{i}")
        
        # 缓存大小不应超过限制
        self.assertLessEqual(len(cache.cache), 5)
    
    def test_cache_stats(self):
        """测试缓存统计"""
        cache = SimpleCache(max_size=100, default_ttl=60)
        
        cache.set("key1", "value1")
        cache.get("key1")  # hit
        cache.get("nonexistent")  # miss
        
        stats = cache.get_stats()
        self.assertEqual(stats['hits'], 1)
        self.assertEqual(stats['misses'], 1)
        self.assertEqual(stats['hit_rate'], "50.00%")
    
    def test_generate_cache_key(self):
        """测试缓存键生成"""
        key1 = generate_cache_key("prefix", "arg1", arg2="value2")
        key2 = generate_cache_key("prefix", "arg1", arg2="value2")
        key3 = generate_cache_key("prefix", "arg1", arg2="value3")
        
        self.assertEqual(key1, key2)
        self.assertNotEqual(key1, key3)
    
    def test_file_cache(self):
        """测试文件缓存"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = FileCache(cache_dir=tmpdir, default_ttl=60)
            
            cache.set("key1", {"data": "value1"})
            result = cache.get("key1")
            self.assertEqual(result, {"data": "value1"})
            
            cache.delete("key1")
            self.assertIsNone(cache.get("key1"))
    
    def test_cache_manager(self):
        """测试缓存管理器"""
        cache = CacheManager(
            enable_memory_cache=True,
            enable_file_cache=False,
            memory_cache_size=100
        )
        
        cache.set("key", "value")
        self.assertEqual(cache.get("key"), "value")
        
        cache.clear()
        self.assertIsNone(cache.get("key"))


class TestRetry(unittest.TestCase):
    """测试重试机制"""
    
    def test_retry_decorator(self):
        """测试重试装饰器"""
        call_count = 0
        
        @retry(max_retries=3, delay=0.1, exceptions=(ValueError,))
        def flaky_function():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("临时错误")
            return "success"
        
        result = flaky_function()
        self.assertEqual(result, "success")
        self.assertEqual(call_count, 3)
    
    def test_retry_manager(self):
        """测试重试管理器"""
        manager = RetryManager(
            max_retries=3,
            initial_delay=0.1,
            backoff_factor=2.0
        )
        
        call_count = 0
        
        def flaky_function():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RuntimeError("错误")
            return "ok"
        
        result = manager.execute(flaky_function, exceptions=(RuntimeError,))
        self.assertEqual(result, "ok")
        self.assertEqual(call_count, 2)


class TestConfig(unittest.TestCase):
    """测试配置验证"""
    
    def test_llm_config(self):
        """测试LLM配置"""
        config = LLMConfig(provider="mock", model="test-model")
        self.assertEqual(config.provider, "mock")
        self.assertEqual(config.temperature, 0.7)
    
    def test_llm_config_validation(self):
        """测试LLM配置验证"""
        # OpenAI provider 需要 API key
        with self.assertRaises(ConfigurationError):
            LLMConfig(provider="openai", api_key="")
    
    def test_rag_config(self):
        """测试完整RAG配置"""
        config = RAGConfig()
        self.assertIsNotNone(config.llm)
        self.assertIsNotNone(config.embeddings)
        self.assertIsNotNone(config.vectorstore)
    
    def test_config_from_yaml(self):
        """测试从YAML加载配置"""
        config_path = Path(__file__).parent.parent / "config" / "config.yaml"
        if config_path.exists():
            config = RAGConfig.from_yaml(str(config_path))
            self.assertIsNotNone(config)


class TestRAGChainWithCache(unittest.TestCase):
    """测试带缓存的RAG链"""
    
    def setUp(self):
        """设置测试环境"""
        self.embeddings = MockEmbeddings(dimension=10)
        self.llm = MockLLM()
        
        # 创建文档
        docs = [
            Document(page_content="机器学习是人工智能的一个分支"),
            Document(page_content="深度学习使用神经网络"),
        ]
        
        # 创建向量存储
        self.store = MemoryVectorStore()
        embeddings_list = self.embeddings.embed_documents([d.page_content for d in docs])
        self.store.add_documents(docs, embeddings_list)
        
        # 创建检索器
        self.retriever = VectorRetriever(self.store, self.embeddings)
    
    def test_rag_chain_with_cache(self):
        """测试带缓存的RAG链"""
        chain = RAGChain(
            retriever=self.retriever,
            llm=self.llm,
            enable_cache=True
        )
        
        # 第一次查询
        result1 = chain.run("什么是机器学习？")
        self.assertIn("answer", result1)
        
        # 第二次查询（应该命中缓存）
        result2 = chain.run("什么是机器学习？")
        self.assertEqual(result1['answer'], result2['answer'])
    
    def test_rag_chain_without_cache(self):
        """测试不带缓存的RAG链"""
        chain = RAGChain(
            retriever=self.retriever,
            llm=self.llm,
            enable_cache=False
        )
        
        result = chain.run("什么是深度学习？")
        self.assertIn("answer", result)


class TestAgenticRAGChain(unittest.TestCase):
    """测试改进的 AgenticRAGChain"""
    
    def setUp(self):
        """设置测试环境"""
        self.embeddings = MockEmbeddings(dimension=10)
        self.llm = MockLLM()
        
        docs = [
            Document(page_content="云计算提供弹性计算资源"),
            Document(page_content="微服务架构支持独立部署"),
        ]
        
        self.store = MemoryVectorStore()
        embeddings_list = self.embeddings.embed_documents([d.page_content for d in docs])
        self.store.add_documents(docs, embeddings_list)
        
        self.retriever = VectorRetriever(self.store, self.embeddings)
    
    def test_agentic_chain(self):
        """测试 Agentic RAG 链"""
        chain = AgenticRAGChain(
            retriever=self.retriever,
            llm=self.llm,
            max_iterations=2,
            confidence_threshold=0.5,
            enable_cache=True
        )
        
        result = chain.run("云计算有什么优势？")
        self.assertIn("answer", result)
        self.assertIn("iterations", result)
        self.assertIn("confidence", result)


class TestErrorHandling(unittest.TestCase):
    """测试错误处理"""
    
    def test_custom_exceptions(self):
        """测试自定义异常"""
        with self.assertRaises(RAGException):
            raise RAGException("测试错误", "TEST_ERROR")
        
        with self.assertRaises(ConfigurationError):
            raise ConfigurationError("配置错误", "test.key")
    
    def test_retryable_error(self):
        """测试可重试异常"""
        error = RetryableError("临时错误", retry_count=0, max_retries=3)
        self.assertTrue(error.should_retry)
        
        error.retry_count = 3
        error.should_retry = False
        self.assertFalse(error.should_retry)


if __name__ == "__main__":
    unittest.main()
