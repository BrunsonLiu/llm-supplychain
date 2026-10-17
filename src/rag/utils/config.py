"""
配置验证模块
使用 Pydantic 进行配置验证
"""
import os
from pydantic import BaseModel, Field, validator
from typing import Optional, Literal
from pathlib import Path
import yaml
from ..utils.exceptions import ConfigurationError


class LLMConfig(BaseModel):
    """LLM配置"""
    provider: Literal["openai", "mock"] = "mock"
    model: str = "gpt-4o-mini"
    api_key: Optional[str] = ""
    base_url: Optional[str] = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2000, ge=1, le=4096)
    
    @validator('api_key')
    def validate_api_key(cls, v, values):
        # api_key 可为空：允许从环境变量回退（OPENAI_API_KEY / DEEPSEEK_API_KEY），
        # 二者都没有时才报错。这样 config.yaml 可以安全提交而不含密钥。
        if values.get('provider') == 'openai' and not v:
            if not os.environ.get('OPENAI_API_KEY') and not os.environ.get('DEEPSEEK_API_KEY'):
                raise ConfigurationError(
                    "OpenAI API key is required when using openai provider "
                    "(config api_key or env OPENAI_API_KEY)",
                    config_key='llm.api_key'
                )
        return v


class EmbeddingsConfig(BaseModel):
    """嵌入模型配置"""
    provider: Literal["openai", "huggingface", "mock"] = "mock"
    model: str = "text-embedding-3-small"
    huggingface_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    api_key: Optional[str] = ""
    dimension: int = Field(default=1536, ge=1)


class VectorStoreConfig(BaseModel):
    """向量存储配置"""
    type: Literal["memory", "faiss"] = "memory"
    dimension: int = Field(default=1536, ge=1)
    persist_path: str = "./data/vectorstore"


class TextSplitterConfig(BaseModel):
    """文本分割配置"""
    type: Literal["recursive", "character", "markdown"] = "recursive"
    chunk_size: int = Field(default=1000, ge=100, le=10000)
    chunk_overlap: int = Field(default=200, ge=0)
    
    @validator('chunk_overlap')
    def validate_overlap(cls, v, values):
        if v >= values.get('chunk_size', 1000):
            raise ConfigurationError(
                "chunk_overlap must be less than chunk_size",
                config_key='text_splitter.chunk_overlap'
            )
        return v


class RetrieverConfig(BaseModel):
    """检索配置"""
    type: Literal["vector", "multi_query"] = "vector"
    top_k: int = Field(default=4, ge=1, le=20)
    use_multi_query: bool = False
    num_queries: int = Field(default=3, ge=1, le=10)


class ChainConfig(BaseModel):
    """RAG链配置"""
    type: Literal["rag", "conversational", "decision", "agentic"] = "rag"
    return_source_documents: bool = True
    max_iterations: int = Field(default=3, ge=1, le=10)


class PathsConfig(BaseModel):
    """路径配置"""
    data_dir: str = "./data"
    documents_dir: str = "./data/documents"
    vectorstore_dir: str = "./data/vectorstore"
    output_dir: str = "./output"


class RAGConfig(BaseModel):
    """RAG系统完整配置"""
    llm: LLMConfig = Field(default_factory=LLMConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    vectorstore: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    text_splitter: TextSplitterConfig = Field(default_factory=TextSplitterConfig)
    retriever: RetrieverConfig = Field(default_factory=RetrieverConfig)
    chain: ChainConfig = Field(default_factory=ChainConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    
    @classmethod
    def from_yaml(cls, config_path: str) -> 'RAGConfig':
        """
        从YAML文件加载配置
        
        Args:
            config_path: 配置文件路径
            
        Returns:
            RAGConfig实例
        """
        config_file = Path(config_path)
        if not config_file.exists():
            raise ConfigurationError(
                f"配置文件不存在: {config_path}",
                config_key='config_path'
            )
        
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
            
            return cls(**config_data)
        except Exception as e:
            if isinstance(e, ConfigurationError):
                raise
            raise ConfigurationError(
                f"加载配置文件失败: {e}",
                config_key='config_path'
            )
    
    def to_yaml(self, config_path: str) -> None:
        """
        保存配置到YAML文件
        
        Args:
            config_path: 配置文件路径
        """
        config_file = Path(config_path)
        config_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.dump(self.dict(), f, default_flow_style=False, allow_unicode=True)
    
    def validate_paths(self) -> None:
        """验证路径是否存在，不存在则创建"""
        for path_field in [self.paths.data_dir, self.paths.documents_dir, 
                          self.paths.vectorstore_dir, self.paths.output_dir]:
            path = Path(path_field)
            path.mkdir(parents=True, exist_ok=True)
