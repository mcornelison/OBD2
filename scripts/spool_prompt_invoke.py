################################################################################
# File Name: spool_prompt_invoke.py
# Purpose/Description: CLI wrapper that loads Spool's prompt templates, builds
#                      drive analytics context, invokes Ollama /api/chat, and
#                      prints the rendered user message + raw response + parsed
#                      recommendations.  Glue for the post-drive review ritual
#                      (US-219); reuses the server-side rendering path so the
#                      CLI and the auto-analysis endpoint agree byte-for-byte
#                      on what Ollama saw.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex          | Initial implementation for US-219 (Sprint 16)
# ================================================================================
################################################################################

"""CLI invocation of Spool's Ollama prompt against a single drive's analytics.

Usage::

    # Render prompt + call Ollama for the latest drive in drive_summary
    python scripts/spool_prompt_invoke.py --drive-id latest

    # Explicit drive_summary id
    python scripts/spool_prompt_invoke.py --drive-id 17

    # Render the prompt but skip the Ollama call (offline preview)
    python scripts/spool_prompt_invoke.py --drive-id latest --dry-run

    # Override the database URL (handy for local SQLite testing)
    python scripts/spool_prompt_invoke.py \\
        --drive-id 1 --db-url sqlite:///data/server_crawl.db

This is the post-drive-review sibling of :mod:`scripts.report`.  The two
together drive the human review ritual: ``report.py`` prints the numeric
summary, this script prints the AI interpretation; both are orchestrated by
:mod:`scripts.post_drive_review`.  Per US-219 invariants, this script
**wires** existing infrastructure and does **not** implement new analysis —
every helper (prompt loader, Jinja renderer, analytics-context builder,
response parser) is imported from :mod:`src.server.services.analysis`.

Ollama base URL, model, and timeout come exclusively from ``config.json``'s
``server.ai`` block (with ``${ENV_VAR:default}`` expansion) — never
hardcoded here.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure project root is importable before any src.* imports.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.exc import OperationalError, SQLAlchemyError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.ai.analyzer_ollama import (  # noqa: E402
    OllamaHttpError,
    OllamaUnreachableError,
    callOllamaChat,
)
from src.server.ai.exceptions import AiAnalyzerGenerationError  # noqa: E402
from src.server.db.models import DriveSummary  # noqa: E402
from src.server.services.analysis import (  # noqa: E402
    NO_DATA_MESSAGE,
    _buildAnalyticsContext,
    _loadSystemMessage,
    _parseRecommendations,
    _renderUserMessage,
)

logger = logging.getLogger(__name__)

# ---- Constants ---------------------------------------------------------------

_DEFAULT_DB_URL_ENV = "DATABASE_URL"
_DEFAULT_DB_URL_FALLBACK = "sqlite:///data/server_crawl.db"
_CONFIG_PATH = _PROJECT_ROOT / "config.json"

# ``${VAR}`` and ``${VAR:default}`` placeholders, matching
# :mod:`src.common.config.secrets_loader` semantics.
_PLACEHOLDER_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)(?::([^}]*))?\}")

_BAR = "═" * 72
_RULE = "─" * 72


# ==============================================================================
# Config loading
# ==============================================================================


def _expandPlaceholders(value: str) -> str:
    """Expand ``${ENV_VAR}`` / ``${ENV_VAR:default}`` placeholders.

    Minimal re-implementation of the validator's env expansion so this script
    stays independent of the full config-loader stack (which pulls in Pi-side
    dependencies irrelevant here).
    """
    def _sub(match: re.Match[str]) -> str:
        var = match.group(1)
        default = match.group(2) or ""
        return os.environ.get(var, default)

    return _PLACEHOLDER_RE.sub(_sub, value)


def loadOllamaConfig(configPath: Path | None = None) -> tuple[str, str, int]:
    """Read ``server.ai`` settings and return ``(baseUrl, model, timeoutSec)``.

    Raises ``KeyError`` if required keys are missing.  Callers should let that
    propagate — a missing Ollama config is a deployment error, not something
    to silently paper over with a default.

    Args:
        configPath: Path to ``config.json``.  Defaults to the module-level
            ``_CONFIG_PATH`` so tests can monkey-patch that attribute.

    Returns:
        Three-tuple ``(baseUrl, model, timeoutSeconds)`` with placeholders
        expanded against the current process environment.
    """
    if configPath is None:
        configPath = _CONFIG_PATH
    raw = json.loads(configPath.read_text(encoding="utf-8"))
    ai = raw["server"]["ai"]
    baseUrl = _expandPlaceholders(str(ai["ollamaBaseUrl"]))
    model = _expandPlaceholders(str(ai["model"]))
    timeout = int(ai.get("apiTimeoutSeconds", 60))
    return baseUrl, model, timeout


# ==============================================================================
# Drive resolution
# ==============================================================================


def resolveDriveId(session: Session, driveRef: str) -> int | None:
    """Resolve ``latest`` or an integer string into a ``drive_summary.id``.

    Returns ``None`` when the database has no drive yet (``latest`` on an
    empty table) or when the integer form does not match a row.
    """
    ref = driveRef.strip()
    if ref == "latest":
        row = session.execute(
            select(DriveSummary).order_by(DriveSummary.start_time.desc()).limit(1),
        ).scalar_one_or_none()
        return row.id if row is not None else None

    if ref.isdigit():
        driveId = int(ref)
        drive = session.get(DriveSummary, driveId)
        return drive.id if drive is not None else None

    return None


# ==============================================================================
# CLI parsing
# ==============================================================================


def parseArguments(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the Spool prompt invoker."""
    parser = argparse.ArgumentParser(
        prog="spool_prompt_invoke.py",
        description=(
            "Invoke Spool's Ollama prompt against a single drive's analytics "
            "and print the raw + parsed response."
        ),
    )
    parser.add_argument(
        "--drive-id",
        dest="driveId",
        required=True,
        metavar="REF",
        help="Drive id (integer) or 'latest' for the most recent drive.",
    )
    parser.add_argument(
        "--db-url",
        dest="dbUrl",
        default=None,
        metavar="URL",
        help=(
            "SQLAlchemy database URL.  Falls back to $DATABASE_URL, then "
            f"'{_DEFAULT_DB_URL_FALLBACK}'."
        ),
    )
    parser.add_argument(
        "--dry-run",
        dest="dryRun",
        action="store_true",
        help=(
            "Render the prompt and print it, but do not call Ollama.  Useful "
            "for offline inspection of what Ollama would see."
        ),
    )
    return parser.parse_args(argv)


