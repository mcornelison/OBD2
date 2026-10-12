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

# NOTE: SHARE_ROOT is deliberately NOT re-exported here.
#
# Resolving it requires $FLEET_SHARE and raises without it (by design -- see
# _paths.resolveShareRoot). If this package's __init__ imported it eagerly, then
# importing ANY tool would require the variable, including the ones that never
# touch share data at all: index_lock (operates on .git/index.lock),
# verify_release_version (reads deploy/RELEASE_VERSION), deploy_preflight_gate,
# backlog_schema, _encoding, _freeze. Their tests would fail at COLLECTION with
# a configuration error about data they do not read.
#
# So the requirement is scoped to the tools that actually need the share: they
# import SHARE_ROOT from tools.pm._paths themselves. Callers wanting it here can
# use resolveShareRoot(), which raises at call time rather than import time.
from tools.pm._paths import REPO_ROOT, findRepoRoot, resolveShareRoot

__all__ = ["REPO_ROOT", "findRepoRoot", "resolveShareRoot"]
