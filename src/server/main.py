################################################################################
# File Name: main.py
# Purpose/Description: Companion service entry point — creates the FastAPI app
#                      with lifespan handler, runnable via uvicorn.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-CMP-001 — lifespan
#               |              | handler, logging setup, uvicorn entry point
# ================================================================================
################################################################################

"""
Companion service entry point.

Creates the FastAPI application via :func:`createApp` with a lifespan handler
that manages startup/shutdown lifecycle.  Runnable with::

    uvicorn src.server.main:app --host 0.0.0.0 --port 8000

Or directly::

    python -m src.server.main
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.server.api.app import createApp
from src.server.config import Settings
from src.server.db.connection import createAsyncEngine

logger = logging.getLogger(__name__)


# ---- Lifespan ----------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Application lifespan handler for startup and shutdown.

    Startup:
        - Loads server settings from environment / .env
        - Stores settings on ``app.state`` for dependency injection
        - Configures logging

    Shutdown:
        - Logs shutdown message (DB/resource cleanup added in later stories)
    """
    settings = Settings()
    app.state.settings = settings
    app.state.startTime = time.time()

    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

    try:
        app.state.engine = createAsyncEngine(settings.DATABASE_URL)
    except Exception as exc:  # noqa: BLE001 — engine init is best-effort at startup
        logger.warning("Failed to create DB engine at startup: %s", exc)
        app.state.engine = None

    logger.info("Server starting on port %d", settings.PORT)
    logger.info("Database: %s", settings.DATABASE_URL.split("@")[-1] if "@" in settings.DATABASE_URL else "(configured)")
    logger.info("Ollama: %s (model: %s)", settings.OLLAMA_BASE_URL, settings.OLLAMA_MODEL)

    yield

    engine = getattr(app.state, "engine", None)
    if engine is not None:
        await engine.dispose()

    logger.info("Server shutting down")


# ---- Application -------------------------------------------------------------

app = createApp(lifespan=lifespan)


# ---- Direct execution --------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    settings = Settings()
    uvicorn.run(
        "src.server.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        log_level=settings.LOG_LEVEL.lower(),
    )
