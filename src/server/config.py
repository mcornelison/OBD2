################################################################################
# File Name: config.py
# Purpose/Description: Server configuration via Pydantic Settings, loaded from
#                      environment variables and .env file.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-CMP-001 — FastAPI
#               |              | scaffold and server configuration
# 2026-04-30    | Rex          | US-246 (B-047 US-B) — RELEASE_VERSION_PATH,
#               |              | RELEASE_HISTORY_PATH, RELEASE_HISTORY_MAX
# ================================================================================
################################################################################

"""
Server-side configuration using Pydantic Settings.

Reads from environment variables and an optional .env file. All variables
from spec §Configuration Variables are defined here with their defaults.

Usage:
    from src.server.config import Settings

    settings = Settings()                           # reads .env + env vars
    settings = Settings(_env_file='.env.example')   # reads specific file
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---- Settings ----------------------------------------------------------------


class Settings(BaseSettings):
    """
    Server configuration loaded from environment variables and .env file.

    Required:
        DATABASE_URL: MariaDB async connection URL.

    All other fields have sensible defaults for development. Override via
    environment variables or a .env file.
    """

    # Required — no default
    DATABASE_URL: str = Field(
        ...,
        description="MariaDB connection URL (e.g. mysql+aiomysql://obd2:pass@localhost/obd2db)",
    )

    # Authentication
    API_KEY: str = Field(
        default="",
        description="Shared-secret API key for X-API-Key header authentication",
    )

    # Server
    PORT: int = Field(
        default=8000,
        description="HTTP port for uvicorn",
    )
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )

    # Ollama / AI
    OLLAMA_BASE_URL: str = Field(
        default="http://localhost:11434",
        description="Base URL for the Ollama API on Chi-Srv-01",  # b044-exempt: pydantic Field description
    )
    OLLAMA_MODEL: str = Field(
        default="llama3.1:8b",
        description="Ollama model to use for AI analysis",
    )

    # Backups
    BACKUP_DIR: str = Field(
        default="./data/backups",
        description="Directory for received backup files",
    )
    MAX_BACKUP_SIZE_MB: int = Field(
        default=100,
        description="Maximum allowed backup file size in megabytes",
    )
    BACKUP_RETENTION_COUNT: int = Field(
        default=30,
        description="Number of backup files to retain before rotation",
    )

    # Sync
    MAX_SYNC_PAYLOAD_MB: int = Field(
        default=10,
        description="Maximum sync payload size in megabytes",
    )

    # Analysis
    ANALYSIS_TIMEOUT_SECONDS: int = Field(
        default=120,
        description="Timeout for AI analysis requests in seconds",
    )
    TREND_WINDOW_DRIVES: int = Field(
        default=10,
        description="Number of recent drives used for trend analysis",
    )
    ANOMALY_THRESHOLD_SIGMA: float = Field(
        default=2.0,
        description="Standard deviations threshold for anomaly flagging",
    )
    CALIBRATION_MIN_DRIVES: int = Field(
        default=5,
        description="Minimum real drives required before calibration recommendations",
    )

    # Release registry (B-047 US-B / US-246) -- the deploy-script-stamped files
    # that GET /api/v1/release/current and /history read from. Defaults are
    # relative paths that resolve against the server CWD (= project root in
    # production -- matches deploy-server.sh ${PROJECT}/.deploy-version write
    # path). Operators can override to absolute paths in .env if they relocate
    # the deploy artifacts (e.g. /etc/eclipse-obd-server/.deploy-version).
    RELEASE_VERSION_PATH: str = Field(
        default=".deploy-version",
        description="Path to the current-release file written by deploy-server.sh step 5.5",
    )
    RELEASE_HISTORY_PATH: str = Field(
        default=".deploy-version-history",
        description="Path to the optional JSONL history append file (absent => empty history)",
    )
    RELEASE_HISTORY_MAX: int = Field(
        default=10,
        description="Maximum number of history entries returned by GET /release/history",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )
