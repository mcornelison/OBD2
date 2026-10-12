################################################################################
# File Name: test_deploy_worktree_aware.py
# Purpose/Description: Standing-rule lint -- the deploy scripts must detect a git
#     repo in a way that works for a WORKTREE, not just a clone. In a worktree
#     `.git` is a FILE holding "gitdir: ...", not a directory, so `[ -d .git ]`
#     is false. After the v2 -> v3 move the repo became a worktree (trunk\) and
#     that check silently failed: every deploy since stamped
#     .deploy-version with gitHash "unknown", so nobody could tell what code was
#     on the car or the server. Nothing failed and nothing said so.
# Author: Claude (post-migration)
# Creation Date: 2026-08-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-26    | Claude       | Initial -- ban `-d .git` in the deploy scripts.
# ================================================================================
################################################################################

"""Lint: deploy scripts must be worktree-aware when detecting a git repo."""

from __future__ import annotations

from pathlib import Path

import pytest

DEPLOY_DIR = Path(__file__).resolve().parents[2] / "deploy"
SCRIPTS = ["deploy-pi.sh", "deploy-server.sh"]


@pytest.mark.parametrize("name", SCRIPTS)
def test_deployScript_doesNotTestGitAsADirectory(name: str) -> None:
    """
    Given: a deploy script that stamps gitHash into .deploy-version
    When: its repo-detection is read
    Then: it does not use `-d` against .git

    `-d` asks "is this a directory". In a worktree .git is a FILE. The correct
    probe is `git rev-parse --is-inside-work-tree`, which is true in both layouts.
    """
    path = DEPLOY_DIR / name
    assert path.is_file(), f"missing deploy script: {path}"
    text = path.read_text(encoding="utf-8")

    # Scope to the LOCAL repo-root probe. deploy-pi.sh legitimately uses
    # `-d "$full/.git"` inside a remote heredoc to find legacy CLONES on the Pi
    # and rm -rf them -- a clone really does have .git as a directory, and
    # rev-parse there would be both wrong and dangerous since it guards a delete.
    # The first version of this test flagged that line: a lint that matches on
    # syntax rather than intent rejects correct code.
    offenders = [
        line.strip()
        for line in text.splitlines()
        if "-d " in line
        and "/.git" in line
        and "REPO_ROOT" in line
        and not line.strip().startswith("#")
    ]

    assert not offenders, (
        f"{name} tests .git with -d, which is FALSE in a git worktree: {offenders}. "
        f"Use `git -C <root> rev-parse --is-inside-work-tree` instead."
    )


@pytest.mark.parametrize("name", SCRIPTS)
def test_deployScript_usesRevParseToDetectTheRepo(name: str) -> None:
    """
    Given: the same script
    When: its repo-detection is read
    Then: it uses rev-parse --is-inside-work-tree

    Banning the wrong probe is not enough; the right one has to be present, or a
    future edit could drop repo detection entirely and still pass the ban above.
    """
    text = (DEPLOY_DIR / name).read_text(encoding="utf-8")

    assert "rev-parse --is-inside-work-tree" in text, (
        f"{name} must detect the repo with `git rev-parse --is-inside-work-tree` "
        f"so it works in a worktree as well as a clone"
    )
