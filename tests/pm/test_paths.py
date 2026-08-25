# ==============================================================================
# File:        tests/pm/test_paths.py
# Purpose:     Cover tools.pm._paths -- the root-resolution SSOT for the PM
#              tool cluster.
# Author:      offices-decouple restructure
# Created:     2026-08-24
# ==============================================================================
# These tests exist because of a defect that was INVISIBLE to the previous
# suite: every PM tool anchored its repo root on
# ``Path(__file__).resolve().parents[3]``, valid only at the old nesting depth
# (offices/pm/scripts/). Moving the package shifted that anchor above the repo,
# and nothing raised -- the tools simply resolved non-existent paths and read
# nothing. So the assertions here are about RESOLUTION BEHAVIOUR, especially
# the failure branch: absence must raise, never degrade quietly.
#
# Updated 2026-08-24: the transitional in-repo offices/ fallback was REMOVED.
# $FLEET_SHARE is now required unconditionally, so resolveShareRoot has exactly
# two outcomes and takes no arguments.
# ==============================================================================

from __future__ import annotations

from pathlib import Path

import pytest

from tools.pm._paths import findRepoRoot, resolveShareRoot

_SHARE_ENV = "FLEET_SHARE"


# ==============================================================================
# REPO_ROOT -- depth independence
# ==============================================================================
def test_findRepoRoot_locatesTheDirectoryHoldingPyproject() -> None:
    """
    Given: this test file, somewhere inside the repo
    When:  findRepoRoot walks upward
    Then:  it returns the directory that actually contains pyproject.toml
    """
    root = findRepoRoot(Path(__file__))
    assert (root / "pyproject.toml").is_file()
    assert (root / "tools" / "pm" / "_paths.py").is_file()


def test_findRepoRoot_isDepthIndependent(tmp_path: Path) -> None:
    """
    Given: a marker file at a tmp root and a deeply nested start point
    When:  findRepoRoot walks upward from six levels down
    Then:  it finds the same root -- no parents[N] assumption

    This is the regression guard for the original defect: the answer must not
    depend on how deeply the caller is nested.
    """
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    deep = tmp_path / "a" / "b" / "c" / "d" / "e" / "f"
    deep.mkdir(parents=True)

    assert findRepoRoot(deep) == tmp_path
    assert findRepoRoot(tmp_path / "a") == tmp_path


def test_findRepoRoot_noMarkerAnywhere_raises(tmp_path: Path) -> None:
    """
    Given: a tree with no pyproject.toml in it or above it
    When:  findRepoRoot is asked to resolve
    Then:  it raises RuntimeError naming the marker
    """
    # tmp_path's ancestors are OS temp dirs, which carry no pyproject.toml.
    lonely = tmp_path / "nowhere"
    lonely.mkdir()
    with pytest.raises(RuntimeError, match="pyproject.toml"):
        findRepoRoot(lonely)


# ==============================================================================
# SHARE_ROOT -- $FLEET_SHARE is the ONLY source (two outcomes: use it, or raise)
# ==============================================================================
def test_resolveShareRoot_envSet_usesIt(tmp_path: Path, monkeypatch) -> None:
    """
    Given: $FLEET_SHARE points at a directory
    When:  the share root is resolved
    Then:  that path is returned
    """
    share = tmp_path / "fleet"
    share.mkdir()
    monkeypatch.setenv(_SHARE_ENV, str(share))

    assert resolveShareRoot() == share


def test_resolveShareRoot_envSet_ignoresAnyInRepoOffices(
    tmp_path: Path, monkeypatch
) -> None:
    """
    Given: BOTH $FLEET_SHARE and an in-repo offices/ exist
    When:  the share root is resolved
    Then:  the env var wins; the local directory is never consulted
    """
    share = tmp_path / "fleet"
    share.mkdir()
    (tmp_path / "offices").mkdir()
    monkeypatch.setenv(_SHARE_ENV, str(share))

    assert resolveShareRoot() == share


# ==============================================================================
# THE INVERSION -- there is NO in-repo fallback any more
# ==============================================================================
def test_resolveShareRoot_unset_doesNotFallBackToInRepoOffices(
    tmp_path: Path, monkeypatch
) -> None:
    """
    Given: $FLEET_SHARE unset, but an in-repo offices/ directory DOES exist
    When:  the share root is resolved
    Then:  it raises anyway -- the directory is not a fallback

    This is the regression guard for the 2026-08-24 inversion. The fallback
    existed while offices/ was tracked; afterwards it survived only in the TRUNK
    worktree (kept on disk deliberately) and never in a fresh bench. Identical
    code with an identical (unset) environment therefore behaved differently
    depending on which worktree it ran in -- and the quiet path read a stale
    copy that drifts from the share. Restoring the fallback would restore both
    faults, so this test asserts its absence directly rather than trusting the
    surrounding prose.
    """
    monkeypatch.delenv(_SHARE_ENV, raising=False)
    (tmp_path / "offices").mkdir()

    with pytest.raises(RuntimeError, match=_SHARE_ENV):
        resolveShareRoot()


# ==============================================================================
# ABSENCE IS LOUD
# ==============================================================================
def test_resolveShareRoot_unsetAndMissing_raises(tmp_path: Path, monkeypatch) -> None:
    """
    Given: $FLEET_SHARE unset AND no in-repo offices/
    When:  the share root is resolved
    Then:  RuntimeError -- never a silent or plausible-looking default

    This is the branch that matters most. A silent fallback here would
    reproduce precisely the failure this module exists to prevent: a tool that
    resolves something path-shaped, reads nothing, and reports success.
    """
    monkeypatch.delenv(_SHARE_ENV, raising=False)

    with pytest.raises(RuntimeError) as excinfo:
        resolveShareRoot()

    message = str(excinfo.value)
    # The operator must be told what to set, what it is for, and where it is
    # already configured -- not merely that something is missing.
    assert _SHARE_ENV in message
    assert "offices" in message
    assert "fleet.json" in message


def test_resolveShareRoot_emptyEnvString_isTreatedAsUnset(
    tmp_path: Path, monkeypatch
) -> None:
    """
    Given: $FLEET_SHARE set to the empty string and no in-repo offices/
    When:  the share root is resolved
    Then:  it raises rather than resolving to the process CWD

    An empty env var is a common shell accident (``export FLEET_SHARE=``);
    Path("") resolves to the current directory, which would be a silently
    wrong share root.
    """
    monkeypatch.setenv(_SHARE_ENV, "")

    with pytest.raises(RuntimeError):
        resolveShareRoot()
