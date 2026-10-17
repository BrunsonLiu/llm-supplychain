"""
RAG管道构建器
用于简化RAG系统的构建
"""
from pathlib import Path
from typing import List, Optional
import yaml

# 注意：必须从具体子模块导入，不能从 ..rag 聚合入口导入——
# 否则 rag/__init__ -> retrievers -> hybrid_retriever -> utils -> 本模块 -> ..rag 形成循环导入
from ..document import Document
from ..loaders import (
    BaseLoader,
    TextLoader,
    JSONLoader,
    CSVLoader,
)
from ..splitters import (
    BaseSplitter,
    RecursiveCharacterTextSplitter,
    CharacterTextSplitter,
    MarkdownTextSplitter,
)
from ..embeddings import (
    BaseEmbeddings,
    OpenAIEmbeddings,
    MockEmbeddings,
    HuggingFaceEmbeddings,
)
from ..vectorstores import (
    BaseVectorStore,
    MemoryVectorStore,
    FAISSVectorStore,
)
from ..retrievers import (
    BaseRetriever,
    VectorRetriever,
    MultiQueryRetriever,
)
from ..llms import (
    BaseLLM,
    LLMResponse,
    OpenAILLM,
    MockLLM,
)
from ..chains import (
    RAGChain,
    ConversationalRAGChain,
    DecisionRAGChain,
    AgenticRAGChain,
)


