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
# SHARE_ROOT -- branch 1: $FLEET_SHARE wins
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

    assert resolveShareRoot(tmp_path) == share


def test_resolveShareRoot_envWinsOverInRepoOffices(tmp_path: Path, monkeypatch) -> None:
    """
    Given: BOTH $FLEET_SHARE and a transitional in-repo offices/ exist
    When:  the share root is resolved
    Then:  the env var wins

    Ordering matters: post-eviction an operator may still have a stale
    offices/ lying around, and the explicitly configured share must take
    precedence over it.
    """
    share = tmp_path / "fleet"
    share.mkdir()
    (tmp_path / "offices").mkdir()
    monkeypatch.setenv(_SHARE_ENV, str(share))

    assert resolveShareRoot(tmp_path) == share


# ==============================================================================
# SHARE_ROOT -- branch 2: transitional in-repo offices/
# ==============================================================================
def test_resolveShareRoot_envUnset_fallsBackToInRepoOffices(
    tmp_path: Path, monkeypatch
) -> None:
    """
    Given: $FLEET_SHARE unset but <repo>/offices/ still present
    When:  the share root is resolved
    Then:  the in-repo offices/ is used (the pre-eviction state)
    """
    monkeypatch.delenv(_SHARE_ENV, raising=False)
    offices = tmp_path / "offices"
    offices.mkdir()

    assert resolveShareRoot(tmp_path) == offices


def test_resolveShareRoot_officesAsFile_doesNotCount(
    tmp_path: Path, monkeypatch
) -> None:
    """
    Given: $FLEET_SHARE unset and 'offices' exists but is a FILE
    When:  the share root is resolved
    Then:  it raises -- the fallback requires a directory, not just a name
    """
    monkeypatch.delenv(_SHARE_ENV, raising=False)
    (tmp_path / "offices").write_text("not a directory", encoding="utf-8")

    with pytest.raises(RuntimeError):
        resolveShareRoot(tmp_path)


# ==============================================================================
# SHARE_ROOT -- branch 3: absence is LOUD
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
        resolveShareRoot(tmp_path)

    message = str(excinfo.value)
    # The operator must be told what to set and what it is for.
    assert _SHARE_ENV in message
    assert "offices" in message
    assert str(tmp_path / "offices") in message


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
        resolveShareRoot(tmp_path)
