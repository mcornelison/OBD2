# ==============================================================================
# File:        tools/pm/__init__.py
# Purpose:     The PM tool cluster -- sprint/backlog/release automation that
#              operates on agent-fleet data.
# Author:      offices-decouple restructure
# Created:     2026-08-24
# ==============================================================================
# These tools were previously ``offices/pm/scripts/`` and were importable only
# because ``offices/`` happened to sit inside the repo, behind three 0-byte
# ``__init__.py`` files. They are first-party source: the CODE lives here, in
# version control, while the DATA it operates on (backlog.json, sprint.json,
# story_counter.json, regression_manifest.json, ralph_agents.json, ...) lives
# on the agent-fleet share.
#
# :mod:`tools.pm._paths` owns that seam. Import ``REPO_ROOT`` / ``SHARE_ROOT``
# from there rather than deriving either from ``__file__`` depth -- a
# ``parents[N]`` anchor is exactly what silently broke when this package moved
# (it resolved one level above the repo, so every tool read nothing while
# raising nothing).
#
# Stdlib-only by convention: these run from a bare interpreter during deploy
# and release rituals, before any project venv is guaranteed to exist.
# ==============================================================================

from __future__ import annotations

from tools.pm._paths import REPO_ROOT, SHARE_ROOT, findRepoRoot, resolveShareRoot

__all__ = ["REPO_ROOT", "SHARE_ROOT", "findRepoRoot", "resolveShareRoot"]
