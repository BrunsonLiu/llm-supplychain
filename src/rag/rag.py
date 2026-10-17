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

__version__ = "0.1.0"

__all__ = [
    # Document
    'Document',
    # Loaders
    'BaseLoader',
    'TextLoader',
    'JSONLoader',
    'CSVLoader',
    # Splitters
    'BaseSplitter',
    'RecursiveCharacterTextSplitter',
    'CharacterTextSplitter',
    'MarkdownTextSplitter',
    'HeadingSectionSplitter',
    # Embeddings
    'BaseEmbeddings',
    'OpenAIEmbeddings',
    'MockEmbeddings',
    'HuggingFaceEmbeddings',
    # VectorStores
    'BaseVectorStore',
    'MemoryVectorStore',
    'FAISSVectorStore',
    # Retrievers
    'BaseRetriever',
    'VectorRetriever',
    'MultiQueryRetriever',
    # LLMs
    'BaseLLM',
    'LLMResponse',
    'OpenAILLM',
    'MockLLM',
    # Chains
    'RAGChain',
    'ConversationalRAGChain',
    'DecisionRAGChain',
    'AgenticRAGChain',
]
