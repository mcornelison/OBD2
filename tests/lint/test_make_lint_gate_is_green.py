################################################################################
# File Name: test_make_lint_gate_is_green.py
# Purpose/Description: Standing-rule lint -- `make lint` is THE gate every
#     Definition of Done names, and it must exit 0. US-603 was written against a
#     narrower predicate (`ruff check src/ tests/`), went green, and left the
#     gate red at 8 errors because Makefile:52 also lints scripts/,
#     validate_config.py, tools/pm and specs/golden_code_sample.py. So this test
#     does not carry a path list of its own: it READS THE RECIPE OUT OF THE
#     MAKEFILE and runs that. A predicate that re-declares the scope can decay
#     away from the gate again; one that extracts it cannot.
#     It also pins the two runtime ordering constraints in
#     scripts/render_advanced_tier_sample.py, because the "obvious" fix for its
#     I001 (`ruff check --fix`) hoists `import pygame` above the
#     SDL_VIDEODRIVER setdefault and breaks the script on a headless box.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-10    | Rex          | Initial -- US-706: the gate itself is the test.
# ================================================================================
################################################################################

"""Lint: `make lint` exits 0, and the suppressions that get it there are honest."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"
PYPROJECT = REPO_ROOT / "pyproject.toml"
RENDER_SCRIPT = REPO_ROOT / "scripts" / "render_advanced_tier_sample.py"

# The per-file-ignores that existed BEFORE US-706. The story forbids buying a
# green by adding another one, so the set is frozen here rather than described.
PREEXISTING_PER_FILE_IGNORES = {
    "tests/*",
    "src/main.py",
    "src/pi/main.py",
    "src/obd/config/loader.py",
    "src/obd/obd_config_loader.py",
    "validate_config.py",
}

# Likewise the global rule-disable list. The 8 US-706 errors were I001, UP017,
# C416, F401 and B007; silencing any of them repo-wide is the forbidden fix.
PREEXISTING_GLOBAL_IGNORES = {"E501", "B008"}


def readMakeRecipe(target: str) -> list[str]:
    """
    Extract the command lines of a Makefile target.

    Args:
        target: The target name, e.g. ``lint``.

    Returns:
        The recipe lines, tab stripped, in order.

    Raises:
        AssertionError: If the target is not present in the Makefile.
    """
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    recipe: list[str] = []
    inTarget = False

    for line in lines:
        if re.match(rf"^{re.escape(target)}\s*:", line):
            inTarget = True
            continue
        if inTarget:
            if line.startswith("\t"):
                recipe.append(line.lstrip("\t").lstrip("@-").strip())
            elif line.strip():
                break

    assert recipe, f"Makefile has no recipe for target '{target}'"
    return recipe


def test_readMakeRecipe_lintTarget_returnsARuffInvocation() -> None:
    """
    Given: the Makefile's lint target
    When: its recipe is extracted
    Then: it is a single ruff invocation with at least one path argument

    This guards the harness, not the code. If the recipe changes shape the
    extraction could silently yield something that trivially exits 0 -- which is
    US-603's failure mode wearing a different hat.
    """
    recipe = readMakeRecipe("lint")

    assert len(recipe) == 1, f"expected one command in the lint recipe, got {recipe}"
    tokens = recipe[0].split()
    assert tokens[0] == "ruff", f"lint recipe no longer starts with ruff: {recipe[0]}"
    assert tokens[1] == "check", f"lint recipe is not a `ruff check`: {recipe[0]}"
    assert len(tokens) > 2, "lint recipe passes ruff no paths at all"


def test_makeLintGate_currentTree_exitsZero() -> None:
    """
    Given: the lint recipe as the Makefile actually declares it
    When: it is run against the current tree
    Then: it exits 0

    THIS IS US-706's ACCEPTANCE. Not `ruff check src/ tests/` -- that is the
    narrower predicate that passed while the gate stayed red at 8 errors.
    """
    tokens = readMakeRecipe("lint")[0].split()

    # The SCOPE comes from the Makefile; only the resolution of the `ruff`
    # executable is an environment detail we are allowed to substitute.
    if shutil.which("ruff"):
        command = tokens
    else:
        command = [sys.executable, "-m", *tokens]

    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, (
        "`make lint` is the command every Definition of Done names and it is "
        f"red.\ncommand: {' '.join(command)}\n{result.stdout}{result.stderr}"
    )


def test_pyprojectRuffConfig_perFileIgnores_gainedNoNewEntry() -> None:
    """
    Given: pyproject.toml's ruff configuration
    When: its per-file-ignores are read
    Then: they are exactly the set that predates US-706

    US-706 forbids buying the green with a per-file-ignore. A green gate under a
    widened ignore list is not a fixed tree, it is a quieter one.
    """
    text = PYPROJECT.read_text(encoding="utf-8")
    section = text.split("[tool.ruff.lint.per-file-ignores]", 1)
    assert len(section) == 2, "pyproject.toml no longer declares per-file-ignores"

    # Stop at the NEXT section header, not at the next `[` -- the first entry's
    # own value is a list, so splitting on a bare bracket truncates the section
    # to one line and the assertion then passes on almost nothing.
    body = re.split(r"^\[", section[1], maxsplit=1, flags=re.MULTILINE)[0]
    declared = set(re.findall(r'^"([^"]+)"\s*=', body, flags=re.MULTILINE))

    assert declared == PREEXISTING_PER_FILE_IGNORES, (
        "per-file-ignores changed. US-706 must be fixed in the code, not by "
        f"exempting a file.\nadded: {declared - PREEXISTING_PER_FILE_IGNORES}\n"
        f"removed: {PREEXISTING_PER_FILE_IGNORES - declared}"
    )


def test_pyprojectRuffConfig_globalIgnoreList_gainedNoNewRule() -> None:
    """
    Given: pyproject.toml's ruff lint.ignore list
    When: it is read
    Then: it is exactly the set that predates US-706

    Disabling I001, UP017, C416, F401 or B007 repo-wide would take the gate green
    while every one of the 8 defects stayed in the tree.
    """
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r"^ignore = \[(.*?)^\]", text, flags=re.MULTILINE | re.DOTALL)
    assert match, "pyproject.toml no longer declares a ruff lint.ignore list"

    declared = set(re.findall(r'"([^"]+)"', match.group(1)))

    assert declared == PREEXISTING_GLOBAL_IGNORES, (
        "ruff lint.ignore changed. Silencing a rule is not fixing the code.\n"
        f"added: {declared - PREEXISTING_GLOBAL_IGNORES}"
    )


def lineIndexOf(needle: str, haystack: list[str]) -> int:
    """
    Find the index of the first line containing a substring.

    Args:
        needle: Substring to search for.
        haystack: The file's lines.

    Returns:
        Zero-based index of the first match.

    Raises:
        AssertionError: If no line contains the substring.
    """
    for index, line in enumerate(haystack):
        if needle in line and not line.lstrip().startswith("#"):
            return index
    raise AssertionError(f"no non-comment line contains {needle!r}")


def test_renderAdvancedTierSample_sdlVideodriverSetdefault_precedesPygameImport() -> None:
    """
    Given: scripts/render_advanced_tier_sample.py
    When: the SDL_VIDEODRIVER setdefault and the pygame import are located
    Then: the setdefault comes first

    pygame reads SDL_VIDEODRIVER AT IMPORT TIME. Sorting the imports (what ruff's
    I001 asks for, and what `--fix` does) hoists `import pygame` above this line
    and the script then tries to open a real display on a headless box.
    """
    lines = RENDER_SCRIPT.read_text(encoding="utf-8").splitlines()

    setdefaultAt = lineIndexOf('os.environ.setdefault("SDL_VIDEODRIVER"', lines)
    pygameAt = lineIndexOf("import pygame", lines)

    assert setdefaultAt < pygameAt, (
        "`import pygame` was hoisted above the SDL_VIDEODRIVER setdefault. "
        "That is a behaviour change, not a lint fix -- pygame reads the "
        "variable at import time."
    )


def test_renderAdvancedTierSample_sysPathInsert_precedesPiDisplayImport() -> None:
    """
    Given: scripts/render_advanced_tier_sample.py
    When: the sys.path.insert and the pi.display import are located
    Then: the sys.path.insert comes first

    The second, less obvious constraint: sys.path.insert is what puts src/ on the
    path. Hoisting the pi.display import above it makes it unresolvable.
    """
    lines = RENDER_SCRIPT.read_text(encoding="utf-8").splitlines()

    sysPathAt = lineIndexOf("sys.path.insert(", lines)
    piImportAt = lineIndexOf("from pi.display.screens.primary_screen_advanced import", lines)

    assert sysPathAt < piImportAt, (
        "the pi.display import was hoisted above sys.path.insert -- src/ is not "
        "on the path yet at that point and the import fails."
    )


def test_renderAdvancedTierSample_i001Suppression_isScopedToThePygameImport() -> None:
    """
    Given: scripts/render_advanced_tier_sample.py
    When: its noqa directives are read
    Then: I001 is suppressed on the pygame import line and nowhere else, and no
          bare `# noqa` appears

    PM's 2026-09-10 ruling permits a single targeted I001 suppression here
    because the rule is asking for a change that breaks the program. It permits
    exactly that -- not a blanket noqa, not a file-level `# ruff: noqa`.
    """
    lines = RENDER_SCRIPT.read_text(encoding="utf-8").splitlines()
    pygameLine = lines[lineIndexOf("import pygame", lines)]

    assert re.search(r"#\s*noqa:\s*[^#]*\bI001\b", pygameLine), (
        "the pygame import does not carry a targeted `# noqa: I001`: " f"{pygameLine!r}"
    )

    bare = [line for line in lines if re.search(r"#\s*noqa\s*(?:$|[^:])", line)]
    assert not bare, f"blanket `# noqa` is forbidden by US-706: {bare}"

    fileLevel = [line for line in lines if re.search(r"#\s*ruff:\s*noqa", line)]
    assert not fileLevel, f"file-level ruff noqa is forbidden by US-706: {fileLevel}"

    suppressed = [
        line for line in lines if re.search(r"#\s*noqa:\s*[^#]*\bI001\b", line)
    ]
    assert len(suppressed) == 1, f"I001 suppressed on more than one line: {suppressed}"


def test_renderAdvancedTierSample_suppressionComment_namesBothConstraints() -> None:
    """
    Given: the comment block immediately above the pygame import
    When: it is read
    Then: it names BOTH ordering constraints by their code

    The comment is the whole point of the suppression: without it the next agent
    reads a noqa with no reason attached, deletes it, runs `--fix`, and ships the
    breakage. One constraint named is not enough -- PM verified there are two and
    the sys.path one is the easy one to miss.
    """
    lines = RENDER_SCRIPT.read_text(encoding="utf-8").splitlines()
    pygameAt = lineIndexOf("import pygame", lines)

    block: list[str] = []
    cursor = pygameAt - 1
    while cursor >= 0 and lines[cursor].lstrip().startswith("#"):
        block.insert(0, lines[cursor])
        cursor -= 1

    commentary = "\n".join(block)
    assert block, "the I001 suppression carries no explanatory comment at all"
    assert "SDL_VIDEODRIVER" in commentary, (
        "the suppression comment does not name the SDL_VIDEODRIVER constraint:\n"
        f"{commentary}"
    )
    assert "sys.path" in commentary, (
        "the suppression comment does not name the sys.path.insert constraint -- "
        f"PM verified there are TWO, and this is the one that gets missed:\n{commentary}"
    )


@pytest.mark.parametrize(
    "relPath",
    [
        "scripts/render_advanced_tier_sample.py",
        "scripts/seed_eclipse_vin.py",
        "tools/pm/archive_sprint_artifacts.py",
        "tools/pm/migrate_backlog_v1_to_v2.py",
        "tools/pm/pm_regression_status.py",
        "tools/pm/pm_status.py",
    ],
)
def test_us706TouchedFile_carriesNoBlanketSuppression(relPath: str) -> None:
    """
    Given: each of the 6 files carrying the 8 US-706 errors
    When: its noqa directives are read
    Then: none is a bare `# noqa` or a file-level `# ruff: noqa`

    The other five files had no behaviour question at all, so none of them has
    any excuse for a suppression.
    """
    lines = (REPO_ROOT / relPath).read_text(encoding="utf-8").splitlines()

    bare = [line for line in lines if re.search(r"#\s*noqa\s*(?:$|[^:])", line)]
    fileLevel = [line for line in lines if re.search(r"#\s*ruff:\s*noqa", line)]

    assert not bare, f"{relPath} carries a blanket `# noqa`: {bare}"
    assert not fileLevel, f"{relPath} carries a file-level ruff noqa: {fileLevel}"
