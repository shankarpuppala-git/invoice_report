"""
db/db_pool.py
─────────────
Manages a psycopg2 ThreadedConnectionPool for the application lifetime.

Usage:
    from db.db_pool import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT ...")
            rows = cur.fetchall()
    # connection is returned to the pool automatically
"""

from contextlib import contextmanager
from typing import Generator

import psycopg2
import psycopg2.extras
from psycopg2 import pool as pg_pool

from common.logger import get_logger
from config.settings import settings

logger = get_logger(__name__)

_pool: pg_pool.ThreadedConnectionPool | None = None


def init_pool() -> None:
    """
    Initialise the connection pool.
    Called once at application startup (lifespan hook in main.py).
    """
    global _pool
    if _pool is not None:
        logger.warning("DB pool already initialised — skipping.")
        return

    logger.info(
        "Initialising PostgreSQL connection pool "
        "(min=%d, max=%d, host=%s, db=%s)",
        settings.DB_MIN_CONN,
        settings.DB_MAX_CONN,
        settings.DB_HOST,
        settings.DB_NAME,
    )
    _pool = pg_pool.ThreadedConnectionPool(
        minconn=settings.DB_MIN_CONN,
        maxconn=settings.DB_MAX_CONN,
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        dbname=settings.DB_NAME,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        cursor_factory=psycopg2.extras.RealDictCursor,
        connect_timeout=10,
        options="-c statement_timeout=30000",  # 30-second query timeout
    )
    logger.info("PostgreSQL connection pool ready.")


def close_pool() -> None:
    """
    Close all connections in the pool.
    Called at application shutdown (lifespan hook in main.py).
    """
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
        logger.info("PostgreSQL connection pool closed.")


@contextmanager
def get_connection() -> Generator:
    """
    Context manager that checks out a connection from the pool,
    yields it, and guarantees it is returned even on exception.

    Example
    -------
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    """
    if _pool is None:
        raise RuntimeError(
            "DB pool is not initialised. Call init_pool() first."
        )

    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)
