"""
自定义异常类
定义项目中使用的各种异常
"""


class RAGException(Exception):
    """RAG系统基础异常类"""
    
    def __init__(self, message: str, error_code: str = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or "RAG_ERROR"


class ConfigurationError(RAGException):
    """配置错误异常"""
    
    def __init__(self, message: str, config_key: str = None):
        super().__init__(message, "CONFIG_ERROR")
        self.config_key = config_key


class DocumentLoadError(RAGException):
    """文档加载失败异常"""
    
    def __init__(self, message: str, file_path: str = None):
        super().__init__(message, "DOCUMENT_LOAD_ERROR")
        self.file_path = file_path


class EmbeddingError(RAGException):
    """嵌入向量生成失败异常"""
    
    def __init__(self, message: str, model_name: str = None):
        super().__init__(message, "EMBEDDING_ERROR")
        self.model_name = model_name


class VectorStoreError(RAGException):
    """向量存储操作失败异常"""
    
    def __init__(self, message: str, operation: str = None):
        super().__init__(message, "VECTOR_STORE_ERROR")
        self.operation = operation


class RetrievalError(RAGException):
    """检索失败异常"""
    
    def __init__(self, message: str, query: str = None):
        super().__init__(message, "RETRIEVAL_ERROR")
        self.query = query


class LLMError(RAGException):
    """大语言模型调用失败异常"""
    
    def __init__(self, message: str, model: str = None, status_code: int = None):
        super().__init__(message, "LLM_ERROR")
        self.model = model
        self.status_code = status_code


class ChainError(RAGException):
    """RAG链执行失败异常"""
    
    def __init__(self, message: str, chain_type: str = None):
        super().__init__(message, "CHAIN_ERROR")
        self.chain_type = chain_type


class APIError(RAGException):
    """API调用失败异常"""
    
    def __init__(self, message: str, endpoint: str = None, status_code: int = None):
        super().__init__(message, "API_ERROR")
        self.endpoint = endpoint
        self.status_code = status_code


class TimeoutError(RAGException):
    """超时异常"""
    
    def __init__(self, message: str, timeout_seconds: float = None):
        super().__init__(message, "TIMEOUT_ERROR")
        self.timeout_seconds = timeout_seconds


class ValidationError(RAGException):
    """数据验证失败异常"""
    
    def __init__(self, message: str, field: str = None):
        super().__init__(message, "VALIDATION_ERROR")
        self.field = field


class RetryableError(RAGException):
    """可重试的异常"""
    
    def __init__(self, message: str, retry_count: int = 0, max_retries: int = 3):
        super().__init__(message, "RETRYABLE_ERROR")
        self.retry_count = retry_count
        self.max_retries = max_retries
        self.should_retry = retry_count < max_retries
