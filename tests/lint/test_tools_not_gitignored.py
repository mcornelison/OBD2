################################################################################
# File Name: test_tools_not_gitignored.py
# Purpose/Description: US-808-c -- guard against a first-party tools/ module
#                      being silently dropped by .gitignore's `tools/*`.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-09-24
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-24    | Rex (US-808-c) | Initial -- index-based guard, a scratch-repo
#               |                | positive control, and the four negations plus
#               |                | the downloaded-binary ignore pinned.
# ================================================================================
################################################################################

"""Lint: no tracked file under ``tools/`` is matched by an ignore rule.

The failure this prevents (Sprint 93, US-808)
---------------------------------------------
``.gitignore`` ignores ``tools/*`` and re-admits first-party directories one
negation at a time. Two new modules were written under a directory with no
negation. ``git status`` printed "working tree clean", ``git add`` printed
nothing, and the tests for them were committed without them. Both modules are
gone.

The predicate (ruled by Atlas, 2026-09-24)
------------------------------------------
First-party ``tools/`` source is what git TRACKS: ``git ls-files`` over the
INDEX. No list of directory names appears here, because a fixed list is the
same shape as the negations themselves, which is exactly what went stale.

For every tracked path under ``tools/`` the guard asks
``git check-ignore --no-index`` whether the ignore rules would match it. The
``--no-index`` matters: without it git reports every tracked file as
not-ignored, and the guard could never fail. A tracked file that the rules
match is one that is in the index only by ``git add -f`` or by an older rule,
and whose NEXT sibling will be skipped silently -- the Sprint 93 loss.

Run it against the index, after ``git add``: a module that has never been
staged is invisible to it (Atlas's chicken-and-egg). The remedy it names is
the negation, never ``git add -f``, because ``-f`` fixes one file and leaves
the directory ignored for the next.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = "tools"
GITIGNORE = ".gitignore"

# The first-party directories re-admitted today. Pinned only to prove the
# negations stay in force -- the guard itself never reads this list.
EXISTING_NEGATIONS = ("pm", "fleet", "sync", "imu")

# Fields per record in `git check-ignore -v -n -z` output:
# source, line number, pattern, pathname.
_CHECK_IGNORE_FIELDS = 4


def _gitEnv() -> dict[str, str]:
    """The caller's environment without GIT_* overrides that would redirect git."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(repoRoot: Path, *args: str, stdin: str | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repoRoot,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_gitEnv(),
    )
    # check-ignore exits 1 when nothing matched; anything above that is an error.
    if result.returncode > 1:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def ignoreMatches(repoRoot: Path, paths: list[str]) -> dict[str, str]:
    """Map each path an ignore rule would exclude to the rule that excludes it.

    Args:
        repoRoot: Root of the git work tree to query.
        paths: Repo-relative paths, tracked or not.

    Returns:
        ``{path: "<source>:<line>:<pattern>"}`` for every path that is ignored.
        A path matched only by a negation (``!...``) is not ignored and is absent.
    """
    if not paths:
        return {}
    out = _git(
        repoRoot,
        "check-ignore", "--no-index", "-v", "-n", "-z", "--stdin",
        stdin="\0".join(paths) + "\0",
    )
    fields = out.split("\0")
    matches: dict[str, str] = {}
    for i in range(0, len(fields) - _CHECK_IGNORE_FIELDS + 1, _CHECK_IGNORE_FIELDS):
        source, line, pattern, path = fields[i : i + _CHECK_IGNORE_FIELDS]
        if pattern and not pattern.startswith("!"):
            matches[path] = f"{source}:{line}:{pattern}"
    return matches


def findIgnoredTrackedTools(repoRoot: Path) -> dict[str, str]:
    """Every tracked path under tools/ that the ignore rules would exclude."""
    tracked = [p for p in _git(repoRoot, "ls-files", "-z", "--", TOOLS_DIR).split("\0") if p]
    return ignoreMatches(repoRoot, tracked)


