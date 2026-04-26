import time
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings

_redis_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


# ── Rate limit — token bucket ─────────────────────────────────────────────────
# Lua script atomique : évite race conditions
_RATE_LIMIT_SCRIPT = """
local key        = KEYS[1]
local capacity   = tonumber(ARGV[1])
local rate       = tonumber(ARGV[2])   -- tokens/seconde
local now        = tonumber(ARGV[3])
local cost       = tonumber(ARGV[4])   -- tokens consommés (1 en général)

local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens     = tonumber(bucket[1]) or capacity
local last_refill = tonumber(bucket[2]) or now

local elapsed = now - last_refill
local refill  = elapsed * rate
tokens = math.min(capacity, tokens + refill)

if tokens >= cost then
    tokens = tokens - cost
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
    redis.call('EXPIRE', key, math.ceil(capacity / rate) + 10)
    return 1
else
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
    redis.call('EXPIRE', key, math.ceil(capacity / rate) + 10)
    return 0
end
"""


async def check_rate_limit(
    r: aioredis.Redis,
    key: str,
    capacity: int,
    rate_per_second: float,
    cost: int = 1,
) -> bool:
    """Retourne True si la requête est autorisée, False si throttlée."""
    now = time.time()
    result = await r.eval(  # type: ignore[attr-defined]
        _RATE_LIMIT_SCRIPT,
        1,
        key,
        capacity,
        rate_per_second,
        now,
        cost,
    )
    return bool(result)


# ── Cache TTL ─────────────────────────────────────────────────────────────────

async def cache_get(r: aioredis.Redis, key: str) -> str | None:
    return await r.get(key)


async def cache_set(r: aioredis.Redis, key: str, value: Any, ttl: int) -> None:
    await r.setex(key, ttl, str(value))


async def cache_delete(r: aioredis.Redis, key: str) -> None:
    await r.delete(key)
