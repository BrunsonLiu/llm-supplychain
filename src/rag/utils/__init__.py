"""
工具函数模块
"""
# 注意：pipeline_builder 不在此处顶层导入。
# 它依赖 chains/retrievers 等高层模块，而 chains 又依赖本模块的 logger/cache，
# 顶层导入会形成循环依赖（utils <-> chains）。改用 PEP 562 模块 __getattr__
# 延迟加载：from rag.utils import RAGPipelineBuilder 仍然可用，但只有在
# 整个 rag 包初始化完成后才真正触发导入。
from .logger import get_logger, LoggerConfig, PerformanceLogger, log_performance
from .exceptions import (
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
)
from .retry import retry, retry_with_state, RetryManager
from .cache import SimpleCache, FileCache, CacheManager, generate_cache_key
from .config import (
    RAGConfig,
    LLMConfig,
    EmbeddingsConfig,
    VectorStoreConfig,
    TextSplitterConfig,
    RetrieverConfig,
    ChainConfig,
    PathsConfig,
)

__all__ = [
    'RAGPipelineBuilder',
    'create_rag_pipeline',
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
    'RAGConfig',
    'LLMConfig',
    'EmbeddingsConfig',
    'VectorStoreConfig',
    'TextSplitterConfig',
    'RetrieverConfig',
    'ChainConfig',
    'PathsConfig',
]


def __getattr__(name):
    """PEP 562 模块级延迟属性：按需加载 pipeline_builder，避免循环导入"""
    if name in ('RAGPipelineBuilder', 'create_rag_pipeline'):
        from . import pipeline_builder
        return getattr(pipeline_builder, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
