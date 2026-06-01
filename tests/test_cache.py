"""Tests for cache module."""
import time
import pytest
from app.cache import SimpleCache


def test_cache_set_and_get():
    """Test setting and getting values from cache."""
    cache = SimpleCache(ttl_seconds=10)
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"


def test_cache_expiration():
    """Test that cache values expire after TTL."""
    cache = SimpleCache(ttl_seconds=1)
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"
    
    time.sleep(1.1)
    assert cache.get("key1") is None


def test_cache_get_nonexistent():
    """Test getting non-existent key returns None."""
    cache = SimpleCache()
    assert cache.get("nonexistent") is None


def test_cache_delete():
    """Test deleting key from cache."""
    cache = SimpleCache()
    cache.set("key1", "value1")
    cache.delete("key1")
    assert cache.get("key1") is None


def test_cache_clear():
    """Test clearing all cache."""
    cache = SimpleCache()
    cache.set("key1", "value1")
    cache.set("key2", "value2")
    cache.clear()
    assert cache.get("key1") is None
    assert cache.get("key2") is None


def test_cache_overwrite():
    """Test overwriting existing cache value."""
    cache = SimpleCache()
    cache.set("key1", "value1")
    cache.set("key1", "value2")
    assert cache.get("key1") == "value2"
