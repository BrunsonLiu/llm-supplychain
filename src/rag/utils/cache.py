"""
缓存系统
提供查询结果和嵌入向量的缓存功能
"""
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from ..utils.logger import get_logger

logger = get_logger(__name__)


class CacheEntry:
    """缓存条目"""
    
    def __init__(self, key: str, value: Any, ttl: Optional[int] = None):
        self.key = key
        self.value = value
        self.created_at = time.time()
        self.ttl = ttl  # Time To Live in seconds, None means no expiration
    
    def is_expired(self) -> bool:
        """检查缓存是否过期"""
        if self.ttl is None:
            return False
        return (time.time() - self.created_at) > self.ttl


class SimpleCache:
    """简单的内存缓存"""
    
    def __init__(self, max_size: int = 1000, default_ttl: Optional[int] = 3600):
        """
        初始化缓存
        
        Args:
            max_size: 最大缓存条目数
            default_ttl: 默认TTL（秒）
        """
        self.cache: Dict[str, CacheEntry] = {}
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.hits = 0
        self.misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存值
        
        Args:
            key: 缓存键
            
        Returns:
            缓存值，如果不存在或已过期则返回 None
        """
        if key not in self.cache:
            self.misses += 1
            return None
        
        entry = self.cache[key]
        if entry.is_expired():
            del self.cache[key]
            self.misses += 1
            logger.debug(f"缓存过期: {key}")
            return None
        
        self.hits += 1
        logger.debug(f"缓存命中: {key}")
        return entry.value
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        设置缓存值
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl: TTL（秒），None 使用默认值
        """
        # 如果缓存已满，清理过期条目
        if len(self.cache) >= self.max_size:
            self._cleanup()
        
        # 如果仍然满了，删除最旧的条目
        if len(self.cache) >= self.max_size:
            oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k].created_at)
            del self.cache[oldest_key]
            logger.debug(f"缓存已满，删除最旧条目: {oldest_key}")
        
        self.cache[key] = CacheEntry(key, value, ttl or self.default_ttl)
    
    def delete(self, key: str) -> bool:
        """删除缓存条目"""
        if key in self.cache:
            del self.cache[key]
            return True
        return False
    
    def clear(self) -> None:
        """清空缓存"""
        self.cache.clear()
        self.hits = 0
        self.misses = 0
    
    def _cleanup(self) -> None:
        """清理过期条目"""
        expired_keys = [k for k, v in self.cache.items() if v.is_expired()]
        for key in expired_keys:
            del self.cache[key]
        logger.debug(f"清理了 {len(expired_keys)} 个过期缓存条目")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        total = self.hits + self.misses
        hit_rate = self.hits / total if total > 0 else 0
        return {
            'size': len(self.cache),
            'max_size': self.max_size,
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': f"{hit_rate:.2%}"
        }


class FileCache:
    """文件缓存（用于持久化）"""
    
    def __init__(self, cache_dir: str = "cache", default_ttl: Optional[int] = 86400):
        """
        初始化文件缓存
        
        Args:
            cache_dir: 缓存目录
            default_ttl: 默认TTL（秒）
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl = default_ttl
    
    def _get_cache_path(self, key: str) -> Path:
        """获取缓存文件路径"""
        key_hash = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{key_hash}.json"
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        cache_path = self._get_cache_path(key)
        
        if not cache_path.exists():
            return None
        
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 检查是否过期
            if data.get('ttl') is not None:
                age = time.time() - data.get('created_at', 0)
                if age > data['ttl']:
                    cache_path.unlink()
                    logger.debug(f"文件缓存过期: {key}")
                    return None
            
            logger.debug(f"文件缓存命中: {key}")
            return data.get('value')
        except Exception as e:
            logger.warning(f"读取文件缓存失败: {e}")
            return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """设置缓存值"""
        cache_path = self._get_cache_path(key)
        
        data = {
            'key': key,
            'value': value,
            'created_at': time.time(),
            'ttl': ttl or self.default_ttl
        }
        
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug(f"设置文件缓存: {key}")
        except Exception as e:
            logger.warning(f"写入文件缓存失败: {e}")
    
    def delete(self, key: str) -> bool:
        """删除缓存条目"""
        cache_path = self._get_cache_path(key)
        if cache_path.exists():
            cache_path.unlink()
            return True
        return False
    
    def clear(self) -> None:
        """清空缓存"""
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()


class CacheManager:
    """缓存管理器（组合内存和文件缓存）"""
    
    def __init__(
        self,
        enable_memory_cache: bool = True,
        enable_file_cache: bool = False,
        memory_cache_size: int = 1000,
        default_ttl: int = 3600,
        cache_dir: str = "cache"
    ):
        self.enable_memory_cache = enable_memory_cache
        self.enable_file_cache = enable_file_cache
        
        if enable_memory_cache:
            self.memory_cache = SimpleCache(
                max_size=memory_cache_size,
                default_ttl=default_ttl
            )
        else:
            self.memory_cache = None
        
        if enable_file_cache:
            self.file_cache = FileCache(
                cache_dir=cache_dir,
                default_ttl=default_ttl
            )
        else:
            self.file_cache = None
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存（先查内存，再查文件）"""
        # 先查内存缓存
        if self.memory_cache:
            value = self.memory_cache.get(key)
            if value is not None:
                return value
        
        # 再查文件缓存
        if self.file_cache:
            value = self.file_cache.get(key)
            if value is not None:
                # 写回内存缓存
                if self.memory_cache:
                    self.memory_cache.set(key, value)
                return value
        
        return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """设置缓存（同时写入内存和文件）"""
        if self.memory_cache:
            self.memory_cache.set(key, value, ttl)
        
        if self.file_cache:
            self.file_cache.set(key, value, ttl)
    
    def delete(self, key: str) -> None:
        """删除缓存"""
        if self.memory_cache:
            self.memory_cache.delete(key)
        if self.file_cache:
            self.file_cache.delete(key)
    
    def clear(self) -> None:
        """清空所有缓存"""
        if self.memory_cache:
            self.memory_cache.clear()
        if self.file_cache:
            self.file_cache.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        stats = {}
        if self.memory_cache:
            stats['memory_cache'] = self.memory_cache.get_stats()
        if self.file_cache:
            stats['file_cache'] = {
                'cache_dir': str(self.file_cache.cache_dir)
            }
        return stats


def generate_cache_key(prefix: str, *args, **kwargs) -> str:
    """
    生成缓存键
    
    Args:
        prefix: 前缀
        *args: 位置参数
        **kwargs: 关键字参数
        
    Returns:
        缓存键
    """
    key_data = {
        'prefix': prefix,
        'args': str(args),
        'kwargs': str(kwargs)
    }
    key_str = json.dumps(key_data, sort_keys=True)
    return hashlib.md5(key_str.encode()).hexdigest()
