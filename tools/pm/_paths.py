# ==============================================================================
# File:        tools/pm/_paths.py
# Purpose:     Single source of truth for the two roots every PM tool needs:
#              the product repo (REPO_ROOT) and the agent-fleet share
#              (SHARE_ROOT).
# Author:      offices-decouple restructure
# Created:     2026-08-24
# ==============================================================================
# Why this module exists
# ----------------------
# Until the decouple, all 13 PM tools computed the repo root as
# ``Path(__file__).resolve().parents[3]`` -- correct only while they lived at
# ``offices/pm/scripts/<tool>.py`` (scripts -> pm -> offices -> root).  Moving
# them to ``tools/pm/`` silently shifted that anchor one level ABOVE the repo.
# Nothing would have raised: the constants would just resolve to paths that do
# not exist and every tool would read nothing.  Depth-coupled anchors are the
# defect (tracked as C6 in the decouple sweep), so this module walks up looking
# for a marker instead and is therefore depth-independent by construction.
#
# The share
# ---------
# The PM tools operate on agent-fleet DATA (backlog.json, sprint.json,
# story_counter.json, regression_manifest.json, ralph_agents.json, ...), which
# lives under ``offices/`` today and moves to the fleet share when offices/ is
# evicted.  The tool code stays in the repo; its data does not.  SHARE_ROOT is
# that seam.
#
# Resolution is deliberately LOUD when it fails.  A silent fallback here would
# reproduce exactly the failure mode this module exists to prevent -- a tool
# that resolves a plausible-looking path, reads nothing, and reports success.
# ==============================================================================

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["REPO_ROOT", "SHARE_ROOT", "findRepoRoot", "resolveShareRoot"]

# Marker that identifies the repo root. pyproject.toml sits at the top of this
# project and nowhere else in it, so it is an unambiguous sentinel.
_REPO_MARKER = "pyproject.toml"

# Environment variable naming the agent-fleet share root (the directory that
# mirrors what offices/ contains: pm/, ralph/, tuner/, architect/, ...).
_SHARE_ENV = "FLEET_SHARE"


def findRepoRoot(start: Path | None = None) -> Path:
    """Walk upward from ``start`` until the repo marker is found.

    Depth-independent on purpose: moving this file to a different nesting level
    must not change the answer.

    Args:
        start: Directory or file to begin the search from. Defaults to this
            module's own location.

    Returns:
        The directory containing ``pyproject.toml``.

    Raises:
        RuntimeError: If no ancestor contains the marker.
    """
    here = Path(start).resolve() if start is not None else Path(__file__).resolve()
    if here.is_file():
        here = here.parent

    for candidate in (here, *here.parents):
        if (candidate / _REPO_MARKER).is_file():
            return candidate

    raise RuntimeError(
        f"Could not locate the repo root: no {_REPO_MARKER} found in any parent "
        f"of {here}. The PM tools resolve their paths relative to it."
    )


def resolveShareRoot(repoRoot: Path | None = None) -> Path:
    """Resolve the agent-fleet share root.

    Order:
      1. ``$FLEET_SHARE`` when set (authoritative -- this is the post-eviction
         configuration, and it wins even if a stale in-repo offices/ exists).
      2. ``<repo>/offices`` while it is still present (pre-eviction).
      3. Raise. There is no third option on purpose.

    Args:
        repoRoot: Repo root to probe for the transitional in-repo offices/.
            Defaults to :data:`REPO_ROOT`.

    Returns:
        Directory that contains ``pm/``, ``ralph/``, etc.

    Raises:
        RuntimeError: If ``$FLEET_SHARE`` is unset and no in-repo ``offices/``
            exists. Named explicitly so the operator is told what to set and
            why, rather than getting an empty read from a tool that appears to
            have succeeded.
    """
    fromEnv = os.environ.get(_SHARE_ENV)
    if fromEnv:
        return Path(fromEnv).expanduser()

    root = repoRoot if repoRoot is not None else REPO_ROOT
    inRepo = root / "offices"
    if inRepo.is_dir():
        return inRepo

    raise RuntimeError(
        f"Cannot resolve the agent-fleet share root. Set ${_SHARE_ENV} to the "
        f"directory holding the agent offices (pm/, ralph/, tuner/, ...) -- the "
        f"PM tools read their backlog, sprint, counter and manifest data from "
        f"there. Checked ${_SHARE_ENV} (unset) and the transitional in-repo "
        f"path {inRepo} (absent)."
    )


REPO_ROOT: Path = findRepoRoot()
SHARE_ROOT: Path = resolveShareRoot(REPO_ROOT)