def _toSyncDriverUrl(url: str) -> str:
    """Rewrite the async MariaDB driver to its sync sibling (matches report.py)."""
    return url.replace("+aiomysql://", "+pymysql://", 1)


def _resolveDbUrl(cliUrl: str | None) -> str:
    if cliUrl is not None:
        return cliUrl
    envUrl = os.environ.get(_DEFAULT_DB_URL_ENV)
    if envUrl:
        return envUrl
    return _DEFAULT_DB_URL_FALLBACK


# ==============================================================================
# Main flow
# ==============================================================================


def _printSection(title: str) -> None:
    print(_BAR)
    print(f"  {title}")
    print(_BAR)


def runReview(args: argparse.Namespace) -> int:
    """Execute the prompt invocation and print the results.

    Returns a Unix exit code.  ``0`` covers every user-visible outcome —
    successful Ollama response, empty drive, Ollama unreachable — because the
    review ritual is a read-only information flow; surfacing a non-zero exit
    for "Ollama is offline" would make the wrapper script abort mid-review.
    """
    dbUrl = _toSyncDriverUrl(_resolveDbUrl(args.dbUrl))
    engine = create_engine(dbUrl)
    try:
        with Session(engine) as session:
            try:
                driveId = resolveDriveId(session, args.driveId)
            except OperationalError as exc:
                # Missing / uninitialised schema is a graceful no-op for the
                # review ritual -- the CIO is pointed at a DB that has no
                # drive history yet.  Treat it as "no drive found".
                print(
                    f"Database at {dbUrl} is missing expected tables: {exc.orig}"
                )
                print("No drives to review (exit 0).")
                return 0
            except SQLAlchemyError as exc:
                print(f"Database query failed: {exc}")
                print("No drives to review (exit 0).")
                return 0

            if driveId is None:
                print(
                    f"No drive found for reference '{args.driveId}'.  "
                    "No data to review (exit 0)."
                )
                return 0

            drive = session.get(DriveSummary, driveId)
            if drive is None:
                print(
                    f"drive_summary.id={driveId} not found.  "
                    "No data to review (exit 0)."
                )
                return 0

            try:
                context = _buildAnalyticsContext(session, drive)
            except SQLAlchemyError as exc:
                print(f"Analytics build failed for drive {driveId}: {exc}")
                print("No data to review (exit 0).")
                return 0
            if context is None:
                print(f"Drive {driveId}: {NO_DATA_MESSAGE}")
                return 0

            systemMessage = _loadSystemMessage()
            userMessage = _renderUserMessage(context)

            try:
                baseUrl, model, timeoutSeconds = loadOllamaConfig()
            except (KeyError, FileNotFoundError) as exc:
                print(f"Ollama config missing from config.json: {exc}")
                print(
                    "Check the 'server.ai' block in config.json "
                    "(ollamaBaseUrl + model required)."
                )
                return 0

            _printSection(f"Spool prompt — drive {driveId}")
            print(f"  Model:    {model}")
            print(f"  Endpoint: {baseUrl}/api/chat")
            print(f"  Timeout:  {timeoutSeconds}s")
            print()

            _printSection("Rendered user message (what Ollama sees)")
            print(userMessage)
            print()

            if args.dryRun:
                _printSection("Dry run — Ollama call skipped")
                print("  Re-run without --dry-run to invoke Ollama.")
                return 0

            try:
                raw = callOllamaChat(
                    baseUrl=baseUrl,
                    model=model,
                    systemMessage=systemMessage,
                    userMessage=userMessage,
                    timeoutSeconds=timeoutSeconds,
                )
            except OllamaUnreachableError as exc:
                _printSection("Ollama unreachable")
                print(f"  {exc}")
                print(f"  (base_url={baseUrl})")
                print("  The review ritual still succeeded — this section is")
                print("  advisory only.  Start ollama and re-run to get AI input.")
                return 0
            except OllamaHttpError as exc:
                _printSection("Ollama HTTP error")
                print(f"  HTTP {exc.code}: {exc}")
                return 0
            except AiAnalyzerGenerationError as exc:
                _printSection("Ollama returned an unusable response")
                print(f"  {exc}")
                return 0

            _printSection("Raw Ollama response")
            print(raw)
            print()

            recs = _parseRecommendations(raw)
            _printSection(f"Parsed recommendations ({len(recs)})")
            if not recs:
                print("  (none — empty array or all items dropped by filter)")
            else:
                for r in recs:
                    print(
                        f"  [{r.rank}] {r.category:<11} "
                        f"conf={r.confidence:.2f}  {r.recommendation}"
                    )
            return 0
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.  Returns a Unix-style exit code.

    Exit codes:
        * 0 — any graceful outcome (successful call, no data, Ollama offline).
        * 2 — invalid arguments (argparse handles the message).
    """
    args = parseArguments(argv)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):  # pragma: no cover — stream-dependent
            pass
    return runReview(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