class RAGPipelineBuilder:
    """RAG管道构建器"""
    
    def __init__(self):
        self.documents: Optional[List[Document]] = None
        self.loader: Optional[BaseLoader] = None
        self.splitter: Optional[BaseSplitter] = None
        self.embeddings: Optional[BaseEmbeddings] = None
        self.vector_store: Optional[BaseVectorStore] = None
        self.retriever: Optional[BaseRetriever] = None
        self.llm: Optional[BaseLLM] = None
        self.chain = None
    
    def load_documents(self, path: str, loader_type: str = "text") -> "RAGPipelineBuilder":
        """加载文档"""
        path = Path(path)
        
        if loader_type == "text":
            self.loader = TextLoader(path)
        elif loader_type == "json":
            self.loader = JSONLoader(path)
        elif loader_type == "csv":
            self.loader = CSVLoader(path)
        else:
            raise ValueError(f"Unknown loader type: {loader_type}")
        
        self.documents = self.loader.load()
        print(f"✓ 加载了 {len(self.documents)} 个文档")
        return self
    
    def split(
        self,
        splitter_type: str = "recursive",
        chunk_size: int = 1000,
        chunk_overlap: int = 200
    ) -> "RAGPipelineBuilder":
        """分割文档"""
        if splitter_type == "recursive":
            self.splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap
            )
        elif splitter_type == "character":
            self.splitter = CharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap
            )
        elif splitter_type == "markdown":
            self.splitter = MarkdownTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap
            )
        else:
            raise ValueError(f"Unknown splitter type: {splitter_type}")
        
        self.documents = self.splitter.split_documents(self.documents)
        print(f"✓ 分割成 {len(self.documents)} 个文本块")
        return self
    
    def with_embeddings(
        self,
        provider: str = "mock",
        **kwargs
    ) -> "RAGPipelineBuilder":
        """配置嵌入模型"""
        if provider == "openai":
            self.embeddings = OpenAIEmbeddings(**kwargs)
        elif provider == "huggingface":
            self.embeddings = HuggingFaceEmbeddings(**kwargs)
        elif provider == "mock":
            self.embeddings = MockEmbeddings(**kwargs)
        else:
            raise ValueError(f"Unknown embeddings provider: {provider}")
        
        print(f"✓ 使用 {provider} 嵌入模型")
        return self
    
    def with_vector_store(
        self,
        store_type: str = "memory",
        **kwargs
    ) -> "RAGPipelineBuilder":
        """配置向量存储"""
        if store_type == "memory":
            self.vector_store = MemoryVectorStore(**kwargs)
        elif store_type == "faiss":
            self.vector_store = FAISSVectorStore(**kwargs)
        else:
            raise ValueError(f"Unknown vector store type: {store_type}")
        
        # 添加文档到向量存储
        if self.documents and self.embeddings:
            embeddings_list = self.embeddings.embed_documents(
                [doc.page_content for doc in self.documents]
            )
            self.vector_store.add_documents(self.documents, embeddings_list)
            print(f"✓ 向量存储已配置，包含 {len(self.documents)} 个文档")
        
        return self
    
    def with_retriever(
        self,
        retriever_type: str = "vector",
        **kwargs
    ) -> "RAGPipelineBuilder":
        """配置检索器"""
        if retriever_type == "vector":
            self.retriever = VectorRetriever(
                self.vector_store,
                self.embeddings,
                **kwargs
            )
        elif retriever_type == "multi_query":
            base_retriever = VectorRetriever(
                self.vector_store,
                self.embeddings
            )
            self.retriever = MultiQueryRetriever(
                base_retriever,
                llm=self.llm,
                **kwargs
            )
        else:
            raise ValueError(f"Unknown retriever type: {retriever_type}")
        
        print(f"✓ 检索器已配置: {retriever_type}")
        return self
    
    def with_llm(
        self,
        provider: str = "mock",
        **kwargs
    ) -> "RAGPipelineBuilder":
        """配置LLM"""
        if provider == "openai":
            self.llm = OpenAILLM(**kwargs)
        elif provider == "mock":
            self.llm = MockLLM(**kwargs)
        else:
            raise ValueError(f"Unknown LLM provider: {provider}")
        
        print(f"✓ 使用 {provider} LLM")
        return self
    
    def build_chain(
        self,
        chain_type: str = "rag",
        **kwargs
    ) -> RAGChain:
        """构建RAG链"""
        if chain_type == "rag":
            self.chain = RAGChain(
                retriever=self.retriever,
                llm=self.llm,
                **kwargs
            )
        elif chain_type == "conversational":
            self.chain = ConversationalRAGChain(
                retriever=self.retriever,
                llm=self.llm,
                **kwargs
            )
        elif chain_type == "decision":
            self.chain = DecisionRAGChain(
                retriever=self.retriever,
                llm=self.llm,
                **kwargs
            )
        elif chain_type == "agentic":
            self.chain = AgenticRAGChain(
                retriever=self.retriever,
                llm=self.llm,
                **kwargs
            )
        else:
            raise ValueError(f"Unknown chain type: {chain_type}")
        
        print(f"✓ RAG链已构建: {chain_type}")
        return self.chain
    
    @classmethod
    def from_config(cls, config_path: str) -> RAGChain:
        """从配置文件构建RAG管道"""
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        builder = cls()
        
        # 配置LLM
        llm_config = config.get('llm', {})
        builder.with_llm(**llm_config)
        
        # 配置嵌入模型
        emb_config = config.get('embeddings', {})
        builder.with_embeddings(**emb_config)
        
        # 配置向量存储
        vs_config = config.get('vectorstore', {})
        builder.with_vector_store(**vs_config)
        
        # 配置检索器
        ret_config = config.get('retriever', {})
        builder.with_retriever(**ret_config)
        
        # 构建链
        chain_config = config.get('chain', {})
        return builder.build_chain(**chain_config)


def create_rag_pipeline(
    documents_path: str,
    llm_provider: str = "mock",
    embeddings_provider: str = "mock",
    chain_type: str = "rag"
) -> RAGChain:
    """
    快速创建RAG管道的便捷函数
    
    Args:
        documents_path: 文档路径
        llm_provider: LLM提供商 (mock, openai)
        embeddings_provider: 嵌入模型提供商 (mock, openai, huggingface)
        chain_type: RAG链类型 (rag, conversational, decision, agentic)
    
    Returns:
        RAGChain实例
    """
    return (
        RAGPipelineBuilder()
        .load_documents(documents_path)
        .split()
        .with_embeddings(provider=embeddings_provider)
        .with_vector_store()
        .with_llm(provider=llm_provider)
        .with_retriever()
        .build_chain(chain_type=chain_type)
    )
