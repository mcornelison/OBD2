################################################################################
# File Name: connection.py
# Purpose/Description: Async SQLAlchemy engine and session factory for MariaDB
#                      using the aiomysql driver.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-CMP-003 — async
#               |              | engine creation + session factory
# ================================================================================
################################################################################

"""
Async database connection for the Eclipse OBD-II server.

Provides :func:`createAsyncEngine` and :func:`getAsyncSession` for use with
MariaDB via the ``aiomysql`` driver.  The lifespan handler in ``main.py``
creates the engine at startup and disposes it at shutdown.

Usage::

    from src.server.db.connection import createAsyncEngine, getAsyncSession

    engine = createAsyncEngine(settings.DATABASE_URL)
    async_session = getAsyncSession(engine)

    async with async_session() as session:
        result = await session.execute(select(RealtimeData))
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.ext.asyncio import (
    create_async_engine as _saCreateAsyncEngine,
)

# ---- Engine ------------------------------------------------------------------


def createAsyncEngine(
    databaseUrl: str,
    *,
    echo: bool = False,
    poolSize: int = 5,
    maxOverflow: int = 10,
) -> AsyncEngine:
    """
    Create an async SQLAlchemy engine for the given database URL.

    Args:
        databaseUrl: Full database URL including driver
            (e.g. ``mysql+aiomysql://obd2:pass@localhost/obd2db``).
        echo: If True, log all SQL statements (debug only).
        poolSize: Number of connections to keep in the pool.
        maxOverflow: Max connections above pool_size before blocking.

    Returns:
        An :class:`AsyncEngine` instance.  Call ``await engine.dispose()``
        at shutdown to release all connections.
    """
    return _saCreateAsyncEngine(
        databaseUrl,
        echo=echo,
        pool_size=poolSize,
        max_overflow=maxOverflow,
        pool_pre_ping=True,
    )


# ---- Session Factory ---------------------------------------------------------


def getAsyncSession(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """
    Build an async session factory bound to the given engine.

    Args:
        engine: The :class:`AsyncEngine` to bind sessions to.

    Returns:
        A :class:`async_sessionmaker` that produces :class:`AsyncSession`
        instances.  Use as a context manager::

            factory = getAsyncSession(engine)
            async with factory() as session:
                ...
    """
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


# ---- Public API --------------------------------------------------------------

__all__ = [
    "createAsyncEngine",
    "getAsyncSession",
]
