################################################################################
# File Name: app.py
# Purpose/Description: FastAPI application factory for the companion server.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-CMP-001 — createApp
#               |              | factory with optional lifespan and settings
# ================================================================================
################################################################################

"""
FastAPI application factory.

Provides ``createApp()`` which builds and configures the FastAPI instance.
The factory accepts optional ``settings`` and ``lifespan`` parameters so
callers can inject configuration (production) or omit them (verification,
testing).

Usage:
    from src.server.api.app import createApp

    app = createApp()                  # bare app for tests / verification
    app = createApp(lifespan=lifespan) # with lifespan handler for production
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from src.server.config import Settings

# ---- Constants ---------------------------------------------------------------

APP_TITLE = "Eclipse OBD-II Server"
APP_VERSION = "1.0.0"
APP_DESCRIPTION = (
    "Analytics and monitoring server for the Eclipse OBD-II "
    "Performance Monitoring System."
)
API_PREFIX = "/api/v1"


# ---- Factory -----------------------------------------------------------------


def createApp(
    settings: Settings | None = None,
    lifespan: Callable[..., Any] | None = None,
) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        settings: Server settings instance.  When provided the settings are
            stored on ``app.state.settings`` for dependency injection.
            Omit for lightweight usage (import verification, unit tests).
        lifespan: Async context-manager callable for startup/shutdown.
            Passed directly to :class:`FastAPI`.

    Returns:
        Configured :class:`FastAPI` application instance.
    """
    app = FastAPI(
        title=APP_TITLE,
        version=APP_VERSION,
        description=APP_DESCRIPTION,
        lifespan=lifespan,
    )

    if settings is not None:
        app.state.settings = settings

    # Routers — imported lazily to avoid circular import (health imports
    # APP_VERSION from this module).
    from src.server.api.health import router as healthRouter

    app.include_router(healthRouter, prefix=API_PREFIX)

    return app
