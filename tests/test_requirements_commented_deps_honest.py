################################################################################
# File Name: test_requirements_commented_deps_honest.py
# Purpose/Description: Sprint 53 US-439 (F-004) -- honesty gate for the project's
#                      requirements files.  A commented-out dependency line of
#                      the form ``# pkg>=x.y`` is a placeholder that lies: it
#                      implies the project "might" use a package it either does
#                      not use at all (dead template cruft) or already declares
#                      elsewhere (e.g. sqlalchemy/httpx live in
#                      requirements-server.txt).  US-439 removed the stale
#                      Python-template "optional" block from requirements.txt
#                      (pyodbc/sqlalchemy/requests/httpx/pandas/numpy/structlog)
#                      and the dead ``# sdnotify`` placeholder from
#                      requirements-pi.txt (no Type=notify systemd unit exists,
#                      so the sd_notify Python package was never needed).
#
#                      The honesty contract this pins: no requirements file may
#                      carry a commented-out DEPENDENCY line.  A package that is
#                      intentionally not pip-managed (pygame -- installed via
#                      ``apt`` on the Pi) is documented in PROSE with the reason,
#                      NOT left as a fake ``# pygame>=x`` pip line.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-02    | Rex          | Initial -- Sprint 53 US-439 (F-004) TDD.
# ================================================================================
################################################################################

"""Regression gate that keeps the requirements files honest (US-439 / F-004).

A ``# pkg>=x`` comment is a promise the file does not keep.  These tests assert
that no requirements file leaves a commented-out dependency declaration behind,
that the dead template packages removed by US-439 do not creep back in, and that
pygame's intentional apt-managed exception stays documented (prose, not a fake
pip line).
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]
REQUIREMENTS_BASE: Path = PROJECT_ROOT / "requirements.txt"
REQUIREMENTS_PI: Path = PROJECT_ROOT / "requirements-pi.txt"
REQUIREMENTS_SERVER: Path = PROJECT_ROOT / "requirements-server.txt"

# A dependency declaration is a package name immediately followed by a PEP-508
# version operator.  Anchoring on the operator is what separates a real
# (commented-out) requirement -- ``# sqlalchemy>=2.0.0`` -- from ordinary prose
# that merely mentions a package name -- ``# pygame is installed via apt``.
_VERSION_OP = r"(?:>=|<=|==|~=|!=|===|>|<)"
_COMMENTED_DEP = re.compile(rf"^#\s*[A-Za-z0-9][A-Za-z0-9._-]*\s*{_VERSION_OP}")
_ANY_DEP = re.compile(rf"^#?\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*{_VERSION_OP}")

# Packages US-439 removed from requirements.txt as dead template scaffolding.
# sqlalchemy/httpx are genuinely USED but belong to requirements-server.txt;
# the rest have zero imports anywhere in the tree.
DEAD_FROM_BASE = ("pyodbc", "sqlalchemy", "requests", "httpx", "pandas", "numpy", "structlog")


def _lines(path: Path) -> list[str]:
    """Return stripped lines of a requirements file."""
    return [raw.strip() for raw in path.read_text(encoding="utf-8").splitlines()]


def _commentedDepLines(path: Path) -> list[str]:
    """Return commented-out dependency-declaration lines (``# pkg>=x``)."""
    return [line for line in _lines(path) if _COMMENTED_DEP.match(line)]


def _declaresPackage(path: Path, packageName: str) -> bool:
    """True if the file declares packageName as a dep on any line, active OR commented."""
    pattern = re.compile(rf"^#?\s*{re.escape(packageName)}\s*{_VERSION_OP}", re.IGNORECASE)
    return any(pattern.match(line) for line in _lines(path))


def _activeRequirementNames(path: Path) -> set[str]:
    """Return the lower-cased package names of ACTIVE (non-comment) requirement lines."""
    names: set[str] = set()
    for line in _lines(path):
        if not line or line.startswith("#"):
            continue
        match = _ANY_DEP.match(line)
        if match:
            names.add(match.group(1).lower())
    return names


class TestRequirementsHonest:
    """No requirements file may carry a commented-out dependency placeholder."""

    def test_baseRequirements_hasNoCommentedDepPlaceholders(self) -> None:
        """
        Given: requirements.txt
        When: scanning for commented-out ``# pkg>=x`` dependency lines
        Then: none remain (the stale "optional" template block was removed)
        """
        stray = _commentedDepLines(REQUIREMENTS_BASE)
        assert stray == [], f"requirements.txt still has commented-out dep placeholders: {stray}"

    def test_piRequirements_hasNoCommentedDepPlaceholders(self) -> None:
        """
        Given: requirements-pi.txt
        When: scanning for commented-out ``# pkg>=x`` dependency lines
        Then: none remain (dead ``# sdnotify`` removed; pygame is prose, not a
              fake pip line)
        """
        stray = _commentedDepLines(REQUIREMENTS_PI)
        assert stray == [], f"requirements-pi.txt still has commented-out dep placeholders: {stray}"

    def test_serverRequirements_hasNoCommentedDepPlaceholders(self) -> None:
        """
        Given: requirements-server.txt
        When: scanning for commented-out ``# pkg>=x`` dependency lines
        Then: none remain (the pymysql block is prose documenting an ACTIVE dep)
        """
        stray = _commentedDepLines(REQUIREMENTS_SERVER)
        assert stray == [], f"requirements-server.txt still has commented-out dep placeholders: {stray}"

    def test_deadTemplateDeps_fullyRemoved_fromBase(self) -> None:
        """
        Given: requirements.txt
        When: checking each package US-439 removed as dead template scaffolding
        Then: it appears on no line -- active or commented (guards re-introduction
              of the misleading "uncomment if using ORM" placeholders when the
              server tier already depends on sqlalchemy/httpx)
        """
        for packageName in DEAD_FROM_BASE:
            assert not _declaresPackage(REQUIREMENTS_BASE, packageName), (
                f"{packageName!r} is back in requirements.txt -- it was removed by "
                "US-439 (unused, or server-only and declared in requirements-server.txt)"
            )

    def test_pygame_stillDocumented_asPy_apt_exception(self) -> None:
        """
        Given: requirements-pi.txt
        When: checking pygame's intentional apt-managed exception
        Then: pygame is mentioned (documentation preserved) but is NOT declared
              as an active pip requirement (it is symlinked from the system
              package -- see the prose block explaining why)
        """
        piText = REQUIREMENTS_PI.read_text(encoding="utf-8")
        assert "pygame" in piText, "pygame documentation vanished from requirements-pi.txt"
        assert "pygame" not in _activeRequirementNames(REQUIREMENTS_PI), (
            "pygame must NOT be an active pip requirement -- it is apt-managed + "
            "symlinked on the Pi (pip-building it there is fragile)"
        )
