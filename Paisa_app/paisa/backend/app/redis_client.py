"""app/redis_client.py — async Redis pool"""
from __future__ import annotations

import redis.asyncio as aioredis
from app.config import settings

_pool: aioredis.Redis | None = None


def get_redis_pool() -> aioredis.Redis:
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(
            settings.REDIS_URL,
            max_connections=settings.REDIS_POOL_SIZE,
            decode_responses=True,
        )
    return _pool


async def get_redis() -> aioredis.Redis:
    """FastAPI dependency."""
    return get_redis_pool()
