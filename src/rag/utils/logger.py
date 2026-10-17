"""
日志系统配置
提供结构化的日志记录功能
"""
import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Optional


class LoggerConfig:
    """日志配置类"""
    
    _initialized = False
    
    @classmethod
    def setup(
        cls,
        log_level: str = "INFO",
        log_dir: str = "logs",
        log_file: str = "rag.log",
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5,
        console_output: bool = True,
        file_output: bool = True,
    ) -> None:
        """
        设置日志系统
        
        Args:
            log_level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            log_dir: 日志目录
            log_file: 日志文件名
            max_bytes: 单个日志文件最大字节数
            backup_count: 保留的日志文件数量
            console_output: 是否输出到控制台
            file_output: 是否输出到文件
        """
        if cls._initialized:
            return
        
        # 创建日志目录
        if file_output:
            log_path = Path(log_dir)
            log_path.mkdir(parents=True, exist_ok=True)
        
        # 配置根日志器
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, log_level.upper()))
        
        # 清除现有处理器
        root_logger.handlers.clear()
        
        # 日志格式
        detailed_formatter = logging.Formatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        simple_formatter = logging.Formatter(
            fmt='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 控制台处理器
        if console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(getattr(logging, log_level.upper()))
            console_handler.setFormatter(simple_formatter)
            root_logger.addHandler(console_handler)
        
        # 文件处理器（带轮转）
        if file_output:
            file_handler = RotatingFileHandler(
                Path(log_dir) / log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
            file_handler.setLevel(getattr(logging, log_level.upper()))
            file_handler.setFormatter(detailed_formatter)
            root_logger.addHandler(file_handler)
        
        cls._initialized = True
        logging.info("日志系统已初始化")
    
    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """
        获取日志器
        
        Args:
            name: 日志器名称
            
        Returns:
            logging.Logger 实例
        """
        if not cls._initialized:
            cls.setup()
        return logging.getLogger(name)


def get_logger(name: str) -> logging.Logger:
    """
    获取日志器的便捷函数
    
    Args:
        name: 日志器名称
        
    Returns:
        logging.Logger 实例
    """
    return LoggerConfig.get_logger(name)


class PerformanceLogger:
    """性能日志记录器"""
    
    def __init__(self, logger: logging.Logger, operation: str):
        self.logger = logger
        self.operation = operation
        self.start_time = None
    
    def __enter__(self):
        import time
        self.start_time = time.time()
        self.logger.info(f"开始执行: {self.operation}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        import time
        elapsed = time.time() - self.start_time
        if exc_type is None:
            self.logger.info(f"完成: {self.operation} (耗时: {elapsed:.3f}秒)")
        else:
            self.logger.error(f"失败: {self.operation} (耗时: {elapsed:.3f}秒, 错误: {exc_val})")


def log_performance(logger: logging.Logger, operation: str):
    """
    性能日志装饰器
    
    Args:
        logger: 日志器
        operation: 操作名称
        
    Returns:
        装饰器函数
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            with PerformanceLogger(logger, operation):
                return func(*args, **kwargs)
        return wrapper
    return decorator
