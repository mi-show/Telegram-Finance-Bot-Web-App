"""Simple in-memory cache for expensive operations."""
import time
from typing import Any, Callable, Optional


class SimpleCache:
    """Basic TTL-based cache."""
    
    def __init__(self, ttl_seconds: int = 300):
        self.ttl = ttl_seconds
        self._cache: dict[str, tuple[Any, float]] = {}
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired."""
        if key not in self._cache:
            return None
        
        value, timestamp = self._cache[key]
        if time.time() - timestamp > self.ttl:
            del self._cache[key]
            return None
        
        return value
    
    def set(self, key: str, value: Any) -> None:
        """Set value in cache with current timestamp."""
        self._cache[key] = (value, time.time())
    
    def clear(self) -> None:
        """Clear all cache."""
        self._cache.clear()
    
    def delete(self, key: str) -> None:
        """Delete specific key from cache."""
        if key in self._cache:
            del self._cache[key]
