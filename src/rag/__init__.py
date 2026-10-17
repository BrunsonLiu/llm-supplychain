"""
RAG (Retrieval-Augmented Generation) 项目

一个完整的RAG实现，包含：
- 文档加载
- 文本分割
- 向量嵌入
- 向量存储
- 检索
- LLM集成
- RAG链
"""

from .document import Document
from .loaders import (
    BaseLoader,
    TextLoader,
    JSONLoader,
    CSVLoader,
)
from .splitters import (
    BaseSplitter,
    RecursiveCharacterTextSplitter,
    CharacterTextSplitter,
    MarkdownTextSplitter,
    HeadingSectionSplitter,
)
from .embeddings import (
    BaseEmbeddings,
    OpenAIEmbeddings,
    MockEmbeddings,
    HuggingFaceEmbeddings,
)
from .vectorstores import (
    BaseVectorStore,
    MemoryVectorStore,
    FAISSVectorStore,
)
from .retrievers import (
    BaseRetriever,
    VectorRetriever,
    MultiQueryRetriever,
)
from .llms import (
    BaseLLM,
    LLMResponse,
    OpenAILLM,
    MockLLM,
)
from .chains import (
    RAGChain,
    ConversationalRAGChain,
    DecisionRAGChain,
    AgenticRAGChain,
)
from .utils import (
    get_logger,
    LoggerConfig,
    PerformanceLogger,
    log_performance,
    RAGException,
    ConfigurationError,
    DocumentLoadError,
    EmbeddingError,
    VectorStoreError,
    RetrievalError,
    LLMError,
    ChainError,
    APIError,
    TimeoutError,
    ValidationError,
    RetryableError,
    retry,
    retry_with_state,
    RetryManager,
    SimpleCache,
    FileCache,
    CacheManager,
    generate_cache_key,
)

__version__ = "0.1.0"

__all__ = [
    'Document',
    'BaseLoader',
    'TextLoader',
    'JSONLoader',
    'CSVLoader',
    'BaseSplitter',
    'RecursiveCharacterTextSplitter',
    'CharacterTextSplitter',
    'MarkdownTextSplitter',
    'HeadingSectionSplitter',
    'BaseEmbeddings',
    'OpenAIEmbeddings',
    'MockEmbeddings',
    'HuggingFaceEmbeddings',
    'BaseVectorStore',
    'MemoryVectorStore',
    'FAISSVectorStore',
    'BaseRetriever',
    'VectorRetriever',
    'MultiQueryRetriever',
    'BaseLLM',
    'LLMResponse',
    'OpenAILLM',
    'MockLLM',
    'RAGChain',
    'ConversationalRAGChain',
    'DecisionRAGChain',
    'AgenticRAGChain',
    'get_logger',
    'LoggerConfig',
    'PerformanceLogger',
    'log_performance',
    'RAGException',
    'ConfigurationError',
    'DocumentLoadError',
    'EmbeddingError',
    'VectorStoreError',
    'RetrievalError',
    'LLMError',
    'ChainError',
    'APIError',
    'TimeoutError',
    'ValidationError',
    'RetryableError',
    'retry',
    'retry_with_state',
    'RetryManager',
    'SimpleCache',
    'FileCache',
    'CacheManager',
    'generate_cache_key',
]
