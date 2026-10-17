"""
重试机制工具
提供可配置的重试策略
"""
import time
import functools
from typing import Callable, Optional, Tuple, Type, Union
from ..utils.exceptions import RetryableError
from ..utils.logger import get_logger

logger = get_logger(__name__)


def retry(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    retry_on: Optional[Callable[[Exception], bool]] = None,
) -> Callable:
    """
    重试装饰器
    
    Args:
        max_retries: 最大重试次数
        delay: 初始延迟时间（秒）
        backoff_factor: 退避因子（每次重试延迟倍数）
        exceptions: 需要重试的异常类型
        retry_on: 自定义重试条件函数
        
    Returns:
        装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    # 检查是否应该重试
                    if retry_on and not retry_on(e):
                        logger.error(f"不满足重试条件，放弃重试: {e}")
                        raise
                    
                    if attempt < max_retries:
                        logger.warning(
                            f"第 {attempt + 1} 次尝试失败，{current_delay:.1f}秒后重试: {e}"
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff_factor
                    else:
                        logger.error(
                            f"达到最大重试次数 ({max_retries})，放弃重试: {e}"
                        )
                        raise
            
            # 理论上不会到这里，但为了类型检查
            raise last_exception
        
        return wrapper
    return decorator


def retry_with_state(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
) -> Callable:
    """
    带状态的重试装饰器（支持 RetryableError）
    
    Args:
        max_retries: 最大重试次数
        delay: 初始延迟时间（秒）
        backoff_factor: 退避因子
        exceptions: 需要重试的异常类型
        
    Returns:
        装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if isinstance(e, RetryableError):
                        e.retry_count = attempt + 1
                        e.max_retries = max_retries
                        e.should_retry = attempt < max_retries
                    
                    if attempt < max_retries:
                        logger.warning(
                            f"第 {attempt + 1} 次尝试失败，{current_delay:.1f}秒后重试: {e}"
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff_factor
                    else:
                        logger.error(f"达到最大重试次数 ({max_retries}): {e}")
                        raise
            
            raise Exception("Should not reach here")
        
        return wrapper
    return decorator


class RetryManager:
    """重试管理器（面向对象方式）"""
    
    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        backoff_factor: float = 2.0,
        max_delay: float = 60.0,
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.backoff_factor = backoff_factor
        self.max_delay = max_delay
    
    def execute(
        self,
        func: Callable,
        *args,
        exceptions: Tuple[Type[Exception], ...] = (Exception,),
        **kwargs
    ) -> any:
        """
        执行函数并支持重试
        
        Args:
            func: 要执行的函数
            *args: 函数参数
            exceptions: 需要重试的异常类型
            **kwargs: 关键字参数
            
        Returns:
            函数执行结果
        """
        current_delay = self.initial_delay
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except exceptions as e:
                last_exception = e
                
                if attempt < self.max_retries:
                    logger.warning(
                        f"第 {attempt + 1} 次尝试失败，{current_delay:.1f}秒后重试: {e}"
                    )
                    time.sleep(current_delay)
                    current_delay = min(current_delay * self.backoff_factor, self.max_delay)
                else:
                    logger.error(f"达到最大重试次数 ({self.max_retries}): {e}")
                    raise
        
        raise last_exception
