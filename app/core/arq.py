import logging
from typing import Optional

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import settings

logger = logging.getLogger(__name__)

_arq_pool: Optional[ArqRedis] = None


async def get_arq_pool() -> ArqRedis:
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        logger.info("ARQ pool created")
    return _arq_pool


async def close_arq_pool() -> None:
    global _arq_pool
    if _arq_pool:
        await _arq_pool.close()
        _arq_pool = None