def _negationFor(path: str) -> str:
    """The .gitignore line that re-admits `path`: its top-level tools/ entry."""
    parts = path.split("/")
    return f"!{parts[0]}/{parts[1]}/" if len(parts) > 2 else f"!{path}"


def describe(offenders: dict[str, str]) -> str:
    """A failure message that names each path and the line that fixes it."""
    lines = ["First-party tools/ source is matched by .gitignore and will be dropped silently:"]
    for path, rule in sorted(offenders.items()):
        lines.append(f"  {path}  (ignored by {rule})")
    lines.append("Add these negations to .gitignore beneath `tools/*` (not `git add -f`):")
    for negation in sorted({_negationFor(p) for p in offenders}):
        lines.append(f"  {negation}")
    return "\n".join(lines)


def _scratchRepo(root: Path, files: list[str], gitignore: str) -> Path:
    """A throwaway repo with the given .gitignore and files force-staged into its index."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    (root / GITIGNORE).write_text(gitignore, encoding="utf-8")
    for rel in files:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    _git(root, "add", "-f", "--", *files)
    return root


def _realGitignore() -> str:
    return (REPO_ROOT / GITIGNORE).read_text(encoding="utf-8")


def test_trackedToolsSource_isNotIgnored() -> None:
    """
    Given: the repository's index and .gitignore
    When: every tracked path under tools/ is checked against the ignore rules
    Then: none is matched
    """
    tracked = [p for p in _git(REPO_ROOT, "ls-files", "-z", "--", TOOLS_DIR).split("\0") if p]
    assert tracked, "git ls-files found nothing under tools/ -- the guard checked nothing"

    offenders = findIgnoredTrackedTools(REPO_ROOT)

    assert not offenders, describe(offenders)


def test_guard_newToolsDirWithoutNegation_failsAndNamesThePath(tmp_path: Path) -> None:
    """
    Given: a scratch repo carrying the real .gitignore, with a staged
           tools/newname/mod.py and no negation for it
    When: the guard runs
    Then: it reports tools/newname/mod.py, and the message names the path and
          the negation to add
    """
    repo = _scratchRepo(
        tmp_path / "repo", ["tools/pm/ok.py", "tools/newname/mod.py"], _realGitignore()
    )

    offenders = findIgnoredTrackedTools(repo)

    assert list(offenders) == ["tools/newname/mod.py"]
    assert offenders["tools/newname/mod.py"].endswith(":tools/*")
    message = describe(offenders)
    assert "tools/newname/mod.py" in message
    assert "!tools/newname/" in message


def test_guard_newToolsDirWithNegation_passes(tmp_path: Path) -> None:
    """
    Given: a scratch repo whose .gitignore adds a negation for a new tools/ package
    When: the guard runs
    Then: it passes -- a legitimately added module (US-808-d's tools/connlog/) lands
    """
    gitignore = _realGitignore() + "\n!tools/connlog/\n"
    repo = _scratchRepo(tmp_path / "repo", ["tools/connlog/mod.py"], gitignore)

    assert findIgnoredTrackedTools(repo) == {}


def test_existingNegations_remainInForce() -> None:
    """
    Given: the repository's .gitignore
    When: a new file inside each re-admitted tools/ directory is checked
    Then: no ignore rule matches it
    """
    probes = [f"{TOOLS_DIR}/{name}/new_module.py" for name in EXISTING_NEGATIONS]

    assert ignoreMatches(REPO_ROOT, probes) == {}


def test_downloadedBinaryUnderTools_isStillIgnored() -> None:
    """
    Given: the repository's .gitignore
    When: a downloaded binary placed directly under tools/ is checked
    Then: it is ignored by `tools/*`
    """
    binary = f"{TOOLS_DIR}/sqlite3.exe"

    matches = ignoreMatches(REPO_ROOT, [binary])

    assert binary in matches
    assert matches[binary].endswith(":tools/*")
