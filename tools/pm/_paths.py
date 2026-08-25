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
# lives on the fleet share -- it was evicted from this repo on 2026-08-24. The
# tool code stays in the repo; its data does not. SHARE_ROOT is that seam, and
# it is resolved from $FLEET_SHARE with NO fallback: see resolveShareRoot for
# why the transitional in-repo fallback had to go.
#
# Resolution is deliberately LOUD when it fails.  A silent fallback here would
# reproduce exactly the failure mode this module exists to prevent -- a tool
# that resolves a plausible-looking path, reads nothing, and reports success.
# ==============================================================================

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["REPO_ROOT", "SHARE_ROOT", "findRepoRoot", "resolveShareRoot"]  # noqa: F822 -- SHARE_ROOT is served lazily by __getattr__ (PEP 562)

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


def resolveShareRoot() -> Path:
    """Resolve the agent-fleet share root from ``$FLEET_SHARE``.

    ``$FLEET_SHARE`` is REQUIRED. There is no fallback -- not even to a
    transitional in-repo ``offices/``.

    Why the fallback was removed
    ----------------------------
    Until 2026-08-24 this function fell back to ``<repo>/offices`` when the
    variable was unset, which was correct while offices/ was tracked. After the
    eviction that directory still exists in the TRUNK worktree (deliberately --
    it is kept on disk until the snapshot restore is proven) but does NOT exist
    in a freshly created bench worktree.

    That made the fallback actively harmful: identical code, run with the same
    (unset) environment, silently read a stale local copy in trunk and raised in
    a bench. Worse, the trunk copy drifts from the share the moment anyone edits
    either one, so the quiet path was also the wrong-data path. A configuration
    error must not depend on which worktree you happen to be standing in.

    Returns:
        The directory named by ``$FLEET_SHARE`` (``~`` expanded).

    Raises:
        RuntimeError: If ``$FLEET_SHARE`` is unset or empty. An empty string is
            treated as unset: ``export FLEET_SHARE=`` is a common shell
            accident, and ``Path("")`` resolves to the process CWD -- a
            silently wrong share root.
    """
    fromEnv = os.environ.get(_SHARE_ENV)
    if not fromEnv:
        raise RuntimeError(
            f"${_SHARE_ENV} is not set. It must name the agent-fleet share "
            f"root -- the directory holding the agent offices (pm/, ralph/, "
            f"tuner/, ...) -- because the PM tools read their backlog, sprint, "
            f"counter and manifest data from there, and it no longer lives in "
            f"this repo." + "\n"
            f"    {_SHARE_ENV}=Z:/O/OBD2v3/offices python -m tools.pm.pm_status"
            + "\n"
            "It is also registered under the 'env' key in fleet.json. There "
            "is NO fallback, on purpose: an in-repo offices/ may still exist "
            "in the trunk worktree but not in a bench, so falling back to it "
            "would make the same command behave differently depending on "
            "which worktree it ran in -- and would read a stale copy."
        )
    return Path(fromEnv).expanduser()


REPO_ROOT: Path = findRepoRoot()

# SHARE_ROOT is resolved LAZILY, via PEP 562 module __getattr__.
#
# It cannot be a module-level constant: resolving it raises when $FLEET_SHARE is
# unset, so a plain assignment would make merely IMPORTING this module a
# configuration error -- and this module is imported for REPO_ROOT by tools that
# never read share data (index_lock, verify_release_version, deploy_preflight_gate).
# Their tests would then fail at COLLECTION, complaining about data they do not
# touch.
#
# With __getattr__, the cost lands exactly where the dependency is:
#   import tools.pm._paths                        -> no resolution, never raises
#   from tools.pm._paths import REPO_ROOT         -> no resolution
#   from tools.pm._paths import SHARE_ROOT        -> resolves; raises if unset
#
# So `python -m tools.pm.index_lock --check` works with no share configured,
# while `python -m tools.pm.pm_status` fails loudly and immediately. That is the
# distinction the eager constant could not express.


def __getattr__(name: str) -> Path:
    """Resolve ``SHARE_ROOT`` on first access (PEP 562)."""
    if name == "SHARE_ROOT":
        return resolveShareRoot()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
