"""Pool de conexiones PostgreSQL/PostGIS y cliente Redis (caché + bus de eventos)."""
import os

import redis
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None
redis_cli = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True,
                                 socket_timeout=2, socket_connect_timeout=2)


def init_pool():
    global _pool
    _pool = ConnectionPool(os.environ["DATABASE_URL"], min_size=2, max_size=10,
                           kwargs={"row_factory": dict_row, "autocommit": True}, open=True)
    _pool.wait(timeout=30)


def close_pool():
    if _pool:
        _pool.close()


def conn():
    return _pool.connection()
