################################################################################
# File Name: test_edr_section_status_consistency.py
# Purpose/Description: US-773 -- specs/architecture.md section 10.8.3 declared
#     US-765/766/767/768 "not yet built" while marking two of them "(built, ...)"
#     further down the same section. A reader cannot tell which half to believe,
#     and both halves were written in good faith: the boundary paragraph was true
#     at the Sprint 88 gate and nobody re-read it when the code landed. This lint
#     pins the property that was violated -- within the section, NO story id
#     appears both as designed and as built -- and refuses to pass by scanning
#     nothing.
# Author: Rex (US-773)
# Creation Date: 2026-09-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-22    | Rex (US-773)   | Initial -- status consistency, the
#               |                | section-must-exist guard, docs-only AST check.
# ================================================================================
################################################################################
"""US-773: section 10.8.3 cannot call one story both designed and built."""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file()
)
_ARCH = _REPO_ROOT / "specs" / "architecture.md"

# The section under test, and the heading that ends it.
_SECTION_HEADING = "### 10.8.3 EDR reaches the server"
_NEXT_HEADING = re.compile(r"^#{1,3} (?!10\.8\.3)", re.MULTILINE)

# "(designed, US-766)" / "(built, US-767-a)" -- the markers the section uses,
# tolerant of the line break the prose wraps them with.
_MARKER = re.compile(
    r"\*\((designed|built)((?:,\s*(?:and\s+)?US-[\w-]+)+)", re.IGNORECASE | re.DOTALL
)
_STORY = re.compile(r"US-(\d+)")


def sectionText(markdown: str) -> str:
    """The body of 10.8.3. Raises if the heading is gone -- see the test below."""
    start = markdown.find(_SECTION_HEADING)
    if start < 0:
        raise AssertionError(
            f"section not found: {_SECTION_HEADING!r}. This lint scans that "
            "section by heading, so a renamed heading must FAIL here rather "
            "than pass by finding nothing to check."
        )
    rest = markdown[start + len(_SECTION_HEADING):]
    nextHeading = _NEXT_HEADING.search(rest)
    return rest[: nextHeading.start()] if nextHeading else rest


def statusByStory(section: str) -> dict[str, set[str]]:
    """{'766': {'built'}, ...} -- every status each story is marked with.

    Keyed on the story NUMBER so US-767, US-767-a and US-767-b are one story:
    a section that calls the parent designed while marking its sub-story built
    is the same contradiction wearing a suffix.
    """
    found: dict[str, set[str]] = {}
    for status, ids in _MARKER.findall(section):
        for number in _STORY.findall(ids):
            found.setdefault(number, set()).add(status.lower())
    return found


# --------------------------------------------------------------- the property


def test_noStoryIsBothDesignedAndBuilt() -> None:
    """
    Given: section 10.8.3
    When: every (designed|built, US-...) marker is collected per story
    Then: no story carries both. US-766 was '(designed)' twice while the same
        section marked US-767-a and US-768 '(built)', and the boundary
        paragraph called all four unbuilt
    """
    contradictions = {
        story: sorted(statuses)
        for story, statuses in statusByStory(sectionText(_ARCH.read_text(encoding="utf-8"))).items()
        if len(statuses) > 1
    }

    assert contradictions == {}, (
        f"section 10.8.3 marks these stories both designed AND built: "
        f"{contradictions}"
    )


def test_theBoundaryParagraphDoesNotCallAShippedStoryUnbuiltInThePresentTense() -> None:
    """
    Given: the status-boundary paragraph
    When: it says a story is not yet built
    Then: it is SCOPED to the date it was true. Erasing the history would be
        the opposite error, so this checks for a date beside the claim, not for
        the absence of the words
    """
    section = sectionText(_ARCH.read_text(encoding="utf-8"))
    for match in re.finditer(r"not yet built", section, re.IGNORECASE):
        window = section[max(0, match.start() - 400): match.end() + 200]
        assert re.search(r"20\d\d-\d\d-\d\d|Sprint \d+ design gate", window), (
            "a 'not yet built' claim with no date beside it reads as the "
            "present tense: scope it to when it was true, or state what "
            "shipped since"
        )


def test_theMarkerScannerSeesBothShapes() -> None:
    """The subset assertion above is only evidence if the scanner matches the
    markers the section actually uses -- including the wrapped one."""
    assert statusByStory("**x** *(designed, US-766)*.") == {"766": {"designed"}}
    assert statusByStory("**x** *(built, US-767-a; Atlas)*") == {"767": {"built"}}
    assert statusByStory("**x** *(designed,\nUS-767)*.") == {"767": {"designed"}}
    assert statusByStory("US-768 with no marker") == {}


def test_aRenamedHeadingFailsRatherThanScanningNothing() -> None:
    """
    Given: a document whose 10.8.3 heading has been renamed
    When: the section is resolved
    Then: it RAISES. An empty scan of a missing section is byte-identical to a
        clean one, and that is how this guard would go inert
    """
    with pytest.raises(AssertionError, match="section not found"):
        sectionText("### 10.8.4 Something else\n\nbody\n")


def test_theRealSectionIsFoundAndNotEmpty() -> None:
    """And the live document still has it -- so the tests above scanned text."""
    section = sectionText(_ARCH.read_text(encoding="utf-8"))
    assert len(section) > 2000
    assert statusByStory(section), "no status markers found -- did the format change?"


# ------------------------------------------------------------ docs-only check


_TOUCHED_SOURCES = (
    "src/common/edr/sync_contract.py",
    "src/pi/data/sync_log.py",
    "src/server/db/models.py",
)


def _stripDocstrings(tree: ast.AST) -> ast.AST:
    """Remove every docstring node, so the comparison is of CODE only.

    A docstring IS part of the AST, and US-773 had to edit one (the stale "a
    declaration only: nothing is wired to it"). "No code changed" therefore
    means: identical once the prose is removed.
    """
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return tree


def _astOf(source: str) -> str:
    return ast.dump(_stripDocstrings(ast.parse(source)))


@pytest.mark.parametrize("relPath", _TOUCHED_SOURCES)
def test_thisStoryChangedNoCode(relPath: str) -> None:
    """
    Given: each src/ file this docs story touched
    When: its AST (docstrings stripped) is compared with dev's
    Then: identical. That is the property "docs only", and it is stronger than
        reading the diff -- a reviewer skims prose and can miss a moved line

    Skips when dev is not fetched (a clean checkout without the remote), which
    is honest: the check cannot run, and saying so beats passing silently.
    """
    try:
        onDev = subprocess.run(
            ["git", "show", f"dev:{relPath}"],
            cwd=_REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as e:  # pragma: no cover
        pytest.skip(f"git unavailable: {e}")
    if onDev.returncode != 0:
        pytest.skip(f"dev:{relPath} not readable here: {onDev.stderr.strip()[:120]}")

    current = (_REPO_ROOT / relPath).read_text(encoding="utf-8")

    assert _astOf(current) == _astOf(onDev.stdout), (
        f"{relPath} differs from dev in CODE, not just documentation -- "
        "US-773 is a docs story and a code change here is a finding to report, "
        "not something to land inside it"
    )
