################################################################################
# File Name: test_report_db_url_resolution.py
# Purpose/Description: Unit tests for scripts/report.py database-URL resolution
#                      (US-321 / I-023).  The phantom sqlite fallback that
#                      pointed at an empty-schema data/server_crawl.db has been
#                      removed; resolving with neither --db-url nor DATABASE_URL
#                      must now fail fast with SystemExit(2) and a clear message.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-11    | Rex          | Initial implementation for US-321 (Sprint 32)
# ================================================================================
################################################################################

"""Tests for the ``--db-url`` / ``DATABASE_URL`` resolution in :mod:`scripts.report`.

Pre-fix behaviour: ``_resolveDbUrl(None)`` with no ``DATABASE_URL`` silently
returned ``"sqlite:///data/server_crawl.db"`` -- a file with an empty schema, so
the very next query crashed with ``OperationalError: no such table: drive_summary``.
Post-fix behaviour: it raises ``SystemExit(2)`` with a message naming the two
ways to supply a URL.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts import report  # noqa: E402


class TestResolveDbUrl:
    """Direct unit coverage of :func:`scripts.report._resolveDbUrl`."""

    def test_cliUrlWins_evenWhenEnvSet(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        Given: a --db-url value AND a DATABASE_URL env var.
        When: _resolveDbUrl is called with the CLI value.
        Then: the CLI value is returned (env ignored).
        """
        monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://env/host")
        assert report._resolveDbUrl("sqlite:///explicit.db") == "sqlite:///explicit.db"

    def test_envUrlUsed_whenNoCliUrl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        Given: no --db-url but DATABASE_URL is set.
        When: _resolveDbUrl(None) is called.
        Then: the env var value is returned.
        """
        monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://env/host")
        assert report._resolveDbUrl(None) == "mysql+pymysql://env/host"

    def test_noCliNoEnv_raisesSystemExit2_withClearMessage(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: neither --db-url nor DATABASE_URL provided.
        When: _resolveDbUrl(None) is called.
        Then: SystemExit(2) is raised and a stderr message names both supply paths.
        (Pre-fix this returned the phantom sqlite path and did NOT raise.)
        """
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(SystemExit) as excinfo:
            report._resolveDbUrl(None)
        assert excinfo.value.code == 2
        message = capsys.readouterr().err
        assert "DATABASE_URL" in message
        assert "--db-url" in message

    def test_emptyEnv_treatedAsUnset_raisesSystemExit2(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: DATABASE_URL is set to an empty string.
        When: _resolveDbUrl(None) is called.
        Then: it is treated as unset -> SystemExit(2).
        """
        monkeypatch.setenv("DATABASE_URL", "")
        with pytest.raises(SystemExit) as excinfo:
            report._resolveDbUrl(None)
        assert excinfo.value.code == 2

    def test_phantomFallbackConstantRemoved(self) -> None:
        """The _DEFAULT_DB_URL_FALLBACK constant must no longer exist (I-023)."""
        assert not hasattr(report, "_DEFAULT_DB_URL_FALLBACK")


class TestMainExitsOnMissingDbUrl:
    """End-to-end: ``report.main`` should exit 2 when no DB URL is resolvable."""

    def test_main_noDbUrl_exitsNonZero(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: no DATABASE_URL env var and no --db-url flag.
        When: report.main(["--drive", "latest"]) runs.
        Then: it exits with code 2 (never reaches engine creation / query).
        """
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(SystemExit) as excinfo:
            report.main(["--drive", "latest"])
        assert excinfo.value.code == 2
