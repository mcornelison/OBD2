################################################################################
# File Name: test_requirements_pymysql_declared.py
# Purpose/Description: Sprint 32 US-320 (I-022 close) -- regression gate that
#                      asserts ``pymysql`` is declared in requirements-server.txt
#                      with a version pin >= 1.1.0.  scripts/report.py rewrites
#                      the async DATABASE_URL (``+aiomysql://``) to a sync URL
#                      (``+pymysql://``) via ``_toSyncDriverUrl`` so the CLI can
#                      drive MariaDB through a synchronous SQLAlchemy engine.
#                      SQLAlchemy resolves that driver by importing the
#                      ``pymysql`` package -- which was never declared, so a
#                      clean-venv ``pip install -r requirements-server.txt``
#                      followed by ``python scripts/report.py --drive|--trends|
#                      --calibrate`` crashed with
#                      ``ModuleNotFoundError: No module named 'pymysql'``.
#                      Mike's ad-hoc MariaDB work went through the ``mysql``
#                      binary CLI (a different thing from the pymysql Python
#                      library) so the gap stayed silent.
#
#                      Pre-fix: the ``pymysql`` line does not exist -> these
#                      tests fail.  Post-fix: the line is present alongside the
#                      existing ``aiomysql>=0.2.0`` (async server path,
#                      unchanged) -> tests pass.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-11    | Rex          | Initial -- Sprint 32 US-320 TDD (I-022 close).
# ================================================================================
################################################################################

"""Regression gate for the US-320 / I-022 ``pymysql`` dependency declaration.

The synchronous CLI path in ``scripts/report.py`` depends on the ``pymysql``
package being importable; SQLAlchemy loads it lazily when it sees a
``mysql+pymysql://`` URL, so a missing declaration produces a runtime crash
rather than an install-time error.  These tests pin the contract: ``pymysql``
must be in ``requirements-server.txt`` with a ``>= 1.1.0`` floor (SQLAlchemy 2.x
compatible), and the async sibling ``aiomysql`` must remain declared.
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
REQUIREMENTS_SERVER: Path = PROJECT_ROOT / "requirements-server.txt"


def _requirementLines() -> list[str]:
    """Return non-comment, non-blank lines from requirements-server.txt."""
    text = REQUIREMENTS_SERVER.read_text(encoding="utf-8")
    lines: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return lines


def _findRequirement(packageName: str) -> str | None:
    """Return the requirement line declaring ``packageName`` (case-insensitive), or None."""
    pattern = re.compile(rf"^{re.escape(packageName)}\b", re.IGNORECASE)
    for line in _requirementLines():
        if pattern.match(line):
            return line
    return None


class TestRequirementsServerPymysql:
    """Pin the pymysql declaration that the report.py sync CLI path depends on."""

    def test_requirementsServer_exists_isReadable(self) -> None:
        """
        Given: the repo root
        When: locating requirements-server.txt
        Then: the file exists (sanity guard so a path typo doesn't masquerade
              as a missing dependency)
        """
        assert REQUIREMENTS_SERVER.is_file(), f"missing {REQUIREMENTS_SERVER}"

    def test_pymysql_isDeclared(self) -> None:
        """
        Given: requirements-server.txt
        When: scanning for a pymysql requirement line
        Then: pymysql is declared (FAILS pre-fix -- the line did not exist;
              scripts/report.py crashed at SQLAlchemy engine creation)
        """
        assert _findRequirement("pymysql") is not None, (
            "pymysql is not declared in requirements-server.txt -- "
            "scripts/report.py's _toSyncDriverUrl rewrites the URL to "
            "mysql+pymysql:// and SQLAlchemy needs the pymysql package to "
            "drive it (US-320 / I-022)"
        )

    def test_pymysql_versionFloor_isAtLeast_1_1_0(self) -> None:
        """
        Given: the pymysql requirement line
        When: parsing its version specifier
        Then: it pins >= 1.1.0 (SQLAlchemy 2.x compatible per the I-022 audit)
        """
        line = _findRequirement("pymysql")
        assert line is not None, "pymysql not declared (see test_pymysql_isDeclared)"
        match = re.search(r">=\s*(\d+)\.(\d+)\.(\d+)", line)
        assert match is not None, (
            f"pymysql requirement {line!r} must use a '>= X.Y.Z' floor"
        )
        major, minor, patch = (int(g) for g in match.groups())
        assert (major, minor, patch) >= (1, 1, 0), (
            f"pymysql floor {major}.{minor}.{patch} is below the required 1.1.0"
        )

    def test_aiomysql_stillDeclared(self) -> None:
        """
        Given: requirements-server.txt
        When: scanning for the async sibling aiomysql
        Then: aiomysql is still declared (the FastAPI server's async DB path
              is unaffected by adding the sync driver -- invariant guard)
        """
        assert _findRequirement("aiomysql") is not None, (
            "aiomysql disappeared from requirements-server.txt -- the async "
            "FastAPI server path still needs it; US-320 only ADDS pymysql"
        )

    def test_pymysql_notDuplicated(self) -> None:
        """
        Given: requirements-server.txt
        When: counting pymysql declaration lines
        Then: exactly one (a duplicate add would mean a merge slip)
        """
        pattern = re.compile(r"^pymysql\b", re.IGNORECASE)
        matches = [line for line in _requirementLines() if pattern.match(line)]
        assert len(matches) == 1, f"expected exactly one pymysql line, got {matches}"
