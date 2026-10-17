"""
性能监控和指标收集
"""
import time
import threading
from typing import Dict, List, Any, Optional
from collections import defaultdict
from dataclasses import dataclass, field
from ..utils import get_logger

logger = get_logger(__name__)


@dataclass
class MetricPoint:
    """指标数据点"""
    value: float
    timestamp: float = field(default_factory=time.time)
    tags: Dict[str, str] = field(default_factory=dict)


class MetricsCollector:
    """指标收集器"""
    
    def __init__(self):
        self._metrics: Dict[str, List[MetricPoint]] = defaultdict(list)
        self._counters: Dict[str, int] = defaultdict(int)
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()
    
    def counter(self, name: str, value: int = 1) -> None:
        """
        计数器（累加）
        
        Args:
            name: 指标名称
            value: 增加值
        """
        with self._lock:
            self._counters[name] += value
    
    def gauge(self, name: str, value: float) -> None:
        """
        仪表盘（当前值）
        
        Args:
            name: 指标名称
            value: 当前值
        """
        with self._lock:
            self._gauges[name] = value
    
    def histogram(self, name: str, value: float) -> None:
        """
        直方图（分布）
        
        Args:
            name: 指标名称
            value: 值
        """
        with self._lock:
            self._histograms[name].append(value)
    
    def timing(self, name: str, duration: float) -> None:
        """
        记录耗时
        
        Args:
            name: 指标名称
            duration: 耗时（秒）
        """
        with self._lock:
            self._metrics[name].append(MetricPoint(value=duration))
            self._histograms[name].append(duration)
    
    def get_counter(self, name: str) -> int:
        """获取计数器值"""
        return self._counters.get(name, 0)
    
    def get_gauge(self, name: str) -> Optional[float]:
        """获取仪表盘值"""
        return self._gauges.get(name)
    
    def get_histogram_stats(self, name: str) -> Dict[str, float]:
        """
        获取直方图统计信息
        
        Args:
            name: 指标名称
            
        Returns:
            统计信息字典
        """
        values = self._histograms.get(name, [])
        if not values:
            return {}
        
        return {
            'count': len(values),
            'min': min(values),
            'max': max(values),
            'avg': sum(values) / len(values),
            'sum': sum(values),
            'p50': sorted(values)[len(values) // 2],
            'p95': sorted(values)[int(len(values) * 0.95)] if len(values) > 20 else max(values),
            'p99': sorted(values)[int(len(values) * 0.99)] if len(values) > 100 else max(values),
        }
    
    def get_all_metrics(self) -> Dict[str, Any]:
        """获取所有指标"""
        with self._lock:
            result = {
                'counters': dict(self._counters),
                'gauges': dict(self._gauges),
                'histograms': {},
                'timings': {}
            }
            
            for name in self._histograms:
                result['histograms'][name] = self.get_histogram_stats(name)
            
            for name, points in self._metrics.items():
                result['timings'][name] = {
                    'count': len(points),
                    'latest': points[-1].value if points else 0
                }
            
            return result
    
    def reset(self) -> None:
        """重置所有指标"""
        with self._lock:
            self._metrics.clear()
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


class Timer:
    """计时器上下文管理器"""
    
    def __init__(self, collector: MetricsCollector, name: str):
        self.collector = collector
        self.name = name
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is not None:
            duration = time.time() - self.start_time
            self.collector.timing(self.name, duration)
            logger.debug(f"{self.name} 耗时: {duration:.3f}秒")


def timer(collector: MetricsCollector, name: str):
    """
    计时器装饰器
    
    Args:
        collector: 指标收集器
        name: 指标名称
        
    Returns:
        装饰器函数
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            with Timer(collector, name):
                return func(*args, **kwargs)
        return wrapper
    return decorator


# 全局指标收集器实例
metrics = MetricsCollector()


class RAGMetrics:
    """RAG系统专用指标"""
    
    def __init__(self):
        self.collector = MetricsCollector()
    
    def record_query(self, question: str, response_time: float, num_docs: int, chain_type: str = "rag"):
        """
        记录查询指标
        
        Args:
            question: 问题
            response_time: 响应时间
            num_docs: 检索文档数量
            chain_type: 链类型
        """
        self.collector.counter("total_queries")
        self.collector.timing("query_response_time", response_time)
        self.collector.histogram("retrieved_docs_count", num_docs)
        self.collector.gauge("last_response_time", response_time)
        
        logger.info(
            f"查询指标 - 响应时间: {response_time:.3f}s, "
            f"检索文档: {num_docs}, 链类型: {chain_type}"
        )
    
    def record_cache_hit(self):
        """记录缓存命中"""
        self.collector.counter("cache_hits")
    
    def record_cache_miss(self):
        """记录缓存未命中"""
        self.collector.counter("cache_misses")
    
    def record_error(self, error_type: str):
        """
        记录错误
        
        Args:
            error_type: 错误类型
        """
        self.collector.counter(f"errors_{error_type}")
    
    def record_retrieval(self, num_docs: int, retrieval_time: float):
        """
        记录检索指标
        
        Args:
            num_docs: 检索到的文档数量
            retrieval_time: 检索耗时
        """
        self.collector.counter("total_retrievals")
        self.collector.timing("retrieval_time", retrieval_time)
        self.collector.histogram("retrieved_docs", num_docs)
    
    def record_llm_call(self, prompt_length: int, response_length: int, llm_time: float):
        """
        记录LLM调用指标
        
        Args:
            prompt_length: 提示词长度
            response_length: 响应长度
            llm_time: LLM调用耗时
        """
        self.collector.counter("total_llm_calls")
        self.collector.timing("llm_call_time", llm_time)
        self.collector.histogram("prompt_length", prompt_length)
        self.collector.histogram("response_length", response_length)
    
    def get_summary(self) -> Dict[str, Any]:
        """获取指标摘要"""
        return self.collector.get_all_metrics()
